from datetime import date

import numpy as np
import pytest

from halden.generator.calendar import (add_business_days, add_months, easter_sunday, london_local_to_utc,
                                       utc_to_london_naive)
from halden.generator.defects import CATALOGUE, DefectLog
from halden.generator.export import _is_ambiguous
from halden.generator.identities import PersonFactory, ascii_fold


def test_monthly_billing_caps_at_28():
    assert add_months(date(2024, 1, 31), 1, 31) == date(2024, 2, 28)
    assert add_months(date(2024, 1, 31), 2, 31) == date(2024, 3, 28)
    assert add_months(date(2024, 11, 15), 2, 15) == date(2025, 1, 15)


def test_business_days_skip_weekends():
    assert add_business_days(date(2024, 3, 1), 2) == date(2024, 3, 5)   # Friday + 2 = Tuesday
    assert add_business_days(date(2024, 3, 4), 1) == date(2024, 3, 5)


@pytest.mark.parametrize("year,expected", [(2023, date(2023, 4, 9)), (2024, date(2024, 3, 31)),
                                           (2025, date(2025, 4, 20))])
def test_easter(year, expected):
    assert easter_sunday(year) == expected


def test_london_summer_time_moves_into_previous_utc_day():
    # 00:30 on 1 July in London is 23:30 on 30 June in UTC: the root of the month-end mismatch.
    ts = london_local_to_utc(date(2024, 7, 1), 0, 30, 0)
    assert (ts.day, ts.hour, ts.minute) == (30, 23, 30)


def test_repeated_hour_is_ambiguous():
    local = utc_to_london_naive(london_local_to_utc(date(2024, 10, 27), 1, 15, 0))
    assert _is_ambiguous(local)
    assert not _is_ambiguous(utc_to_london_naive(london_local_to_utc(date(2024, 10, 28), 1, 15, 0)))


def test_ascii_fold_writes_out_umlauts():
    assert ascii_fold("Müller-Groß") == "Mueller-Gross"


def test_person_factory_is_deterministic():
    a = PersonFactory(np.random.default_rng(1), 1).new_person("DE")
    b = PersonFactory(np.random.default_rng(1), 1).new_person("DE")
    assert a == b


def test_defect_log_rejects_unknown_codes():
    log = DefectLog()
    with pytest.raises(KeyError):
        log.add("NOT_A_DEFECT", "f", "k")


def test_catalogue_entries_are_complete():
    for code, (source, symptom, handling) in CATALOGUE.items():
        assert source in {"shop", "payproc", "ful", "crm", "exp"}, code
        assert symptom and handling, code
