"""The workbook's formulas: built from the committed CSVs, readable by older Excel and LibreOffice."""
import re
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from halden.kpi.workbook import BRIDGE, METRICS, build

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "project_03_kpi_pack"


def _formulas(wb):
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    yield ws.title, c.coordinate, c.value


def test_committed_workbook_is_a_fresh_build(tmp_path):
    out = build(PACK / "data", ROOT / "docs" / "metrics.md", tmp_path / "pack.xlsx")
    assert out.read_bytes() == (PACK / "halden_kpi_pack.xlsx").read_bytes()


def test_no_functions_that_older_excel_or_libreoffice_lack():
    wb = load_workbook(PACK / "halden_kpi_pack.xlsx")
    banned = re.compile(r"\b(XLOOKUP|XMATCH|LET|LAMBDA|FILTER|SORT|UNIQUE|SEQUENCE)\(|\[#|\]\[")
    found = [(s, c, f) for s, c, f in _formulas(wb) if banned.search(f)]
    assert not found


def test_formulas_name_columns_that_exist():
    cols = {**{k: "kpi_monthly.csv" for k, *_ in METRICS}, **{k: "revenue_bridge_monthly.csv" for k, _ in BRIDGE}}
    for key, file_name in cols.items():
        assert key in pd.read_csv(PACK / "data" / file_name, nrows=0).columns, key


def test_names_and_month_picker():
    wb = load_workbook(PACK / "halden_kpi_pack.xlsx")
    assert wb.defined_names["DataFolder"].attr_text == "Settings!$C$4"
    assert "COUNTA(Data_Monthly!$A:$A)" in wb.defined_names["MonthList"].attr_text
    dv = wb["Summary"].data_validations.dataValidation
    assert len(dv) == 1 and str(dv[0].sqref) == "C5" and dv[0].formula1 == "=MonthList"
    assert wb["Summary"]["C5"].value == "2025-06"
