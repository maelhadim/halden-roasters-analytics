"""Prove the KPI pack shows the right numbers. The only file in project 3 that reads the ground truth.

Three questions, answered in order:

1. Does the workbook show what the warehouse holds? I set the month cell to several months,
   recalculate the file in LibreOffice with no screen, and read every figure back. The edge
   months matter most: the first month has no previous month and no year-ago month, and the
   thirteenth is the first with a year-ago month.
2. Do the workbook's own checks catch a bad refresh? I break a copy on purpose (a partial
   load, a number read as text, a month that is not in the data) and expect a FAIL each time.
3. Does the warehouse agree with the ground truth? Every difference must be one I can name.

Power Query itself only runs in Excel, so it cannot be tested here. The runbook has the
manual check for that step.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pandas as pd
from openpyxl import load_workbook

from .workbook import BRIDGE, COUNTRIES, METRICS

log = logging.getLogger("halden.kpi.validate")
MONTHS = ["2023-01", "2023-02", "2024-01", "2024-06", "2025-06"]
SUMMARY_FIRST_ROW = 9   # row of the first metric on Summary; workbook.py writes the header on row 8


def recalc(xlsx: Path, edit=None) -> "openpyxl.Workbook":
    """Apply `edit` to a copy of the workbook, recalculate it in LibreOffice and return the values."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice is needed to recalculate the workbook: apt-get install libreoffice-calc")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "in" / xlsx.name
        src.parent.mkdir()
        wb = load_workbook(xlsx)
        if edit:
            edit(wb)
        wb.save(src)
        # A private profile, so a LibreOffice window the user has open cannot block the run.
        subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/profile", "--headless", "--calc",
                        "--convert-to", "xlsx", "--outdir", str(tmp / "out"), str(src)],
                       check=True, capture_output=True, timeout=180)
        return load_workbook(tmp / "out" / xlsx.name, data_only=True)


def _blank(v) -> bool:
    return v is None or v == ""


def _summary(wb) -> dict:
    ws = wb["Summary"]
    out = {"month": ws["C5"].value, "status": ws["C6"].value, "metrics": {}, "countries": {}, "bridge": {}}
    for i, (key, *_rest) in enumerate(METRICS):
        r = SUMMARY_FIRST_ROW + i
        assert ws.cell(row=r, column=10).value == key, f"Summary row {r} is not {key}"
        out["metrics"][key] = {"this": ws.cell(row=r, column=3).value, "previous": ws.cell(row=r, column=4).value,
                               "year_ago": ws.cell(row=r, column=7).value}
    for row in ws.iter_rows(min_row=SUMMARY_FIRST_ROW, max_col=10):
        key = row[9].value
        if key in {c for c, _ in COUNTRIES}:
            out["countries"][key] = [row[2].value, row[3].value, row[4].value]
        elif key in {k for k, _ in BRIDGE} and row[1].value in {label for _, label in BRIDGE}:
            out["bridge"][key] = row[2].value
    return out


def _same(a, b, tol=1e-9) -> bool:
    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)
    return abs(float(a) - float(b)) <= tol


def workbook_matches(xlsx: Path, con) -> list[dict]:
    kpi = con.execute("SELECT * FROM mart_kpi_monthly ORDER BY month").df().set_index("month")
    country = con.execute("SELECT * FROM mart_kpi_country_monthly").df().set_index(["month", "country_code"])
    bridge = con.execute("SELECT * FROM mart_revenue_bridge_monthly").df().set_index("month")
    months = list(kpi.index)
    results = []
    for month in MONTHS:
        def pick(wb, m=month):
            wb["Summary"]["C5"] = m
        s = _summary(recalc(xlsx, pick))
        i = months.index(month)
        compared, wrong = 0, []
        for key, vals in s["metrics"].items():
            for label, j in (("this", i), ("previous", i - 1), ("year_ago", i - 12)):
                want = kpi[key].iloc[j] if j >= 0 else None
                compared += 1
                if not _same(vals[label], want):
                    wrong.append(f"{key} {label}: workbook {vals[label]!r}, warehouse {want!r}")
        for code, vals in s["countries"].items():
            row = country.loc[(month, code)]
            for got, key in zip(vals, ["active_subscribers", "mrr_gbp", "net_revenue_gbp"]):
                compared += 1
                if not _same(got, row[key]):
                    wrong.append(f"{code} {key}: workbook {got!r}, warehouse {row[key]!r}")
        for key, got in s["bridge"].items():
            compared += 1
            if not _same(got, bridge.loc[month, key]):
                wrong.append(f"bridge {key}: workbook {got!r}, warehouse {bridge.loc[month, key]!r}")
        results.append({"month": month, "values_compared": compared, "mismatches": wrong,
                        "status": s["status"], "passed": not wrong and s["status"] == "All checks pass"})
        log.info("%s: %d values compared, %d mismatches, %s", month, compared, len(wrong), s["status"])
    return results


