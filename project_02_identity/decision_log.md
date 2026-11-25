# Decision log: project 2

Each entry records what I chose, what I rejected and why, in the order I made the decisions.

## 1. A held-out half I never looked at

Chosen: split people by their true person number, even numbers for development and odd for
holdout. I looked at errors in the development half while building the rules and report the
holdout half as the result.

Rejected: tuning on all of the truth. With labels this clean, it is easy to keep adding
rules until every error disappears and then report a perfect score. A split costs nothing
and makes the headline number honest. I wrote the generator, so I cannot be fully blind,
but I can at least not tune to the answers.

## 2. Fellegi-Sunter, not hand-picked points

Chosen: the Fellegi-Sunter model. Each field's agreement level carries a weight,
`log2(m / u)`, learned from the data.

Rejected: a points table I made up ("email match = 40 points, phone = 30"). It is easy to
explain, but the points mean nothing, and nobody can say what a score of 70 means. In
Fellegi-Sunter a weight of +10 means "about 1,000 times more likely if it is the same
person", and the total converts into a probability.

Rejected: a supervised classifier trained on the truth. A real company has no truth table.
It would have to label thousands of pairs by hand first. An unsupervised method is the one
I could actually run there.

I did not use Splink, the usual Python library for this. The project pins a small set of
dependencies, and the core of the model is about 150 lines that I can explain line by line
in an interview. In a team I would use Splink.

## 3. u from random pairs, m from EM, one block at a time

Chosen: `u`, the chance that two different people agree on a field, is measured from 400,000
random pairs of accounts. `m`, the chance that a true duplicate agrees, comes from EM on the
candidate pairs. EM runs once on the pairs that share a phone, without the phone field, and
once on the pairs that share a full name and town, without those fields.

Rejected: one EM run over all candidate pairs and all fields. I tried it first. Every
candidate pair shares a blocking key by construction, so EM concluded that 100% of them
were matches. A field that every pair in a block agrees on carries no information about
which pairs match, and must be left out of that block's estimate.

## 4. The whole mailbox, not the part before the @

Chosen: an email agrees only if the whole mailbox agrees (after case, spaces and gmail
rules).

Rejected: a second level for "same name before the @, different provider". It produced
false merges like `fkaul@gmx.de` and `fkaul@web.de`. Those local parts are built from the
name, so the level was counting the name twice. The model assumes fields are independent,
and this level broke that. Dropping it cut the non-matching pairs scoring above 0.5 from 75
to 3. Those two counts were printed over both halves, which was a slip. I made it once more,
when testing decision 6, and reran on the development half before deciding. The pairs I actually read were all from the development
half.

## 5. Common names count for less

Chosen: for surname, first name and town, an exact match on a common value uses that value's
frequency as `u`. Two Smiths in London prove less than two Wiśniewskis in Köln. A rare value
never counts for more than the average, because a single unusual spelling is not proof.

## 6. Never merge on a name and a town alone

Chosen: a pair is merged only if its probability is at least 0.99 and it shares a phone
number, a mailbox, a legacy ID, or the same first name at the same street and postcode.
Everything between 0.5 and the merge rule goes to a review queue.

Rejected: a probability threshold alone. In the development half, namesakes in the same
city, with different phones, emails and addresses, still scored above 0.99. A shop with
17,000 customers in a few dozen cities has many of those. Merging two real customers is
worse than missing a duplicate: one person sees the other's orders and address. So a merge
needs at least one identifier that a stranger would not have.

The "same home" part came from the stress test (decision 9). Without it, removing 30% of
phone numbers left recall at 0.54 on the development half, with 359 pairs to review. With
it, recall was 0.81 with 94 pairs to review, and still no false merges in the development
half. A same first name at the same street and postcode is a strong sign of one person. The
risk is a parent and child with the same name at home, and I accept it.

## 7. Union-find, with one rule against chains

Chosen: merged pairs are joined with union-find, so the result is consistent: if A is B and
B is C, A is C. A person is named after their oldest account, so the key is stable when new
accounts are added. A person may not hold two different legacy IDs, because the old system
already had one account per customer. Merges are applied strongest first, so if the rule
has to cut a chain, it cuts the weakest link.

Rejected: keeping only pairs and leaving transitivity to whoever uses them. Then two reports
can count different people from the same pairs.

## 8. Restate the numbers people actually use

Chosen: per-person subscriber counts, churn and a new metric, `new_customers`, added to
`docs/metrics.md`. The per-account counts stay in the same tables, side by side, so anyone
can see the difference.

The result I expected was a large drop in subscribers. It was not: active subscribers fell
by only about 1%, because most duplicates are old accounts their owner had stopped using.
The number that really moved was new customers, by 7.5%. The useful finding is that the
duplicates hurt acquisition reporting, not the subscriber count.

## 9. Stress-test by damaging the data

Chosen: rerun the whole method after removing or changing a field on a random share of
accounts, and report what happens.

The generator copies a person's phone number onto every account they open, so in the
clean data EM learns that a true duplicate never has a different phone. A real CRM is not
so tidy. The stress test shows the method still works when 30% of phones are missing or
changed, because EM re-learns the weights on each run, and shows how much work moves to
the review queue.

## 10. Fix the generator when it is wrong, and log it

Chosen: when profiling showed unrelated people sharing one email address, I fixed the
generator (project 0) instead of working around it here. The fix makes no random draws, so
every count and every project 1 report is unchanged. It is logged in
`docs/change_log.md` and in the project 0 decision log.

Rejected: keeping the flaw and calling it a "shared mailbox" defect. Real shared mailboxes
belong to households, and these were strangers with nothing else in common. Matching to a
defect that does not exist in real data would teach the model the wrong thing.
