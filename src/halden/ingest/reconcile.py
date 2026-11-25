"""Why did the old BI revenue figure disagree with the card processor? A step-by-step bridge.

The old monthly report summed `total_amount` over every row of every shop file, grouped by
the date in the file name, and converted EUR at the month's average rate. That method is
reconstructed here as step 0. Each later step changes one thing, in the order a finance
analyst would explain it, and the last step lands on net revenue as defined in
docs/metrics.md. Each step is the difference between two measures, so the bridge adds up
exactly; the residual column proves it.
"""
from __future__ import annotations

STEPS = [
    ("m0_bi_reported", "Old BI report: every shop file row, file month, monthly average FX"),
    ("m1_unique_orders", "Count each order once (the March 2024 resend was loaded twice)"),
    ("m2_no_test_orders", "Remove QA test orders"),
    ("m3_paid_orders", "Remove orders whose payment never succeeded"),
    ("m4_capture_month", "Book revenue in the UTC month the payment was captured"),
    ("m5_daily_fx", "Convert EUR at the rate for the capture date, not the month average"),
    ("m6_after_refunds", "Subtract refunds and chargebacks, including those with no order"),
    ("m7_ex_vat", "Remove VAT: net revenue as defined in docs/metrics.md"),
]

SQL = """
CREATE OR REPLACE TABLE mart_revenue_bridge_monthly AS
WITH fx_month AS (
    SELECT strftime(rate_date, '%Y-%m') AS month, avg(gbp_per_eur) AS avg_rate FROM int_fx_rates GROUP BY 1
),
m0 AS (
    SELECT strftime(m.period_start, '%Y-%m') AS month,
           sum(CAST(o.total_amount AS DOUBLE) * CASE WHEN o.currency_code = 'EUR' THEN f.avg_rate ELSE 1 END) AS v
    FROM stg_shop_orders o JOIN meta_file_loads m ON m.file_name = o._source_file
    JOIN fx_month f ON f.month = strftime(m.period_start, '%Y-%m')
    GROUP BY 1
),
orders AS (
    SELECT o.*, strftime(o.created_at_local, '%Y-%m') AS local_month FROM int_orders o
),
m1 AS (SELECT local_month AS month, sum(CAST(total_amount AS DOUBLE) * CASE WHEN currency_code = 'EUR' THEN f.avg_rate ELSE 1 END) AS v
       FROM orders JOIN fx_month f ON f.month = local_month GROUP BY 1),
m2 AS (SELECT local_month AS month, sum(CAST(total_amount AS DOUBLE) * CASE WHEN currency_code = 'EUR' THEN f.avg_rate ELSE 1 END) AS v
       FROM orders JOIN fx_month f ON f.month = local_month WHERE NOT is_test GROUP BY 1),
m3 AS (SELECT local_month AS month, sum(CAST(total_amount AS DOUBLE) * CASE WHEN currency_code = 'EUR' THEN f.avg_rate ELSE 1 END) AS v
       FROM orders JOIN fx_month f ON f.month = local_month WHERE NOT is_test AND is_paid GROUP BY 1),
rev AS (SELECT * FROM int_revenue_transactions WHERE NOT is_test_order),
m4 AS (SELECT revenue_month AS month, sum(CAST(gross_amount AS DOUBLE) * CASE WHEN currency_code = 'EUR' THEN f.avg_rate ELSE 1 END) AS v
       FROM rev JOIN fx_month f ON f.month = revenue_month WHERE txn_type = 'CAPTURE' GROUP BY 1),
m5 AS (SELECT revenue_month AS month, sum(CAST(gross_amount AS DOUBLE) * fx_rate) AS v FROM rev WHERE txn_type = 'CAPTURE' GROUP BY 1),
m6 AS (SELECT revenue_month AS month, sum(CAST(gross_amount AS DOUBLE) * fx_rate) AS v FROM rev GROUP BY 1),
m7 AS (SELECT revenue_month AS month, sum(amount_gbp_ex_vat) AS v FROM rev GROUP BY 1),
months AS (SELECT month FROM m0 UNION SELECT month FROM m4)
SELECT
    months.month,
    round(coalesce(m0.v, 0), 2) AS bi_reported_gbp,
    round(coalesce(m1.v, 0) - coalesce(m0.v, 0), 2) AS step1_duplicate_loads,
    round(coalesce(m2.v, 0) - coalesce(m1.v, 0), 2) AS step2_test_orders,
    round(coalesce(m3.v, 0) - coalesce(m2.v, 0), 2) AS step3_unpaid_orders,
    round(coalesce(m4.v, 0) - coalesce(m3.v, 0), 2) AS step4_capture_month,
    round(coalesce(m5.v, 0) - coalesce(m4.v, 0), 2) AS step5_daily_fx,
    round(coalesce(m6.v, 0) - coalesce(m5.v, 0), 2) AS step6_refunds_chargebacks,
    round(coalesce(m7.v, 0) - coalesce(m6.v, 0), 2) AS step7_vat,
    round(coalesce(m7.v, 0), 2) AS net_revenue_gbp
FROM months
LEFT JOIN m0 USING (month) LEFT JOIN m1 USING (month) LEFT JOIN m2 USING (month) LEFT JOIN m3 USING (month)
LEFT JOIN m4 USING (month) LEFT JOIN m5 USING (month) LEFT JOIN m6 USING (month) LEFT JOIN m7 USING (month)
WHERE months.month BETWEEN '2023-01' AND '2025-06'
ORDER BY months.month;

CREATE OR REPLACE TABLE mart_revenue_bridge_monthly AS
SELECT *,
       round(bi_reported_gbp + step1_duplicate_loads + step2_test_orders + step3_unpaid_orders + step4_capture_month
             + step5_daily_fx + step6_refunds_chargebacks + step7_vat - net_revenue_gbp, 2) AS residual_gbp
FROM mart_revenue_bridge_monthly;
"""


def build_reconciliation(con):
    for stmt in [s.strip() for s in SQL.split(";\n") if s.strip()]:
        con.execute(stmt)
