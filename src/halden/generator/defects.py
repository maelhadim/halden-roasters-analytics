"""The defect manifest: every problem the exporters put into the raw files, on purpose.

Pipelines must never read this. It exists so validation can prove that each
defect was caught, and so nobody can claim a clean result by accident.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# code -> (source, what it looks like in the raw file, what a correct pipeline should do)
CATALOGUE = {
    "SHOP_TRUNCATED_FILE": ("shop", "Export stopped mid-file; last line cut off part-way",
                            "Reject the partial line; take the day from the resend"),
    "SHOP_RESEND": ("shop", "Same business day sent again as *_resend.csv, CRLF line endings",
                    "Load each order once; resend wins on overlap"),
    "SHOP_DATE_FORMAT": ("shop", "created_at as DD/MM/YYYY HH:MM (Excel re-save, Oct 2023; platform update, Feb 2024)",
                         "Parse both formats; seconds are lost for these rows"),
    "SHOP_PHONE_SCIENTIFIC": ("shop", "File opened and re-saved in Excel: phone shows as 4.47712E+11",
                              "Flag; the original digits cannot be recovered from this file"),
    "SHOP_MISSING_POSTCODE": ("shop", "billing_postcode blank", "Keep the row; flag the missing value"),
    "SHOP_TEST_ORDER": ("shop", "QA order with a @haldenroasters.test address",
                        "Exclude from all business metrics"),
    "SHOP_AMBIGUOUS_LOCAL_TIME": ("shop", "London time inside the repeated hour when clocks go back",
                                  "Resolve with the processor's UTC timestamp or flag"),
    "SHOP_EMAIL_FORMATTING": ("shop", "Email with capitals or surrounding spaces",
                              "Trim and lower-case for matching; keep the original"),
    "SHOP_TRAILING_DELIMITER": ("shop", "Every line ends with an extra comma (export plugin bug)",
                                "Drop the empty trailing column"),
    "SHOP_BLANK_LINES": ("shop", "Blank lines at the end of the file", "Ignore"),
    "SUBS_LATE_EVENT": ("shop", "Cancellation appears in the next day's subscription file",
                        "Use event_at, not the file date"),
    "SUBS_REASON_QUOTED": ("shop", "Free-text cancel_reason containing commas and quotes",
                           "Parse with proper CSV quoting"),
    "PAYPROC_DUPLICATE_ROW": ("payproc", "Same transaction row twice in one file; trailer counts it once",
                              "Deduplicate on txn_id; trailer check exposes it"),
    "PAYPROC_MISSING_DAY": ("payproc", "No file for a day; its rows arrive inside the next day's file",
                            "Detect the gap; do not double count when the rows appear"),
    "PAYPROC_LATE_FILE": ("payproc", "File received more than 24 hours after the 06:00 UTC deadline",
                          "Load it on the next run; report the day as late"),
    "PAYPROC_SCHEMA_CHANGE": ("payproc", "From 2024-07-01, schema v2: columns reordered, net_amount added",
                              "Read the schema version from the header record"),
    "PAYPROC_UNLINKED_REFUND": ("payproc", "Refund against an order from the pre-2023 shop",
                                "Count as revenue loss; it cannot be linked to an order"),
    "FUL_ENCODING_CP1252": ("ful", "Windows-1252 file; reading as UTF-8 corrupts umlauts",
                            "Decode as cp1252"),
    "FUL_UNMAPPABLE_CHAR": ("ful", "Character outside Windows-1252 replaced by '?' by the partner",
                            "Flag; take the name from the CRM instead"),
    "FUL_CORRECTED_FILE": ("ful", "Week re-sent as *_v2.csv; v1 had wrong delivery dates and weights",
                           "v2 replaces v1 for the whole week"),
    "FUL_DUPLICATE_EVENT": ("ful", "Delivery event repeated in the following week's file",
                            "Keep one status event per shipment and status"),
    "FUL_LATE_FILE": ("ful", "Weekly file received days late over Christmas", "Load on arrival; report"),
    "CRM_DUPLICATE_PERSON": ("crm", "One person, more than one customer_id",
                             "Resolve in project 2; never merge on name alone"),
    "CRM_EMBEDDED_NEWLINE": ("crm", "Quoted notes field containing a line break or tab",
                             "Parse with quoting; the record is one row"),
    "CRM_STRAY_QUOTE": ("crm", "Notes field opens a quote that never closes",
                        "Reject the row with the reason; do not let it swallow the next rows"),
    "EXP_LOG_OUTAGE": ("exp", "Assignment events lost for part of the treatment group, 9 to 11 April 2025",
                       "Detect the sample ratio mismatch; recover exposure from RET30 orders"),
    "EXP_DUPLICATE_EVENT": ("exp", "Same assignment event logged twice", "Deduplicate"),
    "EXP_PERSON_BOTH_ARMS": ("exp", "One person with two accounts sits in both arms",
                             "Exclude or analyse at person level"),
}


@dataclass
class DefectLog:
    rows: list = field(default_factory=list)

    def add(self, code: str, file_name: str, record_key: str, detail: str = ""):
        if code not in CATALOGUE:
            raise KeyError(f"unknown defect code {code}")
        self.rows.append({"defect_code": code, "source": CATALOGUE[code][0], "file_name": file_name,
                          "record_key": record_key, "detail": detail})

    def frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.rows, columns=["defect_code", "source", "file_name", "record_key", "detail"])
        return df.sort_values(["source", "defect_code", "file_name", "record_key"], kind="stable")


def catalogue_frame() -> pd.DataFrame:
    return pd.DataFrame([{"defect_code": k, "source": v[0], "symptom": v[1], "expected_handling": v[2]}
                         for k, v in CATALOGUE.items()])
