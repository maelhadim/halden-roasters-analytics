"""Load landed files into DuckDB, then rebuild the integrated and mart tables.

    python -m halden.ingest run [--as-of 2024-09-14T06:00:00Z] [--db data/warehouse.duckdb]

A run is safe to repeat. A file is parsed only if its name and SHA-256 are not already in
the ledger. If a file of the same name arrives with different content, its old rows are
deleted before the new ones go in, in the same transaction. The int_ and mart_ tables are
rebuilt from staging on every run, so they always reflect exactly what has been loaded.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from . import landing
from .parsers import PARSERS

log = logging.getLogger("halden.ingest")
HERE = Path(__file__).parent
UTC = timezone.utc


def connect(db: Path) -> duckdb.DuckDBPyConnection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone = 'UTC'")
    con.execute((HERE / "schema.sql").read_text())
    return con


def _columns(con, table: str) -> list[str]:
    return [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]


def load_files(con, raw: Path, as_of: datetime | None) -> dict:
    inv = landing.inventory(raw, as_of)
    done = dict(con.execute("SELECT file_name, sha256 FROM meta_file_loads").fetchall())
    todo = inv[[done.get(f) != s for f, s in zip(inv["file_name"], inv["sha256"])]]
    run_id = (con.execute("SELECT coalesce(max(run_id), 0) + 1 FROM meta_runs").fetchone()[0])
    started = datetime.now(UTC)
    con.execute("INSERT INTO meta_runs (run_id, started_at_utc, as_of_utc, files_seen) VALUES (?, ?, ?, ?)",
                [run_id, started, as_of, len(inv)])
    log.info("run %d: %d files visible, %d new or changed", run_id, len(inv), len(todo))

    for (source, entity), group in todo.groupby(["source", "entity"], sort=True):
        table, parse = PARSERS[(source, entity)]
        staged, rejected, ledger = [], [], []
        for f in group.itertuples(index=False):
            res = parse(Path(f.path))
            staged += res.rows
            rejected += [{"source": source, "entity": entity, **r} for r in res.rejects]
            ledger.append({"file_name": f.file_name, "source": source, "entity": entity,
                           "period_start": f.period_start, "suffix": f.suffix, "received_at_utc": f.received_at_utc,
                           "sha256": f.sha256, "records_read": res.records_read, "staged": len(res.rows),
                           "rejected": len(res.rejects), "blank_ignored": res.blank_ignored,
                           "notes": "; ".join(res.notes) or None,
                           "control_json": json.dumps(res.control) if res.control else None, "run_id": run_id})
        names = group["file_name"].tolist()
        cols = _columns(con, table)
        stg = pd.DataFrame(staged, columns=cols)
        rej = pd.DataFrame(rejected, columns=_columns(con, "rej_records"))
        led = pd.DataFrame(ledger, columns=_columns(con, "meta_file_loads"))
        con.execute("BEGIN TRANSACTION")
        try:
            con.register("names", pd.DataFrame({"n": names}))
            con.execute(f"DELETE FROM {table} WHERE _source_file IN (SELECT n FROM names)")
            con.execute("DELETE FROM rej_records WHERE _source_file IN (SELECT n FROM names)")
            con.execute("DELETE FROM meta_file_loads WHERE file_name IN (SELECT n FROM names)")
            for name, df in ((table, stg), ("rej_records", rej), ("meta_file_loads", led)):
                if len(df):
                    con.register("df", df)
                    con.execute(f"INSERT INTO {name} ({', '.join(df.columns)}) SELECT {', '.join(df.columns)} FROM df")
                    con.unregister("df")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        log.info("%s/%s: %d files, %d staged, %d rejected", source, entity, len(names), len(stg), len(rej))

    con.execute("UPDATE meta_runs SET files_loaded = ?, files_unchanged = ?, finished_at_utc = ? WHERE run_id = ?",
                [len(todo), len(inv) - len(todo), datetime.now(UTC), run_id])
    arr = landing.arrivals(inv, as_of or datetime.now(UTC))
    con.register("arr", arr)
    con.execute("CREATE OR REPLACE TABLE mart_file_arrivals AS SELECT * FROM arr")
    con.unregister("arr")
    return {"run_id": run_id, "files_seen": len(inv), "files_loaded": len(todo)}


def build_models(con):
    sql = (HERE / "models.sql").read_text()
    for stmt in [s.strip() for s in sql.split(";\n") if s.strip()]:
        con.execute(stmt)


def run(raw: Path, db: Path, as_of: datetime | None = None) -> dict:
    t0 = time.perf_counter()
    con = connect(db)
    try:
        stats = load_files(con, raw, as_of)
        build_models(con)
        from .reconcile import build_reconciliation
        build_reconciliation(con)
    finally:
        con.close()
    stats["seconds"] = round(time.perf_counter() - t0, 1)
    log.info("run %(run_id)d finished in %(seconds)ss", stats)
    return stats
