# Runbook: project 2

## Run it

```bash
make ingest              # project 1 first: the CRM and orders must be in the warehouse
make identity            # about 2 seconds
make identity-validate   # compares with the ground truth; exits 1 if any check fails
```

A normal run ends with:

```
INFO  halden.identity decisions: {'no': 2666, 'merge': 1058, 'review': 2}; 0 merges blocked by a legacy ID or a review decision
INFO  halden.identity 18620 accounts resolve to 17616 people (1004 accounts merged away)
```

Run `make identity` again after every `make ingest`. Project 1 rebuilds the CRM tables, and
project 2's tables still hold the previous run's people until you do.

`make identity` also regenerates the read-only profiling report first.

## What it writes

| Table | One row per | Use it for |
| --- | --- | --- |
| `int_identity_accounts` | account | The match keys built from each account |
| `int_identity_pairs` | candidate pair | Every field's agreement level, the weight, the probability, the decision, and whether a reviewer set it |
| `int_customer_person` | account | `person_key`: join on `customer_id` to count people instead of accounts |
| `ref_identity_weights` | field and level | `m`, `u` and the weight the model learned in this run |
| `mart_identity_review_queue` | pair to review | The two accounts side by side |
| `mart_subscribers_monthly` | month | Active, new and churned subscribers, per person and per account |
| `mart_new_customers_monthly` | month | New accounts against new customers |

To count people in any query, join `int_customer_person` and count `DISTINCT person_key`.

## Working the review queue

```sql
SELECT * FROM mart_identity_review_queue ORDER BY match_probability DESC;
```

For each pair, look at the orders and the delivery addresses of both accounts, then add a
row to [`review_decisions.csv`](review_decisions.csv):

```
left_id,right_id,decision,reviewed_by,reviewed_on,note
C000038,C015792,different,<your initials>,2026-11-25,Holmes household: shared landline, different first names and emails
```

`same` merges the two accounts. `different` keeps them apart for good, even if a chain of
other merges would join them later. Commit the file and run `make identity`: the pair leaves
the queue, and the decision is applied on every run after that. A decision is never undone
by the model, only by editing the file.

In this run the queue holds 2 pairs, Holmes and Ahmed, each sharing a phone and a surname
with different first names and emails. They look like households, so "different" is the
likely answer. I have left the decisions file empty, because recording a review I did not
do with the customer's history in front of me would be inventing evidence.

If the queue suddenly grows into the hundreds, something upstream changed. The usual cause
would be a CRM export that stops including phone numbers. The stress test in the validation
report shows what that looks like: with 30% of phones missing, the queue grows to about 94
pairs.

## When something looks wrong

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `int_customer_person` has fewer rows than the CRM | An account was lost in loading | This is a bug. Every account must map to one person, and the test on the build checks it |
| The people count jumps between runs with no new data | The run is not repeatable | This is a bug. A test runs the method twice and requires identical results |
| A customer says another person's orders show in their account | A false merge | Find both accounts in `int_identity_pairs`, read the levels, and report the pair. Do not edit `int_customer_person`: it is rebuilt every run |
| EM log says close to 100% of pairs are matches | A blocking rule's field is being estimated in its own block | Check `TRAINING` in `matching.py`: each block must leave out the fields it blocks on |
