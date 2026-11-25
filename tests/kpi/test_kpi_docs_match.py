"""The numbers in the project 3 docs must be the numbers the committed files and validation hold.

CI regenerates the files and the validation and fails if they differ from the committed copies,
so checking the docs against the committed copies is enough.
"""
import json
import re
from pathlib import Path

from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P3 = ROOT / "project_03_kpi_pack"
S = json.loads((P3 / "validation" / "summary.json").read_text())
K = pd.read_csv(P3 / "data" / "kpi_monthly.csv", dtype={"month": str}).set_index("month")
# Excel rounds halves away from zero (4.635% shows as 4.64%); Python's float formatting may not.
pc = lambda x: str((Decimal(str(x)) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)) + "%"
flat = lambda p: re.sub(r"\s+", " ", p.read_text())
README, SUMMARY, RUNBOOK = flat(P3 / "README.md"), flat(P3 / "manager_summary.md"), flat(P3 / "runbook.md")


def test_validation_passed_and_counts():
    assert S["passed"]
    total = sum(r["values_compared"] for r in S["workbook_vs_warehouse"])
    assert f"{total} values compared, 0 mismatches" in README
    assert f"all {total} figures on the Summary sheet matched" in README
    assert len(S["checks_catch_tampering"]) == 3 and all(t["caught"] for t in S["checks_catch_tampering"])


def test_june_table():
    j, m, y = K.loc["2025-06"], K.loc["2025-05"], K.loc["2024-06"]
    rows = [
        f"| Active subscribers (people) | {int(j.active_subscribers):,} | {int(m.active_subscribers):,} | {int(y.active_subscribers):,} |",
        f"| Monthly churn rate | {pc(j.monthly_churn_rate)} | {pc(m.monthly_churn_rate)} | {pc(y.monthly_churn_rate)} |",
        f"| MRR, GBP | {j.mrr_gbp:,.0f} | {m.mrr_gbp:,.0f} | {y.mrr_gbp:,.0f} |",
        f"| Net revenue, GBP | {j.net_revenue_gbp:,.0f} | {m.net_revenue_gbp:,.0f} | {y.net_revenue_gbp:,.0f} |",
        f"| Late delivery rate | {pc(j.late_delivery_rate)} | {pc(m.late_delivery_rate)} | {pc(y.late_delivery_rate)} |",
    ]
    for r in rows:
        assert r in README, r


def test_manager_summary_figures():
    j, m, y = K.loc["2025-06"], K.loc["2025-05"], K.loc["2024-06"]
    for text in [f"{int(j.active_subscribers):,} active subscribers**, up {int(j.active_subscribers - m.active_subscribers)} on May "
                 f"and {j.active_subscribers / y.active_subscribers - 1:.1%} on June 2024",
                 f"Churn fell to {pc(j.monthly_churn_rate)}** from {pc(m.monthly_churn_rate)}",
                 f"MRR {j.mrr_gbp:,.0f} GBP**, {j.mrr_gbp / y.mrr_gbp - 1:.1%} above June 2024",
                 f"Net revenue {j.net_revenue_gbp:,.0f} GBP**, {j.net_revenue_gbp / y.net_revenue_gbp - 1:.1%} above",
                 f"{pc(j.late_delivery_rate)} of parcels arrived late**, up from {pc(y.late_delivery_rate)}"]:
        assert text in SUMMARY, text


def test_june_mrr_gap():
    gap = S["june_2025_mrr_gap"]["explained_gbp"]
    mrr = next(r for r in S["warehouse_vs_truth"] if r["metric"] == "mrr_gbp")
    assert mrr["differences"] == {"2025-06": gap}
    assert f"{gap:.2f} GBP higher than the truth" in README and f"{gap:.2f} GBP" in RUNBOOK
    assert f"restated by {round(gap)} GBP" in SUMMARY
    assert len(S["june_2025_mrr_gap"]["subscriptions"]) == 2


def test_paid_orders_and_exact_metrics():
    rows = {r["metric"]: r for r in S["warehouse_vs_truth"]}
    assert rows["paid_orders"]["differences"] == {"2025-06": -26.0} and "26 lower than the truth" in README
    for m in ("gross_revenue_gbp", "net_revenue_gbp", "late_delivery_rate", "active_subscription_accounts"):
        assert rows[m]["months_different"] == 0, m
    person = [rows[m]["months_different"] for m in ("active_subscribers", "new_subscribers", "churned_subscribers",
                                                     "monthly_churn_rate")]
    assert max(person) == 3 and "in at most three months" in README


def test_runbook_log_lines():
    man = pd.read_csv(P3 / "data" / "_manifest.csv")
    for r in man.itertuples():
        assert f"{r.file_name}: {r.rows} rows, net_revenue_gbp total {r.control_total:.2f}" in RUNBOOK


def test_revenue_without_country():
    u = S["revenue_without_country"]
    n = sum(v["transactions"] for v in u.values())
    assert f"- {n} transactions, mostly refunds" in README
    assert f"puts {u['EUR']['net_gbp']:.2f} GBP on Germany over 30 months" in README
