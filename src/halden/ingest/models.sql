-- Integrated and mart tables, rebuilt from staging on every run.
-- Statements are separated by a semicolon at the end of a line.

-- VAT rates for roasted coffee by delivery country, as defined in docs/metrics.md.
CREATE OR REPLACE TABLE ref_vat_rates AS
SELECT * FROM (VALUES ('GB', 0.00), ('IE', 0.00), ('DE', 0.07), ('NL', 0.09)) t(country_code, vat_rate);

CREATE OR REPLACE TABLE int_fx_rates AS
SELECT rate_date, any_value(gbp_per_eur) AS gbp_per_eur, count(*) AS n_rows
FROM stg_fx_rates GROUP BY rate_date;

-- One row per processor transaction. In-file repeats were already rejected by the parser;
-- this also covers a transaction resent in a later file, keeping the latest delivery.
CREATE OR REPLACE TABLE int_transactions AS
SELECT * EXCLUDE (rn) FROM (
    SELECT t.*, row_number() OVER (PARTITION BY t.txn_id ORDER BY m.received_at_utc DESC, t._source_line) AS rn
    FROM stg_payproc_transactions t JOIN meta_file_loads m ON m.file_name = t._source_file
) WHERE rn = 1;

-- One row per order. When the same order is in two files (the March 2024 resend), the file
-- received last wins. London wall-clock times inside the repeated autumn hour are resolved
-- with the processor: the first payment attempt follows order creation within seconds.
CREATE OR REPLACE TABLE int_orders AS
WITH versions AS (
    SELECT o.*, m.received_at_utc AS _received_at_utc,
           row_number() OVER (PARTITION BY o.order_id ORDER BY m.received_at_utc DESC, o._source_line) AS rn,
           count(*) OVER (PARTITION BY o.order_id) AS n_versions
    FROM stg_shop_orders o JOIN meta_file_loads m ON m.file_name = o._source_file
),
first_attempt AS (
    SELECT order_ref, min(txn_at_utc) AS first_attempt_at_utc
    FROM int_transactions WHERE txn_type IN ('CAPTURE', 'DECLINE') GROUP BY order_ref
),
capture AS (
    SELECT order_ref, min(txn_at_utc) AS paid_at_utc, sum(gross_amount) AS captured_amount, count(*) AS n_captures
    FROM int_transactions WHERE txn_type = 'CAPTURE' GROUP BY order_ref
)
SELECT
    v.order_id, v.customer_id, v.email_raw, v.email_norm, v.first_name, v.last_name, v.phone_raw,
    v.is_phone_scientific, v.billing_postcode, v.billing_city, v.country_code, v.currency_code, v.order_type,
    v.subscription_id, v.plan_code, v.line_items, v.discount_code, v.subtotal_amount, v.discount_amount,
    v.shipping_amount, v.vat_amount, v.total_amount, v.is_test,
    v.created_at_local,
    CASE
        WHEN v.is_ambiguous_local_time
             AND f.first_attempt_at_utc - (v.created_at_utc + INTERVAL 1 HOUR) BETWEEN INTERVAL 0 SECOND AND INTERVAL 10 MINUTE
            THEN v.created_at_utc + INTERVAL 1 HOUR
        ELSE v.created_at_utc
    END AS created_at_utc,
    CASE
        WHEN v.is_ambiguous_local_time
             AND f.first_attempt_at_utc - (v.created_at_utc + INTERVAL 1 HOUR) BETWEEN INTERVAL 0 SECOND AND INTERVAL 10 MINUTE
            THEN 'resolved_second_instant'
        WHEN v.is_ambiguous_local_time
             AND f.first_attempt_at_utc - v.created_at_utc BETWEEN INTERVAL 0 SECOND AND INTERVAL 10 MINUTE
            THEN 'resolved_first_instant'
        WHEN v.is_ambiguous_local_time THEN 'ambiguous_unresolved'
        WHEN v.created_at_precision = 'minute' THEN 'minute_precision'
        ELSE 'exact'
    END AS created_at_quality,
    c.paid_at_utc, coalesce(c.captured_amount, 0) AS captured_amount, c.paid_at_utc IS NOT NULL AS is_paid,
    v.n_versions, v._source_file, v._source_line
