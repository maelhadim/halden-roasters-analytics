# Summary for managers: project 1

All data is synthetic. Halden Roasters is a fictional company.

**The question.** Why does the revenue in the monthly BI report not match the money the card
processor collected?

**The answer.** The old report overstated revenue in every month from January 2023 to June
2025, by 4.56% overall: 4,761,866 GBP reported against 4,554,211 GBP of real net revenue, a
difference of 207,655 GBP. Almost all of it has three causes:

- VAT was never taken off EU orders: 117,733 GBP.
- Refunds and chargebacks were never subtracted, because the report never looked at the
  processor's files: 43,591 GBP.
- Orders whose payment failed were counted as sales: 40,320 GBP.

A file that was sent twice in March 2024 explains 4,552 GBP, and QA test orders 1,467 GBP.
Each cause is shown month by month, in pounds, and the steps add up to the penny.

There is a smaller problem that the 30-month total hides. The old report put some orders in
the wrong month, because the shop records London time and the processor records UTC. Over 30
months this nets to 8 GBP. In a single month it can move up to 1,706 GBP.

**What was built.** One warehouse that loads all six data feeds (shop, card processor,
delivery partner, customer database, experiments and exchange rates) every day. It keeps
every record it cannot use, with the reason, so nothing disappears without trace. It can be
rerun at any time without double counting. It flags any file that is late or missing:
in 30 months, the processor missed one day and was late four times, and the delivery partner
was late twice over Christmas.

**How you know it is right.** Because the data is synthetic, the true figures are known. The
warehouse matches them to the penny in every month, and it found all 14,994 planted data problems
that this project is responsible for, without flagging anything that was not a problem. The
other three kinds, such as duplicate customers, belong to later projects.

**What it means.** Revenue reporting can move to the new warehouse. Finance should check the
old report's actual figures against the reconstruction of it; the bridge explains the old
method, and the old SQL was not available to confirm it. The duplicate customer records still
in the customer database are the next problem, and the subject of project 2.
