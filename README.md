# Halden Roasters analytics

This repository is a year of data work at one company, built as a portfolio. Halden Roasters
is a fictional coffee subscription business in Manchester that ships to the UK, Ireland,
Germany and the Netherlands. **The company and all of its data are synthetic.** The data
comes from a seeded generator in this repository, and the exchange rates are synthetic
too. I built it this way so every project works on the same customers, the same timeline and
the same metric definitions, and so each result can be checked against a known truth.

## The projects

Each project starts from a problem the business had, uses the output of the projects before
it, and ends with a validation against the ground truth.

| # | Project | Business problem | Status |
| --- | --- | --- | --- |
| 0 | [Data generator and conventions](project_00_data_generator/README.md) | Five projects need one consistent company to work on | Done |
| 1 | [Multi-source ingestion and revenue reconciliation](project_01_ingestion/README.md) | BI revenue does not match the card processor | Done |
| 2 | [Customer identity resolution](project_02_identity/README.md) | The customer count is inflated by duplicate accounts | Done |
| 3 | Monthly KPI pack in Excel and Power Query | The monthly report is rebuilt by hand | Planned |
| 4 | Churn risk scoring with cost-based targeting | Cancellations rose after the February 2025 price increase | Planned |
| 5 | Retention offer A/B test and decision memo | Does a 30% offer pay for itself, and for whom? | Planned |

## Shared rules

- [`docs/company.md`](docs/company.md): the company, its systems and its timeline
- [`docs/conventions.md`](docs/conventions.md): folders, file names, table layers, column rules
- [`docs/metrics.md`](docs/metrics.md): the one set of KPI definitions every project uses
- [`docs/source_specs.md`](docs/source_specs.md): what each source system says it sends
- [`docs/change_log.md`](docs/change_log.md): every change to the plan or the shared rules

## Quick start

```bash
make setup          # Python 3.12+, pinned dependencies
make data           # builds data/raw and data/ground_truth, about 2 minutes
make test
make verify-data    # proves your build is byte-identical to the published one
make ingest         # project 1: loads data/raw into data/warehouse.duckdb, about 40 seconds
make validate       # project 1: checks the warehouse against the ground truth
make identity       # project 2: resolves accounts into people, about 2 seconds
make identity-validate
```

`data/` is not committed. It is about 134 MB and rebuilds the same way every time.
