"""Date helpers shared by the simulation and the exporters."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")


def add_months(d: date, months: int, anchor_day: int) -> date:
    """Monthly billing keeps the original day of the month, capped at 28.

    Capping at 28 is what most subscription platforms do, and it avoids the
    31 January -> 28 February -> 28 March drift.
    """
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(anchor_day, 28))


def is_business_day(d: date) -> bool:
    return d.weekday() < 5


def add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining:
        d += timedelta(days=step)
        if is_business_day(d):
            remaining -= 1
    return d


def next_business_day(d: date) -> date:
    return add_business_days(d, 1)


def easter_sunday(year: int) -> date:
    # Anonymous Gregorian algorithm (Meeus/Jones/Butcher).
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def target_holidays(year: int) -> set[date]:
    """Days with no euro reference rate: TARGET2 closing days."""
    easter = easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        date(year, 5, 1),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def london_local_to_utc(d: date, hour: int, minute: int, second: int) -> datetime:
    """Interpret a London wall-clock time and return the UTC instant.

    Times inside the spring-forward gap are shifted by zoneinfo, which is what
    the shop's scheduler does too: it never emits a wall-clock time that did
    not exist.
    """
    local = datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=LONDON)
    return local.astimezone(UTC)


def utc_to_london_naive(ts: datetime) -> datetime:
    return ts.astimezone(LONDON).replace(tzinfo=None)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