def _drop_last_country_row(wb):
    ws = wb["Data_Country"]
    ws.delete_rows(ws.max_row)


def _text_number(wb):
    # What a refresh on a PC with comma decimals would load if the query did not set en-US.
    ws = wb["Data_Monthly"]
    col = [c.value for c in ws[1]].index("net_revenue_gbp") + 1
    ws.cell(row=ws.max_row, column=col).value = "175478,81"


def _missing_month(wb):
    wb["Summary"]["C5"] = "2025-07"


TAMPER = [
    ("a refresh that loaded Data_Country only partly (last row missing)", _drop_last_country_row,
     "Data_Country: rows match the manifest"),
    ("June 2025 net revenue loaded as the text \"175478,81\"", _text_number,
     "Data_Monthly: net revenue total matches the manifest"),
    ("a month typed into Summary!C5 that is not in the data", _missing_month, "Selected month is in the data"),
]


def checks_catch_tampering(xlsx: Path) -> list[dict]:
    out = []
    for what, edit, expected_check in TAMPER:
        ck = recalc(xlsx, edit)["Checks"]
        failed = [ck.cell(row=r, column=2).value for r in range(7, ck.max_row + 1)
                  if ck.cell(row=r, column=4).value not in (None, "PASS")]
        caught = ck["C3"].value == "FAIL" and expected_check in failed
        out.append({"tampering": what, "overall": ck["C3"].value, "failed_checks": failed, "caught": caught})
        log.info("tamper %r: overall %s, failed %s", what, ck["C3"].value, failed)
    return out


