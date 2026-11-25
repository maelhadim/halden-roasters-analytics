"""One parser per source entity. Each turns one raw file into staged rows and rejected rows.

Rules every parser follows:
- Every value is read as text. Types are converted here, once, with a stated rule.
- Every physical record ends up in exactly one place: staged, rejected, or (for blank
  lines only) counted as ignored. `ParseResult.check()` enforces that.
- Rows keep `_source_file` and `_source_line`, so any value traces back to its line.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc

SHOP_ORDER_COLUMNS = ["order_id", "created_at", "customer_id", "email", "first_name", "last_name", "phone",
                      "billing_postcode", "billing_city", "country_code", "currency_code", "order_type",
                      "subscription_id", "plan_code", "line_items", "subtotal_amount", "discount_code",
                      "discount_amount", "shipping_amount", "vat_amount", "total_amount"]
SUBS_EVENT_COLUMNS = ["event_id", "event_at", "subscription_id", "customer_id", "event_type", "plan_code",
                      "frequency", "cancel_reason"]
SUBS_SNAPSHOT_COLUMNS = ["subscription_id", "customer_id", "status", "plan_code", "frequency", "started_at"]
PAYPROC_V1 = ["txn_id", "txn_type", "order_ref", "txn_at_utc", "currency_code", "gross_amount", "fee_amount",
              "settlement_date", "card_country", "decline_code"]
PAYPROC_V2 = ["txn_id", "order_ref", "txn_type", "txn_at_utc", "currency_code", "gross_amount", "fee_amount",
              "net_amount", "settlement_date", "card_country", "decline_code"]
FUL_RENAME = {"Sendungsnr": "shipment_no", "Auftragsnr": "order_id", "Kundennr": "partner_customer_no",
              "Standort": "site_code", "Empfaenger": "recipient_name", "Land": "country_code",
              "Versanddatum": "dispatch_date", "Soll_Lieferdatum": "promised_date", "Lieferdatum": "delivered_date",
              "Status": "status_de", "Statusdatum": "status_date", "Gewicht_kg": "weight_kg"}
FUL_STATUS = {"VERSANDT": "DISPATCHED", "ZUGESTELLT": "DELIVERED", "VERLOREN": "LOST"}
CRM_COLUMNS = ["customer_id", "legacy_id", "first_name", "last_name", "email", "phone", "street", "city",
               "postcode", "country_code", "marketing_opt_in", "created_at", "updated_at", "notes"]

RE_ORDER_ID = re.compile(r"^\d{7}$")
RE_CUSTOMER_ID = re.compile(r"^C\d{6}$")
RE_MONEY = re.compile(r"^-?\d+\.\d{2}$")
RE_SCI = re.compile(r"^\d\.\d+E\+\d+$")


class Reject(Exception):
    """A record that cannot be staged. The message is the reject reason code."""


@dataclass
class ParseResult:
    source_file: str
    rows: list[dict] = field(default_factory=list)
    rejects: list[dict] = field(default_factory=list)
    records_read: int = 0
    blank_ignored: int = 0
    notes: list[str] = field(default_factory=list)
    control: dict = field(default_factory=dict)

    def reject(self, line_no: int, raw: str, reason: str):
        self.rejects.append({"_source_file": self.source_file, "_source_line": line_no,
                             "raw_record": raw, "reject_reason": reason})

    def check(self):
        if self.records_read != len(self.rows) + len(self.rejects) + self.blank_ignored:
            raise AssertionError(f"{self.source_file}: {self.records_read} read != {len(self.rows)} staged + "
                                 f"{len(self.rejects)} rejected + {self.blank_ignored} blank")
        return self


# ------------------------------------------------------------------ helpers
def london_to_utc(local: datetime) -> tuple[datetime, bool]:
    """Return (UTC instant, is_ambiguous). Ambiguous times take the first (summer-time) instant;
    the caller is expected to correct them from a better source where one exists."""
    a = local.replace(tzinfo=LONDON, fold=0)
    b = local.replace(tzinfo=LONDON, fold=1)
    return a.astimezone(UTC), a.utcoffset() != b.utcoffset()


def parse_shop_time(value: str) -> tuple[datetime, str]:
    """The shop normally writes ISO; one platform update and one Excel re-save wrote UK format
    without seconds. Both are London wall-clock time."""
    for fmt, precision in (("%Y-%m-%d %H:%M:%S", "second"), ("%d/%m/%Y %H:%M", "minute")):
        try:
            return datetime.strptime(value, fmt), precision
        except ValueError:
            pass
    raise Reject("invalid_timestamp")


def money(value: str) -> float:
    if not RE_MONEY.match(value):
        raise Reject("invalid_amount")
    return float(value)


def de_date(value: str):
    if value == "":
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        raise Reject("invalid_date")


def csv_records(text: str, delimiter: str):
    """Yield (line_no, fields, raw) per CSV record, line_no being the physical line it starts on."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    prev_line = 0
    for fields in reader:
        start = prev_line + 1
        prev_line = reader.line_num
        yield start, fields, delimiter.join(fields)


