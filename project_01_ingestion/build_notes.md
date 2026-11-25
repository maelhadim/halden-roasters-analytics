# Build notes: project 1

These are the problems I hit while building the pipeline, in the order they happened. Most of
them were caught by the validation step, which is the main reason it exists.

**A query for messy emails also caught tidy ones.** The defect check for badly formatted
shop emails first reported far more rows than the manifest. My condition was
`a OR b AND c`, and SQL reads that as `a OR (b AND c)`, so it also counted emails with capital
letters that the customer had typed on purpose. I rewrote it as one test, "the raw value has
spaces around it", which is what the defect actually is. The count then matched: 1,255 of 1,255.

**The corrected fulfilment file has a different name.** The `_v2` file for the week of 20 May
2024 was scored as "missed" for duplicate status events. The manifest names the original file, and the pipeline found the events in the `_v2` file.
The fix was to compare on the base file name, but only for the defect types keyed by file.
For the encoding defect, which is recorded once per file, the `_v2` file is a file of its
own and must be counted separately. I got that wrong the first time too.

**One capture with no order.** I expected 12 processor transactions with no matching order,
the 12 legacy refunds. There were 13. The extra one is a capture at 23:20 UTC on 30 June 2025
for an order created a few minutes earlier, just after midnight on 1 July in London. Its
order is in the 1 July shop file, which is outside the data window. It is not an error. It does mean the VAT rate for that one
payment falls back to the rate for its currency, because the warehouse cannot see the
customer's country. It is one payment of 14.90 EUR.

**June 2025 paid orders did not match the truth.** The truth said 26 more orders were paid in
June 2025 than the warehouse did. They were orders whose payment succeeded in July, after a
failed first attempt, or orders sitting in the 1 July file. The truth knows the future; the
warehouse, correctly, does not. I changed the check to compare paid status "as known on 30
June 2025" and to name the 26 orders, rather than loosening the tolerance until it passed.

**pandas renamed my columns without telling me.** The spot-check table came out with blank
file names. `DataFrame.itertuples()` silently renames columns that start with an underscore,
so `_source_file` was no longer reachable by that name. I renamed the columns before the loop.

**Guest orders broke the spot checks.** A random order from a guest checkout has no
`customer_id`, which pandas holds as `NaN`, and `NaN == NaN` is false, so the check said the
customer was "DIFFERENT". The same `None`-versus-`NaN` problem from project 0, in a new place.

**A week that does not exist was reported missing.** The first arrivals table said the
fulfilment file for the week of 26 December 2022 was missing. That week contains one day of
the window, Sunday 1 January 2023, when nothing ships, so no file was ever due. The weekly
calendar now starts on the first Monday inside the window. I only noticed because the count
of missing files was one higher than the defect manifest said.
