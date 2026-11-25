"""The numbers in the project 0 README must be the numbers this build produced."""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
GT = ROOT / "data" / "ground_truth"
README = ROOT / "project_00_data_generator" / "README.md"

pytestmark = pytest.mark.skipif(not (GT / "gt_build_summary.json").exists(), reason="no build; run make data")


def table_rows(text: str, first_header: str) -> list[list[str]]:
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"| {first_header} |"))
    rows = []
    for ln in lines[start + 2:]:
        if not ln.startswith("|"):
            break
        rows.append([c.strip().strip("`") for c in ln.strip("|").split("|")])
    return rows


def test_headline_counts():
    s = json.loads((GT / "gt_build_summary.json").read_text())
    text = README.read_text()
    for key in ("persons", "accounts", "persons_with_multiple_accounts", "subscriptions", "orders",
                "transactions", "shipments", "experiment_assignments", "raw_files", "defect_records",
                "persons_with_account", "duplicate_accounts"):
        assert f"{s[key]:,}" in text, key
    assert f"{s['raw_megabytes']} MB" in text
    by_source = {r[0].split(" ")[0].strip("`"): int(r[1].replace(",", "")) for r in table_rows(text, "Source")}
    assert by_source == s["files_by_source"]


def test_defect_table():
    d = pd.read_csv(GT / "gt_defects.csv")
    rows = table_rows(README.read_text(), "Code")
    assert {r[0] for r in rows} == set(d["defect_code"])
    for code, _src, _what, records, files in rows:
        sub = d[d["defect_code"] == code]
        assert int(records.replace(",", "")) == len(sub), code
        assert int(files.replace(",", "")) == sub["file_name"].nunique(), code


def test_metric_table():
    m = pd.read_csv(GT / "gt_monthly_metrics.csv").set_index("month")
    for month, act, acc, churn, mrr, rev, late in table_rows(README.read_text(), "Month"):
        row = m.loc[month]
        num = lambda v: float(re.sub(r"[,%]", "", v))
        assert num(act) == row["active_subscribers"]
        assert num(acc) == row["active_subscription_accounts"]
        assert round(row["monthly_churn_rate"] * 100, 2) == num(churn)
        assert num(mrr) == row["mrr_gbp"]
        assert num(rev) == row["net_revenue_gbp"]
        assert round(row["late_delivery_rate"] * 100, 2) == num(late)
