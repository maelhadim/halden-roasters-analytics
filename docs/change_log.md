# Change log

Changes to the plan, the shared conventions or the metric definitions, newest first. A change
made by a later project to an earlier one is recorded here and in both projects' decision logs.

| Date | Change | Why | Affects |
| --- | --- | --- | --- |
| 2026-11-25 | `docs/conventions.md` now lists the `meta_` and `ref_` table prefixes. | Project 1 introduced `meta_file_loads`, `meta_runs` and `ref_vat_rates` without adding the prefixes to the conventions; the project 2 consistency check found the gap. | `docs/conventions.md` |
| 2026-11-25 | New metric `new_customers`: people whose first ever account opened in the month. | Marketing counted new accounts as new customers. Project 2 shows 1,004 of the 14,420 accounts opened from January 2023 to June 2025 belonged to someone who already had one. | `docs/metrics.md`, projects 2 and 3 |
| 2026-11-25 | The generator no longer gives two unrelated people the same email address. If a generated address is taken, a number is added to it (`john.smith2@...`). | Project 2 found 55 pairs of different people sharing a mailbox in the development half alone. A real mailbox belongs to one person, so this was a flaw in the simulation, not a realistic defect. The fix makes no random draws, so every count in the build is unchanged; only those email strings and the checksums changed. Every project 1 report came out byte-identical. | Project 0 checksums, project 2 |
| 2026-11-25 | The VAT fallback for transactions with no linked order applies to captures as well as refunds. | Project 1 found one capture on 30 June 2025 whose order is in the 1 July shop file, outside the window. The rule had only named refunds. The result is unchanged: the fallback rate was already applied to it. | `docs/metrics.md`, project 1 |
| 2026-11-25 | The retention test `RET-2025-04` randomises all eligible subscribers (active, at least 60 days' tenure) instead of only those flagged by the churn model. | The data is generated before the churn model exists, so eligibility cannot depend on it. A test across everyone eligible also lets project 5 check whether project 4's targeting would have paid, instead of assuming it. | Projects 4 and 5 |
| 2026-11-25 | A lapsed subscription ends after three failed payment attempts, not after 45 days without a payment. | This matches how the shop actually closes subscriptions, so churn is dated to a real event. | `docs/metrics.md`, all projects |
| 2026-11-25 | FX rates are synthetic instead of ECB reference rates. | The ECB site is blocked from the build environment. A fixed synthetic series keeps every build identical; switching sources later would change every GBP figure. | All GBP figures |
| 2026-11-25 | The company has 17,617 customers with an account and 20,142 people in total, not the "about 40,000 customer records" in the first plan. | A smaller base builds in under two minutes and is still big enough for every analysis planned. | Plan document |
