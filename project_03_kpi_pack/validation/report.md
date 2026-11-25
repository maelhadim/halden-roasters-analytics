# Project 3 validation

Overall: **pass**. Written by `python -m halden.kpi validate`; do not edit by hand. Synthetic data.

## 1. The workbook shows what the warehouse holds

For each month I set Summary!C5, recalculated the file in LibreOffice and compared every figure on the Summary sheet (this month, previous month and a year earlier for 11 metrics, four countries and the nine bridge lines) with the warehouse tables. A blank must be blank, for example the previous month of January 2023.

| Month | Values compared | Mismatches | Status cell |
|---|---:|---:|---|
| 2023-01 | 54 | 0 | All checks pass |
| 2023-02 | 54 | 0 | All checks pass |
| 2024-01 | 54 | 0 | All checks pass |
| 2024-06 | 54 | 0 | All checks pass |
| 2025-06 | 54 | 0 | All checks pass |

270 values compared in all, 0 mismatches.

## 2. The workbook's checks catch a bad refresh

Each row is a copy of the workbook broken on purpose. The overall check must say FAIL, and the check named for that problem must be among the failures.

| Broken copy | Overall | Checks that failed | Caught |
|---|---|---|---|
| a refresh that loaded Data_Country only partly (last row missing) | FAIL | Data_Country: rows match the manifest; Data_Country: net revenue total matches the manifest; Countries add up to the total for the selected month | yes |
| June 2025 net revenue loaded as the text "175478,81" | FAIL | Data_Monthly: net revenue total matches the manifest; Countries add up to the total for the selected month; Bridge ends on the same net revenue as the KPI table | yes |
| a month typed into Summary!C5 that is not in the data | FAIL | Countries add up to the total for the selected month; Selected month is in the data | yes |

## 3. The warehouse agrees with the ground truth

Monthly figures in `kpi_monthly.csv` compared with `gt_monthly_metrics.csv`, which the generator wrote from its own records before any defects were added.

| Metric | Months different | Largest difference | Why | Result |
|---|---:|---:|---|---|
| `active_subscribers` | 2 | 1 | identity resolution merged one pair of people wrongly (project 2), which moves a count by 1 | pass |
| `active_subscription_accounts` | 0 | 0 |  | pass |
| `new_subscribers` | 2 | 1 | identity resolution merged one pair of people wrongly (project 2), which moves a count by 1 | pass |
| `churned_subscribers` | 2 | 1 | identity resolution merged one pair of people wrongly (project 2), which moves a count by 1 | pass |
| `monthly_churn_rate` | 3 | 0.00015 | identity resolution merged one pair of people wrongly (project 2), which moves a count by 1 | pass |
| `mrr_gbp` | 1 | 61.48 | subscriptions whose start or cancellation on 30 June arrived in the 1 July file | pass |
| `gross_revenue_gbp` | 0 | 0 |  | pass |
| `net_revenue_gbp` | 0 | 0 |  | pass |
| `paid_orders` | 1 | 26 | orders paid after 30 June or sitting in the 1 July shop file, which the warehouse cannot see (project 1) | pass |
| `late_delivery_rate` | 0 | 0 |  | pass |

### The June 2025 MRR gap

MRR counts subscriptions active at 23:59:59 UTC on 30 June. These subscriptions are active then in one source and not the other. Priced the way `mart_mrr_monthly` prices them, they add up to 61.48 GBP, which is the whole gap.

| Subscription | Active at month end in | Started (UTC) | Ended (UTC) | MRR effect, GBP |
|---|---|---|---|---:|
| S008289 | warehouse only | 2023-11-13 16:21:07+00:00 | 2025-06-30 19:33:30+00:00 | 73.67 |
| S018868 | truth only | 2025-06-30 23:19:22+00:00 |  | -12.19 |

The warehouse can only know what the feeds delivered by 30 June. A cancellation made late on 30 June, or a subscription started then, reaches it in the 1 July file, and loading that file will restate June by this amount. I left the June figure as the warehouse sees it rather than patch it, because a pack that quietly differs from its own source is worse than one with a known, explained lag.

## Revenue with no country

13 transactions in the 30 months cannot be linked to an order, so they have no country. On the country table the GBP ones go to the United Kingdom (8, -178.50 GBP) and the EUR ones to Germany, the largest euro market (5, -64.48 GBP). Monthly totals are not affected.

## What this does not test

Power Query runs only inside Excel, so the refresh step is checked by hand on Windows (runbook, step 4). The M scripts are tested here only for their column lists and types.
