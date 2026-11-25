# Change log

Changes to the plan, the shared conventions or the metric definitions, newest first. A change
made by a later project to an earlier one is recorded here and in both projects' decision logs.

| Date | Change | Why | Affects |
| --- | --- | --- | --- |
| 2026-11-25 | The VAT fallback for transactions with no linked order applies to captures as well as refunds. | Project 1 found one capture on 30 June 2025 whose order is in the 1 July shop file, outside the window. The rule had only named refunds. The result is unchanged: the fallback rate was already applied to it. | `docs/metrics.md`, project 1 |
| 2026-11-25 | The retention test `RET-2025-04` randomises all eligible subscribers (active, at least 60 days' tenure) instead of only those flagged by the churn model. | The data is generated before the churn model exists, so eligibility cannot depend on it. A test across everyone eligible also lets project 5 check whether project 4's targeting would have paid, instead of assuming it. | Projects 4 and 5 |
| 2026-11-25 | A lapsed subscription ends after three failed payment attempts, not after 45 days without a payment. | This matches how the shop actually closes subscriptions, so churn is dated to a real event. | `docs/metrics.md`, all projects |
| 2026-11-25 | FX rates are synthetic instead of ECB reference rates. | The ECB site is blocked from the build environment. A fixed synthetic series keeps every build identical; switching sources later would change every GBP figure. | All GBP figures |
| 2026-11-25 | The company has 17,617 customers with an account and 20,142 people in total, not the "about 40,000 customer records" in the first plan. | A smaller base builds in under two minutes and is still big enough for every analysis planned. | Plan document |
