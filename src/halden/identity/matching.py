"""Find accounts that belong to the same person.

The method is the Fellegi-Sunter model, the standard approach to record linkage. For every
candidate pair of accounts, each field is compared and lands on an agreement level (for a
surname: exact, close, loosely close, different). Each level has two probabilities:

    m = P(this level | the two accounts are the same person)
    u = P(this level | they are different people)

A pair's evidence is the sum of log2(m / u) over its fields, plus the prior odds of a match.
u is measured from random pairs of accounts, which are almost all different people. m and
the prior are estimated with expectation maximisation (EM) on the candidate pairs, with no
labels. The ground truth is not used anywhere in this file.
"""
from __future__ import annotations

import logging

import duckdb
import numpy as np
import pandas as pd

from . import standardise as std

log = logging.getLogger("halden.identity")

# Field -> SQL expression giving its agreement level for a pair (l, r). NULL means one side is
# missing, which counts as no evidence either way. Higher level = closer agreement.
LEVELS: dict[str, str] = {
    # Only the whole mailbox counts. The part before the @ is usually built from the name
    # (fkaul@gmx.de, fkaul@web.de), so scoring it as well would count the name twice.
    "email": """CASE WHEN l.email_key = '' OR r.email_key = '' THEN NULL
                     WHEN l.email_key = r.email_key THEN 1 ELSE 0 END""",
    "phone": """CASE WHEN l.phone_key = '' OR r.phone_key = '' THEN NULL
                     WHEN l.phone_key = r.phone_key THEN 1 ELSE 0 END""",
    "legacy_id": """CASE WHEN l.legacy_id IS NULL OR r.legacy_id IS NULL THEN NULL
                         WHEN l.legacy_id = r.legacy_id THEN 1 ELSE 0 END""",
    "last_name": """CASE WHEN l.last_key = '' OR r.last_key = '' THEN NULL
                         WHEN l.last_key = r.last_key THEN 3
                         WHEN jaro_winkler_similarity(l.last_key, r.last_key) >= 0.92 THEN 2
                         WHEN jaro_winkler_similarity(l.last_key, r.last_key) >= 0.80 THEN 1 ELSE 0 END""",
    "first_name": """CASE WHEN l.first_key = '' OR r.first_key = '' THEN NULL
                          WHEN l.first_key = r.first_key AND NOT l.first_is_initial THEN 3
                          WHEN l.first_formal = r.first_formal AND NOT l.first_is_initial AND NOT r.first_is_initial THEN 2
                          WHEN (l.first_is_initial OR r.first_is_initial) AND left(l.first_key, 1) = left(r.first_key, 1) THEN 1
                          WHEN jaro_winkler_similarity(l.first_key, r.first_key) >= 0.90 THEN 1 ELSE 0 END""",
    "postcode": """CASE WHEN l.postcode_key = '' OR r.postcode_key = '' THEN NULL
                        WHEN l.postcode_key = r.postcode_key THEN 1 ELSE 0 END""",
    "street": """CASE WHEN l.street_key = '' OR r.street_key = '' THEN NULL
                      WHEN l.street_key = r.street_key THEN 2
                      WHEN jaro_winkler_similarity(l.street_key, r.street_key) >= 0.85 THEN 1 ELSE 0 END""",
    "city": """CASE WHEN l.city_key = '' OR r.city_key = '' THEN NULL
                    WHEN l.city_key = r.city_key THEN 1 ELSE 0 END""",
}
N_LEVELS = {"email": 2, "phone": 2, "legacy_id": 2, "last_name": 4, "first_name": 4, "postcode": 2, "street": 3,
            "city": 2}

# A pair is compared only if it shares at least one of these. Each rule is cheap to join on,
# and together they catch a duplicate that changed any one or two fields.
BLOCKS = {
    "phone": "l.phone_key = r.phone_key AND l.phone_key <> ''",
    "email": "l.email_key = r.email_key AND l.email_key <> ''",
    "legacy_id": "l.legacy_id = r.legacy_id",
    "postcode_initial": "l.postcode_key = r.postcode_key AND l.postcode_key <> '' AND left(l.last_key, 1) = left(r.last_key, 1)",
    "name_city": "l.last_key = r.last_key AND l.first_formal = r.first_formal AND l.city_key = r.city_key",
}


