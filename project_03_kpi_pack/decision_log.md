# Decision log: project 3

Each entry records what I chose, what I rejected and why, in the order I made the decisions.

## 1. Python computes the metrics, Excel only compares them

Chosen: every metric is calculated in the warehouse and exported as one row per month. The
workbook only looks values up, compares months and runs checks.

Rejected: loading order-level data into Power Query and building the metrics there with
Power Pivot measures. That is the more impressive Excel demo, but it would put a second copy
of every definition in a place that CI cannot test, and the two copies would drift. The
definitions already live in `docs/metrics.md` and in SQL that projects 1 and 2 validated
against the truth. A pack that recalculates them differently would undo that work.

The cost: a new metric needs a change to `extract.py`, not just the workbook. For a monthly
pack read by a handful of people, I think that is the right trade.

## 2. CSV files and a manifest, not a database connection

Chosen: `extract` writes plain CSV files with a manifest that lists each file's rows,
SHA-256 and a control total. Power Query reads the files.

Rejected: Power Query reading DuckDB directly through ODBC. It would need a driver installed
on every PC that opens the pack, and the founders' laptops are not mine to manage. CSV needs
nothing.

Rejected: an `.xlsx` export from Python with the numbers pasted in. It works, but then the
workbook is rebuilt every month and nobody can add their own sheet to it. With Power Query
the workbook stays and only the data changes.

The manifest is there because a CSV file has no way to say it is complete. A file cut off
half-way through still loads. With the row count and control total written next to it, the
workbook can tell.

## 3. Look up columns by name, never by position

Chosen: `INDEX(sheet!$A:$AZ, row, MATCH("column_name", sheet!$1:$1, 0))` everywhere.

Rejected: structured references like `Data_Monthly[mrr_gbp]`. They read better, but the
setup macro replaces each snapshot table with a new query table, and formulas that pointed
at the old table turn into `#REF!`. Whole-column references do not care which table is on
the sheet.

Rejected: `XLOOKUP` and `LET`. They are cleaner in Excel 365, but LibreOffice 24.2, which CI
uses to recalculate the file, does not have them, and some readers may open the pack in an
older Excel. A test fails if any formula uses them.

## 4. Previous month and year-ago month by row offset

Chosen: find the selected month's row with `MATCH`, then use that row minus 1 and minus 12.

Rejected: building the previous month's text ("2025-05") with `EDATE` and `TEXT` and looking
it up. `TEXT` format codes depend on the PC's language: `"yyyy-mm"` has to be `"JJJJ-MM"` in German
Excel. Row offsets have no language. They need the data sorted by month with no gaps, so the
query sorts it and a test checks that every month from January 2023 to June 2025 is present
exactly once.

## 5. Ship a snapshot, add Power Query with a macro

Chosen: the workbook is built by Python with the data already on the Data_ sheets. A VBA
macro, run once, replaces the snapshots with Power Query tables.

Rejected: building the queries into the file from Python. Power Query keeps its queries in a
binary part of the file (the "DataMashup") that openpyxl cannot write, and the few
open-source tools that can are small projects I would not trust with a file for the founders. A wrong byte there makes Excel refuse to open the file.

Rejected: shipping only the `.pq` scripts with instructions to paste them into the Power
Query editor. Four queries pasted by hand, every time the scripts change, is the kind of
manual step this project exists to remove.

The macro is idempotent: it replaces queries that already exist, so running it twice is safe.
It is the only part of the pack I have not been able to run (see the runbook).

## 6. Types with a fixed culture, columns checked by name

Chosen: each query reads UTF-8, types every column with `"en-US"`, and errors if the
column names are not exactly the expected list.

Rejected: Power Query's automatic type detection. It looks at the first 200 rows and uses the
PC's regional settings. On a PC set to German, `0.05813` becomes 5,813, and the pack would
show a churn rate of 581,300%. The error is loud in that case, but a control total that
happens to round the same way would not be. The validation's broken copy with a
comma-decimal number is the nearest case I can test without Excel.

Rejected: letting a renamed column load as a new column. Power Query would load it, the
`MATCH` for the old name would fail, and the user would see `#N/A` in one row of the summary.
An error at refresh time, naming the expected and found columns, is easier to act on.

## 7. MRR from list prices, at the month-end FX rate

Chosen: MRR as `docs/metrics.md` defines it. For each subscription active at 23:59:59 UTC on
the last day of the month: the list price on that date, without VAT, made monthly (26/12 for
fortnightly plans), converted at the last published rate on or before that date.

The list prices are a small reference table, `ref_plan_prices`, written in the extract code
from `docs/company.md`. No source system sends them. In a real company they would come from
the shop's product catalogue; here they are business reference data, and keeping them next
to the one query that uses them made them easy to check.

Rejected: MRR from the amounts actually charged. That mixes in discounts, failed payments and
timing, which are revenue questions. MRR is meant to measure the size of the subscription
base.

## 8. Leave June 2025 as the warehouse sees it

Chosen: the June 2025 MRR is 61.48 GBP above the truth, and the pack shows it that way. The
validation names the two subscriptions responsible.

Rejected: holding the latest month back until the next day's files arrive, or patching it
from the truth. The first delays every pack by a day for a difference of 0.04% of MRR. The
second is impossible in a real company, which has no truth table. A known, explained lag is
the honest option, and the runbook tells the reader to expect it.

## 9. Recalculate in LibreOffice to test the workbook

Chosen: CI installs LibreOffice, sets the month cell, recalculates the file with no screen
and reads the results back with openpyxl.

Rejected: checking only that the formulas are present. A formula can be present and wrong,
for example looking up the wrong row for the year-ago month. Recalculating is the only way to
test what the reader sees.

Rejected: reimplementing the formulas in Python with a formula library. It would test my
reading of the formulas, not the formulas. LibreOffice is a real spreadsheet engine. It is
not Excel, which is why decision 3 keeps the formulas to functions both share.

## 10. A byte-identical workbook

Chosen: the build fixes the file's timestamps, so the same data always gives the same bytes.
CI rebuilds the workbook and fails if it differs from the committed one.

Rejected: not committing the workbook and building it on demand. The pack is the
deliverable, and a hiring manager clicking through the repository should be able to download
it. Committing a binary is only safe if CI can prove it is current, so the build had to be
repeatable.
