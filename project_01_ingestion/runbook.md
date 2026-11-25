# Runbook: project 1

## Run it

```bash
make data        # once, if data/raw does not exist yet (project 0)
make ingest      # load new or changed files, rebuild the int_ and mart_ tables
make validate    # compare with the ground truth; exits 1 if any check fails
make replay      # optional: rebuild history in three runs and compare with the full load
```

A first load of all 2,959 files takes about 40 seconds and ends with lines like:

```
INFO  halden.ingest run 1: 2959 files visible, 2959 new or changed
...
INFO  halden.ingest run 1 finished in 37.1s
```

A rerun with nothing new says `0 new or changed` and takes about 4 seconds.

To see the warehouse as it was on a given morning, write to a separate file so the main
warehouse is not touched:

```bash
PYTHONPATH=src python3 -m halden.ingest run --db data/asof.duckdb --as-of 2024-09-14T06:00:00+00:00
```

## Daily checks

After each run, these three queries answer "can I trust today's numbers?".

```sql
-- Files expected but not received, or received after the deadline
SELECT source, period_start, arrival_status, hours_late
FROM mart_file_arrivals WHERE arrival_status IN ('late', 'missing') ORDER BY period_start DESC;

-- Every file must balance, and every processor file must match its trailer
SELECT * FROM mart_load_checks WHERE NOT rows_balance OR trailer_matches = false;

-- What was quarantined, and why
SELECT source, reject_reason, count(*) FROM rej_records GROUP BY ALL ORDER BY 3 DESC;
```

The first query normally returns the 7 rows listed in the README. The second normally returns
nothing. The third normally returns 4 reasons and 51 records.

## When something fails

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `file names outside the convention` | A supplier changed its file name | Check with the supplier. Do not rename the file; add the pattern only if the change is agreed |
| `landing log lists files that are not on disk` | The landing log was written before the file was copied | Wait and rerun. Nothing was loaded, because the check runs first |
| A parser raises `incomplete` for a processor file | The trailer record is missing, so the file may be cut off | Do not load it by hand. Ask the processor to resend. See "What a failed run leaves behind" below |
| `RowBalanceError: <file>: N read != ...` | A parser rule dropped or doubled a record | This is a bug in the parser, not in the file. Fix the parser, add a test with the failing line, and rerun |
| A day shows `missing` | The supplier did not send it | Check whether the next file contains its rows, as on 12 September 2024. Report it either way |
| `make validate` fails | A rule changed and broke a check | Read `validation/report.md`. The defect table shows which rule now misses or over-matches |

## What a failed run leaves behind

Feeds load one at a time, in alphabetical order, each in its own transaction. If a run stops
with an error, the feeds before the failing one are fully loaded, and the failing feed and
those after it are untouched. Its row in `meta_runs` has no `finished_at_utc`. The int_ and
mart_ tables still hold the previous run's results, because they are only rebuilt after every
feed has loaded. Once the cause is fixed, `make ingest` picks up exactly the files that are
still missing from the ledger.

## Replacing a file

If a supplier sends a corrected file with the same name, copy it into `data/raw/<source>/`,
update its line in `_landing_log.csv` with the new received time and SHA-256, and run
`make ingest`. The old rows are replaced in one transaction. A test
(`tests/ingest/test_pipeline.py`) checks exactly this.

A corrected file with a new name (such as `_resend` or `_v2`) is loaded alongside the
original. The model rules then decide which version wins: the later file for shop orders, the
highest version for a fulfilment week.

## Starting again

Delete `data/warehouse.duckdb` and run `make ingest`. Nothing else holds state.