FROM versions v
LEFT JOIN first_attempt f ON f.order_ref = v.order_id
LEFT JOIN capture c ON c.order_ref = v.order_id
WHERE v.rn = 1;

-- The fulfilment partner's corrected file (_v2) replaces the whole week of the original.
CREATE OR REPLACE TABLE int_shipment_events AS
WITH files AS (
    SELECT file_name,
           row_number() OVER (PARTITION BY period_start
                              ORDER BY CASE WHEN suffix LIKE 'v%' THEN CAST(substr(suffix, 2) AS INTEGER) ELSE 1 END DESC,
                                       received_at_utc DESC) AS file_rank
    FROM meta_file_loads WHERE source = 'ful'
),
current_files AS (SELECT file_name FROM files WHERE file_rank = 1),
events AS (
    SELECT s.*, row_number() OVER (PARTITION BY s.shipment_no, s.status ORDER BY s._source_file, s._source_line) AS rn
    FROM stg_ful_shipment_events s WHERE s._source_file IN (SELECT file_name FROM current_files)
)
SELECT * EXCLUDE (rn) FROM events WHERE rn = 1;

CREATE OR REPLACE TABLE int_shipments AS
SELECT
    shipment_no,
    any_value(order_id) AS order_id,
    any_value(customer_id) AS customer_id,
    any_value(site_code) AS site_code,
    any_value(country_code) AS country_code,
    min(dispatch_date) AS dispatch_date,
    max(promised_date) AS promised_date,
    max(CASE WHEN status = 'DELIVERED' THEN delivered_date END) AS delivered_date,
    max(CASE WHEN status = 'LOST' THEN status_date END) AS lost_date,
    CASE
        WHEN max(CASE WHEN status = 'LOST' THEN 1 END) = 1 THEN 'LOST'
        WHEN max(CASE WHEN status = 'DELIVERED' THEN 1 END) = 1 THEN 'DELIVERED'
        ELSE 'IN_TRANSIT'
    END AS shipment_status,
    max(CASE WHEN status = 'DELIVERED' THEN delivered_date END) > max(promised_date) AS is_late,
    max(weight_kg) AS weight_kg,
    bool_or(has_replacement_char) AS has_replacement_char
FROM int_shipment_events
GROUP BY shipment_no;

CREATE OR REPLACE TABLE int_subscription_events AS
SELECT * EXCLUDE (rn) FROM (
    SELECT s.*, row_number() OVER (PARTITION BY coalesce(s.event_id, s.subscription_id || '|snapshot')
                                   ORDER BY s._source_file, s._source_line) AS rn
    FROM stg_shop_subscription_events s
) WHERE rn = 1;

-- Current state of each CRM customer: the latest version by updated_at.
CREATE OR REPLACE TABLE int_crm_customers AS
SELECT * EXCLUDE (rn) FROM (
    SELECT c.*, row_number() OVER (PARTITION BY c.customer_id ORDER BY c.updated_at_utc DESC, m.received_at_utc DESC) AS rn
    FROM stg_crm_customer_versions c JOIN meta_file_loads m ON m.file_name = c._source_file
) WHERE rn = 1;

CREATE OR REPLACE TABLE int_exp_assignments AS
SELECT * EXCLUDE (rn) FROM (
    SELECT e.*, row_number() OVER (PARTITION BY e.event_id ORDER BY e.event_at_utc, e._source_file) AS rn
    FROM stg_exp_assignments e
) WHERE rn = 1;

