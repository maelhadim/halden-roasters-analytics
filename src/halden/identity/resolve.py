"""Decide which pairs to merge, build persons from them, and write the results to the warehouse.

    python -m halden.identity run [--db data/warehouse.duckdb]

Decision rule for a scored pair:

- merge:  match probability at least 0.99 AND the accounts share a phone number, a mailbox,
          a legacy ID, or the same first name at the same street and postcode. A name and a
          town are never enough on their own, however rare.
- review: match probability at least 0.5 but not merged. These go to a queue for a person.
- no:     everything else.

Merged pairs are joined into persons with union-find, so if A=B and B=C then A, B and C are
one person. A person may not contain two different legacy IDs, because the old system
already had one account per customer; if the chain would join two, the weakest link is cut.

Decisions a person made on the review queue (`project_02_identity/review_decisions.csv`)
override the model: "same" merges a pair, "different" keeps it apart for good.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import matching

log = logging.getLogger("halden.identity")
AUTO, REVIEW = 0.99, 0.5


def decide(scored: pd.DataFrame) -> pd.Series:
    level = lambda f, v: scored[f].eq(v).fillna(False).to_numpy(dtype=bool)   # a missing field is not agreement
    same_home = level("street", 2) & level("postcode", 1) & level("first_name", 3)
    strong = level("phone", 1) | level("email", 1) | level("legacy_id", 1) | same_home
    p = scored["match_probability"].to_numpy(dtype=float)
    return pd.Series(np.select([(p >= AUTO) & strong, p >= REVIEW], ["merge", "review"], "no"), index=scored.index)


class _UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)   # the oldest customer_id names the person


def cluster(acc: pd.DataFrame, scored: pd.DataFrame,
            different: set[tuple[str, str]] = frozenset()) -> tuple[pd.DataFrame, int]:
    """customer_id -> person_key. Returns the map and how many merges the rules blocked.

    `different` holds pairs a reviewer said are two people. Like two legacy IDs, they may
    never end up in one person, even through a chain of other merges.
    """
    legacy = dict(zip(acc["customer_id"], acc["legacy_id"]))
    uf = _UnionFind(acc["customer_id"])
    legacy_of_root = {c: ({legacy[c]} if isinstance(legacy[c], str) else set()) for c in acc["customer_id"]}
    members = {c: {c} for c in acc["customer_id"]}
    apart: dict[str, set[str]] = {}
    for a, b in different:
        apart.setdefault(a, set()).add(b)
        apart.setdefault(b, set()).add(a)
    blocked = 0
    merges = scored[scored["decision"] == "merge"].sort_values("match_weight", ascending=False, kind="stable")
    for left, right in zip(merges["left_id"], merges["right_id"]):   # strongest evidence first
        ra, rb = uf.find(left), uf.find(right)
        if ra == rb:
            continue
        kept_apart = any(apart.get(x, set()) & members[rb] for x in members[ra])
        if kept_apart or len(legacy_of_root[ra] | legacy_of_root[rb]) > 1:
            blocked += 1
            continue
        uf.union(ra, rb)
        root = uf.find(ra)
        legacy_of_root[root] = legacy_of_root[ra] | legacy_of_root[rb]
        members[root] = members.pop(ra if root == rb else rb) | members[root]
    out = pd.DataFrame({"customer_id": acc["customer_id"]})
    out["person_key"] = [uf.find(c) for c in out["customer_id"]]
    out["accounts_in_person"] = out.groupby("person_key")["customer_id"].transform("size")
    return out, blocked


REVIEW_FILE = Path(__file__).resolve().parents[3] / "project_02_identity" / "review_decisions.csv"


def load_review_decisions(path: Path = REVIEW_FILE) -> pd.DataFrame:
    """Decisions a person made on the review queue. They win over the model, every run."""
    if not path.exists():
        return pd.DataFrame(columns=["left_id", "right_id", "decision"])
    d = pd.read_csv(path, dtype=str, comment="#")
    bad = ~d["decision"].isin(["same", "different"])
    if bad.any():
        raise ValueError(f"{path.name}: decision must be 'same' or 'different': {d[bad].to_dict('records')}")
    # Store each pair with the smaller ID on the left, as the pairs table does.
    lo, hi = d[["left_id", "right_id"]].min(axis=1), d[["left_id", "right_id"]].max(axis=1)
    return d.assign(left_id=lo, right_id=hi)


def apply_review(scored: pd.DataFrame, reviews: pd.DataFrame) -> tuple[pd.DataFrame, set]:
    """'same' forces a merge and 'different' forbids one. Returns the pairs and the cannot-link set."""
    out = scored.copy()
    key = list(zip(out["left_id"], out["right_id"]))
    verdict = dict(zip(zip(reviews["left_id"], reviews["right_id"]), reviews["decision"]))
    out["decision"] = [{"same": "merge", "different": "no"}.get(verdict.get(k), d) for k, d in zip(key, out["decision"])]
    out["reviewed"] = [k in verdict for k in key]
    missing = [k for k, v in verdict.items() if v == "same" and k not in set(key)]
    if missing:   # a reviewer can join two accounts the blocking rules never paired
        extra = pd.DataFrame(missing, columns=["left_id", "right_id"]).assign(
            decision="merge", reviewed=True, match_weight=float("inf"), match_probability=1.0, found_by="review")
        out = pd.concat([out, extra], ignore_index=True)
    different = {k for k, v in verdict.items() if v == "different"}
    return out, different


MODELS = """
-- One row per subscription: when it started and, if it has, when it ended.
CREATE OR REPLACE TABLE int_subscriptions AS
SELECT subscription_id, any_value(customer_id) AS customer_id,
       min(event_at_utc) FILTER (WHERE event_type IN ('CREATED', 'ACTIVE_AT_SNAPSHOT')) AS started_at_utc,
       min(event_at_utc) FILTER (WHERE event_type IN ('CANCELLED', 'LAPSED')) AS ended_at_utc