def load_accounts(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per customer_id with its latest details.

    Most come from the CRM. A few customer IDs appear in shop orders but not in the CRM,
    because their CRM record was quarantined in project 1 (a stray quote). Dropping them
    would undercount people, so they are built from their latest shop order instead.
    """
    acc = con.execute("""
        SELECT customer_id, legacy_id, first_name, last_name, email, phone, street, city, postcode, country_code,
               created_at_utc, 'crm' AS details_from
        FROM int_crm_customers
        UNION ALL
        SELECT customer_id, NULL, first_name, last_name, email_raw, phone_raw, NULL, billing_city, billing_postcode,
               country_code, first_order_at, 'shop_order'
        FROM (SELECT *, row_number() OVER (PARTITION BY customer_id ORDER BY created_at_utc DESC, order_id DESC) AS rn,
                     -- the account was open by its first order; the CRM date is not available
                     min(created_at_utc) OVER (PARTITION BY customer_id) AS first_order_at
              FROM int_orders WHERE customer_id IS NOT NULL
                AND customer_id NOT IN (SELECT customer_id FROM int_crm_customers)) WHERE rn = 1
        ORDER BY customer_id""").df()
    keys = acc.apply(lambda r: std.first_name_key(r.first_name), axis=1, result_type="expand")
    acc["first_key"], acc["first_formal"], acc["first_is_initial"] = keys[0], keys[1], keys[2].astype(bool)
    acc["last_key"] = acc["last_name"].map(std.fold).str.replace(" ", "", regex=False)
    acc["email_key"] = acc["email"].map(std.email_key)
    acc["phone_key"] = [std.phone_key(p, c) for p, c in zip(acc["phone"], acc["country_code"])]
    acc["postcode_key"] = acc["postcode"].map(std.postcode_key)
    acc["street_key"] = acc["street"].map(std.street_key)
    acc["city_key"] = acc["city"].map(std.fold)
    acc["legacy_id"] = acc["legacy_id"].where(acc["legacy_id"].notna() & (acc["legacy_id"] != ""), None)
    log.info("accounts: %d (%d from the CRM, %d from shop orders only)", len(acc),
             (acc.details_from == "crm").sum(), (acc.details_from == "shop_order").sum())
    return acc


def _level_sql(alias_pairs: str) -> str:
    cols = ",\n       ".join(f"{expr} AS {name}" for name, expr in LEVELS.items())
    return f"SELECT p.left_id, p.right_id, {cols}\nFROM {alias_pairs} p JOIN acc l ON l.customer_id = p.left_id JOIN acc r ON r.customer_id = p.right_id\nORDER BY p.left_id, p.right_id"   # fixed order, so sums and reports repeat exactly


def candidate_pairs(con, acc: pd.DataFrame) -> pd.DataFrame:
    """Pairs sharing at least one blocking key, with the field levels and which rules found them."""
    con.register("acc", acc)
    union = "\nUNION ALL\n".join(
        f"SELECT l.customer_id AS left_id, r.customer_id AS right_id, '{name}' AS rule FROM acc l JOIN acc r "
        f"ON {cond} AND l.customer_id < r.customer_id" for name, cond in BLOCKS.items())
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cand AS
                    SELECT left_id, right_id, string_agg(rule, ',' ORDER BY rule) AS found_by
                    FROM ({union}) GROUP BY ALL""")
    pairs = con.execute(_level_sql("cand").replace("SELECT p.left_id, p.right_id,",
                                                   "SELECT p.left_id, p.right_id, p.found_by,")).df()
    log.info("candidate pairs: %d", len(pairs))
    return pairs


def random_pairs(con, acc: pd.DataFrame, n: int = 400_000, seed: int = 11) -> pd.DataFrame:
    """Random pairs of accounts. Among 18,000 accounts, two picked at random are the same
    person about 1 time in 170,000, so these pairs measure u, the chance of agreeing by luck."""
    rng = np.random.default_rng(seed)
    ids = acc["customer_id"].to_numpy()
    a, b = rng.integers(0, len(ids), n), rng.integers(0, len(ids), n)
    keep = a != b
    con.register("rp", pd.DataFrame({"left_id": ids[a[keep]], "right_id": ids[b[keep]]}))
    return con.execute(_level_sql("rp")).df()


def u_probabilities(rand: pd.DataFrame) -> dict[str, np.ndarray]:
    u = {}
    for f, k in N_LEVELS.items():
        counts = np.bincount(rand[f].dropna().astype(int), minlength=k).astype(float)
        u[f] = (counts + 0.5) / (counts.sum() + 0.5 * k)   # +0.5 so a level never seen by luck is not "impossible"
    return u


# EM is run once per training block. Inside a block every pair agrees on the blocking fields
# by construction, so those fields say nothing about which pairs match and are left out of
# that session. Two sessions cover every field between them.
TRAINING = {"phone": ("phone",), "name_city": ("last_name", "first_name", "city")}


