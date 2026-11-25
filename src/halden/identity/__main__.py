"""Command line for project 2.

    python -m halden.identity run       [--db data/warehouse.duckdb]
    python -m halden.identity validate  [--db ...] [--truth data/ground_truth] [--out project_02_identity/validation]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from halden.common.log import setup_logging


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m halden.identity")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="resolve accounts into people inside the warehouse")
    r.add_argument("--db", type=Path, default=Path("data/warehouse.duckdb"))
    v = sub.add_parser("validate", help="score the result against the ground truth")
    v.add_argument("--db", type=Path, default=Path("data/warehouse.duckdb"))
    v.add_argument("--truth", type=Path, default=Path("data/ground_truth"))
    v.add_argument("--out", type=Path, default=Path("project_02_identity/validation"))
    a = ap.parse_args(argv)
    setup_logging()
    if a.cmd == "run":
        from .resolve import run
        run(a.db)
        return 0
    from .validate import validate
    return 0 if validate(a.db, a.truth, a.out) else 1


if __name__ == "__main__":
    sys.exit(main())
