# Summary for managers: project 3

All data is synthetic. Halden Roasters is a fictional company.

**The question.** Can the monthly KPI pack update itself, use the agreed definitions, and
warn us when its numbers are wrong?

**The answer.** Yes. The new pack is still an Excel file. Choose a month
and it shows that month against the month before and the same month a year earlier, by
country, with the explanation of how the old BI revenue figure became the real one. The
monthly update is one click: Data > Refresh All.

June 2025, from the pack:

- **6,647 active subscribers**, up 75 on May and 9.8% on June 2024.
- **Churn fell to 5.81%** from 7.95% in May. A year earlier it was 6.14%.
- **MRR 170,098 GBP**, 21.3% above June 2024. That is faster than subscriber growth (9.8%),
  and the February 2025 price increase is part of the reason.
- **Net revenue 175,479 GBP**, 12.0% above June 2024.
- **5.13% of parcels arrived late**, up from 4.64% a year earlier.

**Why you can trust it.** Every number comes from the same cleaned data and the same
definitions as the rest of our reporting. Nothing is typed in. The pack checks itself each
time it recalculates: it confirms it loaded every row and that the totals match what was sent.
If anything is off, the summary says "CHECK FAILED" instead of showing numbers that look
fine. I tested this by deliberately breaking three copies of the file; it caught all three.

Because the data is synthetic, the true figures are known. Revenue and late deliveries match
them exactly. A few figures for the latest month are slightly off for reasons we know: events
made late on 30 June only reach us on 1 July. June's MRR, for example, will be restated by 61
GBP when those files load.

**What is left.** The automatic refresh only runs inside Excel on Windows, so its first real
run needs to happen on a company laptop. The setup is a one-off, and the steps are written
down.
