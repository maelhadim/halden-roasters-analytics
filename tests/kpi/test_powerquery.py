"""The committed Power Query scripts must load exactly the columns the committed CSV files have."""
import re
from pathlib import Path

import pandas as pd
import pytest

from halden.kpi.powerquery import QUERIES, TEXT_COLUMNS, m_script

PACK = Path(__file__).resolve().parents[2] / "project_03_kpi_pack"


@pytest.mark.parametrize("query", QUERIES)
def test_script_matches_its_csv(query):
    file_name, _sheet = QUERIES[query]
    header = (PACK / "data" / file_name).read_text(encoding="utf-8").splitlines()[0].split(",")
    raw = (PACK / "powerquery" / f"{query}.pq").read_bytes()
    pq = raw.decode("utf-8")
    expected = re.search(r"Expected = \{(.*?)\}", pq)[1]
    assert [c.strip().strip('"') for c in expected.split(",")] == header
    typed = re.findall(r'\{"([a-z0-9_]+)", (type text|type number|Int64\.Type)\}', pq)
    assert [c for c, _ in typed] == header
    assert all((t == "type text") == (c in TEXT_COLUMNS) for c, t in typed)
    # Windows line ends, single backslashes (M has no escape sequences) and the en-US culture.
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert "\\\\" not in pq and '"en-US"' in pq and "Encoding = 65001" in pq


def test_text_columns_keep_leading_zeros_and_long_ids():
    df = pd.DataFrame({"month": ["2025-06"], "sha256": ["00ab"], "rows": [3], "control_total": [1.5]})
    pq = m_script("x.csv", df)
    assert '{"month", type text}' in pq and '{"sha256", type text}' in pq
    assert '{"rows", Int64.Type}' in pq and '{"control_total", type number}' in pq