# --------------------------------------------------------------- shop orders
def parse_shop_orders(path: Path) -> ParseResult:
    res = ParseResult(path.name)
    text = path.read_bytes().decode("utf-8")
    records = list(csv_records(text, ","))
    header = records[0][1]
    trailing = header[-1] == "" and header[:-1] == SHOP_ORDER_COLUMNS
    if trailing:
        res.notes.append("trailing delimiter on every line; empty last column dropped")
    elif header != SHOP_ORDER_COLUMNS:
        raise ValueError(f"{path.name}: unexpected header {header}")
    for line_no, fields, raw in records[1:]:
        res.records_read += 1
        if not fields or all(f == "" for f in fields):
            res.blank_ignored += 1
            continue
        if trailing and len(fields) == 22 and fields[-1] == "":
            fields = fields[:-1]
        if len(fields) != 21:
            res.reject(line_no, raw, "field_count_mismatch")
            continue
        r = dict(zip(SHOP_ORDER_COLUMNS, fields))
        try:
            if not RE_ORDER_ID.match(r["order_id"]):
                raise Reject("invalid_order_id")
            if r["customer_id"] and not RE_CUSTOMER_ID.match(r["customer_id"]):
                raise Reject("invalid_customer_id")
            local, precision = parse_shop_time(r["created_at"])
            utc, ambiguous = london_to_utc(local)
            amounts = {k: money(r[k]) for k in ("subtotal_amount", "discount_amount", "shipping_amount",
                                                "vat_amount", "total_amount")}
            if round(amounts["subtotal_amount"] - amounts["discount_amount"] + amounts["shipping_amount"], 2) \
                    != amounts["total_amount"]:
                raise Reject("amounts_do_not_add_up")
            if r["currency_code"] not in ("GBP", "EUR"):
                raise Reject("invalid_currency")
        except Reject as e:
            res.reject(line_no, raw, str(e))
            continue
        email_norm = r["email"].strip().lower()
        res.rows.append({
            "order_id": r["order_id"], "created_at_local": local, "created_at_utc": utc,
            "created_at_precision": precision, "is_ambiguous_local_time": ambiguous,
            "customer_id": r["customer_id"] or None, "email_raw": r["email"], "email_norm": email_norm,
            "first_name": r["first_name"], "last_name": r["last_name"], "phone_raw": r["phone"],
            "is_phone_scientific": bool(RE_SCI.match(r["phone"])),
            "billing_postcode": r["billing_postcode"] or None, "billing_city": r["billing_city"],
            "country_code": r["country_code"], "currency_code": r["currency_code"],
            "order_type": r["order_type"], "subscription_id": r["subscription_id"] or None,
            "plan_code": r["plan_code"] or None, "line_items": r["line_items"],
            "discount_code": r["discount_code"] or None, **amounts,
            "is_test": email_norm.endswith("@haldenroasters.test"),
            "_source_file": path.name, "_source_line": line_no,
        })
    return res.check()


# ------------------------------------------------------- shop subscriptions
def parse_shop_subscriptions(path: Path) -> ParseResult:
    res = ParseResult(path.name)
    records = list(csv_records(path.read_bytes().decode("utf-8"), ","))
    header = records[0][1]
    snapshot = header == SUBS_SNAPSHOT_COLUMNS
    if not snapshot and header != SUBS_EVENT_COLUMNS:
        raise ValueError(f"{path.name}: unexpected header {header}")
    file_date = datetime.strptime(path.name.split("_")[2][:8], "%Y%m%d").date()
    for line_no, fields, raw in records[1:]:
        res.records_read += 1
        if not fields:
            res.blank_ignored += 1
            continue
        cols = SUBS_SNAPSHOT_COLUMNS if snapshot else SUBS_EVENT_COLUMNS
        if len(fields) != len(cols):
            res.reject(line_no, raw, "field_count_mismatch")
            continue
        r = dict(zip(cols, fields))
        try:
            local, _ = parse_shop_time(r["started_at" if snapshot else "event_at"])
        except Reject as e:
            res.reject(line_no, raw, str(e))
            continue
        utc, ambiguous = london_to_utc(local)
        row = {"subscription_id": r["subscription_id"], "customer_id": r["customer_id"],
               "plan_code": r["plan_code"], "frequency": r["frequency"],
               "_source_file": path.name, "_source_line": line_no}
        if snapshot:
            row.update({"record_type": "SNAPSHOT", "event_id": None, "event_type": "ACTIVE_AT_SNAPSHOT",
                        "event_at_utc": utc, "cancel_reason": None, "is_late_event": False})
        else:
            row.update({"record_type": "EVENT", "event_id": r["event_id"], "event_type": r["event_type"],
                        "event_at_utc": utc, "cancel_reason": r["cancel_reason"] or None,
                        "is_late_event": local.date() < file_date})
        row["is_ambiguous_local_time"] = ambiguous
        res.rows.append(row)
    return res.check()


