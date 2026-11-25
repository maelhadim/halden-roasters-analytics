"""Build the monthly KPI tables and write the files the Excel pack reads.

    python -m halden.kpi extract [--db data/warehouse.duckdb] [--out project_03_kpi_pack/data]

Every number in the pack comes from the warehouse built by projects 1 and 2. Nothing is
calculated in Excel except comparisons between months and the checks, so the workbook can
never disagree with the warehouse about what a metric means.

The files are plain UTF-8 CSV with a header, comma separators, dot decimals, ISO dates and
LF line ends, because that is what Power Query reads without guessing. A manifest lists each
file's rows, SHA-256 and a control total, and the workbook checks itself against it.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import duckdb
import pandas as pd

log = logging.getLogger("halden.kpi")

# List prices from docs/company.md. They are business reference data, not something the
# pipelines can read from a file, so they live here, next to the one query that uses them.
PRICES_SQL = """
CREATE OR REPLACE TABLE ref_plan_prices AS
SELECT * FROM (VALUES
    ('CLASSIC_250',    'GBP', DATE '2000-01-01', DATE '2025-01-31', 11.50), ('CLASSIC_250',    'GBP', DATE '2025-02-01', DATE '2099-12-31', 12.50),
    ('CLASSIC_250',    'EUR', DATE '2000-01-01', DATE '2025-01-31', 13.50), ('CLASSIC_250',    'EUR', DATE '2025-02-01', DATE '2099-12-31', 14.90),
    ('EXPLORER_2X250', 'GBP', DATE '2000-01-01', DATE '2025-01-31', 21.00), ('EXPLORER_2X250', 'GBP', DATE '2025-02-01', DATE '2099-12-31', 22.50),
    ('EXPLORER_2X250', 'EUR', DATE '2000-01-01', DATE '2025-01-31', 24.50), ('EXPLORER_2X250', 'EUR', DATE '2025-02-01', DATE '2099-12-31', 26.50),
    ('ESPRESSO_1KG',   'GBP', DATE '2000-01-01', DATE '2025-01-31', 32.00), ('ESPRESSO_1KG',   'GBP', DATE '2025-02-01', DATE '2099-12-31', 34.00),
    ('ESPRESSO_1KG',   'EUR', DATE '2000-01-01', DATE '2025-01-31', 37.00), ('ESPRESSO_1KG',   'EUR', DATE '2025-02-01', DATE '2099-12-31', 39.50)
) t(plan_code, currency_code, valid_from, valid_to, list_price)
"""

MODELS = """
-- Plan and frequency per subscription (the same on every event of one subscription).
CREATE OR REPLACE TABLE int_subscription_plans AS
SELECT subscription_id, any_value(plan_code) AS plan_code, any_value(frequency) AS frequency
FROM int_subscription_events GROUP BY 1;

-- MRR as defined in docs/metrics.md: list price at month end, without VAT, made monthly,
-- converted at the month-end rate.
CREATE OR REPLACE TABLE mart_mrr_monthly AS
WITH months AS (
    SELECT strftime(d, '%Y-%m') AS month, d + INTERVAL 1 MONTH - INTERVAL 1 SECOND AS month_end,
           CAST(d + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE) AS month_end_date
    FROM generate_series(TIMESTAMPTZ '2023-01-01 00:00:00+00', TIMESTAMPTZ '2025-06-01 00:00:00+00', INTERVAL 1 MONTH) g(d)
),
fx AS (   -- the last rate published on or before the month-end date
    SELECT m.month, (SELECT gbp_per_eur FROM int_fx_rates r WHERE r.rate_date <= m.month_end_date
                     ORDER BY r.rate_date DESC LIMIT 1) AS gbp_per_eur
    FROM months m
),
active AS (
    SELECT m.month, m.month_end_date, s.subscription_id, a.country_code,
           CASE WHEN a.country_code = 'GB' THEN 'GBP' ELSE 'EUR' END AS currency_code, p.plan_code, p.frequency
    FROM months m
    JOIN int_subscriptions s ON s.started_at_utc <= m.month_end AND (s.ended_at_utc IS NULL OR s.ended_at_utc > m.month_end)
    JOIN int_subscription_plans p USING (subscription_id)
    JOIN int_identity_accounts a ON a.customer_id = s.customer_id
)
SELECT a.month, a.country_code,
       sum(pr.list_price / (1 + v.vat_rate) * CASE WHEN a.frequency = 'FORTNIGHTLY' THEN 26.0 / 12 ELSE 1 END
           * CASE WHEN a.currency_code = 'EUR' THEN fx.gbp_per_eur ELSE 1 END) AS mrr_gbp,
       count(*) AS active_subscriptions
FROM active a
JOIN ref_plan_prices pr ON pr.plan_code = a.plan_code AND pr.currency_code = a.currency_code
     AND a.month_end_date BETWEEN pr.valid_from AND pr.valid_to
JOIN ref_vat_rates v ON v.country_code = a.country_code
JOIN fx USING (month)
GROUP BY ALL;

