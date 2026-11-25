"""Simulate the true history of Halden Roasters, before any system gets it wrong.

The output of this module is the ground truth: what actually happened to every
person, account, subscription, order, payment and parcel. The exporters then
write that truth out the way each source system would, defects included.
"""
from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import config as cfg
from .calendar import (UTC, add_business_days, add_months, daterange, london_local_to_utc,
                       next_business_day, target_holidays)
from .identities import PersonFactory

log = logging.getLogger(__name__)

CANCEL_REASONS_DEFAULT = (("Too much coffee", 0.30), ("Trying another brand", 0.15),
                          ("Moving house", 0.07), ("Too expensive", 0.15), ("Other", 0.13), ("", 0.20))


@dataclass
class World:
    persons: pd.DataFrame
    accounts: pd.DataFrame
    subscriptions: pd.DataFrame
    orders: pd.DataFrame
    order_lines: pd.DataFrame
    transactions: pd.DataFrame
    shipments: pd.DataFrame
    crm_changes: pd.DataFrame
    assignments: pd.DataFrame
    fx: pd.DataFrame


class Simulator:
    def __init__(self, seed: int = cfg.SEED):
        self.rng = np.random.default_rng(seed)
        self.people = PersonFactory(self.rng, seed)
        self.persons: list[dict] = []
        self.person_by_id: dict[str, dict] = {}
        self.accounts: list[dict] = []
        self.subs: list[dict] = []
        self.orders: list[dict] = []
        self.lines: list[dict] = []
        self.txns: list[dict] = []
        self.shipments: list[dict] = []
        self.assignments: list[dict] = []
        self.next_customer = 1
        self.next_order = 1000001
        self.next_txn = 100000001
        self.next_shipment = 1
        self.events: list[tuple] = []      # heap of (date, seq, kind, payload)
        self.seq = 0
        self.active_subs: list[dict] = []  # for picking people who open a parallel account
        self.fx = self._fx_rates()

    # ------------------------------------------------------------------ helpers
    def _choice(self, items, weights):
        w = np.asarray(weights, dtype=float)
        return items[int(self.rng.choice(len(items), p=w / w.sum()))]

    def _push(self, d: date, kind: str, payload: dict):
        self.seq += 1
        heapq.heappush(self.events, (d, self.seq, kind, payload))

    def _new_person(self, country: str | None = None) -> dict:
        if country is None:
            country = self._choice([c.code for c in cfg.COUNTRIES], [c.share for c in cfg.COUNTRIES])
        p = self.people.new_person(country)
        self.persons.append(p)
        self.person_by_id[p["person_id"]] = p
        return p

    def _new_account(self, person: dict, created_at: datetime, origin: str, email: str | None = None,
                     name: tuple[str, str] | None = None, legacy_id: str | None = None) -> dict:
        first, last = name if name else (person["first_name"], person["last_name"])
        acct = {
            "customer_id": f"C{self.next_customer:06d}",
            "person_id": person["person_id"],
            "origin": origin,
            "legacy_id": legacy_id,
            "created_at_utc": created_at,
            "first_name": first,
            "last_name": last,
            "email": email or person["email"],
            "phone": person["phone"],
            "street": person["street"],
            "city": person["city"],
            "postcode": person["postcode"],
            "country_code": person["country_code"],
            "marketing_opt_in": bool(self.rng.random() < 0.62),
        }
        self.next_customer += 1
        self.accounts.append(acct)
        return acct

    def _fx_rates(self) -> pd.DataFrame:
        """Synthetic GBP-per-EUR reference rates on TARGET business days.

        I wanted real ECB rates here, but the ECB site is not reachable from the
        build environment. A mean-reverting random walk in the range the real
        rate actually moved in keeps the conversions realistic without
        pretending the numbers are official.
        """
        rows, rate = [], 0.872
        holidays = set()
        for y in range(cfg.DATA_START.year - 1, cfg.DATA_END.year + 1):
            holidays |= target_holidays(y)
        for d in daterange(cfg.DATA_START - timedelta(days=10), cfg.DATA_END):
            if d.weekday() >= 5 or d in holidays:
                continue
            rate += 0.02 * (0.862 - rate) + self.rng.normal(0, 0.0022)
            rows.append({"rate_date": d, "gbp_per_eur": round(rate, 5)})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------- orders etc.
    def _price(self, plan_code: str, currency: str, d: date) -> float:
        plan = cfg.PLAN_BY_CODE[plan_code]
        pair = plan.gbp if currency == "GBP" else plan.eur
        return pair[1] if d >= cfg.PRICE_INCREASE_DATE else pair[0]

    def _order(self, acct: dict | None, person: dict, created_at: datetime, order_type: str,
               sub: dict | None, guest_email: str | None = None, discount: tuple[str, float] | None = None,
               is_test: bool = False) -> dict:
        country = cfg.COUNTRY_BY_CODE[person["country_code"]]
        cur = country.currency
        lines = []
        if order_type == "SUBSCRIPTION":
            lines.append((sub["plan_code"], 1, self._price(sub["plan_code"], cur, created_at.date())))
        else:
            n = 1 + int(self.rng.random() < 0.35) + int(self.rng.random() < 0.1)
            for i in self.rng.choice(len(cfg.PRODUCTS), size=n, replace=False):
                sku, gbp, eur = cfg.PRODUCTS[int(i)]
                lines.append((sku, 1 + int(self.rng.random() < 0.15), gbp if cur == "GBP" else eur))
        subtotal = round(sum(q * p for _, q, p in lines), 2)
        code, pct = discount if discount else ("", 0.0)
        disc = round(subtotal * pct, 2)
        shipping = 0.0
        if order_type == "ONE_OFF" and subtotal - disc < cfg.FREE_SHIPPING_FROM[cur]:
            shipping = cfg.SHIPPING_FEE[cur]
        total = round(subtotal - disc + shipping, 2)
        vat = round(total - total / (1 + country.vat_rate), 2)
        o = {
            "order_id": str(self.next_order),
            "customer_id": acct["customer_id"] if acct else None,
            "person_id": person["person_id"],
            "guest_email": guest_email,
            "created_at_utc": created_at,
            "order_type": order_type,
            "subscription_id": sub["subscription_id"] if sub else None,
            "country_code": country.code,
            "currency_code": cur,
            "subtotal_amount": subtotal,
            "discount_code": code,
            "discount_amount": disc,
            "shipping_amount": shipping,
            "vat_amount": vat,
            "total_amount": total,
            "vat_rate": country.vat_rate,
            "is_test": is_test,
            "status": "PENDING",
        }
        self.next_order += 1
        for sku, q, p in lines:
            self.lines.append({"order_id": o["order_id"], "sku": sku, "quantity": q, "unit_price": p})
        self.orders.append(o)
        return o

    def _txn(self, order: dict, txn_type: str, at: datetime, gross: float, fee: float = 0.0,
             decline_code: str = "") -> dict:
        settles = txn_type != "DECLINE"
        t = {
            "txn_id": f"T{self.next_txn}",
            "order_id": order["order_id"],
            "txn_type": txn_type,
            "txn_at_utc": at,
            "currency_code": order["currency_code"],
            "gross_amount": round(gross, 2),
            "fee_amount": round(fee, 2),
            "net_amount": round(gross - fee, 2),
            "settlement_date": add_business_days(at.date(), 2) if settles else None,
            "card_country": order["country_code"] if self.rng.random() > 0.03 else "US",
            "decline_code": decline_code,
            "vat_rate": order["vat_rate"],
        }
        self.next_txn += 1
        self.txns.append(t)
        return t

    def _pay(self, order: dict, first_success: float, retries: tuple) -> datetime | None:
        """Run the payment attempts. Returns the time of the successful capture, or None."""
        at = order["created_at_utc"] + timedelta(seconds=int(self.rng.integers(2, 40)))
        probs = (first_success,) + retries
        for attempt, p in enumerate(probs):
            if attempt > 0:
                day = order["created_at_utc"].date() + timedelta(days=3 * attempt)
                at = datetime(day.year, day.month, day.day, 10, int(self.rng.integers(0, 59)),
                              int(self.rng.integers(0, 59)), tzinfo=UTC)
            if self.rng.random() < p:
                fee = order["total_amount"] * cfg.PAYMENTS.fee_pct + cfg.PAYMENTS.fee_fixed
                self._txn(order, "CAPTURE", at, order["total_amount"], fee)
                order["status"] = "PAID"
                order["paid_at_utc"] = at
                return at
            code = self._choice(["insufficient_funds", "card_expired", "do_not_honour"], [0.6, 0.25, 0.15])
            self._txn(order, "DECLINE", at, 0.0, decline_code=code)
            order["last_attempt_at_utc"] = at
        order["status"] = "PAYMENT_FAILED"
        return None

    def _ship(self, order: dict, acct_name: tuple[str, str], paid_at: datetime) -> dict:
        country = cfg.COUNTRY_BY_CODE[order["country_code"]]
        dispatch = next_business_day(paid_at.date())
        lo, hi = country.transit_days
        promised = add_business_days(dispatch, hi)
        delivered = add_business_days(dispatch, int(self.rng.integers(lo, hi + 1)))
        p_late = cfg.FULFILMENT.late_prob
        if date(dispatch.year, 12, 1) <= dispatch <= date(dispatch.year, 12, 23):
            p_late = cfg.FULFILMENT.late_prob_peak
        if country.site == "HAM" and cfg.WAREHOUSE_INCIDENT[0] <= dispatch <= cfg.WAREHOUSE_INCIDENT[1]:
            p_late = cfg.FULFILMENT.late_prob_incident
        late = bool(self.rng.random() < p_late)
        if late:
            delivered = add_business_days(promised, int(self.rng.integers(1, 6)))
        lost = bool(self.rng.random() < cfg.FULFILMENT.lost_prob)
        s = {
            "shipment_no": f"{self.next_shipment:010d}",
            "order_id": order["order_id"],
            "site_code": country.site,
            "recipient_name": f"{acct_name[0]} {acct_name[1]}",
            "country_code": country.code,
            "dispatch_date": dispatch,
            "promised_date": promised,
            "delivered_date": None if lost else delivered,
            "lost_declared_date": dispatch + timedelta(days=10) if lost else None,
            "is_late": (not lost) and late,
            "weight_kg": None,
        }
        self.next_shipment += 1
        self.shipments.append(s)
        if lost:
            at = datetime.combine(s["lost_declared_date"] + timedelta(days=1), datetime.min.time(), UTC) \
                + timedelta(hours=11, minutes=int(self.rng.integers(0, 59)))
            self._txn(order, "REFUND", at, -order["total_amount"])
        else:
            if self.rng.random() < cfg.PAYMENTS.goodwill_refund_prob:
                d = delivered + timedelta(days=int(self.rng.integers(3, 21)))
                at = datetime(d.year, d.month, d.day, 14, int(self.rng.integers(0, 59)), tzinfo=UTC)
                self._txn(order, "REFUND", at, -round(order["total_amount"] * 0.5, 2))
            if self.rng.random() < cfg.PAYMENTS.chargeback_prob:
                d = paid_at.date() + timedelta(days=int(self.rng.integers(30, 76)))
                at = datetime(d.year, d.month, d.day, 6, int(self.rng.integers(0, 59)), tzinfo=UTC)
                self._txn(order, "CHARGEBACK", at, -order["total_amount"], cfg.PAYMENTS.chargeback_fee)
        return s

    # ---------------------------------------------------------- subscriptions
    def _start_subscription(self, acct: dict, person: dict, start_at: datetime, promo: bool,
                            legacy_start: date | None = None):
        plan = self._choice([p.code for p in cfg.PLANS], [p.share for p in cfg.PLANS])
        freq = self._choice([f for f, _ in cfg.FREQUENCIES], [w for _, w in cfg.FREQUENCIES])
        sub = {
            "subscription_id": f"S{len(self.subs) + 1:06d}",
            "customer_id": acct["customer_id"],
            "person_id": person["person_id"],
            "plan_code": plan,
            "frequency": freq,
            "promo_acquired": promo,
            "started_at_utc": start_at,
            "ended_at_utc": None,
            "end_type": None,
            "cancel_reason": None,
            "is_legacy": legacy_start is not None,
        }
        self.subs.append(sub)
        self._run_subscription(sub, acct, person, legacy_start)
        if sub["end_type"] is None or sub["ended_at_utc"].date() > start_at.date():
            self.active_subs.append(sub)
        return sub

    def _run_subscription(self, sub: dict, acct: dict, person: dict, legacy_start: date | None):
        first_day = legacy_start or sub["started_at_utc"].date()
        anchor = min(first_day.day, 28)
        step_days = 14 if sub["frequency"] == "FORTNIGHTLY" else None

        def cycle_date(k: int) -> date:
            if step_days:
                return first_day + timedelta(days=step_days * k)
            return first_day if k == 0 else add_months(first_day, k, anchor)

        k = 0
        if legacy_start:
            while cycle_date(k) < cfg.DATA_START:
                k += 1
        late_history: list[bool] = []
        treated_orders_left = 0
        treat_decisions_left = 0
        assignment = None
        name = (acct["first_name"], acct["last_name"])
        while True:
            d = cycle_date(k)
            if d > cfg.DATA_END:
                return
            if k == 0 and not legacy_start:
                created = sub["started_at_utc"] + timedelta(seconds=int(self.rng.integers(5, 90)))
            else:
                # Renewals are created by the shop's nightly batch, between 00:30 and 02:30 London time.
                mins = int(self.rng.integers(30, 150))
                created = london_local_to_utc(d, mins // 60, mins % 60, int(self.rng.integers(0, 60)))
            discount = None
            if k == 0 and sub["promo_acquired"] and not legacy_start:
                discount = ("WELCOME50", 0.5)
            elif treated_orders_left > 0:
                discount = ("RET30", cfg.EXPERIMENT.discount_pct)
                treated_orders_left -= 1
            order = self._order(acct, person, created, "SUBSCRIPTION", sub, discount=discount)
            paid = self._pay(order, cfg.PAYMENTS.first_attempt_success, cfg.PAYMENTS.retry_success)
            if paid is None:
                sub["ended_at_utc"] = order["last_attempt_at_utc"] + timedelta(minutes=5)
                sub["end_type"] = "LAPSED"
                return
            shipment = self._ship(order, name, paid)
            late_history.append(shipment["is_late"])

            if self.rng.random() < cfg.VOLUMES.oneoff_per_cycle:
                od = d + timedelta(days=int(self.rng.integers(1, 12)))
                if od <= cfg.DATA_END:
                    self._oneoff(acct, person, od)

            # Churn decision for the period until the next box.
            p = cfg.CHURN.base_per_cycle[sub["frequency"]]
            for max_k, mult in cfg.CHURN.tenure_mult:
                if k <= max_k:
                    p *= mult
                    break
            if sub["promo_acquired"] and k < 6:
                p *= cfg.CHURN.promo_mult
            if shipment["is_late"]:
                p *= cfg.CHURN.late_this_cycle_mult
            if sum(late_history[-3:]) >= 2:
                p *= cfg.CHURN.two_late_recent_mult / cfg.CHURN.late_this_cycle_mult
            in_price_window = cfg.PRICE_INCREASE_DATE <= d < cfg.PRICE_INCREASE_DATE + timedelta(
                days=cfg.CHURN.price_rise_window_days)
            if in_price_window:
                p *= cfg.PLAN_BY_CODE[sub["plan_code"]].price_rise_churn_mult
            if person["country_code"] == "NL":
                p *= cfg.CHURN.nl_mult
            p = min(p, 0.9)

            if assignment is None and cfg.EXPERIMENT_ENROL[0] <= d <= cfg.EXPERIMENT_ENROL[1]:
                tenure_days = (d - first_day).days
                if tenure_days >= cfg.EXPERIMENT.min_tenure_days:
                    variant = "treatment" if self.rng.random() < cfg.EXPERIMENT.treatment_share else "control"
                    assignment = {
                        "customer_id": acct["customer_id"],
                        "person_id": person["person_id"],
                        "subscription_id": sub["subscription_id"],
                        "variant": variant,
                        "assigned_at_utc": created + timedelta(minutes=int(self.rng.integers(20, 300))),
                        "risk_before_treatment": round(p, 5),
                        "true_relative_reduction": 0.0,
                    }
                    if variant == "treatment":
                        high = p >= cfg.EXPERIMENT.high_risk_threshold
                        assignment["true_relative_reduction"] = (
                            cfg.EXPERIMENT.relative_reduction_high_risk if high
                            else cfg.EXPERIMENT.relative_reduction_low_risk)
                        treated_orders_left = cfg.EXPERIMENT.discounted_orders
                        treat_decisions_left = cfg.EXPERIMENT.discounted_orders
                    self.assignments.append(assignment)
            if treat_decisions_left > 0:
                p *= 1 - assignment["true_relative_reduction"]
                treat_decisions_left -= 1

            if self.rng.random() < p:
                nxt = cycle_date(k + 1)
                earliest = (shipment["delivered_date"] or shipment["dispatch_date"]) + timedelta(days=1)
                span = max((nxt - earliest).days - 1, 1)
                cd = earliest + timedelta(days=int(self.rng.integers(0, span)))
                if cd > cfg.DATA_END:
                    return
                sub["ended_at_utc"] = datetime(cd.year, cd.month, cd.day, int(self.rng.integers(7, 23)),
                                               int(self.rng.integers(0, 60)), int(self.rng.integers(0, 60)),
                                               tzinfo=UTC)
                sub["end_type"] = "CANCELLED"
                sub["cancel_reason"] = self._cancel_reason(shipment["is_late"], in_price_window)
                if self.rng.random() < cfg.CHURN.winback_prob:
                    wd = cd + timedelta(days=int(self.rng.integers(60, 241)))
                    if wd <= cfg.DATA_END:
                        self._push(wd, "winback", {"person": person, "account": acct})
                return
            k += 1

    def _cancel_reason(self, late: bool, price_window: bool) -> str:
        if late and self.rng.random() < 0.6:
            return "Delivery problems"
        if price_window and self.rng.random() < 0.5:
            return "Too expensive"
        reasons = CANCEL_REASONS_DEFAULT
        return self._choice([r for r, _ in reasons], [w for _, w in reasons])

    def _oneoff(self, acct: dict | None, person: dict, d: date, guest_email: str | None = None):
        country = cfg.COUNTRY_BY_CODE[person["country_code"]]
        # Daytime shopping, in the customer's own evening-heavy pattern.
        hour = int(self._choice(list(range(7, 24)), [1, 2, 3, 3, 3, 4, 4, 3, 3, 3, 4, 5, 7, 8, 8, 6, 3]))
        local_offset = 0 if country.code in ("GB", "IE") else 1
        created = london_local_to_utc(d, max(hour - local_offset, 0), int(self.rng.integers(0, 60)),
                                      int(self.rng.integers(0, 60)))
        order = self._order(acct, person, created, "ONE_OFF", None, guest_email=guest_email)
        paid = self._pay(order, cfg.PAYMENTS.oneoff_first_attempt_success, ())
        if paid is not None:
            name = (acct["first_name"], acct["last_name"]) if acct else (person["first_name"], person["last_name"])
            self._ship(order, name, paid)

    # ------------------------------------------------------------- main loop
    def _signup_time(self, d: date) -> datetime:
        hour = int(self._choice(list(range(6, 24)), [1, 2, 3, 4, 4, 4, 5, 5, 4, 4, 4, 5, 6, 8, 9, 8, 6, 3]))
        return datetime(d.year, d.month, d.day, hour, int(self.rng.integers(0, 60)),
                        int(self.rng.integers(0, 60)), tzinfo=UTC)

    def _promo(self, d: date) -> bool:
        share = cfg.VOLUMES.promo_share_january if d.month == 1 else cfg.VOLUMES.promo_share
        return bool(self.rng.random() < share)

    def run(self) -> World:
        self._legacy_base()
        months = 0
        for d in daterange(cfg.DATA_START, cfg.DATA_END):
            months = (d.year - cfg.DATA_START.year) * 12 + d.month - 1
            while self.events and self.events[0][0] <= d:
                _, _, kind, payload = heapq.heappop(self.events)
                self._handle_event(kind, payload, d)
            if d == cfg.CRM_MIGRATION_DATE:
                self._migration_duplicates()
            lam = cfg.VOLUMES.signups_per_day * (1 + cfg.VOLUMES.signup_growth_per_month) ** months
            lam *= cfg.SEASONALITY[d.month]
            for _ in range(int(self.rng.poisson(lam))):
                self._new_signup(d)
            for _ in range(int(self.rng.poisson(cfg.VOLUMES.guests_per_day * cfg.SEASONALITY[d.month]))):
                self._guest(d)
            if d.day == 1:
                self.active_subs = [s for s in self.active_subs
                                    if s["ended_at_utc"] is None or s["ended_at_utc"].date() >= d]
        self._test_orders()
        self._legacy_refunds()
        log.info("simulation finished: persons=%d accounts=%d subscriptions=%d orders=%d",
                 len(self.persons), len(self.accounts), len(self.subs), len(self.orders))
        return self._to_world()

    def _legacy_base(self):
        span = (date(2022, 12, 20) - date(2021, 3, 1)).days
        starts = sorted(date(2021, 3, 1) + timedelta(days=int(x))
                        for x in self.rng.integers(0, span, cfg.VOLUMES.legacy_active_subscribers))
        for i, s in enumerate(starts):
            person = self._new_person()
            created = datetime(s.year, s.month, s.day, 12, 0, tzinfo=UTC)
            acct = self._new_account(person, created, "legacy", legacy_id=f"HRL-{i + 1:05d}")
            self._start_subscription(acct, person, created, promo=False, legacy_start=s)

    def _new_signup(self, d: date):
        at = self._signup_time(d)
        if self.active_subs and self.rng.random() < cfg.VOLUMES.parallel_account_prob:
            for _ in range(20):
                s = self.active_subs[int(self.rng.integers(len(self.active_subs)))]
                if s["started_at_utc"].date() < d and (s["ended_at_utc"] is None or s["ended_at_utc"].date() > d):
                    person = self.person_by_id[s["person_id"]]
                    email = self.people.other_email(person, work=True)
                    acct = self._new_account(person, at, "parallel_account", email=email)
                    self._start_subscription(acct, person, at, promo=False)
                    return
        person = self._new_person()
        acct = self._new_account(person, at, "signup")
        self._start_subscription(acct, person, at, promo=self._promo(d))

    def _guest(self, d: date):
        person = self._new_person()
        self._oneoff(None, person, d, guest_email=person["email"])
        if self.rng.random() < 0.25:
            d2 = d + timedelta(days=int(self.rng.integers(30, 181)))
            if d2 <= cfg.DATA_END:
                self._push(d2, "guest_repeat", {"person": person})
        if self.rng.random() < cfg.VOLUMES.guest_registers_prob:
            d3 = d + timedelta(days=int(self.rng.integers(10, 151)))
            if d3 <= cfg.DATA_END:
                self._push(d3, "guest_registers", {"person": person})

    def _handle_event(self, kind: str, payload: dict, d: date):
        person = payload["person"]
        at = self._signup_time(d)
        if kind == "guest_repeat":
            self._oneoff(None, person, d, guest_email=person["email"])
        elif kind == "guest_registers":
            email = self.people.email_variant(person["email"]) if self.rng.random() < 0.4 else person["email"]
            acct = self._new_account(person, at, "guest_registration", email=email)
            self._start_subscription(acct, person, at, promo=self._promo(d))
        elif kind == "winback":
            if self.rng.random() < cfg.CHURN.winback_new_account_prob:
                email = self.people.other_email(person, work=False)
                f, l, _ = self.people.name_variant(person["first_name"], person["last_name"])
                acct = self._new_account(person, at, "winback_new_account", email=email, name=(f, l))
                if self.rng.random() < 0.3:
                    acct.update(self.people.new_address(person["country_code"]))
            else:
                acct = payload["account"]
            self._start_subscription(acct, person, at, promo=False)

    def _migration_duplicates(self):
        """The March 2023 CRM migration imported part of the legacy list twice."""
        legacy = [a for a in self.accounts if a["origin"] == "legacy"]
        n = int(len(legacy) * 0.04)
        at = datetime(cfg.CRM_MIGRATION_DATE.year, cfg.CRM_MIGRATION_DATE.month, cfg.CRM_MIGRATION_DATE.day,
                      21, 0, tzinfo=UTC)
        for i in sorted(self.rng.choice(len(legacy), size=n, replace=False)):
            src = legacy[int(i)]
            person = self.person_by_id[src["person_id"]]
            f, l, _ = self.people.name_variant(src["first_name"], src["last_name"])
            email = self.people.email_variant(src["email"]) if self.rng.random() < 0.5 else src["email"]
            dup = self._new_account(person, at + timedelta(seconds=int(i)), "migration_duplicate",
                                    email=email, name=(f, l), legacy_id=src["legacy_id"])
            dup["marketing_opt_in"] = src["marketing_opt_in"]

    def _test_orders(self):
        """Staff place test orders on production with a .test address. They must not count as revenue."""
        tester = self._new_person("GB")
        tester["email"] = "qa.checkout@haldenroasters.test"
        days = sorted(self.rng.choice((cfg.DATA_END - cfg.DATA_START).days, size=37, replace=False))
        for x in days:
            d = cfg.DATA_START + timedelta(days=int(x))
            created = london_local_to_utc(d, 10, int(self.rng.integers(0, 60)), 0)
            o = self._order(None, tester, created, "ONE_OFF", None, guest_email=tester["email"], is_test=True)
            paid = self._pay(o, 1.0, ())
            # QA refunds its own test orders straight away, so the money nets to zero but gross is inflated.
            self._txn(o, "REFUND", paid + timedelta(minutes=int(self.rng.integers(20, 90))), -o["total_amount"])

    def _legacy_refunds(self):
        """Refunds keyed in by customer service against orders from the pre-2023 shop.

        Those orders do not exist in the current shop, so these refunds have no
        order to join to. They are still real money leaving the business.
        """
        days = sorted(self.rng.choice(120, size=12, replace=False))
        for i, x in enumerate(days):
            d = cfg.DATA_START + timedelta(days=int(x))
            cur = "GBP" if self.rng.random() < 0.6 else "EUR"
            ref = {"order_id": f"L{880000 + int(self.rng.integers(0, 9999))}", "currency_code": cur,
                   "country_code": "GB" if cur == "GBP" else "DE", "vat_rate": 0.0 if cur == "GBP" else 0.07}
            at = datetime(d.year, d.month, d.day, 15, int(self.rng.integers(0, 59)), tzinfo=UTC)
            self._txn(ref, "REFUND", at, -float(self._choice([11.50, 21.00, 32.00, 13.50, 24.50], [1] * 5)))

    def _crm_changes(self, accounts: pd.DataFrame) -> pd.DataFrame:
        """Customers move house, change email and flip marketing consent."""
        rows = []
        end = datetime(cfg.DATA_END.year, cfg.DATA_END.month, cfg.DATA_END.day, 23, 59, tzinfo=UTC)
        rates = {"address": 0.004, "email": 0.002, "marketing_opt_in": 0.010}
        for a in accounts.itertuples(index=False):
            start = max(a.created_at_utc, datetime(2023, 3, 14, tzinfo=UTC))
            months = (end - start).days / 30.4
            if months <= 0:
                continue
            for field_name, rate in rates.items():
                for _ in range(int(self.rng.poisson(rate * months))):
                    at = start + timedelta(seconds=int(self.rng.integers(0, int((end - start).total_seconds()))))
                    rows.append({"customer_id": a.customer_id, "changed_at_utc": at, "field": field_name})
        df = pd.DataFrame(rows).sort_values(["changed_at_utc", "customer_id", "field"], kind="stable")
        return df.reset_index(drop=True)

    def _to_world(self) -> World:
        persons = pd.DataFrame(self.persons)
        accounts = pd.DataFrame(self.accounts)
        orders = pd.DataFrame(self.orders)
        world = World(
            persons=persons,
            accounts=accounts,
            subscriptions=pd.DataFrame(self.subs),
            orders=orders,
            order_lines=pd.DataFrame(self.lines),
            transactions=pd.DataFrame(self.txns),
            shipments=pd.DataFrame(self.shipments),
            crm_changes=self._crm_changes(accounts),
            assignments=pd.DataFrame(self.assignments),
            fx=self.fx,
        )
        return world


def simulate(seed: int = cfg.SEED) -> World:
    return Simulator(seed).run()
