"""Project 3: the monthly KPI pack.

openpyxl writes its XML with lxml when lxml is installed and with the standard library when
it is not, and the two put different bytes in the workbook (`"/>` against `" />`). Turning
lxml off here, before openpyxl is imported, makes the workbook the same on every machine.
"""
import os

os.environ["OPENPYXL_LXML"] = "False"
