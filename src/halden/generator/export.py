"""Write the true history out the way each source system really sends it.

Each exporter owns one source system. It formats the data the way that system
does (delimiter, encoding, date format, file cadence), then applies that
system's known defects and records each one in the defect log.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg
from .calendar import LONDON, UTC, utc_to_london_naive
from .defects import DefectLog

log = logging.getLogger(__name__)

SKU_WEIGHT_KG = {"CLASSIC_250": 0.30, "EXPLORER_2X250": 0.58, "ESPRESSO_1KG": 1.08,
                 "BEANS_250_SINGLE_ORIGIN": 0.30, "BEANS_1KG_HOUSE": 1.08, "GIFT_BOX_3X250": 0.95,
                 "HAND_GRINDER": 0.72, "POUR_OVER_KIT": 0.85, "MUG_SET": 1.10}

OTHER_REASON_TEXT = (
    'Other: moving abroad, will be back',
    'Other: "decaf" range too small',
    'Other: boxes too big for letterbox, neighbours keep taking them',
    'Other: bought a bean-to-cup machine, needs different roast',
)
CRM_NOTES = (
    "Prefers deliveries left with neighbour",
    "Leave parcel in porch\nNot in the bin store",
    "Called about grinder settings",
    "VIP - founder's friend",
    "Gift subscription paid by\tparent",
    "Asked for invoice with company name",
    "Allergic to hazelnut flavourings, no flavoured samples",
)


@dataclass
class Landing:
    rows: list = field(default_factory=list)

    def write(self, root: Path, source: str, name: str, data: bytes, business_date: date,
              received_at: datetime):
        folder = root / source
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
        self.rows.append({"file_name": name, "source": source, "business_date": business_date.isoformat(),
                          "received_at_utc": received_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})


def _at(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


def _is_ambiguous(local: datetime) -> bool:
    a = local.replace(tzinfo=LONDON, fold=0).utcoffset()
    b = local.replace(tzinfo=LONDON, fold=1).utcoffset()
    return a != b


def _csv_text(df: pd.DataFrame, sep: str = ",", line_end: str = "\n") -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=sep, lineterminator=line_end, quoting=csv.QUOTE_MINIMAL)
    return buf.getvalue()


class Exporter:
    def __init__(self, world, raw_root: Path, seed: int):
        self.w = world
        self.root = raw_root
        self.rng = np.random.default_rng(seed + 1)
        self.defects = DefectLog()
        self.landing = Landing()
        self.accounts = world.accounts.set_index("customer_id")
        self.persons = world.persons.set_index("person_id")

    def run(self):
        self.shop_orders()
        self.shop_subscriptions()
        self.payproc()
        self.fulfilment()
        self.crm()
        self.experiment()
        self.fx()
        lp = self.root / "_landing_log.csv"
        pd.DataFrame(self.landing.rows).sort_values(["source", "file_name"]).to_csv(lp, index=False)
        return self.defects, self.landing

    # ------------------------------------------------------------------ shop
    def shop_orders(self):
        o = self.w.orders.copy()
        lines = self.w.order_lines
        items = (lines.assign(item=lines["sku"] + ":" + lines["quantity"].astype(str))
                 .groupby("order_id")["item"].agg(";".join))
        o["line_items"] = o["order_id"].map(items)
        subs = self.w.subscriptions.set_index("subscription_id")
        o["plan_code"] = o["subscription_id"].map(subs["plan_code"]).fillna("")
        # Contact details as the shop holds them: the account for members, the person for guests.
        acc = self.accounts
        is_member = o["customer_id"].notna()
        for col, src in (("first_name", "first_name"), ("last_name", "last_name"), ("phone", "phone"),
                         ("billing_postcode", "postcode"), ("billing_city", "city")):
            o[col] = np.where(is_member, o["customer_id"].map(acc[src]), o["person_id"].map(self.persons[src]))
        o["email"] = np.where(is_member, o["customer_id"].map(acc["email"]), o["guest_email"])
        test_mask = o["is_test"]
        o.loc[test_mask, ["first_name", "last_name"]] = ["QA", "Checkout"]
        local = o["created_at_utc"].map(utc_to_london_naive)
        o["local_ts"] = local
        o["local_date"] = local.map(lambda t: t.date())
        o["created_at"] = local.map(lambda t: t.strftime("%Y-%m-%d %H:%M:%S"))
        o["customer_id"] = o["customer_id"].fillna("")
        o["subscription_id"] = o["subscription_id"].fillna("")
        cols = ["order_id", "created_at", "customer_id", "email", "first_name", "last_name", "phone",
                "billing_postcode", "billing_city", "country_code", "currency_code", "order_type",
                "subscription_id", "plan_code", "line_items", "subtotal_amount", "discount_code",
                "discount_amount", "shipping_amount", "vat_amount", "total_amount"]
        money = ["subtotal_amount", "discount_amount", "shipping_amount", "vat_amount", "total_amount"]
        for c in money:
            o[c] = o[c].map(lambda v: f"{v:.2f}")
        o = o.sort_values(["local_ts", "order_id"], kind="stable")

        excel_week = (date(2023, 10, 2), date(2023, 10, 8))
        trailing_month = (date(2023, 6, 1), date(2023, 6, 30))
        truncated_day = date(2024, 3, 18)
        for d, day in o.groupby("local_date", sort=True):
            if d > cfg.DATA_END:
                continue
            name = f"shop_orders_{d:%Y%m%d}.csv"
            day = day.copy()
            for r in day[day["is_test"]].itertuples():
                self.defects.add("SHOP_TEST_ORDER", name, r.order_id)
            for r in day[day["local_ts"].map(_is_ambiguous)].itertuples():
                self.defects.add("SHOP_AMBIGUOUS_LOCAL_TIME", name, r.order_id, r.created_at)
            blank = self.rng.random(len(day)) < 0.015
            for oid in day.loc[blank, "order_id"]:
                self.defects.add("SHOP_MISSING_POSTCODE", name, oid)
            day.loc[blank, "billing_postcode"] = ""
            messy = self.rng.random(len(day)) < 0.005
            for idx in day.index[messy]:
                e = day.at[idx, "email"]
                day.at[idx, "email"] = (" " + e.upper()) if self.rng.random() < 0.5 else (e + " ")
                self.defects.add("SHOP_EMAIL_FORMATTING", name, day.at[idx, "order_id"])
            bug = cfg.SHOP_DATE_FORMAT_BUG[0] <= d <= cfg.SHOP_DATE_FORMAT_BUG[1]
            excel = excel_week[0] <= d <= excel_week[1]
            if bug or excel:
                day["created_at"] = day["local_ts"].map(lambda t: t.strftime("%d/%m/%Y %H:%M"))
                for oid in day["order_id"]:
                    self.defects.add("SHOP_DATE_FORMAT", name, oid, "excel re-save" if excel else "platform update")
            if excel:
                def sci(p):
                    digits = "".join(ch for ch in p if ch.isdigit())
                    return f"{float(digits):.5E}" if digits else p
                day["phone"] = day["phone"].map(sci)
                for oid in day["order_id"]:
                    self.defects.add("SHOP_PHONE_SCIENTIFIC", name, oid)
            out = day[cols]
            text = _csv_text(out)
            if trailing_month[0] <= d <= trailing_month[1]:
                text = "\n".join(line + "," if line else line for line in text.split("\n"))
                self.defects.add("SHOP_TRAILING_DELIMITER", name, "*")
            if self.rng.random() < 0.02:
                text += "\n\n"
                self.defects.add("SHOP_BLANK_LINES", name, "*")
            received = _at(d + timedelta(days=1), 1, int(self.rng.integers(5, 40)))
            if d == truncated_day:
                full = _csv_text(out, line_end="\r\n").encode("utf-8")
                rows = text.split("\n")
                keep = len(rows) - 15
                cut = "\n".join(rows[:keep]) + "\n" + rows[keep][: len(rows[keep]) // 2]
                for oid in out["order_id"].iloc[keep - 1:]:
                    self.defects.add("SHOP_TRUNCATED_FILE", name, oid)
                self.landing.write(self.root, "shop", name, cut.encode("utf-8"), d, received)
                rname = f"shop_orders_{d:%Y%m%d}_resend.csv"
                for oid in out["order_id"]:
                    self.defects.add("SHOP_RESEND", rname, oid)
                self.landing.write(self.root, "shop", rname, full, d, received + timedelta(hours=31))
                continue
            self.landing.write(self.root, "shop", name, text.encode("utf-8"), d, received)

    def shop_subscriptions(self):
        s = self.w.subscriptions
        acc = self.accounts
        start_ts = datetime(2023, 1, 1, tzinfo=UTC)
        snap = s[(s["started_at_utc"] < start_ts) & (s["ended_at_utc"].isna() | (s["ended_at_utc"] >= start_ts))]
        snap_out = pd.DataFrame({
            "subscription_id": snap["subscription_id"], "customer_id": snap["customer_id"],
            "status": "ACTIVE", "plan_code": snap["plan_code"], "frequency": snap["frequency"],
            "started_at": snap["started_at_utc"].map(lambda t: utc_to_london_naive(t).strftime("%Y-%m-%d %H:%M:%S")),
        })
        self.landing.write(self.root, "shop", "shop_subscriptions_20230101_full.csv",
                           _csv_text(snap_out).encode("utf-8"), date(2023, 1, 1), _at(date(2023, 1, 1), 3))
        events = []
        for r in s.itertuples(index=False):
            if r.started_at_utc >= start_ts:
                events.append((r.started_at_utc, r.subscription_id, r.customer_id, "CREATED", r.plan_code,
                               r.frequency, ""))
            if pd.notna(r.end_type):
                reason = r.cancel_reason if isinstance(r.cancel_reason, str) else ""
                events.append((r.ended_at_utc, r.subscription_id, r.customer_id, r.end_type, r.plan_code,
                               r.frequency, reason))
        ev = pd.DataFrame(events, columns=["ts", "subscription_id", "customer_id", "event_type", "plan_code",
                                           "frequency", "cancel_reason"])
        ev = ev.sort_values(["ts", "subscription_id", "event_type"], kind="stable").reset_index(drop=True)
        ev["event_id"] = [f"E{i + 1:07d}" for i in range(len(ev))]
        local = ev["ts"].map(utc_to_london_naive)
        ev["event_at"] = local.map(lambda t: t.strftime("%Y-%m-%d %H:%M:%S"))
        ev["file_date"] = local.map(lambda t: t.date())
        is_cancel = ev["event_type"] == "CANCELLED"
        late = is_cancel & (self.rng.random(len(ev)) < 0.01)
        ev.loc[late, "file_date"] = ev.loc[late, "file_date"].map(lambda d: d + timedelta(days=1))
        other = is_cancel & (ev["cancel_reason"] == "Other") & (self.rng.random(len(ev)) < 0.5)
        ev.loc[other, "cancel_reason"] = [OTHER_REASON_TEXT[int(i)] for i in
                                          self.rng.integers(0, len(OTHER_REASON_TEXT), int(other.sum()))]
        cols = ["event_id", "event_at", "subscription_id", "customer_id", "event_type", "plan_code", "frequency",
                "cancel_reason"]
        for d, day in ev.groupby("file_date", sort=True):
            if d > cfg.DATA_END:
                continue
            name = f"shop_subscriptions_{d:%Y%m%d}.csv"
            for r in day[late.loc[day.index]].itertuples():
                self.defects.add("SUBS_LATE_EVENT", name, r.event_id, r.subscription_id)
            for r in day[other.loc[day.index]].itertuples():
                self.defects.add("SUBS_REASON_QUOTED", name, r.event_id)
            self.landing.write(self.root, "shop", name, _csv_text(day[cols]).encode("utf-8"), d,
                               _at(d + timedelta(days=1), 1, int(self.rng.integers(40, 59))))

    # --------------------------------------------------------------- payproc
    def payproc(self):
        t = self.w.transactions.copy()
        t["txn_date"] = t["txn_at_utc"].dt.date
        t = t[t["txn_date"] <= cfg.DATA_END].sort_values(["txn_at_utc", "txn_id"], kind="stable")
        missing_day = date(2024, 9, 12)
        t.loc[t["txn_date"] == missing_day, "file_date"] = missing_day + timedelta(days=1)
        t["file_date"] = t["file_date"].fillna(t["txn_date"]) if "file_date" in t else t["txn_date"]
        known_orders = set(self.w.orders["order_id"])
        days = sorted(t["file_date"].unique())
        dup_days = set(self.rng.choice(len(days), size=3, replace=False).tolist())
        late_days = set(self.rng.choice(len(days), size=4, replace=False).tolist())
        for i, d in enumerate(days):
            day = t[t["file_date"] == d]
            v2 = d >= cfg.PROCESSOR_SCHEMA_CHANGE
            name = f"payproc_transactions_{d:%Y%m%d}.txt"
            recs = []
            for r in day.itertuples(index=False):
                sd = r.settlement_date.strftime("%Y-%m-%d") if pd.notna(r.settlement_date) else ""
                ts = r.txn_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                if v2:
                    recs.append(["D", r.txn_id, r.order_id, r.txn_type, ts, r.currency_code,
                                 f"{r.gross_amount:.2f}", f"{r.fee_amount:.2f}", f"{r.net_amount:.2f}", sd,
                                 r.card_country, r.decline_code])
                else:
                    recs.append(["D", r.txn_id, r.txn_type, r.order_id, ts, r.currency_code,
                                 f"{r.gross_amount:.2f}", f"{r.fee_amount:.2f}", sd, r.card_country,
                                 r.decline_code])
                if r.order_id not in known_orders:
                    self.defects.add("PAYPROC_UNLINKED_REFUND", name, r.txn_id, r.order_id)
            trailer = ["T", str(len(recs)), f"{day['gross_amount'].sum():.2f}"]
            if i in dup_days:
                for j in sorted(self.rng.choice(len(recs), size=5, replace=False).tolist(), reverse=True):
                    recs.insert(j + 1, list(recs[j]))
                    self.defects.add("PAYPROC_DUPLICATE_ROW", name, recs[j][1])
            if d == missing_day + timedelta(days=1):
                self.defects.add("PAYPROC_MISSING_DAY", name, missing_day.isoformat(),
                                 "no file for 2024-09-12; its rows are in this file")
            if v2 and d == cfg.PROCESSOR_SCHEMA_CHANGE:
                self.defects.add("PAYPROC_SCHEMA_CHANGE", name, "*")
            lines = ["|".join(["H", f"{d:%Y%m%d}", "v2" if v2 else "v1"])] + ["|".join(x) for x in recs]
            lines.append("|".join(trailer))
            received = _at(d + timedelta(days=1), 5, int(self.rng.integers(0, 50)))
            if i in late_days:
                received += timedelta(hours=int(self.rng.integers(26, 51)))
                self.defects.add("PAYPROC_LATE_FILE", name, "*", received.isoformat())
            self.landing.write(self.root, "payproc", name, ("\n".join(lines) + "\n").encode("ascii"), d, received)

    # ------------------------------------------------------------- fulfilment
    def fulfilment(self):
        sh = self.w.shipments
        lines = self.w.order_lines
        weight = (lines.assign(kg=lines["sku"].map(SKU_WEIGHT_KG) * lines["quantity"])
                  .groupby("order_id")["kg"].sum())
        orders = self.w.orders.set_index("order_id")
        ev = []
        for r in sh.itertuples(index=False):
            base = {"shipment_no": r.shipment_no, "order_id": r.order_id, "site": r.site_code,
                    "recipient": r.recipient_name, "country": r.country_code, "dispatch": r.dispatch_date,
                    "promised": r.promised_date, "kg": weight.get(r.order_id, 0.3)}
            ev.append({**base, "status": "VERSANDT", "status_date": r.dispatch_date, "delivered": None})
            if pd.notna(r.delivered_date):
                ev.append({**base, "status": "ZUGESTELLT", "status_date": r.delivered_date,
                           "delivered": r.delivered_date})
            elif pd.notna(r.lost_declared_date):
                ev.append({**base, "status": "VERLOREN", "status_date": r.lost_declared_date, "delivered": None})
        ev = pd.DataFrame(ev)
        ev = ev[ev["status_date"] <= cfg.DATA_END]
        cust = orders["customer_id"]
        ev["kundennr"] = ev["order_id"].map(cust).map(lambda c: c[1:] if isinstance(c, str) else "")
        ev["week"] = ev["status_date"].map(lambda d: d - timedelta(days=d.weekday()))
        ev = ev.sort_values(["status_date", "shipment_no", "status"], kind="stable")
        fmt = lambda d: d.strftime("%d.%m.%Y") if d is not None and not pd.isna(d) else ""
        weeks = sorted(ev["week"].unique())
        carry: list[dict] = []
        correction_week = date(2024, 5, 20)
        for w in weeks:
            day = ev[ev["week"] == w]
            name = f"ful_shipments_{w:%Y%m%d}.csv"
            rows = []
            for r in day.itertuples(index=False):
                rows.append({"Sendungsnr": r.shipment_no, "Auftragsnr": r.order_id, "Kundennr": r.kundennr,
                             "Standort": r.site, "Empfaenger": r.recipient, "Land": r.country,
                             "Versanddatum": fmt(r.dispatch), "Soll_Lieferdatum": fmt(r.promised),
                             "Lieferdatum": fmt(r.delivered), "Status": r.status,
                             "Statusdatum": fmt(r.status_date), "Gewicht_kg": f"{r.kg:.2f}".replace(".", ",")})
            for c in carry:
                self.defects.add("FUL_DUPLICATE_EVENT", name, c["Sendungsnr"], c["Status"])
            rows = rows + carry
            carry = [dict(x) for x in rows if x["Status"] == "ZUGESTELLT" and self.rng.random() < 0.003
                     and x not in carry]
            received = _at(w + timedelta(days=8), 9, int(self.rng.integers(0, 59)))
            if any(date(y, 12, 25) - timedelta(days=6) <= w <= date(y, 12, 25) for y in (2023, 2024)):
                received = _at(date(w.year + 1, 1, 3), 10)
                self.defects.add("FUL_LATE_FILE", name, "*", received.isoformat())
            if w == correction_week:
                bad = [dict(x) for x in rows]
                for x in bad:
                    if x["Standort"] == "HAM" and x["Status"] == "ZUGESTELLT":
                        dd = datetime.strptime(x["Lieferdatum"], "%d.%m.%Y").date() + timedelta(days=1)
                        x["Lieferdatum"] = fmt(dd)
                        x["Statusdatum"] = fmt(dd)
                        if self.rng.random() < 0.3:
                            kg = float(x["Gewicht_kg"].replace(",", ".")) * 2
                            x["Gewicht_kg"] = f"{kg:.2f}".replace(".", ",")
                        self.defects.add("FUL_CORRECTED_FILE", name, x["Sendungsnr"], "v1 wrong; see _v2")
                self.landing.write(self.root, "ful", name, self._ful_bytes(bad, name), w, received)
                v2 = f"ful_shipments_{w:%Y%m%d}_v2.csv"
                self.landing.write(self.root, "ful", v2, self._ful_bytes(rows, v2), w, received + timedelta(days=2))
                continue
            self.landing.write(self.root, "ful", name, self._ful_bytes(rows, name), w, received)

    def _ful_bytes(self, rows: list[dict], name: str) -> bytes:
        df = pd.DataFrame(rows)
        self.defects.add("FUL_ENCODING_CP1252", name, "*")
        for x in rows:
            enc = x["Empfaenger"].encode("cp1252", errors="replace").decode("cp1252")
            if enc != x["Empfaenger"]:
                self.defects.add("FUL_UNMAPPABLE_CHAR", name, x["Sendungsnr"], x["Empfaenger"])
        text = _csv_text(df, sep=";", line_end="\r\n")
        return text.encode("cp1252", errors="replace")

    # -------------------------------------------------------------------- crm
    def crm(self):
        acc = self.w.accounts.copy().sort_values("created_at_utc", kind="stable")
        changes = self.w.crm_changes
        people_factory_rng = np.random.default_rng(int(self.rng.integers(0, 2**31)))
        from .identities import PersonFactory
        pf = PersonFactory(people_factory_rng, cfg.SEED + 7)
        # A new address must not be someone else's.
        pf.mailbox_owner = {e.lower(): p for e, p in zip(self.w.persons["email"], self.w.persons["person_id"])}
        pf.mailbox_owner.update({e.lower(): p for e, p in zip(acc["email"], acc["person_id"])})
        state = {}
        for a in acc.itertuples(index=False):
            note = ""
            if self.rng.random() < 0.03:
                note = CRM_NOTES[int(self.rng.integers(len(CRM_NOTES)))]
            state[a.customer_id] = {
                "customer_id": a.customer_id, "legacy_id": a.legacy_id if isinstance(a.legacy_id, str) else "", "first_name": a.first_name,
                "last_name": a.last_name, "email": a.email, "phone": a.phone, "street": a.street,
                "city": a.city, "postcode": a.postcode, "country_code": a.country_code,
                "marketing_opt_in": "Y" if a.marketing_opt_in else "N",
                "created_at": a.created_at_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": a.created_at_utc.strftime("%Y-%m-%d %H:%M:%S"), "notes": note,
                "_created": a.created_at_utc,
            }
        stray = set(acc["customer_id"].iloc[self.rng.choice(len(acc), size=6, replace=False)].tolist())

        acc_person = dict(zip(acc["customer_id"], acc["person_id"]))
        person_first: dict[str, str] = {}
        for a in acc.itertuples(index=False):
            person_first.setdefault(a.person_id, a.customer_id)

        migration_cut = datetime(2023, 3, 13, 23, 59, 59, tzinfo=UTC)
        periods = [(datetime(2023, 3, 14, tzinfo=UTC), "crm_customers_20230314.txt")]
        m = date(2023, 4, 1)
        while m <= cfg.DATA_END:
            periods.append((datetime(m.year, m.month, 1, tzinfo=UTC), f"crm_customers_{m:%Y%m%d}.txt"))
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)

        def apply_changes(upto: datetime, frm: datetime) -> set:
            touched = set()
            sel = changes[(changes["changed_at_utc"] >= frm) & (changes["changed_at_utc"] < upto)]
            for c in sel.itertuples(index=False):
                st = state[c.customer_id]
                if c.changed_at_utc < st["_created"]:
                    continue
                if c.field == "address":
                    st.update(pf.new_address(st["country_code"]))
                elif c.field == "email":
                    person = {"first_name": st["first_name"], "last_name": st["last_name"], "email": st["email"],
                              "country_code": st["country_code"], "person_id": acc_person[c.customer_id]}
                    st["email"] = pf.other_email(person, work=False)
                else:
                    st["marketing_opt_in"] = "N" if st["marketing_opt_in"] == "Y" else "Y"
                st["updated_at"] = c.changed_at_utc.strftime("%Y-%m-%d %H:%M:%S")
                touched.add(c.customer_id)
            return touched

        snap_ids = acc.loc[acc["created_at_utc"] <= migration_cut, "customer_id"].tolist()
        self._crm_write("crm_customers_20230313_full.txt", [state[c] for c in snap_ids], date(2023, 3, 13),
                        _at(date(2023, 3, 14), 7), stray, person_first)
        for i, (start, name) in enumerate(periods):
            end = periods[i + 1][0] if i + 1 < len(periods) else datetime(2025, 7, 1, tzinfo=UTC)
            touched = apply_changes(end, start)
            new = acc.loc[(acc["created_at_utc"] >= start) & (acc["created_at_utc"] < end)
                          & (acc["created_at_utc"] > migration_cut), "customer_id"].tolist()
            ids = list(dict.fromkeys(new + sorted(touched)))
            recs = [state[c] for c in ids]
            self._crm_write(name, recs, start.date(), _at(end.date(), 7, int(self.rng.integers(0, 30))), stray,
                            person_first)

    def _crm_write(self, name, recs, business_date, received, stray, person_first):
        cols = ["customer_id", "legacy_id", "first_name", "last_name", "email", "phone", "street", "city",
                "postcode", "country_code", "marketing_opt_in", "created_at", "updated_at", "notes"]
        buf = io.StringIO()
        wr = csv.writer(buf, delimiter="\t", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
        wr.writerow(cols)
        id_to_person = self.w.accounts.set_index("customer_id")["person_id"]
        for r in recs:
            vals = [r[c] for c in cols]
            if r["notes"] and any(ch in r["notes"] for ch in "\n\t"):
                self.defects.add("CRM_EMBEDDED_NEWLINE", name, r["customer_id"])
            first = person_first[id_to_person[r["customer_id"]]]
            if first != r["customer_id"]:
                self.defects.add("CRM_DUPLICATE_PERSON", name, r["customer_id"], f"same person as {first}")
            if r["customer_id"] in stray:
                vals[-1] = '"Customer says: best coffee ever'
                buf.write("\t".join(vals) + "\r\n")
                self.defects.add("CRM_STRAY_QUOTE", name, r["customer_id"])
                continue
            wr.writerow(vals)
        self.landing.write(self.root, "crm", name, b"\xff\xfe" + buf.getvalue().encode("utf-16-le"),
                           business_date, received)

    # ------------------------------------------------------------- experiment
    def experiment(self):
        a = self.w.assignments.copy().sort_values(["assigned_at_utc", "customer_id"], kind="stable")
        a["event_id"] = [f"evt_{i + 1:08d}" for i in range(len(a))]
        a["day"] = a["assigned_at_utc"].dt.date
        outage = (a["day"] >= cfg.EXPERIMENT_LOG_OUTAGE[0]) & (a["day"] <= cfg.EXPERIMENT_LOG_OUTAGE[1])
        lost = outage & (a["variant"] == "treatment") & (self.rng.random(len(a)) < cfg.EXPERIMENT.log_loss_share_in_outage)
        a["logged"] = ~lost
        self.w.assignments["logged"] = a.sort_index()["logged"].values
        self.w.assignments["event_id"] = a.sort_index()["event_id"].values
        both = a.groupby("person_id")["variant"].nunique()
        both_people = set(both[both > 1].index)
        for d, day in a.groupby("day", sort=True):
            name = f"exp_assignments_{d:%Y%m%d}.jsonl"
            out = []
            for r in day.itertuples(index=False):
                if r.person_id in both_people:
                    self.defects.add("EXP_PERSON_BOTH_ARMS", name, r.event_id, r.customer_id)
                if not r.logged:
                    self.defects.add("EXP_LOG_OUTAGE", name, r.event_id, r.customer_id)
                    continue
                line = json.dumps({"event_id": r.event_id, "event_type": "assignment",
                                   "experiment_id": cfg.EXPERIMENT_ID, "customer_id": r.customer_id,
                                   "variant": r.variant,
                                   "event_ts": r.assigned_at_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
                                  separators=(",", ":"))
                out.append(line)
                if self.rng.random() < 0.005:
                    out.append(line)
                    self.defects.add("EXP_DUPLICATE_EVENT", name, r.event_id)
            self.landing.write(self.root, "exp", name, ("\n".join(out) + "\n").encode("utf-8"), d,
                               _at(d + timedelta(days=1), 0, 10))

    def fx(self):
        fx = self.w.fx.copy()
        fx["month"] = fx["rate_date"].map(lambda d: date(d.year, d.month, 1))
        for m, g in fx.groupby("month", sort=True):
            out = pd.DataFrame({"rate_date": g["rate_date"].map(lambda d: d.isoformat()),
                                "base_currency": "EUR", "quote_currency": "GBP",
                                "rate": g["gbp_per_eur"].map(lambda v: f"{v:.5f}")})
            last = g["rate_date"].max()
            self.landing.write(self.root, "fx", f"fx_eurgbp_{m:%Y%m%d}.csv", _csv_text(out).encode("utf-8"), m,
                               _at(last + timedelta(days=1), 16))
