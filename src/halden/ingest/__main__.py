"""Command line for project 1.

    python -m halden.ingest run       [--raw data/raw] [--db data/warehouse.duckdb] [--as-of ISO-8601]
    python -m halden.ingest validate  [--db ...] [--truth data/ground_truth] [--out project_01_ingestion/validation]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from halden.common.log import setup_logging


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m halden.ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="load new files and rebuild the integrated tables")
    r.add_argument("--raw", type=Path, default=Path("data/raw"))
    r.add_argument("--db", type=Path, default=Path("data/warehouse.duckdb"))
    r.add_argument("--as-of", type=datetime.fromisoformat, default=None,
                   help="replay history: ignore files received after this UTC time")
    v = sub.add_parser("validate", help="compare the warehouse with the ground truth")
    v.add_argument("--db", type=Path, default=Path("data/warehouse.duckdb"))
    v.add_argument("--truth", type=Path, default=Path("data/ground_truth"))
    v.add_argument("--out", type=Path, default=Path("project_01_ingestion/validation"))
    a = ap.parse_args(argv)
    setup_logging()
    if a.cmd == "run":
        from .pipeline import run
        run(a.raw, a.db, a.as_of)
        return 0
    from .validate import validate
    return 0 if validate(a.db, a.truth, a.out) else 1


if __name__ == "__main__":
    sys.exit(main())
