"""Score the warehouse against the ground truth. This is the only project 1 code that reads it.

Writes `report.md` and `summary.json` to the output folder and returns True only if every
hard check passes. Defects that belong to later projects are listed, not scored.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

log = logging.getLogger("halden.ingest.validate")

LATER = {"CRM_DUPLICATE_PERSON": "project 2", "EXP_PERSON_BOTH_ARMS": "project 5", "EXP_LOG_OUTAGE": "project 5"}


def _gt(truth: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(truth / name, dtype=str, keep_default_na=False)


def _keys(df: pd.DataFrame, col: str) -> set:
    return set(df[col].astype(str))


def defect_scores(con, manifest: pd.DataFrame) -> pd.DataFrame:
    """For each defect, the keys the pipeline flagged or handled vs the keys in the manifest."""
    q = lambda sql: con.execute(sql).df()
    found: dict[str, set] = {
        "SHOP_TRUNCATED_FILE": _keys(q("""SELECT order_id FROM int_orders WHERE _source_file LIKE '%_resend.csv'
                                          AND order_id NOT IN (SELECT order_id FROM stg_shop_orders
                                                               WHERE _source_file = 'shop_orders_20240318.csv')
                                          UNION SELECT regexp_extract(raw_record, '^(\\d{7})', 1) FROM rej_records
                                          WHERE source = 'shop'"""), "order_id"),
        "SHOP_RESEND": _keys(q("SELECT order_id FROM int_orders WHERE _source_file LIKE '%_resend.csv'"), "order_id"),
        "SHOP_DATE_FORMAT": _keys(q("SELECT order_id FROM stg_shop_orders WHERE created_at_precision = 'minute'"), "order_id"),
        "SHOP_PHONE_SCIENTIFIC": _keys(q("SELECT order_id FROM stg_shop_orders WHERE is_phone_scientific"), "order_id"),
        "SHOP_MISSING_POSTCODE": _keys(q("SELECT order_id FROM stg_shop_orders WHERE billing_postcode IS NULL"), "order_id"),
        "SHOP_TEST_ORDER": _keys(q("SELECT order_id FROM int_orders WHERE is_test"), "order_id"),
        "SHOP_AMBIGUOUS_LOCAL_TIME": _keys(q("SELECT order_id FROM stg_shop_orders WHERE is_ambiguous_local_time"), "order_id"),
        # Every injected case has surrounding spaces. Capitals alone also occur in genuine
        # account emails, so they are normalised but not counted as this defect.
        "SHOP_EMAIL_FORMATTING": _keys(q("SELECT order_id FROM stg_shop_orders WHERE email_raw <> trim(email_raw)"), "order_id"),
        "SHOP_TRAILING_DELIMITER": _keys(q("SELECT file_name FROM meta_file_loads WHERE notes LIKE 'trailing delimiter%'"), "file_name"),
        "SHOP_BLANK_LINES": _keys(q("SELECT file_name FROM meta_file_loads WHERE blank_ignored > 0"), "file_name"),
        "SUBS_LATE_EVENT": _keys(q("SELECT event_id FROM stg_shop_subscription_events WHERE is_late_event"), "event_id"),
        "SUBS_REASON_QUOTED": _keys(q("""SELECT event_id FROM stg_shop_subscription_events
                                         WHERE cancel_reason LIKE '%,%' OR cancel_reason LIKE '%"%'"""), "event_id"),
        "PAYPROC_DUPLICATE_ROW": _keys(q("""SELECT split_part(raw_record, '|', 2) AS txn_id FROM rej_records
                                            WHERE source = 'payproc' AND reject_reason = 'duplicate_record_in_file'"""), "txn_id"),
        "PAYPROC_MISSING_DAY": _keys(q("""SELECT CAST(period_start AS VARCHAR) AS d FROM mart_file_arrivals
                                          WHERE source = 'payproc' AND arrival_status = 'missing'"""), "d"),
        "PAYPROC_LATE_FILE": _keys(q("""SELECT 'payproc_transactions_' || strftime(period_start, '%Y%m%d') || '.txt' AS f
                                        FROM mart_file_arrivals WHERE source = 'payproc' AND arrival_status = 'late'"""), "f"),
        "PAYPROC_SCHEMA_CHANGE": _keys(q("""SELECT min(_source_file) AS f FROM stg_payproc_transactions
                                            WHERE schema_version = 'v2'"""), "f"),
        "PAYPROC_UNLINKED_REFUND": _keys(q("SELECT txn_id FROM int_revenue_transactions WHERE NOT is_linked "
                                           "AND txn_type = 'REFUND'"), "txn_id"),
        "FUL_ENCODING_CP1252": _keys(q("SELECT DISTINCT _source_file FROM stg_ful_shipment_events"), "_source_file"),
        "FUL_UNMAPPABLE_CHAR": set(q("""SELECT _source_file || '|' || shipment_no AS k FROM stg_ful_shipment_events
                                        WHERE has_replacement_char""")["k"]),
        "FUL_CORRECTED_FILE": _keys(q("""SELECT shipment_no FROM stg_ful_shipment_events s
                                         WHERE _source_file = 'ful_shipments_20240520.csv'
                                           AND _source_file NOT IN (SELECT DISTINCT _source_file FROM int_shipment_events)
                                           AND status = 'DELIVERED' AND site_code = 'HAM'"""), "shipment_no"),
        "FUL_DUPLICATE_EVENT": set(q("""SELECT s._source_file || '|' || s.shipment_no AS k FROM stg_ful_shipment_events s
                                        JOIN int_shipment_events i USING (shipment_no, status)
                                        WHERE s._source_file <> i._source_file
                                          AND s._source_file IN (SELECT DISTINCT _source_file FROM int_shipment_events)""")["k"]),
        "FUL_LATE_FILE": _keys(q("""SELECT 'ful_shipments_' || strftime(period_start, '%Y%m%d') || '.csv' AS f
                                    FROM mart_file_arrivals WHERE source = 'ful' AND arrival_status = 'late'"""), "f"),
        "CRM_EMBEDDED_NEWLINE": set(q("""SELECT _source_file || '|' || customer_id AS k FROM stg_crm_customer_versions
                                         WHERE notes LIKE '%' || chr(10) || '%' OR notes LIKE '%' || chr(9) || '%'""")["k"]),
        "CRM_STRAY_QUOTE": set(q("""SELECT _source_file || '|' || split_part(raw_record, chr(9), 1) AS k FROM rej_records
                                    WHERE source = 'crm' AND reject_reason = 'unbalanced_quote'""")["k"]),
        "EXP_DUPLICATE_EVENT": set(q("""SELECT json_extract_string(raw_record, '$.event_id') AS k FROM rej_records
                                        WHERE source = 'exp' AND reject_reason = 'duplicate_record_in_file'""")["k"]),
    }
    file_keyed = {"FUL_UNMAPPABLE_CHAR", "FUL_DUPLICATE_EVENT", "CRM_EMBEDDED_NEWLINE", "CRM_STRAY_QUOTE"}
    rows = []
    for code, grp in manifest.groupby("defect_code"):
        if code in LATER:
            rows.append({"defect_code": code, "manifest": len(grp), "found": None, "matched": None, "missed": None,
                         "extra": None, "note": f"handled in {LATER[code]}"})
            continue
        if code in ("SHOP_TRAILING_DELIMITER", "SHOP_BLANK_LINES", "PAYPROC_LATE_FILE", "FUL_LATE_FILE",
                    "PAYPROC_SCHEMA_CHANGE", "FUL_ENCODING_CP1252"):
            expected = set(grp["file_name"])
        elif code == "PAYPROC_MISSING_DAY":
            expected = set(grp["record_key"])
        elif code in file_keyed:
            # A corrected _v2 file repeats its week; count a defect once per week and record.
            expected = set(grp["file_name"].str.replace("_v2.csv", ".csv") + "|" + grp["record_key"])
        else:
            expected = set(grp["record_key"])
        got = {k.replace("_v2.csv", ".csv") for k in found[code]} if code in file_keyed else found[code]
        rows.append({"defect_code": code, "manifest": len(expected), "found": len(got),
                     "matched": len(expected & got), "missed": len(expected - got), "extra": len(got - expected),
                     "note": ""})
    return pd.DataFrame(rows)


def validate(db: Path, truth: Path, out: Path) -> bool:
    con = duckdb.connect(str(db), read_only=True)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        log.info("%s %s: %s", "PASS" if passed else "FAIL", name, detail)

    # 1. Every record accounted for, file by file.
    lc = con.execute("SELECT * FROM mart_load_checks").df()
    tot = lc[["records_read", "staged", "rejected", "blank_ignored"]].sum()
    check("rows balance per file", lc["rows_balance"].all(),
          f"{len(lc):,} files; {int(tot.records_read):,} records read = {int(tot.staged):,} staged + "
          f"{int(tot.rejected):,} rejected + {int(tot.blank_ignored):,} blank lines")
    pp = lc[lc["source"] == "payproc"]
    check("processor trailers match", pp["trailer_matches"].all(),
          f"{int(pp['trailer_matches'].sum()):,} of {len(pp):,} files match their trailer count and gross total")

    # 2. Orders.
    gto = _gt(truth, "gt_orders.csv")
    gto["created"] = pd.to_datetime(gto["created_at_utc"], utc=True)
    gto = gto[gto["created"].dt.tz_convert("Europe/London").dt.date <= pd.Timestamp("2025-06-30").date()]
    io_ = con.execute("SELECT order_id, created_at_utc, created_at_quality, total_amount, is_test, is_paid "
                      "FROM int_orders").df()
    check("orders: same set as truth", set(io_["order_id"]) == set(gto["order_id"]) and io_["order_id"].is_unique,
          f"{len(io_):,} orders in warehouse, {len(gto):,} in truth, "
          f"{len(set(gto['order_id']) - set(io_['order_id'])):,} missing, "
          f"{len(set(io_['order_id']) - set(gto['order_id'])):,} extra")
    m = io_.merge(gto[["order_id", "created", "total_amount", "is_test", "status"]], on="order_id", suffixes=("", "_gt"))
    diff = (pd.to_datetime(m["created_at_utc"], utc=True) - m["created"]).dt.total_seconds()
    exact = m["created_at_quality"].isin(["exact", "resolved_first_instant", "resolved_second_instant"])
    check("orders: UTC creation time", (diff[exact] == 0).all() and diff[~exact].abs().max() < 60,
          f"{int((diff[exact] == 0).sum()):,} of {int(exact.sum()):,} exact-time orders match to the second; "
          f"{int((~exact).sum()):,} minute-precision orders are within {diff[~exact].abs().max():.0f} s")
    amb = m[m["created_at_quality"].str.startswith("resolved") | (m["created_at_quality"] == "ambiguous_unresolved")]
    check("orders: ambiguous autumn times resolved", (diff.loc[amb.index] == 0).all(),
          f"{len(amb):,} orders in the repeated hour; {int((diff.loc[amb.index] == 0).sum()):,} resolved to the true instant; "
          f"{int((amb['created_at_quality'] == 'ambiguous_unresolved').sum()):,} left unresolved")
    gcap = _gt(truth, "gt_transactions.csv").query("txn_type == 'CAPTURE'").set_index("order_id")["txn_at_utc"]
    paid_in_window = m["order_id"].map(gcap).fillna("9999").str[:10] <= "2025-06-30"
    check("orders: totals and flags", (m["total_amount"].astype(float) == m["total_amount_gt"].astype(float)).all()
          and (m["is_test"] == (m["is_test_gt"] == "True")).all() and (m["is_paid"] == paid_in_window).all(),
          "total_amount, is_test and paid status (paid by 30 June 2025) match truth for every order")

    # 3. Transactions.
    gtt = _gt(truth, "gt_transactions.csv")
    gtt = gtt[gtt["txn_at_utc"].str[:10] <= "2025-06-30"]
    it = con.execute("SELECT txn_id, gross_amount, txn_type FROM int_transactions").df()
    mt = it.merge(gtt, on="txn_id", suffixes=("", "_gt"))
    check("transactions: same set and amounts", len(it) == len(gtt) == len(mt)
          and (mt["gross_amount"].astype(float) == mt["gross_amount_gt"].astype(float)).all(),
          f"{len(it):,} in warehouse, {len(gtt):,} in truth, {len(mt):,} matched on txn_id and amount")

    # 4. Shipments.
    gts = _gt(truth, "gt_shipments.csv")
    ish = con.execute("SELECT shipment_no, CAST(delivered_date AS VARCHAR) AS delivered_date, is_late, shipment_status "
                      "FROM int_shipments").df()
    ms = ish.merge(gts, on="shipment_no", suffixes=("", "_gt"))
    delivered = ms["shipment_status"] == "DELIVERED"
    ok_dates = (ms.loc[delivered, "delivered_date"] == ms.loc[delivered, "delivered_date_gt"]).mean()
    ok_late = (ms.loc[delivered, "is_late"] == (ms.loc[delivered, "is_late_gt"] == "True")).mean()
    check("shipments: delivery dates and lateness", ok_dates == 1 and ok_late == 1,
          f"{len(ish):,} shipments; {int(delivered.sum()):,} delivered, all with the true delivery date "
          f"({ok_dates:.2%}) and lateness ({ok_late:.2%})" if ok_dates == 1 else
          f"delivery date match {ok_dates:.4%}, lateness match {ok_late:.4%}")

    # 5. Revenue and KPIs against the truth table.
    gm = pd.read_csv(truth / "gt_monthly_metrics.csv").set_index("month")
    rev = con.execute("SELECT * FROM mart_revenue_monthly").df().set_index("month")
    rd = (rev["net_revenue_gbp"] - gm["net_revenue_gbp"]).abs()
    gd = (rev["gross_revenue_gbp"] - gm["gross_revenue_gbp"]).abs()
    check("revenue: net and gross per month", rd.max() <= 0.01 and gd.max() <= 0.01 and len(rev) == len(gm),
          f"{len(rev)} months; largest difference {max(rd.max(), gd.max()):.2f} GBP; 30-month net revenue "
          f"{rev['net_revenue_gbp'].sum():,.2f} GBP vs truth {gm['net_revenue_gbp'].sum():,.2f}")
    om = con.execute("SELECT * FROM mart_orders_monthly WHERE month BETWEEN '2023-01' AND '2025-06'").df().set_index("month")
    gap = (gm["paid_orders"] - om["paid_orders"])
    # The truth knows about payments after the window closes; the warehouse cannot. Count the
    # June 2025 orders whose capture is after 30 June, plus orders whose shop file is outside
    # the window, and require that they explain the gap exactly.
    gtt_all = _gt(truth, "gt_transactions.csv")
    cap = gtt_all[gtt_all["txn_type"] == "CAPTURE"].set_index("order_id")["txn_at_utc"]
    allo = _gt(truth, "gt_orders.csv")
    allo = allo[(allo["status"] == "PAID") & (allo["is_test"] == "False") & (allo["created_at_utc"].str[:7] == "2025-06")]
    after = (allo["order_id"].map(cap).str[:10] > "2025-06-30") | ~allo["order_id"].isin(io_["order_id"])
    explained = int(after.sum())
    other = gap.drop("2025-06")
    check("paid orders per month", (other == 0).all() and gap["2025-06"] == explained,
          f"29 months match exactly; June 2025 is {int(gap['2025-06'])} lower than truth, and all {explained} are "
          f"orders paid after 30 June or sitting in the 1 July shop file, which the warehouse cannot see")
    dm = con.execute("SELECT * FROM mart_deliveries_monthly WHERE month BETWEEN '2023-01' AND '2025-06'").df().set_index("month")
    ld = (dm["late_delivery_rate"] - gm["late_delivery_rate"]).abs()
    check("late delivery rate per month", ld.max() < 1e-5, f"largest difference {ld.max():.6f}")

    br = con.execute("SELECT * FROM mart_revenue_bridge_monthly").df()
    check("revenue bridge adds up", br["residual_gbp"].abs().max() <= 0.05,
          f"largest monthly residual {br['residual_gbp'].abs().max():.2f} GBP across {len(br)} months")

    # 6. Defects.
    scores = defect_scores(con, _gt(truth, "gt_defects.csv"))
    scored = scores[scores["note"] == ""]
    check("defects: every in-scope defect found", (scored["missed"] == 0).all() and (scored["extra"] == 0).all(),
          f"{len(scored)} defect types scored, {int(scored['matched'].sum()):,} of {int(scored['manifest'].sum()):,} "
          f"defect records matched; {int(scored['missed'].sum())} missed, {int(scored['extra'].sum())} extra")

    # 7. Spot checks: random orders, raw line vs warehouse vs truth.
    rng = np.random.default_rng(7)
    sample = io_["order_id"].iloc[rng.choice(len(io_), size=10, replace=False)].tolist()
    con.register("s", pd.DataFrame({"order_id": sample}))
    spot = con.execute("""SELECT o.order_id, o._source_file, o._source_line, o.created_at_local, o.created_at_utc,
                                 o.customer_id, o.currency_code, o.total_amount FROM int_orders o JOIN s USING (order_id)
                          ORDER BY o.order_id""").df()
    spot = spot.rename(columns={"_source_file": "source_file", "_source_line": "source_line"})
    spot = spot.merge(gto[["order_id", "created_at_utc", "customer_id", "total_amount"]], on="order_id",
                      suffixes=("", "_truth"))
    con.close()

    out.mkdir(parents=True, exist_ok=True)
    passed = all(c["passed"] for c in checks)
    (out / "summary.json").write_text(json.dumps({"passed": passed, "checks": checks,
                                                  "defects": scores.to_dict(orient="records")}, indent=2,
                                                 default=str) + "\n")
    md = ["# Validation report: project 1", "",
          "Generated by `python -m halden.ingest validate`. It compares the warehouse with `data/ground_truth`,",
          "which no pipeline code reads.", "", f"Overall: **{'PASS' if passed else 'FAIL'}**", "",
          "| Check | Result | Detail |", "| --- | --- | --- |"]
    md += [f"| {c['check']} | {'pass' if c['passed'] else 'FAIL'} | {c['detail']} |" for c in checks]
    md += ["", "## Defects", "", "| Defect | In manifest | Found | Matched | Missed | Extra | Note |",
           "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for r in scores.itertuples():
        f = lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{int(v):,}"
        md.append(f"| `{r.defect_code}` | {r.manifest:,} | {f(r.found)} | {f(r.matched)} | {f(r.missed)} | "
                  f"{f(r.extra)} | {r.note} |")
    md += ["", "## Spot checks", "", "Ten random orders (seed 7), traced from the raw line to the warehouse and compared with the truth. Most orders "
           "are subscription renewals made by the nightly batch, so most London times fall between 00:30 and 02:30.",
           "", "| Order | Raw file:line | London time | Warehouse UTC | Truth UTC | Customer | Total |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in spot.itertuples():
        cust = r.customer_id if isinstance(r.customer_id, str) else ""
        same = "same" if pd.Timestamp(r.created_at_utc) == pd.Timestamp(r.created_at_utc_truth) else "DIFFERENT"
        md.append(f"| {r.order_id} | {r.source_file}:{r.source_line} | {r.created_at_local} | "
                  f"{pd.Timestamp(r.created_at_utc):%Y-%m-%d %H:%M:%S} | {same} | {cust or 'guest'} "
                  f"({'same' if cust == r.customer_id_truth else 'DIFFERENT'}) | "
                  f"{r.currency_code} {float(r.total_amount):.2f} ({'same' if float(r.total_amount) == float(r.total_amount_truth) else 'DIFFERENT'}) |")
    (out / "report.md").write_text("\n".join(md) + "\n")
    return passed