-- One row per month with every metric in docs/metrics.md, in the order the pack shows them.
CREATE OR REPLACE TABLE mart_kpi_monthly AS
SELECT s.month,
       s.active_subscribers, s.active_subscription_accounts, s.new_subscribers, s.churned_subscribers,
       s.monthly_churn_rate, n.new_customers, n.new_accounts,
       round(m.mrr_gbp, 2) AS mrr_gbp,
       round(r.gross_revenue_gbp, 2) AS gross_revenue_gbp, round(r.refunds_gbp, 2) AS refunds_gbp,
       round(r.chargebacks_gbp, 2) AS chargebacks_gbp, round(r.net_revenue_gbp, 2) AS net_revenue_gbp,
       o.paid_orders, d.delivered AS parcels_delivered, d.late AS parcels_late, round(d.late_delivery_rate, 5) AS late_delivery_rate
FROM mart_subscribers_monthly s
JOIN mart_new_customers_monthly n USING (month)
JOIN (SELECT month, sum(mrr_gbp) AS mrr_gbp FROM mart_mrr_monthly GROUP BY 1) m USING (month)
JOIN mart_revenue_monthly r USING (month)
JOIN mart_orders_monthly o USING (month)
JOIN mart_deliveries_monthly d USING (month)
ORDER BY s.month;

-- The same core metrics by country, for the second page of the pack.
CREATE OR REPLACE TABLE mart_kpi_country_monthly AS
WITH subs AS (
    SELECT m.month, a.country_code, count(DISTINCT p.person_key) AS active_subscribers
    FROM (SELECT strftime(d, '%Y-%m') AS month, d + INTERVAL 1 MONTH - INTERVAL 1 SECOND AS month_end
          FROM generate_series(TIMESTAMPTZ '2023-01-01 00:00:00+00', TIMESTAMPTZ '2025-06-01 00:00:00+00', INTERVAL 1 MONTH) g(d)) m
    JOIN int_subscriptions s ON s.started_at_utc <= m.month_end AND (s.ended_at_utc IS NULL OR s.ended_at_utc > m.month_end)
    JOIN int_customer_person p USING (customer_id)
    JOIN int_identity_accounts a ON a.customer_id = s.customer_id
    GROUP BY ALL
),
-- A transaction with no order (mostly unlinked refunds) has no country. GBP goes to GB and EUR to
-- DE, the largest euro market. The validation report lists how much this moves.
rev AS (
    SELECT r.revenue_month AS month, coalesce(o.country_code, CASE r.currency_code WHEN 'GBP' THEN 'GB' ELSE 'DE' END) AS country_code,
           sum(r.amount_gbp_ex_vat) AS net_revenue_gbp
    FROM int_revenue_transactions r LEFT JOIN int_orders o ON o.order_id = r.order_ref
    WHERE NOT r.is_test_order AND r.revenue_month BETWEEN '2023-01' AND '2025-06'
    GROUP BY ALL
)
SELECT s.month, s.country_code, s.active_subscribers, round(m.mrr_gbp, 2) AS mrr_gbp,
       round(coalesce(r.net_revenue_gbp, 0), 2) AS net_revenue_gbp
FROM subs s
JOIN mart_mrr_monthly m USING (month, country_code)
LEFT JOIN rev r USING (month, country_code)
ORDER BY s.month, s.country_code;
"""

EXPORTS = {
    "kpi_monthly.csv": ("SELECT * FROM mart_kpi_monthly ORDER BY month", "net_revenue_gbp"),
    "kpi_country_monthly.csv": ("SELECT * FROM mart_kpi_country_monthly ORDER BY month, country_code", "net_revenue_gbp"),
    "revenue_bridge_monthly.csv": ("SELECT * FROM mart_revenue_bridge_monthly ORDER BY month", "net_revenue_gbp"),
}


def build(con) -> None:
    con.execute(PRICES_SQL)
    for stmt in [s.strip() for s in MODELS.split(";\n") if s.strip()]:
        con.execute(stmt)


def _csv(df: pd.DataFrame) -> bytes:
    # Fixed formatting, so the same data always gives the same bytes and the same checksum.
    # Adding 0.0 turns -0.0 into 0.0, which would otherwise be written as "-0".
    df = df.copy()
    for c in df.select_dtypes("float").columns:
        df[c] = df[c] + 0.0
    return df.to_csv(index=False, lineterminator="\n", float_format="%.10g").encode("utf-8")


def extract(db: Path, out: Path) -> pd.DataFrame:
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone = 'UTC'")
    try:
        build(con)
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for name, (sql, control) in EXPORTS.items():
            df = con.execute(sql).df()
            data = _csv(df)
            (out / name).write_bytes(data)
            rows.append({"file_name": name, "rows": len(df), "columns": len(df.columns),
                         "control_column": control, "control_total": round(float(df[control].sum()), 2),
                         "sha256": hashlib.sha256(data).hexdigest()})
            log.info("%s: %d rows, %s total %.2f", name, len(df), control, rows[-1]["control_total"])
    finally:
        con.close()
    manifest = pd.DataFrame(rows)
    (out / "_manifest.csv").write_bytes(_csv(manifest))
    return manifest
