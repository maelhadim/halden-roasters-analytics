"""Command line for project 3.

    python -m halden.kpi extract   [--db data/warehouse.duckdb] [--out project_03_kpi_pack]
    python -m halden.kpi workbook  [--pack project_03_kpi_pack] [--month 2025-06]
    python -m halden.kpi validate  [--db ...] [--truth data/ground_truth] [--pack project_03_kpi_pack]

`extract` writes the CSV files, their manifest and the Power Query scripts. `workbook` builds
the Excel file from those CSV files. `validate` recalculates the workbook in LibreOffice and
compares what it shows with the warehouse and the ground truth.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from halden.common.log import setup_logging


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m halden.kpi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="write the KPI CSV files, manifest and Power Query scripts")
    e.add_argument("--db", type=Path, default=Path("data/warehouse.duckdb"))
    e.add_argument("--out", type=Path, default=Path("project_03_kpi_pack"))
    w = sub.add_parser("workbook", help="build the Excel pack from the CSV files")
    w.add_argument("--pack", type=Path, default=Path("project_03_kpi_pack"))
    w.add_argument("--month", default=None, help="month shown when the file opens (default: the latest)")
    v = sub.add_parser("validate", help="recalculate the workbook and check it against the warehouse")
    v.add_argument("--db", type=Path, default=Path("data/warehouse.duckdb"))
    v.add_argument("--truth", type=Path, default=Path("data/ground_truth"))
    v.add_argument("--pack", type=Path, default=Path("project_03_kpi_pack"))
    a = ap.parse_args(argv)
    setup_logging()
    if a.cmd == "extract":
        from .extract import extract
        from .powerquery import write_scripts
        extract(a.db, a.out / "data")
        write_scripts(a.out / "data", a.out / "powerquery")
        return 0
    if a.cmd == "workbook":
        from .workbook import build
        build(a.pack / "data", Path("docs/metrics.md"), a.pack / "halden_kpi_pack.xlsx", a.month)
        return 0
    from .validate import validate
    return 0 if validate(a.db, a.truth, a.pack) else 1


if __name__ == "__main__":
    sys.exit(main())
