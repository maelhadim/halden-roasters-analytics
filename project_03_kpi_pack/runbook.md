# Runbook: project 3

## Build the pack

```bash
make identity        # projects 1 and 2 first: the pack reads their tables
make kpi             # about 1 second: CSV files, manifest, Power Query scripts, workbook
make kpi-validate    # about 12 seconds; needs LibreOffice; exits 1 if any check fails
```

A normal `make kpi` run logs:

```
INFO  halden.kpi kpi_monthly.csv: 30 rows, net_revenue_gbp total 4554211.37
INFO  halden.kpi kpi_country_monthly.csv: 120 rows, net_revenue_gbp total 4554211.41
INFO  halden.kpi revenue_bridge_monthly.csv: 30 rows, net_revenue_gbp total 4554211.37
```

`make kpi-validate` needs `soffice` on the path. On Ubuntu:
`sudo apt-get install libreoffice-calc`.

## What it writes

| Path | What it is |
| --- | --- |
| `data/kpi_monthly.csv` | One row per month, every metric in `docs/metrics.md` |
| `data/kpi_country_monthly.csv` | Active subscribers, MRR and net revenue per month and country |
| `data/revenue_bridge_monthly.csv` | Project 1's bridge from the old BI figure to net revenue |
| `data/_manifest.csv` | Rows, columns, control total and SHA-256 of each file above |
| `powerquery/*.pq` | One Power Query script per file. Generated; edit `src/halden/kpi/powerquery.py` instead |
| `halden_kpi_pack.xlsx` | The pack, with a snapshot of the data on its Data_ sheets |
| `vba/setup_power_query.bas` | The one-time setup macro |

## One-time setup in Excel (Windows, Excel 365)

1. Copy the whole `project_03_kpi_pack` folder to the PC, keeping `data`, `powerquery` and
   `vba` next to the workbook.
2. Open `halden_kpi_pack.xlsx`. On the Settings sheet, put the full path of the `data`
   folder in C4, for example `C:\Users\you\halden\project_03_kpi_pack\data`. If you skip
   this, the macro uses the `data` folder next to the workbook.
3. Press Alt+F11. In the VBA editor choose File > Import File and pick
   `vba\setup_power_query.bas`. Close the editor.
4. Press Alt+F8, choose `SetupQueries` and click Run. It takes a few seconds and ends with a
   message that should say "All checks pass".
5. Check by hand that:
   - Data > Queries & Connections lists four queries: `kpi_monthly`, `kpi_country_monthly`,
     `revenue_bridge_monthly` and `kpi_manifest`.
   - Data_Monthly has 31 rows (a header and 30 months) and starts at 2023-01.
   - Summary for 2025-06 shows 6,647 active subscribers and 175,479 net revenue.
   - Checks says PASS in C3.
   - On Summary, the Change % cell for "Active subscription accounts" has no colour. A
     LibreOffice PDF export once shaded it green; Excel should not (build notes).
6. Save. Excel warns that the VB project cannot be saved in a macro-free workbook. Choose
   Yes: the macro is dropped and the queries stay.

If Excel asks about privacy levels at step 4, the query is combining the folder cell with
the files. Choose Data > Get Data > Query Options > Current Workbook > Privacy > "Ignore the
Privacy Levels", then run the macro again. Both sources are on the same PC, so nothing leaves
it.

## One-time setup in Excel for Mac (Excel 365)

The setup macro does not run on a Mac: it reads files with ADODB and creates connections
through the Windows Power Query provider, and neither exists in Excel for Mac. The queries
themselves do run, so on a Mac they are added by hand. Do `kpi_monthly` first; the other
three are the same steps.

1. Copy the whole `project_03_kpi_pack` folder to the Mac, keeping `data`, `powerquery` and
   `vba` next to the workbook.
2. On the Settings sheet, put the full path of the `data` folder in C4, for example
   `/Users/you/Downloads/project_03_kpi_pack/data`. In Finder, select the `data` folder and
   press Option+Cmd+C to copy its path.
3. Go to Data_Monthly. Click any cell in the table, then on the Table tab choose Convert to
   Range and confirm. Select A1:Z100 and choose Edit > Clear > All. Do not delete the sheet or
   its columns: the Summary formulas point at them.
4. Choose Data > Get Data (Power Query) > Blank query. In the Power Query editor choose
   Advanced Editor, delete what is there, and paste the whole of `powerquery/kpi_monthly.pq`
   (open it in TextEdit). Click OK.
5. In the Query Settings pane on the right, rename the query to `kpi_monthly`.
6. If Excel asks for access to the folder, grant it. Excel for Mac can only read folders it
   has been given.
7. Choose Close & Load To, then Existing worksheet, `=Data_Monthly!$A$1`. If your version
   only offers Close & Load, it loads to a new sheet: select the whole table there, cut it
   with Cmd+X, paste it at Data_Monthly A1, and delete the empty new sheet.
8. Check that Data_Monthly has 31 rows starting at 2023-01, that Summary still shows 6,647
   active subscribers for 2025-06, and that Checks says PASS.

Repeat steps 3 to 8 for `kpi_country_monthly` on Data_Country, `revenue_bridge_monthly` on
Data_Bridge and `kpi_manifest` on Data_Manifest.

## The monthly update

1. Run `make ingest`, `make identity` and `make kpi` after the month's last daily files have
   loaded.
2. Open the pack and choose Data > Refresh All.
3. Choose the new month in Summary!C5. The month list grows on its own.
4. Check that Summary!C6 says "All checks pass". If it does not, do not send the pack: see
   below.

The latest month can change slightly when the next day's files load, because events made
late on the last day arrive in the next morning's files. In the June 2025 build, MRR moved by
61.48 GBP this way (validation report, section 3).

## When a check fails

| Check that fails | Usual cause | What to do |
| --- | --- | --- |
| rows match the manifest | Refresh read a file while `make kpi` was still writing it, or a file was copied without its manifest | Run `make kpi` again, then Refresh All |
| net revenue total matches the manifest | A column loaded as text, or the files are from two different runs | Check the query has `"en-US"` in its `Table.TransformColumnTypes` step; rerun `make kpi` |
| Bridge adds up in every month | Project 1's bridge changed | Run `make validate` for project 1 and read its report |
| Countries add up to the total | A country is missing, or the selected month is not in the data | Check Data_Country for the month |
| Accounts never fewer than people | Project 2's tables are out of date | Run `make identity`, then `make kpi` |
| Bridge ends on the same net revenue as the KPI table | Files from different runs | Run `make kpi` again |
| Selected month is in the data | A month was typed into C5 by hand | Choose a month from the list |

| Error during refresh | Cause | Fix |
| --- | --- | --- |
| `Unexpected columns in kpi_monthly.csv` | The extract changed and the queries are older | Run the setup macro again; it replaces the queries |
| `DataSource.NotFound` or a missing file | Settings!C4 points at the wrong folder | Fix the path in C4 |
| `Formula.Firewall` | Privacy levels (see above) | Set "Ignore the Privacy Levels" for this workbook |

## Change the pack

- A new metric: add it to `mart_kpi_monthly` in `src/halden/kpi/extract.py` and to `METRICS`
  in `src/halden/kpi/workbook.py`, define it in `docs/metrics.md`, then run `make kpi`,
  `make kpi-validate` and `make test`. Rerun the setup macro, because the query's column list
  changed.
- A new month of history: nothing to change. The Trend charts keep their 30 months until the
  file is rebuilt with `make kpi`.
- Commit the CSV files, scripts, workbook and validation report together. CI rebuilds them
  and fails if any of them differs.
