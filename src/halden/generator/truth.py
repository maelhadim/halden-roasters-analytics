"""Monthly KPIs computed from the true history, using the definitions in docs/metrics.md.

These are the numbers a perfect pipeline would report. Later projects are
scored against them, so any change here must also change docs/metrics.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import config as cfg
from .calendar import UTC

FORTNIGHTLY_TO_MONTHLY = 26 / 12


def fx_lookup(fx: pd.DataFrame, dates: pd.Series) -> np.ndarray:
    """GBP per EUR for each date: the latest published rate on or before that date."""
    rates = fx.sort_values("rate_date")
    idx = np.searchsorted(rates["rate_date"].to_numpy(), dates.to_numpy(), side="right") - 1
    if (idx < 0).any():
        raise ValueError("a date falls before the first FX rate")
    return rates["gbp_per_eur"].to_numpy()[idx]


def to_gbp(amount: pd.Series, currency: pd.Series, rate: np.ndarray) -> pd.Series:
    return pd.Series(np.where(currency.to_numpy() == "EUR", amount.to_numpy() * rate, amount.to_numpy()),
                     index=amount.index)


def month_ends() -> list[datetime]:
    out = []
    m = pd.Period(cfg.DATA_START, "M") - 1
    while m <= pd.Period(cfg.DATA_END, "M"):
        last = m.end_time.date()
        out.append(datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=UTC))
        m += 1
    return out


def monthly_metrics(world) -> pd.DataFrame:
    subs = world.subscriptions
    ends = month_ends()
    started = subs["started_at_utc"]
    ended = subs["ended_at_utc"]
    active_people, active_accounts, mrr = [], [], []
    plan_price_cols = {}
    for ts in ends:
        mask = (started <= ts) & (ended.isna() | (ended > ts))
        act = subs[mask]
        active_people.append(set(act["person_id"]))
        active_accounts.append(act["customer_id"].nunique())
        # List price at month end, VAT removed, monthly-normalised, converted at the month-end rate.
        rate = fx_lookup(world.fx, pd.Series([ts.date()]))[0]
        total = 0.0
        country = world.accounts.set_index("customer_id")["country_code"]
        for row in act.itertuples(index=False):
            c = cfg.COUNTRY_BY_CODE[country[row.customer_id]]
            plan = cfg.PLAN_BY_CODE[row.plan_code]
            pair = plan.gbp if c.currency == "GBP" else plan.eur
            price = pair[1] if ts.date() >= cfg.PRICE_INCREASE_DATE else pair[0]
            price = price / (1 + c.vat_rate)
            if row.frequency == "FORTNIGHTLY":
                price *= FORTNIGHTLY_TO_MONTHLY
            total += price * (rate if c.currency == "EUR" else 1.0)
        mrr.append(round(total, 2))

    tx = world.transactions.copy()
    test_orders = set(world.orders.loc[world.orders["is_test"], "order_id"])
    tx = tx[tx["txn_type"].isin(["CAPTURE", "REFUND", "CHARGEBACK"]) & ~tx["order_id"].isin(test_orders)]
    tx_date = tx["txn_at_utc"].dt.date
    rate = fx_lookup(world.fx, tx_date)
    gbp = to_gbp(tx["gross_amount"], tx["currency_code"], rate) / (1 + tx["vat_rate"])
    tx = tx.assign(month=tx["txn_at_utc"].dt.strftime("%Y-%m"), net_gbp_ex_vat=gbp)
    revenue = tx.groupby("month")["net_gbp_ex_vat"].sum()
    gross = tx[tx["txn_type"] == "CAPTURE"].groupby("month")["net_gbp_ex_vat"].sum()

    orders = world.orders[(world.orders["status"] == "PAID") & ~world.orders["is_test"]]
    order_counts = orders.groupby(orders["created_at_utc"].dt.strftime("%Y-%m")).size()

    sh = world.shipments[world.shipments["delivered_date"].notna()].copy()
    sh["month"] = pd.to_datetime(sh["delivered_date"]).dt.strftime("%Y-%m")
    late = sh.groupby("month")["is_late"].mean()

    rows = []
    for i in range(1, len(ends)):
        month = ends[i].strftime("%Y-%m")
        prev, cur = active_people[i - 1], active_people[i]
        churned = len(prev - cur)
        rows.append({
            "month": month,
            "active_subscribers": len(cur),
            "active_subscription_accounts": active_accounts[i],
            "new_subscribers": len(cur - prev),
            "churned_subscribers": churned,
            "monthly_churn_rate": round(churned / len(prev), 5) if prev else None,
            "mrr_gbp": mrr[i],
            "gross_revenue_gbp": round(float(gross.get(month, 0.0)), 2),
            "net_revenue_gbp": round(float(revenue.get(month, 0.0)), 2),
            "paid_orders": int(order_counts.get(month, 0)),
            "late_delivery_rate": round(float(late.get(month, 0.0)), 5),
        })
    return pd.DataFrame(rows)