def _log_lr(X, fields, m, u):
    total = 0.0
    for f in fields:
        x = X[f]
        ok = ~np.isnan(x)
        xi = np.where(ok, x, 0).astype(int)
        total = total + np.where(ok, np.log(m[f][xi]) - np.log(u[f][xi]), 0.0)
    return total


def _em(X, fields, u, m, lam, learn_m=True, iters=200, tol=1e-9):
    for it in range(iters):
        logit = np.log(lam) - np.log1p(-lam) + _log_lr(X, fields, m, u)
        p = 1 / (1 + np.exp(-np.clip(logit, -700, 700)))
        new_lam = float(np.clip(p.mean(), 1e-6, 1 - 1e-6))
        new_m = dict(m)
        if learn_m:
            for f in fields:
                x = X[f]
                ok = ~np.isnan(x)
                w = np.bincount(x[ok].astype(int), weights=p[ok], minlength=N_LEVELS[f]) + 1e-3
                new_m[f] = w / w.sum()
        delta = abs(new_lam - lam) + sum(np.abs(new_m[f] - m[f]).sum() for f in fields)
        lam, m = new_lam, new_m
        if delta < tol:
            break
    return m, lam, it + 1


def fit_em(pairs: pd.DataFrame, u: dict[str, np.ndarray]):
    """Estimate m per field from the training blocks, then the overall match share. u stays fixed."""
    X = {f: pairs[f].to_numpy(dtype=float) for f in N_LEVELS}
    # Start from "a match usually agrees exactly": most of the mass on the top level.
    start = {f: np.r_[np.full(k - 1, 0.1 / (k - 1)), 0.9] for f, k in N_LEVELS.items()}
    estimates: dict[str, list[np.ndarray]] = {f: [] for f in N_LEVELS}
    for rule, fixed in TRAINING.items():
        rows = pairs["found_by"].str.contains(rule).to_numpy()
        Xb = {f: X[f][rows] for f in N_LEVELS}
        fields = [f for f in N_LEVELS if f not in fixed]
        m_b, lam_b, n_it = _em(Xb, fields, u, dict(start), 0.5)
        log.info("EM on %s block: %d pairs, %d iterations, %.1f%% matches", rule, rows.sum(), n_it, 100 * lam_b)
        for f in fields:
            estimates[f].append(m_b[f])
    m = {f: np.mean(v, axis=0) for f, v in estimates.items()}
    _, lam, _ = _em(X, list(N_LEVELS), u, m, 0.1, learn_m=False)
    log.info("share of all candidate pairs that look like matches: %.1f%%", 100 * lam)
    return m, lam


# Exact agreement on a common value is weaker evidence than on a rare one: two accounts both
# called Smith in London prove less than two both called Wiśniewski. For these fields the u of
# the exact level is replaced by how often that value occurs among all accounts.
TERM_FREQUENCY = {"last_name": ("last_key", 3), "first_name": ("first_formal", 3), "city": ("city_key", 1)}


def term_frequencies(acc: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {f: (acc[col].value_counts() / len(acc)).to_dict() for f, (col, _) in TERM_FREQUENCY.items()}


def score(pairs: pd.DataFrame, m, u, lam, acc: pd.DataFrame | None = None) -> pd.DataFrame:
    """Match weight (log2 Bayes factor per field) and the posterior match probability."""
    out = pairs.copy()
    total = np.full(len(out), np.log2(lam / (1 - lam)))
    tf = term_frequencies(acc) if acc is not None else {}
    if tf:
        lookup = acc.set_index("customer_id")
    for f in N_LEVELS:
        x = out[f].to_numpy(dtype=float)
        ok = ~np.isnan(x)
        xi = np.where(ok, x, 0).astype(int)
        u_pair = u[f][xi]
        if f in tf:
            col, exact = TERM_FREQUENCY[f]
            freq = lookup.loc[out["left_id"], col].map(tf[f]).to_numpy(dtype=float)
            # Never stronger than the average-based u: a value seen once is not proof on its own.
            u_pair = np.where(xi == exact, np.maximum(freq, u[f][exact]), u_pair)
        w = np.where(ok, np.log2(m[f][xi] / u_pair), 0.0)
        out[f"w_{f}"] = w
        total += w
    out["match_weight"] = total
    out["match_probability"] = 1 / (1 + np.power(2.0, -total))
    return out


def weights_table(m, u) -> pd.DataFrame:
    rows = []
    for f, k in N_LEVELS.items():
        for lvl in range(k):
            rows.append({"field": f, "level": lvl, "m": m[f][lvl], "u": u[f][lvl],
                         "weight_log2": np.log2(m[f][lvl] / u[f][lvl])})
    return pd.DataFrame(rows)
