"""Score project 2 against the ground truth. The only file in project 2 that reads it.

People are split in two by their true person number: even numbers are the development half,
odd numbers the holdout half. I looked at errors in the development half while building the
rules, and never at the holdout half, so the holdout numbers are the honest ones. A pair of
accounts belongs to the holdout half if either account's true person is in it.

Pairs here are pairs inside the final persons, not just the pairs the model scored: if the
model merged A-B and B-C, then A-C counts as a predicted pair too.
"""
from __future__ import annotations

import itertools
import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import matching
from . import resolve as resolve_mod
from .resolve import resolve

log = logging.getLogger("halden.identity.validate")
STRESS = [("phone", 0.3, "blank"), ("phone", 0.3, "change"), ("email", 0.3, "blank"), ("postcode", 0.5, "blank")]


def _pairs(groups: pd.Series) -> set[tuple[str, str]]:
    out = set()
    for ids in groups:
        out.update(itertools.combinations(sorted(ids), 2))
    return out


def pair_scores(pred_map: pd.DataFrame, true_map: dict[str, str]) -> dict:
    pred = _pairs(pred_map.groupby("person_key")["customer_id"].agg(list))
    truth = _pairs(pd.Series(true_map).reset_index().groupby(0)["index"].agg(list))
    is_hold = lambda c: int(true_map[c][1:]) % 2 == 1
    out = {}
    for name, keep in (("development", lambda a, b: not (is_hold(a) or is_hold(b))),
                       ("holdout", lambda a, b: is_hold(a) or is_hold(b)), ("all", lambda a, b: True)):
        p = {x for x in pred if keep(*x)}
        t = {x for x in truth if keep(*x)}
        tp = len(p & t)
        out[name] = {"true_pairs": len(t), "predicted_pairs": len(p), "correct": tp, "false_merges": len(p - t),
                     "missed": len(t - p), "precision": round(tp / len(p), 4) if p else None,
                     "recall": round(tp / len(t), 4) if t else None}
    return out


def _stress(con, base_acc: pd.DataFrame, true_map, field: str, share: float, how: str) -> dict:
    """Blank a field on a random share of accounts, as if those customers never gave it, or
    change it to a value nobody else has, as if they had a new number since."""
    acc = base_acc.copy()
    rng = np.random.default_rng(5)
    hit = rng.random(len(acc)) < share
    col = {"phone": "phone_key", "email": "email_key", "postcode": "postcode_key"}[field]
    acc.loc[hit, col] = "" if how == "blank" else [f"new{i}" for i in range(int(hit.sum()))]
    res = resolve(con, acc)
    s = pair_scores(res["persons"], true_map)["holdout"]
    rv = res["scored"][res["scored"]["decision"] == "review"]
    rv_true = sum(true_map[a] == true_map[b] for a, b in zip(rv["left_id"], rv["right_id"]))
    return {"field": field, "change": how, "share": share, "precision": s["precision"], "recall": s["recall"],
            "false_merges": s["false_merges"], "missed": s["missed"], "review_pairs": len(rv),
            "review_pairs_same_person": int(rv_true)}


