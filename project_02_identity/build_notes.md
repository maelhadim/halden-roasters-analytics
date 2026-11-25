# Build notes: project 2

These are the problems I hit while building the matcher, in the order they happened.

**Six customers were missing before I started.** The CRM had 18,614 accounts and the shop
orders mentioned 18,620. The six missing ones were the CRM records that project 1 had
quarantined for a stray quote. Matching only the CRM would have quietly dropped six people.
They are now built from their latest shop order. Their creation date was a problem too: I
first took the date of that latest order, which put some of them in the wrong month for
"new customers". The first order is the right date, because the account existed by then.

**`NaN` again.** The first run crashed in the name folding with `'float' object has no
attribute 'strip'`. A missing street in pandas is `NaN`, a float, not `None`. This is the
third project in a row where that has bitten me. Every key function now checks
`isinstance(value, str)`.

**EM said every pair was a match.** My first EM run concluded that 100% of the 3,960
candidate pairs were the same person. Every candidate shares a blocking key, so a shared
phone looked like overwhelming evidence for every pair. The fix is the standard one: run EM
per blocking rule, leaving out the fields that rule blocks on.

**The generator gave strangers the same email address.** With EM working, the false matches
in the development half were mostly pairs with the same name and the same mailbox, and
nothing else in common. The truth said they were different people. I checked how the
generator builds emails: from the name, with no check that the address was taken. Two
unrelated people with the same initial and surname could both be `jbailey@outlook.com`. I
fixed the generator rather than the matcher, made sure the fix used no random draws, and
rebuilt. Every count stayed the
same, and every project 1 report was byte-identical.

**The email local part counted the name twice.** After that fix, `fkaul@gmx.de` and
`fkaul@web.de` were still merged as one person. My "same local part, different provider"
level was really a second name comparison. I removed it.

**Eight names, too many people.** Some false matches were people called Paweł Nowak or
Bartłomiej Dąbrowski in the same city. The generator adds Polish and Turkish names to German
customers from a list of only eight, so several different people share each one. That is
less realistic than I would like, but namesakes in a city are real, so I did not change it.
It is part of why a name and a town are never enough to merge (decision 6).

**The pair order changed between runs.** The repeatability test failed: the people were
identical, but the match weights came back in a different order. DuckDB does not promise an
order without `ORDER BY`, and the same lesson came up in project 1's CI. The pair query now
sorts, so the EM sums run in the same order and the report is byte-identical across runs.

**A SQL comment that ate a line.** I added a comment at the end of a line in the subscriber
model, and it commented out the rest of the `generate_series` call. DuckDB's error pointed
at the next statement. Comments now go on their own line.
