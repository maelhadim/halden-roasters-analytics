# Summary for managers: project 0

**What this is.** A realistic, entirely made-up history of a small coffee subscription
company, Halden Roasters, covering January 2023 to June 2025. It has about 20,000 customers
in four countries, a quarter of a million orders, and the files that a shop, a card processor,
a delivery partner, a customer database and an experiment tool would really send.

**Why it was needed.** The rest of this portfolio shows the work a data team does at one
company: fixing data loads, removing duplicate customers, automating the monthly report,
predicting cancellations and testing a retention offer. That needs one consistent set of data
for the same customers over time. Public datasets do not offer that, so I built one.

**What makes it useful.** The files contain 28 kinds of problems that real data has: late and
re-sent files, duplicate customers, text in the wrong encoding, numbers mangled by Excel, a
test that lost some of its records, and times recorded in the wrong time zone. Separately, the
generator keeps a record of what really happened. Every later project can therefore be checked
against the truth, rather than against what looks reasonable.

**How you know it is reliable.** Building it twice gives exactly the same files, checked
byte for byte. 23 automated tests check that every record is where it should be, that every
listed problem is really in the files, and that every number in the documentation matches the
data.

**What it is not.** It is not real data, and it is labelled as synthetic everywhere. Some
things are simplified on purpose, such as bank holidays and tax rates. They are listed in the
decision log.
