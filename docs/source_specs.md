# Source file specifications

This is what each source system says it sends. The real files do not always match.
The known differences are listed in `data/ground_truth/gt_defect_catalogue.csv`, which
pipelines must not read, and project 1 has to find them in the files themselves.

## shop: orders

`shop/shop_orders_YYYYMMDD.csv`. One file per London calendar day, UTF-8, comma-delimited,
double-quote quoting, header row. Arrives around 01:00 UTC the next day.

| Column | Notes |
| --- | --- |
| `order_id` | Text, 7 digits |
| `created_at` | `YYYY-MM-DD HH:MM:SS`, Europe/London wall-clock time, no offset |
| `customer_id` | `C` plus 6 digits; blank for guest checkout |
| `email`, `first_name`, `last_name`, `phone` | As held on the account, or as typed at guest checkout |
| `billing_postcode`, `billing_city`, `country_code` | Delivery country, ISO 3166 alpha-2 |
| `currency_code` | GBP for GB, EUR otherwise |
| `order_type` | `SUBSCRIPTION` or `ONE_OFF` |
| `subscription_id`, `plan_code` | Blank for one-off orders |
| `line_items` | `SKU:qty` pairs separated by `;` |
| `subtotal_amount`, `discount_amount`, `shipping_amount`, `vat_amount`, `total_amount` | Decimal point, 2 places. `total = subtotal - discount + shipping`. Prices include VAT; `vat_amount` is the VAT inside the total. |
| `discount_code` | `WELCOME50` (first box, 50%), `RET30` (retention offer, 30%) or blank |

## shop: subscription events

`shop/shop_subscriptions_YYYYMMDD.csv`, same format and timing as orders. Columns:
`event_id`, `event_at` (London local), `subscription_id`, `customer_id`, `event_type`
(`CREATED`, `CANCELLED`, `LAPSED`), `plan_code`, `frequency` (`MONTHLY`, `FORTNIGHTLY`),
`cancel_reason` (free text, may be blank).

`shop/shop_subscriptions_20230101_full.csv` is a one-off snapshot of the subscriptions active at
the start of 1 January 2023, when the data window opens. Columns: `subscription_id`,
`customer_id`, `status`, `plan_code`, `frequency`, `started_at` (London local).

## payproc: transactions

`payproc/payproc_transactions_YYYYMMDD.txt`. One file per UTC day, ASCII, pipe-delimited,
no quoting, no column header. Due by 06:00 UTC the next day.

- Header record: `H|YYYYMMDD|<schema version>`
- Detail records start with `D`
- Trailer record: `T|<number of detail records>|<sum of gross amounts>`

Schema v1, until 30 June 2024:

`D|txn_id|txn_type|order_ref|txn_at_utc|currency|amount|fee|settlement_date|card_country|decline_code`

Schema v2, from 1 July 2024:

`D|txn_id|order_ref|txn_type|txn_at_utc|currency|gross_amount|fee_amount|net_amount|settlement_date|card_country|decline_code`

`txn_type` is `CAPTURE`, `DECLINE`, `REFUND` or `CHARGEBACK`. Refunds and chargebacks are
negative. Declines carry no amount and no settlement date. `fee` on a chargeback is the
chargeback fee. Settlement is two business days after the transaction.

## ful: shipment status

`ful/ful_shipments_YYYYMMDD.csv`, dated with the Monday of the week. Windows-1252,
semicolon-delimited, CRLF line endings, decimal comma, dates as `DD.MM.YYYY`. Arrives on the
Tuesday after the week ends. One row per status event in the week, so a parcel normally
appears twice: once when it is dispatched and once when it is delivered.

| Column | Meaning |
| --- | --- |
| `Sendungsnr` | Shipment number, 10 digits with leading zeros |
| `Auftragsnr` | Our `order_id` |
| `Kundennr` | Our `customer_id` without the `C`, leading zeros kept; blank for guests |
| `Standort` | Site: `MAN` (Manchester, ships GB) or `HAM` (Hamburg, ships IE, DE, NL) |
| `Empfaenger` | Recipient name |
| `Land` | Delivery country |
| `Versanddatum` | Dispatch date |
| `Soll_Lieferdatum` | Promised delivery date |
| `Lieferdatum` | Actual delivery date, only on `ZUGESTELLT` rows |
| `Status` | `VERSANDT` (dispatched), `ZUGESTELLT` (delivered), `VERLOREN` (declared lost) |
| `Statusdatum` | Date of this status event |
| `Gewicht_kg` | Parcel weight |

## crm: customers

`crm/crm_customers_YYYYMMDD.txt`. Exported from Excel as "Unicode Text": UTF-16 little-endian
with a byte-order mark, tab-delimited, CRLF, double-quote quoting where needed.

`crm_customers_20230313_full.txt` is the full list after the CRM migration on 13 March 2023.
From then on, one delta file a month lists every customer created or changed in the month,
in their state at the end of the month. The first delta covers 14 to 31 March 2023.

Columns: `customer_id`, `legacy_id` (from the old system, blank for newer customers),
`first_name`, `last_name`, `email`, `phone`, `street`, `city`, `postcode`, `country_code`,
`marketing_opt_in` (`Y`/`N`), `created_at`, `updated_at` (both UTC, `YYYY-MM-DD HH:MM:SS`),
`notes` (free text).

## exp: experiment assignments

`exp/exp_assignments_YYYYMMDD.jsonl`, one JSON object per line, one file per UTC day while the
experiment enrols. Fields: `event_id`, `event_type` (`assignment`), `experiment_id`
(`RET-2025-04`), `customer_id`, `variant` (`control` or `treatment`), `event_ts` (UTC, ISO 8601).

## fx: reference rates

`fx/fx_eurgbp_YYYYMM01.csv`, one file per month. Columns: `rate_date`, `base_currency` (EUR),
`quote_currency` (GBP), `rate` (GBP per 1 EUR, 5 decimal places). No rows for weekends or
TARGET holidays. These rates are synthetic; see the project 0 README.
