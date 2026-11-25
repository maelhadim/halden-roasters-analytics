-- Staging, reject and ledger tables. Types are fixed here rather than inferred from pandas,
-- so a file that happens to contain only blanks in a column cannot change a column's type.

CREATE TABLE IF NOT EXISTS meta_file_loads (
    file_name        VARCHAR PRIMARY KEY,
    source           VARCHAR NOT NULL,
    entity           VARCHAR NOT NULL,
    period_start     DATE NOT NULL,
    suffix           VARCHAR NOT NULL,
    received_at_utc  TIMESTAMPTZ NOT NULL,
    sha256           VARCHAR NOT NULL,
    records_read     INTEGER NOT NULL,
    staged           INTEGER NOT NULL,
    rejected         INTEGER NOT NULL,
    blank_ignored    INTEGER NOT NULL,
    notes            VARCHAR,
    control_json     VARCHAR,
    run_id           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta_runs (
    run_id           INTEGER PRIMARY KEY,
    started_at_utc   TIMESTAMPTZ NOT NULL,
    as_of_utc        TIMESTAMPTZ,
    files_seen       INTEGER,
    files_loaded     INTEGER,
    files_unchanged  INTEGER,
    finished_at_utc  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS stg_shop_orders (
    order_id VARCHAR, created_at_local TIMESTAMP, created_at_utc TIMESTAMPTZ, created_at_precision VARCHAR,
    is_ambiguous_local_time BOOLEAN, customer_id VARCHAR, email_raw VARCHAR, email_norm VARCHAR,
    first_name VARCHAR, last_name VARCHAR, phone_raw VARCHAR, is_phone_scientific BOOLEAN,
    billing_postcode VARCHAR, billing_city VARCHAR, country_code VARCHAR, currency_code VARCHAR,
    order_type VARCHAR, subscription_id VARCHAR, plan_code VARCHAR, line_items VARCHAR, discount_code VARCHAR,
    subtotal_amount DECIMAL(12,2), discount_amount DECIMAL(12,2), shipping_amount DECIMAL(12,2),
    vat_amount DECIMAL(12,2), total_amount DECIMAL(12,2), is_test BOOLEAN,
    _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_shop_subscription_events (
    subscription_id VARCHAR, customer_id VARCHAR, plan_code VARCHAR, frequency VARCHAR, record_type VARCHAR,
    event_id VARCHAR, event_type VARCHAR, event_at_utc TIMESTAMPTZ, cancel_reason VARCHAR,
    is_late_event BOOLEAN, is_ambiguous_local_time BOOLEAN,
    _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_payproc_transactions (
    txn_id VARCHAR, order_ref VARCHAR, txn_type VARCHAR, txn_at_utc TIMESTAMPTZ, currency_code VARCHAR,
    gross_amount DECIMAL(12,2), fee_amount DECIMAL(12,2), net_amount DECIMAL(12,2), settlement_date VARCHAR,
    card_country VARCHAR, decline_code VARCHAR, schema_version VARCHAR, is_off_file_date BOOLEAN,
    _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_ful_shipment_events (
    shipment_no VARCHAR, order_id VARCHAR, customer_id VARCHAR, site_code VARCHAR, recipient_name VARCHAR,
    has_replacement_char BOOLEAN, country_code VARCHAR, status VARCHAR, dispatch_date DATE, promised_date DATE,
    delivered_date DATE, status_date DATE, weight_kg DECIMAL(8,2),
    _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_crm_customer_versions (
    customer_id VARCHAR, legacy_id VARCHAR, first_name VARCHAR, last_name VARCHAR, email VARCHAR, phone VARCHAR,
    street VARCHAR, city VARCHAR, postcode VARCHAR, country_code VARCHAR, marketing_opt_in VARCHAR, notes VARCHAR,
    email_norm VARCHAR, created_at_utc TIMESTAMPTZ, updated_at_utc TIMESTAMPTZ, is_snapshot BOOLEAN,
    _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_exp_assignments (
    event_id VARCHAR, experiment_id VARCHAR, customer_id VARCHAR, variant VARCHAR, event_at_utc TIMESTAMPTZ,
    _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_fx_rates (
    rate_date DATE, gbp_per_eur DECIMAL(10,5), _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rej_records (
    source VARCHAR NOT NULL, entity VARCHAR NOT NULL, _source_file VARCHAR NOT NULL, _source_line INTEGER NOT NULL,
    raw_record VARCHAR, reject_reason VARCHAR NOT NULL
);
