"""Checks on a full build in data/. Run `make data` first; these skip otherwise.

These tests check the generator against itself: every true record must be
present in the raw files the expected number of times, and every defect the
manifest claims must really be in the files.
"""
import csv
import hashlib
import io
from pathlib import Path

import pandas as pd
import pytest

from halden.generator.defects import CATALOGUE

DATA = Path(__file__).resolve().parents[2] / "data"
RAW, GT = DATA / "raw", DATA / "ground_truth"

pytestmark = pytest.mark.skipif(not (GT / "gt_defects.csv").exists(), reason="no build in data/; run make data")


def gt(name):
    return pd.read_csv(GT / name, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def landing():
    return pd.read_csv(RAW / "_landing_log.csv", dtype=str)


def test_landing_log_matches_files(landing):
    files = {p.name for p in RAW.rglob("*") if p.is_file() and not p.name.startswith("_")}
    assert files == set(landing["file_name"])
    for row in landing.sample(50, random_state=1).itertuples():
        data = (RAW / row.source / row.file_name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row.sha256


def test_every_catalogued_defect_is_present():
    # A defect listed in the catalogue but absent from the files would be a false claim in the docs.
    assert set(gt("gt_defects.csv")["defect_code"]) == set(CATALOGUE)


def test_each_order_appears_once_outside_the_resend_day():
    orders = gt("gt_orders.csv")
    seen = []
    for p in sorted((RAW / "shop").glob("shop_orders_*.csv")):
        if "_resend" in p.name:
            continue
        text = p.read_text(encoding="utf-8")
        reader = csv.reader(io.StringIO(text))
        next(reader)
        seen += [r[0] for r in reader if r and r[0].isdigit()]
    counts = pd.Series(seen).value_counts()
    assert counts.max() == 1
    truncated = set(gt("gt_defects.csv").query("defect_code == 'SHOP_TRUNCATED_FILE'")["record_key"])
    # Orders after 23:00 UTC on 30 June fall on 1 July London time, in a file outside the window.
    local = pd.to_datetime(orders["created_at_utc"]).dt.tz_convert("Europe/London").dt.date.astype(str)
    in_window = orders[local <= "2025-06-30"]
    missing = set(in_window["order_id"]) - set(counts.index)
    # The truncated file loses whole rows; the half-written last row still starts with its order_id.
    assert missing <= truncated and len(truncated - missing) == 1


def test_payproc_trailers_match_unique_rows():
    for p in sorted((RAW / "payproc").glob("*.txt")):
        lines = p.read_text().splitlines()
        header, body, trailer = lines[0].split("|"), lines[1:-1], lines[-1].split("|")
        assert header[0] == "H" and trailer[0] == "T"
        ids = [ln.split("|")[1] for ln in body]
        gross_col = 6
        unique = {}
        for ln in body:
            parts = ln.split("|")
            unique[parts[1]] = float(parts[gross_col])
        assert int(trailer[1]) == len(unique), p.name
        assert abs(sum(unique.values()) - float(trailer[2])) < 0.005, p.name
        assert len(ids) - len(unique) in (0, 5), p.name


def test_payproc_covers_every_true_transaction_once():
    tx = gt("gt_transactions.csv")
    tx = tx[tx["txn_at_utc"].str[:10] <= "2025-06-30"]
    seen = set()
    for p in (RAW / "payproc").glob("*.txt"):
        for ln in p.read_text().splitlines()[1:-1]:
            seen.add(ln.split("|")[1])
    assert seen == set(tx["txn_id"])


def test_experiment_log_loss_only_hits_treatment_in_outage():
    a = gt("gt_experiment_assignments.csv")
    lost = a[a["logged"] == "False"]
    assert (lost["variant"] == "treatment").all()
    assert lost["assigned_at_utc"].str[:10].between("2025-04-09", "2025-04-11").all()
    logged_ids = set()
    for p in (RAW / "exp").glob("*.jsonl"):
        logged_ids |= {ln.split('"event_id":"')[1].split('"')[0] for ln in p.read_text().splitlines() if ln}
    assert logged_ids == set(a.loc[a["logged"] == "True", "event_id"])


def test_monthly_metrics_are_internally_consistent():
    m = pd.read_csv(GT / "gt_monthly_metrics.csv")
    prev = m["active_subscribers"].shift(1)
    flow = prev + m["new_subscribers"] - m["churned_subscribers"]
    assert (flow.iloc[1:] == m["active_subscribers"].iloc[1:]).all()
    assert (m["active_subscription_accounts"] >= m["active_subscribers"]).all()
    assert (m["net_revenue_gbp"] < m["gross_revenue_gbp"]).all()


def test_fx_has_no_weekend_rates():
    rates = pd.concat(pd.read_csv(p) for p in (RAW / "fx").glob("*.csv"))
    days = pd.to_datetime(rates["rate_date"]).dt.weekday
    assert (days < 5).all()
    assert rates["rate"].between(0.80, 0.95).all()


def test_fulfilment_files_are_cp1252_not_utf8():
    failures = 0
    for p in (RAW / "ful").glob("*.csv"):
        data = p.read_bytes()
        data.decode("cp1252")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            failures += 1
    assert failures > 100