FROM int_subscription_events GROUP BY subscription_id;

-- Month-end counts, per person (the real subscriber count) and per account (what the old
-- reports used). docs/metrics.md defines both. The account-level churn is here only to show
-- how far it was off: a person who cancels and comes back on a new account looks like one
-- lost and one new customer if accounts are counted.
CREATE OR REPLACE TABLE mart_subscribers_monthly AS
WITH months AS (   -- December 2022 is only there as the base for January's new and churned counts
    SELECT strftime(d, '%Y-%m') AS month, strftime(d - INTERVAL 1 MONTH, '%Y-%m') AS prev_month,
           d + INTERVAL 1 MONTH - INTERVAL 1 SECOND AS month_end
    FROM generate_series(TIMESTAMPTZ '2022-12-01 00:00:00+00', TIMESTAMPTZ '2025-06-01 00:00:00+00', INTERVAL 1 MONTH) g(d)
),
active AS (
    SELECT DISTINCT m.month, s.customer_id, p.person_key
    FROM months m JOIN int_subscriptions s ON s.started_at_utc <= m.month_end
         AND (s.ended_at_utc IS NULL OR s.ended_at_utc > m.month_end)
    JOIN int_customer_person p USING (customer_id)
),
people AS (SELECT DISTINCT month, person_key FROM active),
accounts AS (SELECT DISTINCT month, customer_id FROM active),
counts AS (
    SELECT m.month,
        (SELECT count(*) FROM people a WHERE a.month = m.month) AS active_subscribers,
        (SELECT count(*) FROM accounts a WHERE a.month = m.month) AS active_subscription_accounts,
        (SELECT count(*) FROM people a WHERE a.month = m.month AND a.person_key NOT IN
            (SELECT person_key FROM people b WHERE b.month = m.prev_month)) AS new_subscribers,
        (SELECT count(*) FROM people b WHERE b.month = m.prev_month AND b.person_key NOT IN
            (SELECT person_key FROM people a WHERE a.month = m.month)) AS churned_subscribers,
        (SELECT count(*) FROM accounts b WHERE b.month = m.prev_month AND b.customer_id NOT IN
            (SELECT customer_id FROM accounts a WHERE a.month = m.month)) AS churned_accounts
    FROM months m
)
SELECT * FROM (
    SELECT *,
           round(churned_subscribers / lag(active_subscribers) OVER (ORDER BY month), 5) AS monthly_churn_rate,
           round(churned_accounts / lag(active_subscription_accounts) OVER (ORDER BY month), 5) AS account_churn_rate
    FROM counts
) WHERE month >= '2023-01' ORDER BY month;

