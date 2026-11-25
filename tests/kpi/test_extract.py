"""The KPI files are written the same way every time, and the manifest describes them truthfully."""
import hashlib
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from halden.kpi.extract import _csv, extract

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "project_03_kpi_pack" / "data"
DB = ROOT / "data" / "warehouse.duckdb"


def test_negative_zero_is_written_as_zero():
    out = _csv(pd.DataFrame({"a": [-0.0, -0.01, 1234567.891]})).decode()
    assert out == "a\n0\n-0.01\n1234567.891\n"


def test_manifest_describes_the_committed_files():
    m = pd.read_csv(DATA / "_manifest.csv", dtype={"sha256": str})
    for r in m.itertuples():
        data = (DATA / r.file_name).read_bytes()
        df = pd.read_csv(DATA / r.file_name)
        assert hashlib.sha256(data).hexdigest() == r.sha256
        assert (len(df), len(df.columns)) == (r.rows, r.columns)
        assert round(df[r.control_column].sum(), 2) == pytest.approx(r.control_total, abs=0.005)


def test_monthly_file_has_every_month_once():
    df = pd.read_csv(DATA / "kpi_monthly.csv", dtype={"month": str})
    assert df["month"].tolist() == [p.strftime("%Y-%m") for p in pd.period_range("2023-01", "2025-06", freq="M")]
    assert (df["active_subscription_accounts"] >= df["active_subscribers"]).all()


@pytest.mark.skipif(not DB.exists(), reason="run `make identity` first")
def test_extract_is_repeatable(tmp_path):
    # Work on a copy: extract writes its tables into the warehouse it is given.
    db = tmp_path / "w.duckdb"
    db.write_bytes(DB.read_bytes())
    a = extract(db, tmp_path / "a")
    b = extract(db, tmp_path / "b")
    assert a.equals(b)
    assert (tmp_path / "a" / "_manifest.csv").read_bytes() == (DATA / "_manifest.csv").read_bytes()
