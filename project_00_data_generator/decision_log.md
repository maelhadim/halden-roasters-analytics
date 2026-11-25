# Decision log: project 0

Each entry records what I chose, what I rejected and why. Newest decisions are at the bottom,
because they read best in the order they were made.

## 1. Generate the data instead of borrowing public datasets

Chosen: one seeded generator that simulates the whole company.

Rejected: stitching together public datasets (Telco churn, Febrl, a Kaggle A/B test). They
share no customers, no dates and no currency, so no project could feed the next one, and the
Telco data has no dates at all, which rules out a time-based train/test split.

Cost: synthetic data can make analysis circular, because I wrote the rules I later "discover".
I deal with that in decision 2.

## 2. Keep the truth out of reach of the pipelines

Chosen: the generator writes two folders. `data/raw/` holds what the source systems would send.
`data/ground_truth/` holds what really happened, plus a manifest of every defect injected.
Pipeline code never reads `ground_truth`; only validation steps do.

This turns the circularity problem into a measurement. For project 2, I know which accounts
really belong to the same person, so I can report precision and recall instead of
describing matches that look plausible.

## 3. Simulate people and events, not tables

Chosen: an event simulation. People sign up, renew, fail payments, get late parcels, cancel and
sometimes come back. The tables fall out of that history.

Rejected: sampling each table separately with realistic-looking distributions. That gives
orders without a reason to exist, and churn that no feature can predict. With a simulation,
a late parcel really does raise the chance of cancelling, which is what project 4 needs to find.

## 4. Each source gets the defects that system would really have

Chosen: defects tied to the system that causes them. The German fulfilment partner sends
Windows-1252 with decimal commas. The CRM export comes from Excel as UTF-16. The shop works
in London time with no offset. The card processor changes its schema once and adds a trailer
record I can check totals against.

Rejected: random noise added to every column. Real files are not uniformly noisy; they break
in a few specific ways that come from how each system is built.

## 5. Shop timestamps are London wall-clock time with no offset

This is the most important defect, so it gets its own entry. Subscription renewals run in a
nightly batch at 00:30 to 02:30 London time. In summer, 00:30 on the 1st is 23:30 UTC on the
last day of the previous month. A pipeline that treats shop times as UTC moves those orders
into the wrong month, and that is enough to make BI revenue disagree with the processor. When
clocks go back, 215 orders fall in the repeated hour, and their London time alone cannot say
which of the two instants they happened at.

## 6. Synthetic FX rates

Chosen: a mean-reverting random walk for GBP per EUR, on TARGET business days only (no
weekends, no TARGET holidays).

Rejected: real ECB reference rates. I wanted them, but the ECB site is blocked from the build
environment. Downloading them on another machine and committing the file was possible, but
then the build would depend on a file nobody can regenerate from the code. The synthetic rates
stay between 0.83 and 0.90, which is roughly where the real rate moved in 2023 to 2025. They
are labelled as synthetic everywhere they appear.

## 7. Byte-identical rebuilds

Chosen: one seed, no wall-clock time in any output, stable sorts everywhere, and a committed
SHA-256 list for every file. `make verify-data` rebuilds and compares.

I tested this by building twice with different `PYTHONHASHSEED` values. All 2,959 raw files and
the ground truth came out identical. Without this, a number quoted in a README could drift
the next time someone ran the code, and nobody would notice.

## 8. Raw data is not committed

Chosen: commit the code and the checksums, not the 134 MB of generated files.

Rejected: committing the files. It would bloat the history, and every change to the generator
would rewrite the whole dataset in git. Anyone can rebuild in under two minutes.

## 9. The experiment randomises everyone eligible

Chosen: the retention test enrols every active subscriber with at least 60 days' tenure at
their first renewal in April 2025, and randomises 50/50.

Rejected: enrolling only customers the churn model flags, as the first plan said. The
generator runs before the churn model exists, so it cannot use the model's list. A test
across everyone eligible is also more useful: project 5 can check whether project 4's
targeting would have paid off, instead of taking it on trust. Logged in `docs/change_log.md`.

The true effect is a 40% relative cut in the chance of cancelling for high-risk customers and
12% for the rest. It is stored in `gt_parameters.json` and used only to simulate outcomes.

## 10. Simplifications I chose to keep

- Settlement is two business days after the transaction, ignoring UK bank holidays.
- Subscriptions never pause or change plan, and refunds are either full (lost parcel) or 50%
  (goodwill). Real subscription data has all three, but none of the planned analyses needs them,
  and each one would add rules to every later project.
- Contact details on a shop order are the account's current details, not a history.
- Cities come from a list of real cities, but streets and postcodes come from Faker. A UK
  postcode has the right shape (all 11,140 UK postcodes in this build match the standard
  pattern), but it is not a real postcode and does not belong to the city. No analysis in this
  portfolio depends on addresses being real, and making them real means geocoding data.
- VAT rates are simplified assumptions for roasted coffee, not tax advice.

## 11. One mailbox, one person (changed in project 2)

Chosen: when the generator builds an email address that already belongs to another person,
it adds a number to the local part, the way a mail provider suggests `john.smith2`. A person
keeps their own address across accounts, which is the signal project 2 is meant to find.

The first build did not check this. Faker draws names from a limited list and I built
addresses from names, so two unrelated people could both be `jbailey@outlook.com`. Project 2
found it while profiling: 55 pairs of different people sharing a mailbox in the development
half alone. That is not a realistic defect. A shared family address is real, but these were
strangers. The fix makes no extra random draws, so every count in this build is unchanged.
Only those email strings and the checksums changed. See `docs/change_log.md`.

