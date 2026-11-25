"""The numbers in the project 1 docs must be the numbers the last validation run produced.

CI regenerates `validation/summary.json` and fails if it differs from the committed copy, so
checking the docs against the committed copy is enough.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P1 = ROOT / "project_01_ingestion"
SUMMARY = json.loads((P1 / "validation" / "summary.json").read_text())
H = SUMMARY["headline"]
README = (P1 / "README.md").read_text()


def money(v: float, sign: bool = False) -> str:
    s = f"{abs(v):,.2f}"
    return (("+" if v >= 0 else "-") + s) if sign else s


def test_validation_passed():
    assert SUMMARY["passed"]


def test_bridge_table():
    answer = README.split("## The answer")[1].split("\n## ")[0]
    lines = [ln for ln in answer.splitlines() if re.match(r"\| [0-7] \|", ln)]
    values = [ln.rstrip(" |").rsplit("|", 1)[1].strip() for ln in lines]
    steps = ["step1_duplicate_loads", "step2_test_orders", "step3_unpaid_orders", "step4_capture_month",
             "step5_daily_fx", "step6_refunds_chargebacks", "step7_vat"]
    assert values == [money(H["bi_reported_gbp"])] + [money(H[s], sign=True) for s in steps]
    assert f"| | Net revenue | {money(H['net_revenue_gbp'])} |" in README


def test_headline_figures():
    gap = H["bi_reported_gbp"] - H["net_revenue_gbp"]
    for s in (money(gap), f"{H['bi_over_net_total_pct']}%", f"{H['bi_over_net_min_pct']}%",
              f"{H['bi_over_net_max_pct']}%", money(H["largest_monthly_step4_gbp"]), money(H["residual_gbp"])):
        assert s in README, s
    for step, share in (("step7_vat", 57), ("step6_refunds_chargebacks", 21), ("step3_unpaid_orders", 19),
                        ("step1_duplicate_loads", 2)):
        assert round(-H[step] / gap * 100) == share and f"{share}%" in README, step


def test_manager_summary_rounds_the_same_numbers():
    text = (P1 / "manager_summary.md").read_text()
    for key in ("bi_reported_gbp", "net_revenue_gbp", "step7_vat", "step6_refunds_chargebacks",
                "step3_unpaid_orders", "step1_duplicate_loads", "step2_test_orders"):
        assert f"{abs(H[key]):,.0f} GBP" in text, key
    assert f"{H['bi_reported_gbp'] - H['net_revenue_gbp']:,.0f} GBP" in text
    assert f"{H['bi_over_net_total_pct']}%" in text
    assert f"{H['largest_monthly_step4_gbp']:,.0f} GBP" in text


def test_arrivals_and_rejects():
    a, r = H["arrivals"], H["rejects"]
    pay_days = a["payproc_on_time"] + a["payproc_late"] + a["payproc_missing"]
    ful_weeks = a["ful_on_time"] + a["ful_late"]
    assert f"{a['payproc_late'] + a['payproc_missing']} of {pay_days} processor days" in README
    assert f"{a['ful_late']} of {ful_weeks} fulfilment weeks" in README
    assert f"There\nare {sum(r.values())} in total" in README or f"are {sum(r.values())} in total" in README
    for key, n in r.items():
        assert str(n) in README, key


def test_check_details_quoted_in_readme():
    details = {c["check"]: c["detail"] for c in SUMMARY["checks"]}
    assert details["rows balance per file"].split("; ")[1] in README
    for n in re.findall(r"\d[\d,]*", details["defects: every in-scope defect found"]):
        assert n in README


def test_replay_table_matches_replay_report():
    rep = (P1 / "validation" / "replay.md").read_text()
    for ln in rep.splitlines():
        m = re.match(r"\| (\d) \| ([^|]+) \| ([\d,]+) \| ([\d,]+) \|", ln)
        if m:
            assert f"| {m[1]} | {m[2].strip()} | {m[3]} | {m[4]} |" in README, ln
    assert "PASS" in rep
