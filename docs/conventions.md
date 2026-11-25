# Conventions

These rules apply to every project in this repository. When a later project needs to
break one, it changes this page in the same commit and adds a line to `docs/change_log.md`.

## Folders

```
data/raw/<source>/          files exactly as the source system sent them; never edited
data/raw/_landing_log.csv   one row per file: when it arrived, its size and SHA-256
data/ground_truth/          what really happened; only validation code may read it
src/halden/<project>/       code, one package per project
tests/<project>/            tests for that package
project_NN_<name>/          the write-up for one project: README, decision log, runbook,
                            build notes, manager summary
docs/                       rules shared by all projects
```

`data/` is not committed. It is rebuilt with `make data`, and `make verify-data` proves the
rebuild is byte-identical to the published checksums.

## Source systems

| Code | System | Cadence | Format |
| --- | --- | --- | --- |
| `shop` | Web shop: orders and subscription events | daily | CSV, UTF-8, comma, London local time |
| `payproc` | Card processor transaction report | daily | Pipe-delimited TXT with header and trailer records, UTC |
| `ful` | Fulfilment partner (sites MAN and HAM) | weekly | CSV, Windows-1252, semicolon, decimal comma, German headers |
| `crm` | Customer database export | monthly | Tab-delimited TXT, UTF-16 LE with BOM |
| `exp` | Experimentation platform assignment events | daily | JSON Lines, UTC |
| `fx` | EUR to GBP reference rates (synthetic) | monthly | CSV |

Field-level layouts are in `docs/source_specs.md`.

## File names

`<source>_<entity>_<YYYYMMDD>[_<suffix>].<ext>`

The date is the first day of the period the file covers: the day for daily files, the
Monday for weekly files and the first of the month for monthly files. A suffix marks a
special delivery: `_full` for a snapshot, `_resend` for a repeat delivery and `_v2` for a
correction. Nothing is ever renamed after it lands.

## Tables

Tables move through four layers. The prefix says which layer a table is in.

| Prefix | Contents | Grain |
| --- | --- | --- |
| `stg_` | One source, typed and cleaned, nothing joined | one row per source record |
| `rej_` | Rows that could not be loaded, with `reject_reason` and the raw line | one row per rejected record |
| `int_` | Joined, deduplicated, identity-resolved | one row per business entity |
| `mart_` | Business-ready tables used by reports and models | stated per table |

## Columns

- `snake_case`, lower case, English. German partner headers are renamed in staging and the
  mapping is documented.
- Identifiers are text, always. `customer_id`, `order_id`, `shipment_no` and phone numbers
  are never cast to numbers, because leading zeros are part of the value.
- Timestamps are stored in UTC and end in `_at_utc`. Dates without a time end in `_date`.
- Money is stored with its currency: `amount_local` plus `currency_code`, and the converted
  value as `amount_gbp`. Amounts are rounded to 2 decimal places only at presentation time.
- Booleans start with `is_` or `has_`.
- Every staged table carries `_source_file` and `_source_line`, so any value can be traced
  back to the exact line it came from.

## Code

- Python 3.12 or later, pandas and DuckDB. Versions are pinned in `pyproject.toml`.
- Read every source column as text first; convert types in one place, with a stated rule.
- A run must be safe to repeat: running it twice gives the same tables as running it once.
- Logs use `halden.common.log`: UTC timestamp, level, logger name, message.
- Comments explain why, not what.
