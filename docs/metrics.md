# Metric definitions

Every project uses these definitions and no others. The reference implementation is
`src/halden/generator/truth.py`, which computes them from the true history into
`data/ground_truth/gt_monthly_metrics.csv`. If a definition changes, that file, this page
and `docs/change_log.md` change in the same commit.

## Shared rules

- **Month** means a calendar month in UTC. The shop exports London local time, so a renewal
  created at 00:30 London time on 1 July is a June event (23:30 UTC on 30 June). This is
  the single most common reason two reports disagree, so it is written down first.
- **Reporting currency** is GBP. EUR amounts convert at the GBP-per-EUR rate for the
  transaction date. On a weekend or a TARGET holiday, the last rate published before that
  date is used.
- **Test orders** (any order whose email ends in `@haldenroasters.test`) are excluded from
  every metric, together with their payments and refunds.
- **A subscriber is a person, not an account.** Until project 2 resolves identities, the
  only count available is per account. That count is reported as
  `active_subscription_accounts` and must not be presented as the number of subscribers.

## Definitions

| Metric | Definition |
| --- | --- |
| `active_subscribers` | People with at least one subscription that started on or before 23:59:59 UTC on the last day of the month, and that had not ended by then. |
| `active_subscription_accounts` | The same count, per `customer_id` instead of per person. It is always greater than or equal to `active_subscribers`. |
| `new_subscribers` | People active at the end of the month who were not active at the end of the previous month. Returning customers count as new. |
| `churned_subscribers` | People active at the end of the previous month who are not active at the end of this month. |
| `monthly_churn_rate` | `churned_subscribers` divided by `active_subscribers` at the end of the previous month. |
| `mrr_gbp` | For every subscription active at month end: its list price on that date, minus VAT, as a monthly amount (fortnightly plans multiplied by 26/12), converted to GBP at the month-end rate. Discounts are ignored, because MRR measures the size of the base, not what was collected. |
| `gross_revenue_gbp` | Captured payments in the month (by `txn_at_utc`), minus VAT, in GBP. |
| `net_revenue_gbp` | Captures, minus refunds and chargebacks, in the month (by `txn_at_utc`), minus VAT, in GBP. Processor fees and chargeback fees are costs, not negative revenue, so they are excluded. Refunds that cannot be linked to an order still count. |
| `paid_orders` | Orders created in the month (UTC) whose payment eventually succeeded. |
| `late_delivery_rate` | Delivered parcels whose delivery date falls in the month and that arrived after the promised date, divided by all parcels delivered in the month. Lost parcels are excluded from both counts. |

## How a subscription ends

A subscription ends in one of two ways, and churn counts both:

- **Cancelled**: the customer cancels. The end time is the cancellation time.
- **Lapsed**: three payment attempts fail (on the renewal date, 3 days later and 6 days later).
  The end time is five minutes after the last failed attempt, when the shop closes it.

VAT is removed with the rate of the order's delivery country. These rates are simplified
assumptions for roasted coffee (GB 0%, IE 0%, DE 7%, NL 9%), not tax advice. Refunds that
cannot be linked to an order have no delivery country, so they use GB for GBP and DE for EUR.
