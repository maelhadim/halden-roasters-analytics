"""The numbers in the project 2 docs must be the numbers the last validation run produced.

CI regenerates `validation/` and fails if it differs from the committed copy, so checking the
docs against the committed copy is enough.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P2 = ROOT / "project_02_identity"
S = json.loads((P2 / "validation" / "summary.json").read_text())
flat = lambda p: re.sub(r"\s+", " ", p.read_text())   # line breaks in prose do not matter
README = flat(P2 / "README.md")
SUMMARY = flat(P2 / "manager_summary.md")
PROFILE = flat(P2 / "profiling_report.md")


def pct(a, b):
    return f"{(a / b - 1) * 100:.2f}%"


def test_validation_passed():
    assert S["passed"] and len(S["checks"]) == 5 and "All 5 checks pass" in README


def test_answer_table():
    acc, ppl = S["accounts"], S["people_resolved"]
    n = S["new_customers"]
    j = S["june_2025"]
    c = S["churn_rate_mean"]
    rows = [f"| Customers with an account | {acc:,} | {ppl:,} | {pct(acc, ppl)} |",
            f"| New customers, January 2023 to June 2025 | {n['new_accounts']:,} | {n['new_customers']:,} | "
            f"{pct(n['new_accounts'], n['new_customers'])} |",
            f"| Active subscribers, June 2025 | {j['active_subscription_accounts']:,} | {j['active_subscribers']:,} | "
            f"{pct(j['active_subscription_accounts'], j['active_subscribers'])} |",
            f"| Average monthly churn rate | {c['accounts'] * 100:.3f}% | {c['people'] * 100:.3f}% | "
            f"{(c['accounts'] - c['people']) * 100:.2f} points |"]
    for r in rows:
        assert r in README, r
    assert f"{acc - ppl:,} accounts" in README and f"{n['extra_accounts']:,} of the {n['new_accounts']:,}" in README
    o = S["account_overcount_pct"]
    assert f"{o['min']}% to {o['max']}%" in README


def test_pair_table_and_errors():
    for half, label in (("development", "Development"), ("holdout", "Holdout")):
        v = S["pairs"][half]
        row = (f"| {label} | {v['true_pairs']:,} | {v['predicted_pairs']:,} | {v['false_merges']} | {v['missed']} | "
               f"{v['precision']:.4f} | {v['recall']:.4f} |")
        assert row in README, row
    assert f"all {S['pairs']['all']['true_pairs']:,} true pairs" in README
    assert len(S["errors"]) == 1 and "one false merge" in README
    e = S["errors"][0]
    assert e["left"].split(",")[0] in README and e["right"].split(",")[0] in README
    assert S["review_queue"] == {"pairs": 2, "same_person": 0}


def test_decisions_and_duplicates():
    d = S["decisions"]
    for k in ("merge", "review", "no"):
        assert re.search(rf"\| {k} \| [^|]+ \| {d[k]:,} \|", README), k
    assert f"That gives {sum(d.values()):,} pairs" in README
    for r in S["duplicates_by_origin"]:
        assert r["duplicates"] == r["found"] and f"{r['duplicates']:,}" in README


def test_stress_table():
    labels = {"blank": "removed", "change": "changed to a new number"}
    for s in S["stress"]:
        row = (f"| {s['field']} | {labels[s['change']]} | {s['share']:.0%} | {s['precision']:.4f} | {s['recall']:.4f} | "
               f"{s['review_pairs']} | {s['review_pairs_same_person']} |")
        assert row in README, row


def test_profiling_numbers_quoted():
    phone = re.search(r"\| Phone \(international digits\) \| ([\d,]+) \| ([\d,]+) \|", PROFILE)
    assert f"{phone[1]} phone numbers are shared by more than one account, covering {phone[2]}" in README
    blocked = re.search(r"\| phone \| ([\d,]+) \|", PROFILE)[1]
    pp = S["phone_pairs"]
    assert blocked == f"{pp['total']:,}"
    assert f"of the {pp['total']:,} pairs that share a phone, {pp['not_merged']:,} were not merged" in README
    for n in re.findall(r"finds ([\d,]+) shared values; after the mailbox key, ([\d,]+)", PROFILE)[0]:
        assert n in README


def test_manager_summary_numbers():
    n, j = S["new_customers"], S["june_2025"]
    for v in (S["accounts"], S["people_resolved"], S["accounts"] - S["people_resolved"], n["new_accounts"],
              n["new_customers"], j["active_subscription_accounts"], j["active_subscribers"]):
        assert f"{v:,}" in SUMMARY, v
    assert f"{(n['new_accounts'] / n['new_customers'] - 1) * 100:.1f}%" in SUMMARY
    assert f"{round(S['stress'][0]['recall'] * 100)}%" in SUMMARY