-- New customers per month: people whose first ever account was opened that month, against
-- the new accounts the CRM shows. The difference is accounts opened by someone who already had one.
CREATE OR REPLACE TABLE mart_new_customers_monthly AS
WITH a AS (
    SELECT p.customer_id, p.person_key, x.created_at_utc,
           min(x.created_at_utc) OVER (PARTITION BY p.person_key) AS person_first_at
    FROM int_customer_person p JOIN int_identity_accounts x USING (customer_id)
)
SELECT strftime(created_at_utc, '%Y-%m') AS month, count(*) AS new_accounts,
       count(*) FILTER (WHERE created_at_utc = person_first_at) AS new_customers,
       count(*) FILTER (WHERE created_at_utc > person_first_at) AS extra_accounts
FROM a WHERE created_at_utc >= TIMESTAMPTZ '2023-01-01 00:00:00+00' AND created_at_utc < TIMESTAMPTZ '2025-07-01 00:00:00+00'
GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE TABLE mart_identity_review_queue AS
SELECT q.left_id, q.right_id, round(q.match_probability, 4) AS match_probability, round(q.match_weight, 2) AS match_weight,
       l.first_name || ' ' || l.last_name AS left_name, r.first_name || ' ' || r.last_name AS right_name,
       l.email AS left_email, r.email AS right_email, l.phone AS left_phone, r.phone AS right_phone,
       l.city AS left_city, r.city AS right_city, q.found_by
FROM int_identity_pairs q JOIN int_identity_accounts l ON l.customer_id = q.left_id
     JOIN int_identity_accounts r ON r.customer_id = q.right_id
WHERE q.decision = 'review' AND NOT q.reviewed ORDER BY q.match_probability DESC
"""


def resolve(con, acc: pd.DataFrame | None = None, seed: int = 11, reviews: pd.DataFrame | None = None) -> dict:
    """Score, decide and cluster. `acc` can be passed in to test on altered account details."""
    acc = matching.load_accounts(con) if acc is None else acc
    pairs = matching.candidate_pairs(con, acc)
    u = matching.u_probabilities(matching.random_pairs(con, acc, seed=seed))
    m, lam = matching.fit_em(pairs, u)
    scored = matching.score(pairs, m, u, lam, acc)
    scored["decision"] = decide(scored)
    scored, different = apply_review(scored, load_review_decisions() if reviews is None else reviews)
    persons, blocked = cluster(acc, scored, different)
    return {"acc": acc, "scored": scored, "persons": persons, "weights": matching.weights_table(m, u),
            "lambda": lam, "blocked_merges": blocked}


def write(con, res: dict) -> None:
    keep = ["left_id", "right_id", "found_by", *matching.N_LEVELS, "match_weight", "match_probability", "decision",
            "reviewed"]
    for name, df in (("int_identity_accounts", res["acc"]), ("int_identity_pairs", res["scored"][keep]),
                     ("int_customer_person", res["persons"]),
                     ("ref_identity_weights", res["weights"])):
        con.register("df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df")
        con.unregister("df")
    for stmt in [s.strip() for s in MODELS.split(";\n") if s.strip()]:
        con.execute(stmt)


def run(db: Path) -> dict:
    t0 = time.perf_counter()
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone = 'UTC'")
    try:
        res = resolve(con)
        write(con, res)
        d = res["scored"]["decision"].value_counts().to_dict()
        n_acc, n_per = len(res["persons"]), res["persons"]["person_key"].nunique()
        log.info("decisions: %s; %d merges blocked by a legacy ID or a review decision", d, res["blocked_merges"])
        log.info("%d accounts resolve to %d people (%d accounts merged away)", n_acc, n_per, n_acc - n_per)
    finally:
        con.close()
    log.info("identity run finished in %.1fs", time.perf_counter() - t0)
    return {"accounts": n_acc, "persons": n_per, **{f"pairs_{k}": v for k, v in d.items()}}
