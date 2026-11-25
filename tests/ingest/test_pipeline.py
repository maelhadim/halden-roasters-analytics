"""The load ledger on a small slice of the real build: balance, safe re-runs, changed files."""
import hashlib
import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from halden.ingest.pipeline import run

RAW = Path("data/raw")
pytestmark = pytest.mark.skipif(not (RAW / "_landing_log.csv").exists(), reason="run `make data` first")

# One week of every source, plus the CRM migration snapshot and an FX month.
PICK = ("_2024031", "_20240301", "fx_eurgbp_202402", "crm_customers_20230313_full")


@pytest.fixture()
def raw(tmp_path):
    log = pd.read_csv(RAW / "_landing_log.csv", dtype=str)
    keep = log[log["file_name"].apply(lambda n: any(p in n for p in PICK))]
    out = tmp_path / "raw"
    for f in keep.itertuples():
        (out / f.source).mkdir(parents=True, exist_ok=True)
        shutil.copy(RAW / f.source / f.file_name, out / f.source / f.file_name)
    keep.to_csv(out / "_landing_log.csv", index=False)
    return out


def counts(db):
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute("""SELECT count(*), sum(records_read), sum(staged), sum(rejected), sum(blank_ignored)
                              FROM meta_file_loads""").fetchone(), con
    except Exception:
        con.close()
        raise


def test_rows_balance_and_rerun_loads_nothing(raw, tmp_path):
    db = tmp_path / "w.duckdb"
    first = run(raw, db)
    assert first["files_loaded"] == first["files_seen"] > 10
    (files, read, staged, rejected, blank), con = counts(db)
    with con:
        assert read == staged + rejected + blank
        for table in ("stg_shop_orders", "stg_payproc_transactions", "stg_ful_shipment_events", "stg_crm_customer_versions"):
            n_tab = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            n_led = con.execute(f"""SELECT sum(staged) FROM meta_file_loads
                                    WHERE file_name IN (SELECT DISTINCT _source_file FROM {table})""").fetchone()[0]
            assert n_tab == n_led, table
        before = con.execute("SELECT count(*) FROM int_orders").fetchone()[0]
    second = run(raw, db)
    assert second["files_loaded"] == 0
    (files2, read2, *_), con = counts(db)
    with con:
        assert (files2, read2) == (files, read)
        assert con.execute("SELECT count(*) FROM int_orders").fetchone()[0] == before


def test_changed_file_replaces_its_rows(raw, tmp_path):
    db = tmp_path / "w.duckdb"
    run(raw, db)
    log = pd.read_csv(raw / "_landing_log.csv", dtype=str)
    name = sorted(n for n in log["file_name"] if n.startswith("shop_orders_"))[0]
    path = raw / "shop" / name
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [lines[0]] + [ln for ln in lines[1:] if ln.strip()][:-1]   # the supplier drops the last order
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    log.loc[log["file_name"] == name, "sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    log.to_csv(raw / "_landing_log.csv", index=False)
    assert run(raw, db)["files_loaded"] == 1
    con = duckdb.connect(str(db), read_only=True)
    with con:
        n = con.execute("SELECT count(*) FROM stg_shop_orders WHERE _source_file = ?", [name]).fetchone()[0]
        led = con.execute("SELECT staged, rejected FROM meta_file_loads WHERE file_name = ?", [name]).fetchall()
    assert len(led) == 1 and n == led[0][0] == len(kept) - 1 - led[0][1]