def june_mrr_gap(con, truth: Path) -> dict:
    """List the subscriptions that are active at the end of June 2025 in one source but not the other,
    and price them the way mart_mrr_monthly does. Their total must equal the MRR gap."""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE gt_subs AS
        SELECT s.subscription_id, s.plan_code, s.frequency, a.country_code,
               CAST(s.started_at_utc AS TIMESTAMPTZ) AS started_at_utc, CAST(s.ended_at_utc AS TIMESTAMPTZ) AS ended_at_utc
        FROM read_csv('{truth / "gt_subscriptions.csv"}', all_varchar = true) s
        JOIN read_csv('{truth / "gt_accounts.csv"}', all_varchar = true) a USING (customer_id)""")
    rows = con.execute("""
        WITH cut AS (SELECT TIMESTAMPTZ '2025-06-30 23:59:59+00' AS t, DATE '2025-06-30' AS d,
                            (SELECT gbp_per_eur FROM int_fx_rates WHERE rate_date <= DATE '2025-06-30'
                             ORDER BY rate_date DESC LIMIT 1) AS fx),
        wh AS (SELECT subscription_id FROM int_subscriptions, cut
               WHERE started_at_utc <= cut.t AND (ended_at_utc IS NULL OR ended_at_utc > cut.t)),
        gt AS (SELECT subscription_id FROM gt_subs, cut
               WHERE started_at_utc <= cut.t AND (ended_at_utc IS NULL OR ended_at_utc > cut.t)),
        diff AS (SELECT subscription_id, 1 AS sign FROM (SELECT * FROM wh EXCEPT SELECT * FROM gt)
                 UNION ALL SELECT subscription_id, -1 FROM (SELECT * FROM gt EXCEPT SELECT * FROM wh))
        SELECT d.subscription_id, d.sign, g.started_at_utc, g.ended_at_utc,
               d.sign * pr.list_price / (1 + v.vat_rate)
                 * CASE WHEN g.frequency = 'FORTNIGHTLY' THEN 26.0 / 12 ELSE 1 END
                 * CASE WHEN g.country_code = 'GB' THEN 1 ELSE cut.fx END AS mrr_effect_gbp
        FROM diff d JOIN gt_subs g USING (subscription_id), cut
        JOIN ref_plan_prices pr ON pr.plan_code = g.plan_code
             AND pr.currency_code = CASE WHEN g.country_code = 'GB' THEN 'GBP' ELSE 'EUR' END
             AND cut.d BETWEEN pr.valid_from AND pr.valid_to
        JOIN ref_vat_rates v ON v.country_code = g.country_code
        ORDER BY 1""").df()
    return {"subscriptions": [
        {"subscription_id": r.subscription_id,
         "side": "warehouse only" if r.sign > 0 else "truth only",
         "started_at_utc": str(r.started_at_utc), "ended_at_utc": None if pd.isna(r.ended_at_utc) else str(r.ended_at_utc),
         "mrr_effect_gbp": round(float(r.mrr_effect_gbp), 2)} for r in rows.itertuples()],
        "explained_gbp": round(float(rows["mrr_effect_gbp"].sum()), 2)}


# What each metric may differ by, and why. Anything not listed here must match exactly.
KNOWN = {
    "paid_orders": ("2025-06", "orders paid after 30 June or sitting in the 1 July shop file, which the warehouse "
                    "cannot see (project 1)"),
    "mrr_gbp": ("2025-06", "subscriptions whose start or cancellation on 30 June arrived in the 1 July file"),
}
PERSON_METRICS = {"active_subscribers", "new_subscribers", "churned_subscribers", "monthly_churn_rate"}


def warehouse_matches_truth(con, truth: Path) -> tuple[list[dict], dict]:
    kpi = con.execute("SELECT * FROM mart_kpi_monthly ORDER BY month").df().set_index("month")
    gt = pd.read_csv(truth / "gt_monthly_metrics.csv", dtype={"month": str}).set_index("month")
    gap = june_mrr_gap(con, truth)
    rows = []
    for col in gt.columns:
        d = (kpi[col] - gt[col]).round(6)
        off = d[d.abs() > 1e-9]
        if col in PERSON_METRICS:
            # The one false merge in project 2 (two people with one phone) can move a count by one.
            ok = (off.abs() <= (1 if col != "monthly_churn_rate" else 0.0002)).all()
            why = "identity resolution merged one pair of people wrongly (project 2), which moves a count by 1"
        elif col in KNOWN:
            month, why = KNOWN[col]
            ok = list(off.index) in ([], [month])
            if col == "mrr_gbp":
                ok = ok and abs(off.sum() - gap["explained_gbp"]) < 0.01
            if col == "paid_orders":
                ok = ok and off.abs().sum() <= 26
        else:
            ok, why = off.empty, ""
        rows.append({"metric": col, "months_different": len(off),
                     "largest_difference": float(d.abs().max()),
                     "differences": {m: float(v) for m, v in off.items()},
                     "explained_by": why if not off.empty else "", "passed": bool(ok)})
    return rows, gap


def unlinked_revenue(con) -> dict:
    """Revenue with no order has no country; mart_kpi_country_monthly puts GBP on GB and EUR on DE."""
    rows = con.execute("""
        SELECT r.currency_code, count(*) AS n, round(sum(r.amount_gbp_ex_vat), 2) AS gbp
        FROM int_revenue_transactions r LEFT JOIN int_orders o ON o.order_id = r.order_ref
        WHERE NOT r.is_test_order AND r.revenue_month BETWEEN '2023-01' AND '2025-06' AND o.country_code IS NULL
        GROUP BY 1 ORDER BY 1""").fetchall()
    return {cur: {"transactions": n, "net_gbp": float(gbp)} for cur, n, gbp in rows}


def _fmt(v: float) -> str:
    if abs(v - round(v)) <= 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:.5f}" if abs(v) < 0.01 else f"{v:,.2f}"   # rates are stored to 5 decimals


def validate(db: Path, truth: Path, pack: Path) -> bool:
    xlsx = pack / "halden_kpi_pack.xlsx"
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone = 'UTC'")
    try:
        shown = workbook_matches(xlsx, con)
        tamper = checks_catch_tampering(xlsx)
        truth_rows, gap = warehouse_matches_truth(con, truth)
        unlinked = unlinked_revenue(con)
    finally:
        con.close()
    passed = all(r["passed"] for r in shown) and all(t["caught"] for t in tamper) and all(r["passed"] for r in truth_rows)

    out = pack / "validation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(
        {"passed": passed, "workbook_vs_warehouse": shown, "checks_catch_tampering": tamper,
         "warehouse_vs_truth": truth_rows, "june_2025_mrr_gap": gap,
         "revenue_without_country": unlinked}, indent=2) + "\n")

    total = sum(r["values_compared"] for r in shown)
    lines = [
        "# Project 3 validation", "",
        f"Overall: **{'pass' if passed else 'FAIL'}**. Written by `python -m halden.kpi validate`; "
        "do not edit by hand. Synthetic data.", "",
        "## 1. The workbook shows what the warehouse holds", "",
        "For each month I set Summary!C5, recalculated the file in LibreOffice and compared every figure on the "
        "Summary sheet (this month, previous month and a year earlier for 11 metrics, four countries and the "
        "nine bridge lines) with the warehouse tables. A blank must be blank, for example the previous month "
        "of January 2023.", "",
        "| Month | Values compared | Mismatches | Status cell |", "|---|---:|---:|---|",
    ]
    lines += [f"| {r['month']} | {r['values_compared']} | {len(r['mismatches'])} | {r['status']} |" for r in shown]
    lines += ["", f"{total} values compared in all, {sum(len(r['mismatches']) for r in shown)} mismatches.", "",
              "## 2. The workbook's checks catch a bad refresh", "",
              "Each row is a copy of the workbook broken on purpose. The overall check must say FAIL, and the "
              "check named for that problem must be among the failures.", "",
              "| Broken copy | Overall | Checks that failed | Caught |", "|---|---|---|---|"]
    lines += [f"| {t['tampering']} | {t['overall']} | {'; '.join(t['failed_checks'])} | "
              f"{'yes' if t['caught'] else 'NO'} |" for t in tamper]
    lines += ["", "## 3. The warehouse agrees with the ground truth", "",
              "Monthly figures in `kpi_monthly.csv` compared with `gt_monthly_metrics.csv`, which the generator "
              "wrote from its own records before any defects were added.", "",
              "| Metric | Months different | Largest difference | Why | Result |", "|---|---:|---:|---|---|"]
    for r in truth_rows:
        lines.append(f"| `{r['metric']}` | {r['months_different']} | {_fmt(r['largest_difference'])} | "
                     f"{r['explained_by']} | {'pass' if r['passed'] else 'FAIL'} |")
    lines += ["", "### The June 2025 MRR gap", "",
              "MRR counts subscriptions active at 23:59:59 UTC on 30 June. These subscriptions are active then in "
              "one source and not the other. Priced the way `mart_mrr_monthly` prices them, they add up to "
              f"{_fmt(gap['explained_gbp'])} GBP, which is the whole gap.", "",
              "| Subscription | Active at month end in | Started (UTC) | Ended (UTC) | MRR effect, GBP |",
              "|---|---|---|---|---:|"]
    lines += [f"| {s['subscription_id']} | {s['side']} | {s['started_at_utc']} | {s['ended_at_utc'] or ''} | "
              f"{s['mrr_effect_gbp']:,.2f} |" for s in gap["subscriptions"]]
    lines += ["", "The warehouse can only know what the feeds delivered by 30 June. A cancellation made late on "
              "30 June, or a subscription started then, reaches it in the 1 July file, and loading that file "
              "will restate June by this amount. I left the June figure as the warehouse sees it rather "
              "than patch it, because a pack that quietly differs from its own source is worse than one with a "
              "known, explained lag.", ""]
    none = {"transactions": 0, "net_gbp": 0.0}
    eur, gbp = unlinked.get("EUR", none), unlinked.get("GBP", none)
    lines += ["## Revenue with no country", "",
              f"{eur['transactions'] + gbp['transactions']} transactions in the 30 months cannot be linked to an "
              "order, so they have no country. On the country table the GBP ones go to the United Kingdom "
              f"({gbp['transactions']}, {gbp['net_gbp']:,.2f} GBP) and the EUR ones to Germany, the largest euro "
              f"market ({eur['transactions']}, {eur['net_gbp']:,.2f} GBP). Monthly totals are not affected.", "",
              "## What this does not test", "",
              "Power Query runs only inside Excel, so the refresh step is checked by hand on Windows "
              "(runbook, step 4). The M scripts are tested here only for their column lists and types.", ""]
    (out / "report.md").write_text("\n".join(lines))
    log.info("validation %s; report in %s", "passed" if passed else "FAILED", out)
    return passed
