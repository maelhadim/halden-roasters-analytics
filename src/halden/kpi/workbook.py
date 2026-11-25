"""Build the KPI pack workbook.

The workbook ships with a snapshot of the data already in its Data_ sheets, so it opens and
works anywhere. Running the setup macro once in Windows Excel replaces those snapshots with
Power Query tables that refresh from the CSV folder (see project_03_kpi_pack/runbook.md).

Every formula looks a column up by its header name, through INDEX and MATCH on the Data_
sheets' whole columns. Nothing refers to a table by name or to a fixed column letter, so the
formulas keep working when Power Query replaces a snapshot, adds a month or reorders
columns. I avoided XLOOKUP, LET and dynamic arrays so that the file also calculates in
LibreOffice, which is how CI checks it, and in older Excel versions.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from .powerquery import QUERIES

import openpyxl.xml   # noqa: E402

if openpyxl.xml.LXML:   # openpyxl was imported before halden.kpi set OPENPYXL_LXML
    raise RuntimeError("openpyxl is using lxml, so the workbook would not be reproducible. "
                       "Import halden.kpi before openpyxl, or set OPENPYXL_LXML=False.")

INK, MUTED, RULE, HEAD_BG, OK_BG, BAD_BG = "1F2933", "616E7C", "D3D8DE", "EEF1F4", "DFF3E4", "FBE0E0"
TITLE = Font(name="Calibri", size=16, bold=True, color=INK)
H2 = Font(name="Calibri", size=12, bold=True, color=INK)
BODY = Font(name="Calibri", size=11, color=INK)
SMALL = Font(name="Calibri", size=9, color=MUTED)
BOLD = Font(name="Calibri", size=11, bold=True, color=INK)
HEAD_FILL = PatternFill("solid", fgColor=HEAD_BG)
LINE = Border(bottom=Side(style="thin", color=RULE))

# (column in kpi_monthly, label, number format, direction: +1 if up is good, -1 if up is bad, 0 neutral)
METRICS = [
    ("active_subscribers", "Active subscribers (people)", "#,##0", 1),
    ("active_subscription_accounts", "Active subscription accounts", "#,##0", 0),
    ("new_subscribers", "New subscribers", "#,##0", 1),
    ("churned_subscribers", "Churned subscribers", "#,##0", -1),
    ("monthly_churn_rate", "Monthly churn rate", "0.00%", -1),
    ("new_customers", "New customers (people)", "#,##0", 1),
    ("mrr_gbp", "MRR, GBP", "#,##0", 1),
    ("gross_revenue_gbp", "Gross revenue, GBP", "#,##0", 1),
    ("net_revenue_gbp", "Net revenue, GBP", "#,##0", 1),
    ("paid_orders", "Paid orders", "#,##0", 1),
    ("late_delivery_rate", "Late delivery rate", "0.00%", -1),
]
BRIDGE = [
    ("bi_reported_gbp", "Old BI report"), ("step1_duplicate_loads", "Duplicate file loads"),
    ("step2_test_orders", "Test orders"), ("step3_unpaid_orders", "Unpaid orders"),
    ("step4_capture_month", "Capture month (UTC)"), ("step5_daily_fx", "Daily FX rate"),
    ("step6_refunds_chargebacks", "Refunds and chargebacks"), ("step7_vat", "VAT"),
    ("net_revenue_gbp", "Net revenue"),
]
COUNTRIES = [("GB", "United Kingdom"), ("IE", "Ireland"), ("DE", "Germany"), ("NL", "Netherlands")]


def _lookup(sheet: str, row_expr: str, col_name_expr: str) -> str:
    """INDEX/MATCH on whole columns: the value in `sheet` at row `row_expr`, column named `col_name_expr`."""
    return f"INDEX('{sheet}'!$A:$AZ,{row_expr},MATCH({col_name_expr},'{sheet}'!$1:$1,0))"


def _width(ws, widths: dict[str, float]):
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def _data_sheet(wb, name: str, df: pd.DataFrame):
    ws = wb.create_sheet(name)
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and pd.isna(v)) else v for v in row])
    ref = f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}"
    t = Table(displayName=f"snapshot_{name.lower()}", ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    ws.add_table(t)
    for i, c in enumerate(df.columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(len(c) + 2, 30))
    ws.freeze_panes = "A2"
    ws.sheet_properties.tabColor = "B0B8C1"
    return ws


def _definitions(metrics_md: Path) -> list[tuple[str, str]]:
    rows = []
    for line in metrics_md.read_text().splitlines():
        m = re.match(r"^\| `([a-z_]+)` \| (.+) \|$", line)
        if m:
            rows.append((m[1], m[2].replace("`", "")))
    return rows


def build(data: Path, metrics_md: Path, out: Path, selected_month: str | None = None) -> Path:
    frames = {sheet: pd.read_csv(data / file_name, dtype={"month": str})
              for _q, (file_name, sheet) in QUERIES.items()}
    monthly = frames["Data_Monthly"]
    months = monthly["month"].tolist()
    selected_month = selected_month or months[-1]
    manifest = frames["Data_Manifest"]

    wb = Workbook()
    cover = wb.active
    cover.title = "Cover"

    # ---------------------------------------------------------------- Summary
    ws = wb.create_sheet("Summary")
    ws.sheet_view.showGridLines = False
    ws["B2"] = "Halden Roasters: monthly KPI pack"
    ws["B2"].font = TITLE
    ws["B3"] = "Synthetic data. Every figure comes from the warehouse built in projects 1 and 2."
    ws["B3"].font = SMALL
    ws["B5"], ws["C5"] = "Month", selected_month
    ws["B5"].font = BOLD
    ws["C5"].font = Font(name="Calibri", size=12, bold=True, color="0B5CAD")
    ws["C5"].fill = PatternFill("solid", fgColor="E8F0FA")
    ws["D5"] = "Choose a month from the list in C5."
    ws["D5"].font = SMALL
    dv = DataValidation(type="list", formula1="=MonthList", allow_blank=False, showDropDown=False)
    dv.error, dv.errorTitle = "Pick a month from the list.", "Unknown month"
    ws.add_data_validation(dv)
    dv.add("C5")
    ws["B6"] = "Checks"
    ws["B6"].font = BOLD
    ws["C6"] = '=IF(Checks!$C$3="PASS","All checks pass","CHECK FAILED: see the Checks sheet")'

    # Helper cells: the row of the selected, previous and year-ago month on Data_Monthly.
    ws["J5"], ws["K5"] = "row", "=MATCH($C$5,'Data_Monthly'!$A:$A,0)"
    ws["J6"], ws["K6"] = "previous", "=IF($K$5>2,$K$5-1,NA())"
    ws["J7"], ws["K7"] = "year ago", "=IF($K$5>13,$K$5-12,NA())"
    ws["L6"] = "=IF(ISNA($K$6),\"\",INDEX('Data_Monthly'!$A:$A,$K$6))"
    ws["L7"] = "=IF(ISNA($K$7),\"\",INDEX('Data_Monthly'!$A:$A,$K$7))"
    for c in ("J5", "J6", "J7", "K5", "K6", "K7", "L6", "L7"):
        ws[c].font = SMALL

    head = ["Metric", "This month", "Previous month", "Change", "Change %", "A year earlier", "Change on a year"]
    r0 = 8
    for j, h in enumerate(head):
        c = ws.cell(row=r0, column=2 + j, value=h)
        c.font, c.fill, c.alignment = BOLD, HEAD_FILL, Alignment(horizontal="left" if j == 0 else "right")
    ws.cell(row=r0, column=10, value="key").font = SMALL
    for i, (key, label, fmt, direction) in enumerate(METRICS, start=1):
        r = r0 + i
        ws.cell(row=r, column=10, value=key).font = SMALL      # the header name the formulas look up
        ws.cell(row=r, column=11, value=direction).font = SMALL
        ws.cell(row=r, column=2, value=label).font = BODY
        k = f"$J{r}"
        ws.cell(row=r, column=3, value="=" + _lookup("Data_Monthly", "$K$5", k))
        ws.cell(row=r, column=4, value=f'=IF(ISNA($K$6),"",{_lookup("Data_Monthly", "$K$6", k)})')
        if "%" in fmt:
            # A rate's change is shown in percentage points, so 5.81% against 7.95% reads -2.14 pp,
            # not "-2.14%", which a reader could take for a relative change.
            ws.cell(row=r, column=5, value=f'=IF(D{r}="","",(C{r}-D{r})*100)')
        else:
            ws.cell(row=r, column=5, value=f'=IF(D{r}="","",C{r}-D{r})')
        ws.cell(row=r, column=6, value=f'=IF(OR(D{r}="",D{r}=0),"",C{r}/D{r}-1)')
        ws.cell(row=r, column=7, value=f'=IF(ISNA($K$7),"",{_lookup("Data_Monthly", "$K$7", k)})')
        ws.cell(row=r, column=8, value=f'=IF(OR(G{r}="",G{r}=0),"",C{r}/G{r}-1)')
        for col in (3, 4, 7):
            ws.cell(row=r, column=col).number_format = fmt
        ws.cell(row=r, column=5).number_format = '+0.00" pp";-0.00" pp";0.00" pp"' if "%" in fmt else "+#,##0;-#,##0;0"
        for col in (6, 8):
            ws.cell(row=r, column=col).number_format = "+0.0%;-0.0%;0.0%"
        for col in range(2, 9):
            ws.cell(row=r, column=col).border = LINE
    last = r0 + len(METRICS)
    # Green when a metric moved the good way, red when it moved the bad way.
    green, red = PatternFill("solid", fgColor=OK_BG), PatternFill("solid", fgColor=BAD_BG)
    for col in ("F", "H"):
        rng = f"{col}{r0 + 1}:{col}{last}"
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'AND(ISNUMBER({col}{r0 + 1}),{col}{r0 + 1}*$K{r0 + 1}>0.0005)'], fill=green))
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'AND(ISNUMBER({col}{r0 + 1}),{col}{r0 + 1}*$K{r0 + 1}<-0.0005)'], fill=red))
    ws.cell(row=last + 2, column=2, value="Change % is green when the metric moved the way the business wants, red when "
            "it moved the other way. Accounts are not coloured: more accounts per person is neither good nor bad.").font = SMALL
    ws.cell(row=last + 3, column=2, value="Definitions are on the Definitions sheet and in docs/metrics.md.").font = SMALL

    # By country for the selected month.
    rc = last + 5
    ws.cell(row=rc, column=2, value="By country").font = H2
    for j, h in enumerate(["Country", "Active subscribers", "MRR, GBP", "Net revenue, GBP", "Share of net revenue"]):
        c = ws.cell(row=rc + 1, column=2 + j, value=h)
        c.font, c.fill = BOLD, HEAD_FILL
    for i, (code, name) in enumerate(COUNTRIES, start=2):
        r = rc + i
        ws.cell(row=r, column=2, value=name).font = BODY
        ws.cell(row=r, column=10, value=code).font = SMALL
        for j, key in enumerate(["active_subscribers", "mrr_gbp", "net_revenue_gbp"]):
            col_rng = f"INDEX('Data_Country'!$A:$AZ,0,MATCH(\"{key}\",'Data_Country'!$1:$1,0))"
            ws.cell(row=r, column=3 + j, value=f"=SUMIFS({col_rng},'Data_Country'!$A:$A,$C$5,'Data_Country'!$B:$B,$J{r})")
            ws.cell(row=r, column=3 + j).number_format = "#,##0"
        ws.cell(row=r, column=6, value=f"=IF(SUM($E${rc + 2}:$E${rc + 5})=0,\"\",E{r}/SUM($E${rc + 2}:$E${rc + 5}))")
        ws.cell(row=r, column=6).number_format = "0.0%"
        for col in range(2, 7):
            ws.cell(row=r, column=col).border = LINE
    rt = rc + 6
    ws.cell(row=rt, column=2, value="Total").font = BOLD
    for col in "CDE":
        ws[f"{col}{rt}"] = f"=SUM({col}{rc + 2}:{col}{rc + 5})"
        ws[f"{col}{rt}"].number_format, ws[f"{col}{rt}"].font = "#,##0", BOLD

    # Revenue bridge for the selected month.
    rb = rt + 3
    ws.cell(row=rb, column=2, value="Why the old BI figure was different").font = H2
    for j, h in enumerate(["Step", "GBP"]):
        c = ws.cell(row=rb + 1, column=2 + j, value=h)
        c.font, c.fill = BOLD, HEAD_FILL
    brow = "MATCH($C$5,'Data_Bridge'!$A:$A,0)"
    for i, (key, label) in enumerate(BRIDGE, start=2):
        r = rb + i
        ws.cell(row=r, column=2, value=label).font = BOLD if key in ("bi_reported_gbp", "net_revenue_gbp") else BODY
        ws.cell(row=r, column=10, value=key).font = SMALL
        ws.cell(row=r, column=3, value="=" + _lookup("Data_Bridge", brow, f"$J{r}"))
        ws.cell(row=r, column=3).number_format = "#,##0.00;-#,##0.00"
        ws.cell(row=r, column=2).border = ws.cell(row=r, column=3).border = LINE
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    _width(ws, {"A": 2, "B": 34, "C": 19, "D": 16, "E": 16, "F": 20, "G": 15, "H": 17, "I": 3, "J": 26, "K": 9, "L": 9})
    for col in "JKL":
        ws.column_dimensions[col].hidden = True   # helper cells; unhide to see how the lookups work
    ws.freeze_panes = "A8"

    # ------------------------------------------------------------------ Trend
    tr = wb.create_sheet("Trend")
    tr.sheet_view.showGridLines = False
    tr["B2"] = "30-month trend"
    tr["B2"].font = TITLE
    tr["B3"] = "Charts read the Data_Monthly sheet directly. Synthetic data."
    tr["B3"].font = SMALL
    # The charts are added after the Data_ sheets exist, further down.

    # ----------------------------------------------------------------- Checks
    ck = wb.create_sheet("Checks")
    ck.sheet_view.showGridLines = False
    ck["B2"] = "Checks"
    ck["B2"].font = TITLE
    ck["B3"] = "Overall"   # its formula is written after the checks, when their count is known
    ck["B3"].font = ck["C3"].font = BOLD
    ck["B4"] = "Each check recalculates whenever the data changes. A FAIL means the pack must not be sent."
    ck["B4"].font = SMALL
    for j, h in enumerate(["Check", "Value", "Result", "What it means"]):
        c = ck.cell(row=6, column=2 + j, value=h)
        c.font, c.fill = BOLD, HEAD_FILL

    def mrow(file_name, field):
        return (f"INDEX('Data_Manifest'!$A:$AZ,MATCH(\"{file_name}\",'Data_Manifest'!$A:$A,0),"
                f"MATCH(\"{field}\",'Data_Manifest'!$1:$1,0))")

    def col_of(sheet, key):
        return f"INDEX('{sheet}'!$A:$AZ,0,MATCH(\"{key}\",'{sheet}'!$1:$1,0))"

    checks = []
    for _q, (file_name, sheet) in QUERIES.items():
        if sheet == "Data_Manifest":
            continue
        checks.append((f"{sheet}: rows match the manifest",
                       f"=COUNTA('{sheet}'!$A:$A)-1-{mrow(file_name, 'rows')}",
                       "=IF(C{r}=0,\"PASS\",\"FAIL\")",
                       f"Rows on {sheet} minus rows the extract wrote. Anything but 0 means a partial load."))
        checks.append((f"{sheet}: net revenue total matches the manifest",
                       f"=ROUND(SUM({col_of(sheet, 'net_revenue_gbp')})-{mrow(file_name, 'control_total')},2)",
                       "=IF(ABS(C{r})<0.01,\"PASS\",\"FAIL\")",
                       "The control total written next to the data. Catches a wrongly typed or shifted column."))
    checks += [
        ("Bridge adds up in every month",
         # SUMIF skips the header text, where ABS over a whole column would return #VALUE!.
         f"=SUMIF({col_of('Data_Bridge', 'residual_gbp')},\">0\")-SUMIF({col_of('Data_Bridge', 'residual_gbp')},\"<0\")",
         "=IF(C{r}<=0.05*COUNTA('Data_Bridge'!$A:$A),\"PASS\",\"FAIL\")",
         "Sum of the rounding residuals. Each month is allowed a few pence of rounding."),
        ("Countries add up to the total for the selected month",
         "=ROUND(Summary!$E$" + str(rt) + "-Summary!$C$" + str(r0 + 1 + [m[0] for m in METRICS].index("net_revenue_gbp")) + ",2)",
         "=IF(ABS(C{r})<1,\"PASS\",\"FAIL\")",
         "Net revenue by country minus net revenue in total. Rounding per country is allowed, up to 1 GBP."),
        ("Accounts never fewer than people",
         f"=SUMPRODUCT(--({col_of('Data_Monthly', 'active_subscription_accounts')}<{col_of('Data_Monthly', 'active_subscribers')}))",
         "=IF(C{r}=0,\"PASS\",\"FAIL\")",
         "Months where accounts are fewer than people. One person can have several accounts, never the reverse."),
        ("Bridge ends on the same net revenue as the KPI table",
         f"=ROUND(SUM({col_of('Data_Bridge', 'net_revenue_gbp')})-SUM({col_of('Data_Monthly', 'net_revenue_gbp')}),2)",
         "=IF(ABS(C{r})<0.01,\"PASS\",\"FAIL\")",
         "Two files, one definition of net revenue. They must agree."),
        ("Selected month is in the data", "=IF(ISNA(Summary!$K$5),1,0)", "=IF(C{r}=0,\"PASS\",\"FAIL\")",
         "The month in Summary!C5 exists on Data_Monthly."),
    ]
    for i, (label, value, result, meaning) in enumerate(checks):
        r = 7 + i
        ck.cell(row=r, column=2, value=label).font = BODY
        ck.cell(row=r, column=3, value=value).number_format = "#,##0.00"
        ck.cell(row=r, column=4, value=result.format(r=r))
        ck.cell(row=r, column=5, value=meaning).font = SMALL
        for col in range(2, 6):
            ck.cell(row=r, column=col).border = LINE
    # PASS only if every check says PASS. Counting FAILs alone would miss a check that shows an error.
    ck["C3"] = f'=IF(COUNTIF($D$7:$D${6 + len(checks)},"PASS")={len(checks)},"PASS","FAIL")'
    ck.conditional_formatting.add("D7:D40", CellIsRule(operator="equal", formula=['"PASS"'], fill=PatternFill("solid", fgColor=OK_BG)))
    ck.conditional_formatting.add("D7:D40", CellIsRule(operator="equal", formula=['"FAIL"'], fill=PatternFill("solid", fgColor=BAD_BG)))
    ck.conditional_formatting.add("C3", CellIsRule(operator="equal", formula=['"FAIL"'], fill=PatternFill("solid", fgColor=BAD_BG)))
    _width(ck, {"A": 2, "B": 52, "C": 14, "D": 9, "E": 90})

    # ------------------------------------------------------------ Definitions
    de = wb.create_sheet("Definitions")
    de.sheet_view.showGridLines = False
    de["B2"] = "Metric definitions"
    de["B2"].font = TITLE
    de["B3"] = "Copied from docs/metrics.md when the workbook was built. That file is the master copy."
    de["B3"].font = SMALL
    for j, h in enumerate(["Metric", "Definition"]):
        c = de.cell(row=5, column=2 + j, value=h)
        c.font, c.fill = BOLD, HEAD_FILL
    for i, (k, text) in enumerate(_definitions(metrics_md), start=6):
        de.cell(row=i, column=2, value=k).font = BOLD
        c = de.cell(row=i, column=3, value=text)
        c.font, c.alignment = BODY, Alignment(wrap_text=True, vertical="top")
        de.cell(row=i, column=2).alignment = Alignment(vertical="top")
    _width(de, {"A": 2, "B": 30, "C": 110})

    # --------------------------------------------------------------- Settings
    st = wb.create_sheet("Settings")
    st["B2"] = "Settings"
    st["B2"].font = TITLE
    st["B4"], st["C4"] = "Data folder", r"C:\halden-roasters-analytics\project_03_kpi_pack\data"
    st["B4"].font = BOLD
    st["B5"] = ("The folder that holds kpi_monthly.csv and the other files. Power Query reads this cell. "
                "Change it to where the repository is on your computer, then Data > Refresh All.")
    st["B5"].font = SMALL
    _width(st, {"A": 2, "B": 14, "C": 70})
    wb.defined_names["DataFolder"] = DefinedName("DataFolder", attr_text="Settings!$C$4")

    # ------------------------------------------------------------------ Data
    for sheet in ("Data_Monthly", "Data_Country", "Data_Bridge", "Data_Manifest"):
        _data_sheet(wb, sheet, frames[sheet])
    # Grows with the data: after a refresh that adds July, July is in the list without editing anything.
    wb.defined_names["MonthList"] = DefinedName(
        "MonthList", attr_text="OFFSET(Data_Monthly!$A$2,0,0,COUNTA(Data_Monthly!$A:$A)-1,1)")

    # Trend charts now that Data_Monthly exists.
    # Fixed ranges are fine here: the charts show the 30 months this copy was built with, and
    # the runbook says to rebuild the file when the history grows.
    dm = wb["Data_Monthly"]
    n = len(months) + 1
    for key, title, anchor, fmt in [("active_subscribers", "Active subscribers (people)", "B5", "#,##0"),
                                    ("net_revenue_gbp", "Net revenue, GBP", "B22", "#,##0"),
                                    ("monthly_churn_rate", "Monthly churn rate", "L5", "0.0%"),
                                    ("late_delivery_rate", "Late delivery rate", "L22", "0.0%")]:
        col = list(monthly.columns).index(key) + 1
        ch = LineChart()
        ch.title, ch.height, ch.width = title, 7.5, 16
        ch.add_data(Reference(dm, min_col=col, min_row=1, max_row=n), titles_from_data=True)
        ch.set_categories(Reference(dm, min_col=1, min_row=2, max_row=n))
        ch.legend = None
        ch.y_axis.number_format = fmt
        ch.y_axis.delete = False
        ch.x_axis.delete = False
        tr.add_chart(ch, anchor)

    # ------------------------------------------------------------------ Cover
    cover.sheet_view.showGridLines = False
    cover["B2"] = "Halden Roasters monthly KPI pack"
    cover["B2"].font = TITLE
    lines = [
        ("All data in this workbook is synthetic. Halden Roasters is a fictional company.", BOLD),
        (f"Data in this copy: {months[0]} to {months[-1]}, from the files listed on Data_Manifest.", BODY),
        ("", BODY),
        ("How to use it", H2),
        ("1. Go to Summary and choose a month in cell C5.", BODY),
        ("2. Check that Summary says \"All checks pass\". If not, do not send the pack: open Checks.", BODY),
        ("3. Trend shows the 30-month history. Definitions explains every metric.", BODY),
        ("", BODY),
        ("How it updates", H2),
        ("The Data_ sheets hold a snapshot so the file works anywhere. To make them refresh from the CSV files,",
         BODY),
        ("run the setup macro once (project_03_kpi_pack/runbook.md). After that, Data > Refresh All is the whole",
         BODY),
        ("monthly update. Nothing is typed in by hand.", BODY),
    ]
    for i, (text, font) in enumerate(lines, start=4):
        cover.cell(row=i, column=2, value=text).font = font
    _width(cover, {"A": 2, "B": 110})

    # Fixed properties, so two builds from the same data differ only in the zip timestamps.
    wb.properties.creator = "halden.kpi"
    wb.properties.created = wb.properties.modified = pd.Timestamp("2025-07-01").to_pydatetime()
    wb.calculation.fullCalcOnLoad = True   # Excel and LibreOffice calculate every formula when the file opens
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    _fix_zip_times(out)
    return out


def _fix_zip_times(path: Path) -> None:
    """An .xlsx is a zip, and openpyxl stamps each part and the file's properties with the
    time of the build. One fixed time makes two builds from the same data byte-identical, so CI
    can diff the workbook like any other committed output."""
    with zipfile.ZipFile(path) as z:
        parts = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    # Stored, not compressed, so the bytes cannot depend on the machine's zlib build. The file
    # grows from about 34 KB to 140 KB.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for name, data in parts:
            if name == "docProps/core.xml":   # openpyxl always writes the save time here
                data = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*", rb"\g<1>2025-07-01T00:00:00Z", data)
            z.writestr(zipfile.ZipInfo(name, date_time=(2025, 7, 1, 0, 0, 0)), data, zipfile.ZIP_STORED)
