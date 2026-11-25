"""The landing zone: which files arrived, when, and which ones we expected but did not get."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

UTC = timezone.utc
NAME = re.compile(r"^(?P<source>[a-z]+)_(?P<entity>[a-z]+)_(?P<date>\d{8})(?:_(?P<suffix>[a-z0-9]+))?\.\w+$")

# The business calendar we expect each feed to follow. These are agreements with the
# suppliers, not something read from the data.
WINDOW = (date(2023, 1, 1), date(2025, 6, 30))


@dataclass(frozen=True)
class Feed:
    source: str
    entity: str
    cadence: str          # daily | weekly | monthly | adhoc
    due_days: int         # days after the period ends
    due_hour: int         # UTC hour on that day


FEEDS = (
    Feed("shop", "orders", "daily", 1, 6),
    Feed("shop", "subscriptions", "daily", 1, 6),
    Feed("payproc", "transactions", "daily", 1, 6),
    Feed("ful", "shipments", "weekly", 2, 12),     # Tuesday after the week ends
    Feed("crm", "customers", "monthly", 1, 12),
    Feed("fx", "eurgbp", "monthly", 1, 18),
    Feed("exp", "assignments", "adhoc", 1, 6),     # only while an experiment runs
)
FEED_BY_KEY = {(f.source, f.entity): f for f in FEEDS}


def inventory(raw: Path, as_of: datetime | None = None) -> pd.DataFrame:
    """Every landed file the pipeline is allowed to see, from the landing log.

    `as_of` replays history: files received after it are treated as not yet arrived.
    """
    log = pd.read_csv(raw / "_landing_log.csv", dtype=str)
    log["received_at_utc"] = pd.to_datetime(log["received_at_utc"], utc=True)
    parts = log["file_name"].str.extract(NAME)
    if parts["source"].isna().any():
        bad = log.loc[parts["source"].isna(), "file_name"].tolist()
        raise ValueError(f"file names outside the convention: {bad}")
    log = pd.concat([log, parts[["entity", "suffix"]]], axis=1)
    log["period_start"] = pd.to_datetime(parts["date"], format="%Y%m%d").dt.date
    log["suffix"] = log["suffix"].fillna("")
    log["path"] = [str(raw / s / f) for s, f in zip(log["source"], log["file_name"])]
    if as_of is not None:
        log = log[log["received_at_utc"] <= pd.Timestamp(as_of)]
    missing = [p for p in log["path"] if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(f"landing log lists files that are not on disk: {missing[:5]}")
    return log.sort_values(["source", "entity", "period_start", "received_at_utc"]).reset_index(drop=True)


def _periods(feed: Feed) -> list[tuple[date, date]]:
    """(period start, period end) pairs the feed should cover inside the window."""
    out = []
    if feed.cadence == "daily":
        d = WINDOW[0]
        while d <= WINDOW[1]:
            out.append((d, d))
            d += timedelta(days=1)
    elif feed.cadence == "weekly":
        # The first Monday inside the window. The week of 26 December 2022 contains only
        # 1 January 2023, a Sunday, when nothing ships.
        d = WINDOW[0] + timedelta(days=(7 - WINDOW[0].weekday()) % 7)
        while d <= WINDOW[1]:
            out.append((d, d + timedelta(days=6)))
            d += timedelta(days=7)
    elif feed.cadence == "monthly":
        d = date(WINDOW[0].year, WINDOW[0].month, 1)
        while d <= WINDOW[1]:
            nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            out.append((d, nxt - timedelta(days=1)))
            d = nxt
    return out


def arrivals(inv: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """One row per expected file: on time, late, missing, or not yet due.

    CRM deltas start after the March 2023 migration and FX history starts in December 2022,
    so those feeds use the first file actually received as their start.
    """
    rows = []
    for feed in FEEDS:
        if feed.cadence == "adhoc":
            continue
        got = inv[(inv["source"] == feed.source) & (inv["entity"] == feed.entity) & (inv["suffix"] == "")]
        first = got["period_start"].min() if feed.source in ("crm", "fx") and len(got) else None
        by_start = got.groupby("period_start")["received_at_utc"].min()
        for start, end in _periods(feed):
            if first is not None and start < date(first.year, first.month, 1):
                continue
            due = datetime.combine(end + timedelta(days=feed.due_days), time(feed.due_hour), UTC)
            received = by_start.get(start)
            if feed.source == "crm" and start == date(2023, 3, 1):
                # March 2023 is covered by the migration snapshot and the 14-31 March delta.
                received = by_start.get(date(2023, 3, 14))
            if received is None:
                status = "not_yet_due" if due > as_of else "missing"
            else:
                status = "on_time" if received <= due else "late"
            rows.append({"source": feed.source, "entity": feed.entity, "period_start": start, "period_end": end,
                         "due_at_utc": due, "received_at_utc": received, "arrival_status": status,
                         "hours_late": round((received - due).total_seconds() / 3600, 1)
                         if status == "late" else None})
    return pd.DataFrame(rows)
