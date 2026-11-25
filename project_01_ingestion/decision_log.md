# Decision log: project 1

Each entry records what I chose, what I rejected and why, in the order I made the decisions.

## 1. Profile first, and write it down

Chosen: a read-only profiler that reports encodings, line endings, delimiters, header
variants and fields per record for every file, before any parser existed. Its output is
committed as [`profiling_report.md`](profiling_report.md).

Rejected: going straight from the source specs in `docs/source_specs.md` to parsers. The
specs say what each supplier promises. The profile shows what they actually send, and the two
differ: the specs mention neither the trailing commas in 30 shop files nor the 15-field CRM
records caused by stray quotes.

## 2. DuckDB in one file

Chosen: DuckDB, one file, `data/warehouse.duckdb`, with plain SQL for every model.

Rejected: PostgreSQL, which needs a server and makes the project harder to run for anyone
reviewing it. Rejected pandas only, because the models are joins and window functions that read
better as SQL, and because a finance analyst can open the file and query it. Rejected dbt for
now: it would add a tool to learn, and there are only 15 models. If the model count
grows, `models.sql` moves into dbt without changes to the SQL itself.

## 3. Every column lands as text first, and every record is accounted for

Chosen: each parser reads the raw file as text, applies the rules for that feed, and returns
three things: good records, rejected records with a reason, and a count of blank lines.
`ParseResult.check()` refuses to continue unless records read = staged + rejected + blank.
Rejected records go to `rej_records` with the file, line number and raw text.

Rejected: `pandas.read_csv` with type inference and `on_bad_lines="skip"`. It turns order IDs
into integers, drops leading zeros from the fulfilment partner's shipment numbers, and skips
bad lines without saying which ones. A row that disappears silently is the problem this
project exists to fix.

## 4. Rerun safety by file name and content hash

Chosen: the ledger `meta_file_loads` stores the SHA-256 of every file loaded. A run parses only
files whose name is new or whose hash changed. If a known file changes, its old staging,
reject and ledger rows are deleted and the new ones inserted in one transaction per feed.

Rejected: loading by date range ("everything since the last run"). Files arrive late and out
of order, so a date watermark would skip the 21 October 2024 processor file that arrived 35
hours late. Rejected: append-only staging with deduplication downstream, because then the
row balance per file stops meaning anything.

## 5. Late and missing files come from a feed calendar, not from the data

Chosen: each feed has an agreed cadence and deadline in `landing.py`, for example processor
files by 06:00 UTC the next day. `mart_file_arrivals` lists every expected file as on time,
late, missing or not yet due. `--as-of` replays history by hiding files received after a time.

Rejected: inferring the schedule from the files that arrived. A missing file leaves no trace in
the data, so it can only be found by comparing with what was expected.

The processor file for 12 September 2024 never arrived; its rows came in the 13 September
file. I report the day as missing and still load every row. Marking it "late" would hide the
fact that the supplier broke the agreement, and finance needs that for the supplier review.

## 6. Shop times: convert London to UTC, and break ties with the payment

Chosen: shop times are London wall-clock time. I convert them to UTC. When the clocks go back,
the hour from 01:00 to 02:00 happens twice, and 215 orders fall in it. For those, I look at the
first payment attempt for the order: the order is the instant that comes 0 to 10 minutes
before it. If neither instant fits, the order is flagged `ambiguous_unresolved` rather than
guessed. `created_at_quality` records which rule applied to each order.

Rejected: always taking the first instant, which is what most libraries do by default. In
this data it happens to give the right answer for all 215, because renewals run in the
nightly batch. I did not want a rule that is right only by luck. Rejected: treating shop
times as UTC, which is what the old BI report effectively did.

## 7. The file received last wins

Chosen: when an order appears in two shop files (the 18 March 2024 file and its resend), the
version received later wins in `int_orders`. For the fulfilment partner, a `_v2` file replaces
every event of its week, not just the rows it contains.

Rejected: merging the two versions field by field. A resend is the supplier telling us the
first file was wrong. If the corrected file leaves something out, that omission is part of
the correction.

## 8. The bridge is a chain of measures, not a list of adjustments

Chosen: eight measures, each changing exactly one thing from the one before, from the old BI
method to net revenue. Each bridge step is the difference between two measures, so the bridge
adds up by construction, and the residual column proves it each month.

Rejected: estimating each cause separately (for example "VAT is about 2.5% of revenue") and
showing what is left as "other". That always leaves an unexplained remainder, and the
remainder is where the argument with finance starts.

The order of the steps changes how much each one shows, because the steps interact. For
example, removing VAT before removing test orders would make the test-order step slightly
smaller. I put them in the order a finance analyst would explain them: first fix what was
counted, then when, then at what rate, then what came back, then tax.

## 9. Old BI method reconstructed from the description

Chosen: step 0 rebuilds the old report from how the BI team described it: sum `total_amount`
over every row of every shop file, grouped by the month in the file name, converting EUR at
the month's average rate.

This is a reconstruction. The old report's SQL was not available. If finance has the actual
monthly figures, the first check should be that they match step 0. Until then, the bridge
explains the old method, not necessarily the old numbers.

## 10. Validation against the truth is separate code

Chosen: `validate.py` is the only code that reads `data/ground_truth`, and it is only run by
`make validate`. It scores every in-scope defect type by matching the keys the pipeline found
with the keys in the defect manifest, so a rule that catches too much shows up as "extra",
not as a pass.

Rejected: tuning rules until the totals match. A matching total can hide two errors that
cancel out. Matching each defect record by key cannot.
