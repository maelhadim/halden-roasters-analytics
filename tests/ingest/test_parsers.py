"""Parser rules on small hand-written files, one defect at a time."""
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from halden.ingest import landing
from halden.ingest.parsers import (SHOP_ORDER_COLUMNS, parse_crm, parse_experiment, parse_fulfilment, parse_payproc,
                                   parse_shop_orders)

HEADER = ",".join(SHOP_ORDER_COLUMNS)
ROW = ("1000001,{ts},C000123,{email},Anna,Smith,{phone},M1 1AA,Manchester,GB,GBP,SUBSCRIPTION,S000001,"
       "CLASSIC_250,CLASSIC_250:1,11.50,,0.00,0.00,0.00,11.50")


def shop_file(tmp_path, lines, name="shop_orders_20241027.csv"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_shop_row_is_staged_with_utc_time(tmp_path):
    p = shop_file(tmp_path, [HEADER, ROW.format(ts="2024-07-01 00:30:00", email="a@b.com", phone="0161 496 0000")])
    r = parse_shop_orders(p)
    row = r.rows[0]
    assert row["created_at_utc"] == datetime(2024, 6, 30, 23, 30, tzinfo=timezone.utc)
    assert row["order_id"] == "1000001" and row["customer_id"] == "C000123"


def test_shop_trailing_delimiter_blank_lines_and_truncated_line(tmp_path):
    good = ROW.format(ts="2024-03-18 01:00:00", email="a@b.com", phone="1") + ","
    p = shop_file(tmp_path, [HEADER + ",", good, good.replace("1000001", "1000002"), "1000003,2024-03-18 01:", "", ""])
    r = parse_shop_orders(p)
    assert len(r.rows) == 2
    assert [x["reject_reason"] for x in r.rejects] == ["field_count_mismatch"]
    assert r.blank_ignored == 2
    assert "trailing delimiter" in r.notes[0]


def test_shop_uk_date_format_excel_phone_and_messy_email(tmp_path):
    p = shop_file(tmp_path, [HEADER, ROW.format(ts="03/10/2023 00:31", email=" ANNA@B.COM", phone="4.47712E+11")])
    row = parse_shop_orders(p).rows[0]
    assert row["created_at_precision"] == "minute"
    assert row["is_phone_scientific"]
    assert row["email_norm"] == "anna@b.com" and row["email_raw"] == " ANNA@B.COM"


def test_shop_repeated_autumn_hour_is_flagged(tmp_path):
    p = shop_file(tmp_path, [HEADER, ROW.format(ts="2024-10-27 01:15:00", email="a@b.com", phone="1")])
    row = parse_shop_orders(p).rows[0]
    assert row["is_ambiguous_local_time"]


def test_shop_amounts_must_add_up(tmp_path):
    bad = ROW.format(ts="2024-07-01 10:00:00", email="a@b.com", phone="1").replace(",11.50\n", ",12.50")
    bad = bad[: bad.rfind(",")] + ",12.50"
    r = parse_shop_orders(shop_file(tmp_path, [HEADER, bad]))
    assert r.rejects[0]["reject_reason"] == "amounts_do_not_add_up"


def test_payproc_v1_v2_duplicates_and_trailer(tmp_path):
    v1 = tmp_path / "payproc_transactions_20240630.txt"
    d = "D|T1|CAPTURE|1000001|2024-06-30T10:00:00Z|GBP|21.00|0.49|2024-07-02|GB|"
    v1.write_text(f"H|20240630|v1\n{d}\n{d}\nT|1|21.00\n")
    r = parse_payproc(v1)
    assert len(r.rows) == 1 and r.rejects[0]["reject_reason"] == "duplicate_record_in_file"
    assert r.rows[0]["net_amount"] == 20.51
    assert r.control["trailer_count"] == r.control["staged_count"] == 1
    v2 = tmp_path / "payproc_transactions_20240701.txt"
    v2.write_text("H|20240701|v2\nD|T2|1000002|REFUND|2024-07-01T10:00:00Z|EUR|-24.50|0.00|-24.50|2024-07-03|DE|\n"
                  "T|1|-24.50\n")
    row = parse_payproc(v2).rows[0]
    assert (row["order_ref"], row["txn_type"], row["gross_amount"]) == ("1000002", "REFUND", -24.50)


def test_payproc_without_trailer_is_refused(tmp_path):
    p = tmp_path / "payproc_transactions_20240701.txt"
    p.write_text("H|20240701|v2\nD|T2|1000002|REFUND|2024-07-01T10:00:00Z|EUR|-24.50|0.00|-24.50|2024-07-03|DE|\n")
    with pytest.raises(ValueError, match="incomplete"):
        parse_payproc(p)


def test_fulfilment_cp1252_decimal_comma_and_german_dates(tmp_path):
    p = tmp_path / "ful_shipments_20241111.csv"
    text = ("Sendungsnr;Auftragsnr;Kundennr;Standort;Empfaenger;Land;Versanddatum;Soll_Lieferdatum;Lieferdatum;"
            "Status;Statusdatum;Gewicht_kg\r\n"
            "0000000435;1000440;000027;HAM;Jürgen Groß;DE;11.11.2024;14.11.2024;15.11.2024;ZUGESTELLT;15.11.2024;0,58\r\n")
    p.write_bytes(text.encode("cp1252"))
    row = parse_fulfilment(p).rows[0]
    assert row["recipient_name"] == "Jürgen Groß"
    assert row["weight_kg"] == 0.58 and row["delivered_date"] == date(2024, 11, 15)
    assert row["shipment_no"] == "0000000435" and row["customer_id"] == "C000027"
    assert row["status"] == "DELIVERED"


def test_crm_embedded_newline_kept_and_stray_quote_contained(tmp_path):
    cols = "customer_id\tlegacy_id\tfirst_name\tlast_name\temail\tphone\tstreet\tcity\tpostcode\tcountry_code\t" \
           "marketing_opt_in\tcreated_at\tupdated_at\tnotes"
    base = "C00000{n}\t\tAnna\tSmith\ta@b.com\t1\t1 Road\tLeeds\tLS1 1AA\tGB\tY\t2024-01-01 10:00:00\t2024-01-01 10:00:00\t"
    lines = [cols, base.format(n=1) + '"Leave in porch\nNot the bin"', base.format(n=2) + '"Says: best coffee',
             base.format(n=3) + "ok"]
    p = tmp_path / "crm_customers_20240101.txt"
    p.write_bytes(b"\xff\xfe" + "\r\n".join(lines).encode("utf-16-le") + "\r\n".encode("utf-16-le"))
    r = parse_crm(p)
    assert [x["customer_id"] for x in r.rows] == ["C000001", "C000003"]
    assert r.rows[0]["notes"] == "Leave in porch\nNot the bin"
    assert r.rejects[0]["reject_reason"] == "unbalanced_quote"


def test_experiment_duplicate_line_rejected(tmp_path):
    line = ('{"event_id":"evt_1","event_type":"assignment","experiment_id":"RET-2025-04","customer_id":"C000001",'
            '"variant":"control","event_ts":"2025-04-01T10:00:00.000Z"}')
    p = tmp_path / "exp_assignments_20250401.jsonl"
    p.write_text(line + "\n" + line + "\n")
    r = parse_experiment(p)
    assert len(r.rows) == 1 and r.rejects[0]["reject_reason"] == "duplicate_record_in_file"


def test_arrivals_flag_late_and_missing():
    inv = pd.DataFrame({"source": ["payproc", "payproc"], "entity": ["transactions"] * 2, "suffix": ["", ""],
                        "period_start": [date(2023, 1, 1), date(2023, 1, 3)],
                        "received_at_utc": [pd.Timestamp("2023-01-02 05:00", tz="UTC"),
                                            pd.Timestamp("2023-01-05 09:00", tz="UTC")]})
    a = landing.arrivals(inv, datetime(2023, 1, 6, tzinfo=timezone.utc))
    pp = a[a["source"] == "payproc"].set_index("period_start")["arrival_status"]
    assert pp[date(2023, 1, 1)] == "on_time"
    assert pp[date(2023, 1, 2)] == "missing"
    assert pp[date(2023, 1, 3)] == "late"
    assert pp[date(2023, 1, 6)] == "not_yet_due"