-- Money movements that count as revenue, in GBP without VAT, per docs/metrics.md.
CREATE OR REPLACE TABLE int_revenue_transactions AS
SELECT
    t.txn_id, t.order_ref, t.txn_type, t.txn_at_utc, CAST(t.txn_at_utc AS DATE) AS txn_date,
    strftime(t.txn_at_utc, '%Y-%m') AS revenue_month, t.currency_code, t.gross_amount,
    o.order_id IS NOT NULL AS is_linked,
    coalesce(o.is_test, false) AS is_test_order,
    coalesce(v.vat_rate, CASE t.currency_code WHEN 'GBP' THEN 0.00 ELSE 0.07 END) AS vat_rate,
    CASE WHEN t.currency_code = 'EUR' THEN fx.gbp_per_eur ELSE 1 END AS fx_rate,
    CAST(t.gross_amount AS DOUBLE) * CASE WHEN t.currency_code = 'EUR' THEN fx.gbp_per_eur ELSE 1 END
        / (1 + coalesce(v.vat_rate, CASE t.currency_code WHEN 'GBP' THEN 0.00 ELSE 0.07 END)) AS amount_gbp_ex_vat
FROM int_transactions t
LEFT JOIN int_orders o ON o.order_id = t.order_ref
LEFT JOIN ref_vat_rates v ON v.country_code = o.country_code
ASOF LEFT JOIN int_fx_rates fx ON CAST(t.txn_at_utc AS DATE) >= fx.rate_date
WHERE t.txn_type IN ('CAPTURE', 'REFUND', 'CHARGEBACK');

CREATE OR REPLACE TABLE mart_revenue_monthly AS
SELECT
    revenue_month AS month,
    round(sum(CASE WHEN txn_type = 'CAPTURE' THEN amount_gbp_ex_vat ELSE 0 END), 2) AS gross_revenue_gbp,
    round(sum(CASE WHEN txn_type = 'REFUND' THEN amount_gbp_ex_vat ELSE 0 END), 2) AS refunds_gbp,
    round(sum(CASE WHEN txn_type = 'CHARGEBACK' THEN amount_gbp_ex_vat ELSE 0 END), 2) AS chargebacks_gbp,
    round(sum(amount_gbp_ex_vat), 2) AS net_revenue_gbp,
    count(*) FILTER (WHERE txn_type = 'CAPTURE') AS captures,
    count(*) FILTER (WHERE NOT is_linked) AS unlinked_transactions
FROM int_revenue_transactions
WHERE NOT is_test_order AND revenue_month BETWEEN '2023-01' AND '2025-06'
GROUP BY revenue_month
ORDER BY revenue_month;

CREATE OR REPLACE TABLE mart_orders_monthly AS
SELECT strftime(created_at_utc, '%Y-%m') AS month,
       count(*) FILTER (WHERE is_paid AND NOT is_test) AS paid_orders,
       count(*) FILTER (WHERE NOT is_paid AND NOT is_test) AS unpaid_orders,
       count(*) FILTER (WHERE is_test) AS test_orders
FROM int_orders GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE TABLE mart_deliveries_monthly AS
SELECT strftime(delivered_date, '%Y-%m') AS month,
       count(*) AS delivered, count(*) FILTER (WHERE is_late) AS late,
       round(count(*) FILTER (WHERE is_late) / count(*), 5) AS late_delivery_rate
FROM int_shipments WHERE delivered_date IS NOT NULL GROUP BY 1 ORDER BY 1;

-- Every loaded file: did the parser account for every record, and did processor files
-- match their own trailer?
CREATE OR REPLACE TABLE mart_load_checks AS
SELECT
    file_name, source, entity, records_read, staged, rejected, blank_ignored,
    records_read = staged + rejected + blank_ignored AS rows_balance,
    CAST(json_extract(control_json, '$.trailer_count') AS INTEGER) AS trailer_count,
    CAST(json_extract(control_json, '$.trailer_gross') AS DECIMAL(14,2)) AS trailer_gross,
    CAST(json_extract(control_json, '$.staged_gross') AS DECIMAL(14,2)) AS staged_gross,
    CASE WHEN source = 'payproc'
         THEN CAST(json_extract(control_json, '$.trailer_count') AS INTEGER) = staged
              AND CAST(json_extract(control_json, '$.trailer_gross') AS DECIMAL(14,2))
                  = CAST(json_extract(control_json, '$.staged_gross') AS DECIMAL(14,2))
    END AS trailer_matches,
    notes
FROM meta_file_loads;