def validate(db: Path, truth: Path, out: Path) -> bool:
    con = duckdb.connect(str(db), read_only=True)
    gt = pd.read_csv(truth / "gt_accounts.csv", dtype=str)
    true_map = dict(zip(gt["customer_id"], gt["person_id"]))
    pmap = con.execute("SELECT customer_id, person_key FROM int_customer_person").df()
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        log.info("%s %s: %s", "PASS" if ok else "FAIL", name, detail)

    check("every account has exactly one person", set(pmap["customer_id"]) == set(true_map)
          and pmap["customer_id"].is_unique,
          f"{len(pmap):,} accounts in the warehouse, {len(true_map):,} in the truth")

    scores = pair_scores(pmap, true_map)
    h = scores["holdout"]
    check("holdout precision and recall at least 0.99", h["precision"] >= 0.99 and h["recall"] >= 0.99,
          f"precision {h['precision']:.4f}, recall {h['recall']:.4f} on {h['true_pairs']:,} true pairs "
          f"({h['false_merges']} false merges, {h['missed']} missed)")

    n_people, n_true = pmap["person_key"].nunique(), gt["person_id"].nunique()
    check("people with an account", abs(n_people - n_true) <= 5,
          f"{n_people:,} resolved vs {n_true:,} true; {len(pmap) - n_people:,} accounts merged away vs "
          f"{len(gt) - n_true:,} true duplicates")

    # Errors in full, so each one can be explained.
    pred = _pairs(pmap.groupby("person_key")["customer_id"].agg(list))
    truth_pairs = _pairs(gt.groupby("person_id")["customer_id"].agg(list))
    acc = matching.load_accounts(con)
    det = acc.set_index("customer_id")
    errors = []
    for kind, ps in (("false merge", sorted(pred - truth_pairs)), ("missed", sorted(truth_pairs - pred))):
        for a, b in ps:
            errors.append({"kind": kind, "left_id": a, "right_id": b,
                           "half": "holdout" if int(true_map[a][1:]) % 2 or int(true_map[b][1:]) % 2 else "development",
                           "left": f"{det.at[a, 'first_name']} {det.at[a, 'last_name']}, {det.at[a, 'city']}",
                           "right": f"{det.at[b, 'first_name']} {det.at[b, 'last_name']}, {det.at[b, 'city']}"})

    # Review queue: how much of it is real.
    rq = con.execute("SELECT left_id, right_id FROM mart_identity_review_queue").fetchall()
    rq_true = sum(true_map[a] == true_map[b] for a, b in rq)

    # Duplicates by how they arose.
    first = gt.sort_values("created_at_utc").groupby("person_id")["customer_id"].first()
    dups = gt[~gt["customer_id"].isin(first)].copy()
    dups["found"] = [pmap.set_index("customer_id").at[c, "person_key"] ==
                     pmap.set_index("customer_id").at[first[p], "person_key"]
                     for c, p in zip(dups["customer_id"], dups["person_id"])]
    by_origin = dups.groupby("origin")["found"].agg(["size", "sum"]).reset_index()
    by_origin.columns = ["origin", "duplicates", "found"]

    # Monthly subscriber metrics against the truth.
    w = con.execute("SELECT * FROM mart_subscribers_monthly").df()
    t = pd.read_csv(truth / "gt_monthly_metrics.csv")
    mm = w.merge(t, on="month", suffixes=("", "_truth"))
    metric_cols = ["active_subscribers", "active_subscription_accounts", "new_subscribers", "churned_subscribers"]
    diffs = {c: int((mm[c] - mm[f"{c}_truth"]).abs().max()) for c in metric_cols}
    check("subscriber metrics per month", len(mm) == 30 and diffs["active_subscription_accounts"] == 0
          and max(diffs.values()) <= 2,
          f"30 months; largest monthly difference: " + ", ".join(f"{c} {v}" for c, v in diffs.items()))
    overcount = (mm["active_subscription_accounts"] / mm["active_subscribers"] - 1) * 100

    # New customers per month against the truth: a person's first account opens their month.
    g = gt.assign(created=pd.to_datetime(gt["created_at_utc"], utc=True))
    g["first"] = g.groupby("person_id")["created"].transform("min")
    g = g[(g["created"] >= "2023-01-01") & (g["created"] < "2025-07-01")]
    tnew = g[g["created"] == g["first"]].groupby(g["created"].dt.strftime("%Y-%m")).size()
    nc = con.execute("SELECT month, new_accounts, new_customers, extra_accounts FROM mart_new_customers_monthly").df()
    nd = (nc.set_index("month")["new_customers"] - tnew).abs()
    check("new customers per month", len(nc) == 30 and nd.max() <= 2,
          f"30 months; largest monthly difference {int(nd.max())}; {int(nc['new_customers'].sum()):,} new customers "
          f"vs {int(tnew.sum()):,} true, from {int(nc['new_accounts'].sum()):,} new accounts")

    # How much does the merge threshold matter? Development half only.
    sp = con.execute("SELECT * FROM int_identity_pairs").df()
    sensitivity = []
    for t in (0.5, 0.9, 0.99, 0.9999):
        saved, resolve_mod.AUTO = resolve_mod.AUTO, t
        try:
            dec = sp.assign(decision=resolve_mod.decide(sp))
        finally:
            resolve_mod.AUTO = saved
        persons, _ = resolve_mod.cluster(acc, dec)
        d = pair_scores(persons, true_map)["development"]
        sensitivity.append({"threshold": t, "precision": d["precision"], "recall": d["recall"],
                            "false_merges": d["false_merges"], "missed": d["missed"]})

    decisions = dict(con.execute("SELECT decision, count(*) FROM int_identity_pairs GROUP BY 1 ORDER BY 1").fetchall())
    phone_pairs = con.execute("""SELECT count(*), count(*) FILTER (WHERE decision <> 'merge') FROM int_identity_pairs
                                 WHERE found_by LIKE '%phone%'""").fetchall()[0]
    stress = [_stress(con, acc, true_map, f, s, how) for f, s, how in STRESS]
    con.close()

    passed = all(c["passed"] for c in checks)
    summary = {"passed": passed, "checks": checks, "pairs": scores, "people_resolved": int(n_people),
               "people_true": int(n_true), "review_queue": {"pairs": len(rq), "same_person": int(rq_true)},
               "duplicates_by_origin": by_origin.to_dict(orient="records"), "errors": errors,
               "account_overcount_pct": {"min": round(float(overcount.min()), 2),
                                         "max": round(float(overcount.max()), 2),
                                         "last_month": round(float(overcount.iloc[-1]), 2)},
               "june_2025": {c: int(mm[c].iloc[-1]) for c in metric_cols},
               "new_customers": {"new_accounts": int(nc["new_accounts"].sum()), "new_customers": int(nc["new_customers"].sum()),
                                 "extra_accounts": int(nc["extra_accounts"].sum())},
               "accounts": len(pmap), "decisions": {k: int(v) for k, v in decisions.items()},
               "phone_pairs": {"total": int(phone_pairs[0]), "not_merged": int(phone_pairs[1])},
               "churn_rate_mean": {"people": round(float(w["monthly_churn_rate"].mean()), 5),
                                   "accounts": round(float(w["account_churn_rate"].mean()), 5)},
               "threshold_sensitivity": sensitivity, "stress": stress}
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")

    md = ["# Validation report: project 2", "",
          "Generated by `python -m halden.identity validate`. It is the only project 2 code that reads",
          "`data/ground_truth`. Synthetic data.", "", f"Overall: **{'PASS' if passed else 'FAIL'}**", "",
          "| Check | Result | Detail |", "| --- | --- | --- |"]
    md += [f"| {c['check']} | {'pass' if c['passed'] else 'FAIL'} | {c['detail']} |" for c in checks]
    md += ["", "## Pairs of accounts that are the same person", "",
           "| Half | True pairs | Predicted pairs | Correct | False merges | Missed | Precision | Recall |",
           "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for k, v in scores.items():
        md.append(f"| {k} | {v['true_pairs']:,} | {v['predicted_pairs']:,} | {v['correct']:,} | {v['false_merges']} | "
                  f"{v['missed']} | {v['precision']:.4f} | {v['recall']:.4f} |")
    md += ["", "## Duplicates by how they arose", "", "| How the duplicate account arose | Duplicates | Found |",
           "| --- | ---: | ---: |"]
    md += [f"| {r.origin} | {r.duplicates:,} | {r.found:,} |" for r in by_origin.itertuples()]
    md += ["", "## Every error", "", "| Kind | Half | Accounts | Left | Right |", "| --- | --- | --- | --- | --- |"]
    md += [f"| {e['kind']} | {e['half']} | {e['left_id']}, {e['right_id']} | {e['left']} | {e['right']} |"
           for e in errors] or ["| none | | | | |"]
    md += ["", f"Review queue: {len(rq)} pairs, of which {rq_true} are the same person.", "",
           "## Merge threshold", "", "The same pairs, merged at different probability thresholds. Development half.", "",
           "| Threshold | Precision | Recall | False merges | Missed |", "| ---: | ---: | ---: | ---: | ---: |"]
    md += [f"| {x['threshold']} | {x['precision']:.4f} | {x['recall']:.4f} | {x['false_merges']} | {x['missed']} |"
           for x in sensitivity]
    md += ["",
           "## Stress test: what if customers had given less information?", "",
           "Each row blanks one field on a random share of all accounts, or changes it to a value no",
           "other account has (seed 5), and reruns the whole method, weights included. Precision and",
           "recall are for the holdout half.", "",
           "Review pairs are counted over both halves, because the queue is one list.", "",
           "| Field | Change | Share of accounts | Precision | Recall | False merges | Missed | Review pairs | Of which same person |",
           "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    md += [f"| {s['field']} | {s['change']} | {s['share']:.0%} | {s['precision']:.4f} | {s['recall']:.4f} | "
           f"{s['false_merges']} | {s['missed']} | {s['review_pairs']} | {s['review_pairs_same_person']} |" for s in stress]
    (out / "report.md").write_text("\n".join(md) + "\n")
    return passed