# ------------------------------------------------------------------ payproc
def parse_payproc(path: Path) -> ParseResult:
    res = ParseResult(path.name)
    lines = path.read_bytes().decode("ascii").splitlines()
    header = lines[0].split("|")
    if header[0] != "H" or header[2] not in ("v1", "v2"):
        raise ValueError(f"{path.name}: bad header record {lines[0]}")
    version = header[2]
    cols = PAYPROC_V1 if version == "v1" else PAYPROC_V2
    trailer = lines[-1].split("|")
    if trailer[0] != "T":
        raise ValueError(f"{path.name}: no trailer record; file is incomplete")
    file_date = datetime.strptime(header[1], "%Y%m%d").date()
    seen: set[str] = set()
    for i, ln in enumerate(lines[1:-1], start=2):
        res.records_read += 1
        parts = ln.split("|")
        if parts[0] != "D" or len(parts) != len(cols) + 1:
            res.reject(i, ln, "field_count_mismatch")
            continue
        if ln in seen:
            # An exact repeat of a line already in this file. The trailer counts it once, so do we.
            res.reject(i, ln, "duplicate_record_in_file")
            continue
        seen.add(ln)
        r = dict(zip(cols, parts[1:]))
        try:
            gross, fee = money(r["gross_amount"]), money(r["fee_amount"])
            net = money(r["net_amount"]) if version == "v2" else round(gross - fee, 2)
            ts = datetime.strptime(r["txn_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except (Reject, ValueError) as e:
            res.reject(i, ln, str(e) if isinstance(e, Reject) else "invalid_timestamp")
            continue
        res.rows.append({
            "txn_id": r["txn_id"], "order_ref": r["order_ref"], "txn_type": r["txn_type"], "txn_at_utc": ts,
            "currency_code": r["currency_code"], "gross_amount": gross, "fee_amount": fee, "net_amount": net,
            "settlement_date": r["settlement_date"] or None, "card_country": r["card_country"],
            "decline_code": r["decline_code"] or None, "schema_version": version,
            "is_off_file_date": ts.date() != file_date,
            "_source_file": path.name, "_source_line": i,
        })
    res.control = {"trailer_count": int(trailer[1]), "trailer_gross": float(trailer[2]),
                   "staged_count": len(res.rows),
                   "staged_gross": round(sum(r["gross_amount"] for r in res.rows), 2),
                   "schema_version": version}
    return res.check()


# ----------------------------------------------------------------- fulfilment
def parse_fulfilment(path: Path) -> ParseResult:
    res = ParseResult(path.name)
    # The partner writes Windows-1252. Decoding as UTF-8 either fails or, worse, succeeds on
    # files that happen to be ASCII and then fails on the next one.
    text = path.read_bytes().decode("cp1252")
    records = list(csv_records(text, ";"))
    header = records[0][1]
    if header != list(FUL_RENAME):
        raise ValueError(f"{path.name}: unexpected header {header}")
    for line_no, fields, raw in records[1:]:
        res.records_read += 1
        if not fields:
            res.blank_ignored += 1
            continue
        if len(fields) != len(header):
            res.reject(line_no, raw, "field_count_mismatch")
            continue
        r = {FUL_RENAME[k]: v for k, v in zip(header, fields)}
        try:
            if r["status_de"] not in FUL_STATUS:
                raise Reject("unknown_status")
            weight = float(r["weight_kg"].replace(",", "."))
            dates = {k: de_date(r[k]) for k in ("dispatch_date", "promised_date", "delivered_date", "status_date")}
        except (Reject, ValueError) as e:
            res.reject(line_no, raw, str(e) if isinstance(e, Reject) else "invalid_number")
            continue
        no = r["partner_customer_no"]
        res.rows.append({
            "shipment_no": r["shipment_no"], "order_id": r["order_id"],
            "customer_id": f"C{no}" if no else None, "site_code": r["site_code"],
            "recipient_name": r["recipient_name"], "has_replacement_char": "?" in r["recipient_name"],
            "country_code": r["country_code"], "status": FUL_STATUS[r["status_de"]], **dates,
            "weight_kg": weight, "_source_file": path.name, "_source_line": line_no,
        })
    return res.check()


# ------------------------------------------------------------------------ crm
def parse_crm(path: Path) -> ParseResult:
    res = ParseResult(path.name)
    data = path.read_bytes()
    if not data.startswith(b"\xff\xfe"):
        raise ValueError(f"{path.name}: expected a UTF-16 LE byte-order mark")
    text = data[2:].decode("utf-16-le")
    # Excel ends rows with CRLF and writes a bare LF for a line break inside a cell. Splitting on
    # CRLF first means one malformed record can never swallow the records after it.
    chunks = text.split("\r\n")
    if chunks[-1] == "":
        chunks = chunks[:-1]
    header = chunks[0].split("\t")
    if header != CRM_COLUMNS:
        raise ValueError(f"{path.name}: unexpected header {header}")
    line_no = 1
    for chunk in chunks[1:]:
        line_no += 1
        res.records_read += 1
        start = line_no
        line_no += chunk.count("\n")
        try:
            fields = next(csv.reader([chunk], delimiter="\t", strict=True))
        except (csv.Error, StopIteration):
            res.reject(start, chunk, "unbalanced_quote")
            continue
        if chunk.count('"') % 2:
            res.reject(start, chunk, "unbalanced_quote")
            continue
        if len(fields) != len(CRM_COLUMNS):
            res.reject(start, chunk, "field_count_mismatch")
            continue
        r = dict(zip(CRM_COLUMNS, fields))
        try:
            if not RE_CUSTOMER_ID.match(r["customer_id"]):
                raise Reject("invalid_customer_id")
            created = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            updated = datetime.strptime(r["updated_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except Reject as e:
            res.reject(start, chunk, str(e))
            continue
        except ValueError:
            res.reject(start, chunk, "invalid_timestamp")
            continue
        res.rows.append({**{k: r[k] or None for k in CRM_COLUMNS if k not in ("created_at", "updated_at")},
                         "email_norm": r["email"].strip().lower(),
                         "created_at_utc": created, "updated_at_utc": updated,
                         "is_snapshot": "_full" in path.name,
                         "_source_file": path.name, "_source_line": start})
    return res.check()


# ------------------------------------------------------------------ experiment
def parse_experiment(path: Path) -> ParseResult:
    res = ParseResult(path.name)
    seen: set[str] = set()
    for i, ln in enumerate(path.read_bytes().decode("utf-8").splitlines(), start=1):
        res.records_read += 1
        if not ln.strip():
            res.blank_ignored += 1
            continue
        if ln in seen:
            res.reject(i, ln, "duplicate_record_in_file")
            continue
        seen.add(ln)
        try:
            e = json.loads(ln)
            ts = datetime.strptime(e["event_ts"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
            if not RE_CUSTOMER_ID.match(e["customer_id"]) or e["variant"] not in ("control", "treatment"):
                raise ValueError
        except (ValueError, KeyError):
            res.reject(i, ln, "invalid_event")
            continue
        res.rows.append({"event_id": e["event_id"], "experiment_id": e["experiment_id"],
                         "customer_id": e["customer_id"], "variant": e["variant"], "event_at_utc": ts,
                         "_source_file": path.name, "_source_line": i})
    return res.check()


# ------------------------------------------------------------------------- fx
def parse_fx(path: Path) -> ParseResult:
    res = ParseResult(path.name)
    records = list(csv_records(path.read_bytes().decode("utf-8"), ","))
    if records[0][1] != ["rate_date", "base_currency", "quote_currency", "rate"]:
        raise ValueError(f"{path.name}: unexpected header")
    for line_no, f, raw in records[1:]:
        res.records_read += 1
        try:
            d = datetime.strptime(f[0], "%Y-%m-%d").date()
            rate = float(f[3])
            if (f[1], f[2]) != ("EUR", "GBP") or not 0.5 < rate < 1.5:
                raise ValueError
        except (ValueError, IndexError):
            res.reject(line_no, raw, "invalid_rate")
            continue
        res.rows.append({"rate_date": d, "gbp_per_eur": rate, "_source_file": path.name, "_source_line": line_no})
    return res.check()


PARSERS = {
    ("shop", "orders"): ("stg_shop_orders", parse_shop_orders),
    ("shop", "subscriptions"): ("stg_shop_subscription_events", parse_shop_subscriptions),
    ("payproc", "transactions"): ("stg_payproc_transactions", parse_payproc),
    ("ful", "shipments"): ("stg_ful_shipment_events", parse_fulfilment),
    ("crm", "customers"): ("stg_crm_customer_versions", parse_crm),
    ("exp", "assignments"): ("stg_exp_assignments", parse_experiment),
    ("fx", "eurgbp"): ("stg_fx_rates", parse_fx),
}


def to_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)
