"""Run the method on the real build: every account gets one person, and two runs agree exactly."""
from pathlib import Path

import duckdb
import pytest

from halden.identity.resolve import resolve

DB = Path("data/warehouse.duckdb")
pytestmark = pytest.mark.skipif(not DB.exists(), reason="run `make ingest` first")


def test_every_account_once_and_runs_are_repeatable():
    con = duckdb.connect(str(DB), read_only=True)
    with con:
        a, b = resolve(con), resolve(con)
        n_crm = con.execute("SELECT count(*) FROM int_crm_customers").fetchone()[0]
    p = a["persons"]
    assert p["customer_id"].is_unique and len(p) >= n_crm
    assert p.equals(b["persons"]) and a["scored"]["match_weight"].equals(b["scored"]["match_weight"])
    # Every merged pair shares a strong identifier.
    merged = a["scored"][a["scored"]["decision"] == "merge"]
    strong = (merged["phone"] == 1) | (merged["email"] == 1) | (merged["legacy_id"] == 1) | (
        (merged["street"] == 2) & (merged["postcode"] == 1) & (merged["first_name"] == 3))
    assert strong.all()
