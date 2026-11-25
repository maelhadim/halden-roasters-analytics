# Summary for managers: project 2

All data is synthetic. Halden Roasters is a fictional company.

**The question.** How many customers do we really have, and which of our numbers were wrong
because one person can have several accounts?

**The answer.** The customer database lists 18,620 accounts, but they belong to 17,616
people. 1,004 accounts are duplicates: 5.70% of the customer base.

The error is not the same everywhere:

- **New customers** were overstated by 7.5%. From January 2023 to June 2025 we counted
  14,420 new accounts, but only 13,416 were new people. The rest were existing customers
  opening another account, often when they came back after cancelling. The real cost of
  winning a customer is 7.5% higher than we thought.
- **Active subscribers** were only slightly overstated, by about 1% (6,714 accounts against
  6,647 people in June 2025). Most duplicate accounts are old ones their owner no longer uses.
- **Churn** was right to within 0.05 percentage points.

**What was built.** A process that links each account to a person, runs in about two
seconds after the daily load, and explains every link it makes. It merges two accounts only
when they share something a stranger would not have, such as a phone number or a home
address. Unclear cases go to a short review list for a person to decide. Today that list has
2 pairs. Both look like family members sharing a landline.

**How you know it is right.** Because the data is synthetic, the true answer is known. On
the half of the customers I kept aside while building it, the process found every duplicate
and made one mistake: it merged two different customers with nearly the same name and the same
phone number. I also tested it with damaged data. With 30% of phone numbers missing, it
still finds 87% of duplicates on its own, and about a third of the rest are on the review
list.

**What it means.** Marketing should report new customers per person from now on; the
definition is in the shared metrics page. Subscriber and churn reports can move to the
per-person count with little change to the numbers. Project 3 builds the monthly report on
these per-person figures.
