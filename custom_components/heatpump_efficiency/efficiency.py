"""Pure arithmetic for the heat pump efficiency integration.

Standard library only: nothing here imports Home Assistant. The time zone and
"now" are always passed in, and every datetime argument must be timezone aware
(a naive one raises ValueError).

Input contract. Rows mirror what Home Assistant's ``statistics_during_period``
returns: dicts with ``start`` and ``end`` as float epoch seconds and ``change``
(float or None). The coordinator always asks for ``units={"energy": "kWh"}``,
so every ``change`` arrives in kWh already (a statistic recorded as 2500 Wh
arrives as 2.5). This module does no unit conversion. A statistic without rows
is absent from the result.

Tables. Rows are grouped by the table (source) they were read from, named
after the ``period`` argument of the read: ``"month"``, ``"day"``, ``"hour"``
and ``"5minute"``. Each read is kept as a ``TableRead``: the UTC window it was
read for, its rows (None when the read failed), which statistics it covers and
when it was made. ``tables`` is ``{source: TableRead}``.

Statistics days. Home Assistant's hourly rows start on whole UTC hours and are
grouped into day and month rows by the local date of their start
(``recorder/statistics.py`` ``reduce_day_ts_factory``,
``reduce_month_ts_factory``). So a day starts at the first whole UTC hour at or
after local midnight: local midnight in whole-hour time zones, 00:30 in
Asia/Kolkata, and the first existing instant (01:00) on a day whose local
midnight does not exist, such as 6 September 2026 in America/Santiago. Today is
the day that contains now; a month and a year start at the day start of their
1st.

Typical update (the coordinator is glue around these functions):

1. Read the metadata (every update), then ``cache_actions`` says what to
   read. When it asks for first hours, read them, recompute
   ``effective_start`` per service and the needed windows
   (``history_windows``) and call ``cache_actions`` again.
2. Read the ``5minute`` (and ``hour``) table first, then ``last_row_ends``;
   read each history table it asks for over its needed window and store it as
   ``TableRead`` with ``coverage`` from those last row ends.
3. Per service: ``reads_hourly``, ``coverage_end``, ``period_ranges``, ``period_summary``,
   ``period_starts``, ``includes_estimated``, ``daily_series`` and
   ``monthly_series``; per statistic ``health``. Use one ``now`` throughout.
   With defrost statistics (a correction: they join the reads but never the
   effective start) also ``defrost_start`` of their first hours (the end of the
   latest one), the ``defrost_ids`` and ``defrost_firsts`` (first hour and
   baseline, so a counter counts from the end of its first hour whatever its
   first sum is) of ``period_summary`` and the series (``corrected_ratio``) and
   ``defrost_partial`` of a covered start.
"""

from __future__ import annotations

import calendar
import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from functools import cached_property, lru_cache
from typing import Any

UTC = timezone.utc
HOUR_SECONDS = 3600

MIN_ELECTRICAL_KWH = 0.1  # below this the ratio is unknown
BTU_PER_WH = 3.412142  # BTU/Wh per W/W: 1 W = 3.412142 BTU/h (International Table BTU)
DAILY_POINTS = 31  # days in the daily series, today included
MONTHLY_POINTS = 24  # calendar months in the monthly series, current included
STALE_AFTER = timedelta(hours=2)  # a last row that ended longer ago than this is stale
STALENESS_WINDOW = timedelta(hours=3)  # how far back the 5-minute and hour reads look

SOURCE_MONTH = "month"
SOURCE_DAY = "day"
SOURCE_HOUR = "hour"
SOURCE_5MINUTE = "5minute"
HISTORY_SOURCES = (SOURCE_MONTH, SOURCE_DAY)  # completed history, cached between updates

RECORDER = "recorder"  # metadata source of statistics compiled by the recorder

PERIOD_TODAY = "today"
PERIOD_MONTH_TO_DATE = "month_to_date"
PERIOD_YEAR_TO_DATE = "year_to_date"
PERIOD_ROLLING_12_MONTHS = "rolling_12_months"
PERIODS = (
    PERIOD_TODAY,
    PERIOD_MONTH_TO_DATE,
    PERIOD_YEAR_TO_DATE,
    PERIOD_ROLLING_12_MONTHS,
)

HEALTH_OK = "ok"
HEALTH_MISSING = "missing"
HEALTH_NOT_ENERGY = "not_energy"
HEALTH_NO_SUM = "no_sum"
HEALTH_STALE = "stale"

# An end before every possible period: a service whose coverage is unknown.
NO_COVERAGE = datetime(1970, 1, 1, tzinfo=UTC)

Row = Mapping[str, Any]
Instant = datetime | float | int
# A defrost statistic's first statistics hour and its baseline (design D12): the ``change`` of
# its first hourly row, which Home Assistant computes against a previous sum of 0.
DefrostFirst = tuple[Instant, float]
DefrostFirsts = Mapping[str, DefrostFirst]


# --- time helpers ---------------------------------------------------------


def aware(value: Instant, name: str = "datetime") -> datetime:
    """A datetime argument checked to be timezone aware; epoch seconds become UTC."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone aware")
        return value
    return datetime.fromtimestamp(value, UTC)


def ts(value: Instant, name: str = "datetime") -> float:
    """Epoch seconds of an aware datetime or of epoch seconds."""
    if isinstance(value, datetime):
        return aware(value, name).timestamp()
    return float(value)


def _ceil_hour(ts: float) -> float:
    """The first whole UTC hour at or after ``ts`` (epoch seconds)."""
    return float(math.ceil(ts / HOUR_SECONDS) * HOUR_SECONDS)


@lru_cache(maxsize=4096)
def _day_start_ts(day: date, tz: tzinfo) -> float:
    """Epoch seconds at which the statistics day ``day`` starts.

    Inputs: the local date and the time zone. The first whole UTC hour at or
    after local midnight. A nonexistent local midnight resolves (fold 0, as in
    Home Assistant's ``replace(hour=0)``) to the instant the clocks jump, the
    day's first existing instant.
    """
    midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
    return _ceil_hour(midnight.timestamp())


def day_start(day: date, tz: tzinfo) -> datetime:
    """The start of statistics day ``day`` as a UTC datetime (inputs: date, time zone)."""
    return datetime.fromtimestamp(_day_start_ts(day, tz), UTC)


def statistics_day(instant: Instant, tz: tzinfo) -> date:
    """The statistics day that contains ``instant`` (inputs: the instant, time zone).

    In Asia/Kolkata 00:20 local still belongs to the previous day, which ends
    at 00:30.
    """
    seconds = ts(instant)
    day = datetime.fromtimestamp(seconds, tz).date()
    if seconds < _day_start_ts(day, tz):
        day -= timedelta(days=1)
    return day


def first_day_at_or_after(instant: Instant, tz: tzinfo) -> date:
    """The first statistics day whose start is at or after ``instant``."""
    seconds = ts(instant)
    day = statistics_day(seconds, tz)
    if _day_start_ts(day, tz) < seconds:
        day += timedelta(days=1)
    return day


def _next_month(day: date) -> date:
    """First day of the month after ``day``'s month."""
    return date(day.year + 1, 1, 1) if day.month == 12 else date(day.year, day.month + 1, 1)


def _add_months(first: date, months: int) -> date:
    """``first`` (a 1st of a month) moved by ``months`` calendar months."""
    index = first.year * 12 + first.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


# --- windows, ranges and table reads --------------------------------------


@dataclass(frozen=True)
class Window:
    """A half-open UTC window [start, end) for which one table is read."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        aware(self.start, "window start")
        aware(self.end, "window end")

    def contains(self, other: Window | Range) -> bool:
        """Whether ``other`` lies inside this window."""
        return self.start <= other.start and other.end <= self.end


@dataclass(frozen=True)
class Range:
    """A half-open UTC range [start, end) whose rows are read from one table.

    ``start_ts`` and ``end_ts`` are the bounds as epoch seconds, computed once.
    """

    source: str
    start: datetime
    end: datetime
    start_ts: float = field(init=False, repr=False, compare=False)
    end_ts: float = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_ts", ts(self.start, "range start"))
        object.__setattr__(self, "end_ts", ts(self.end, "range end"))

    def contains(self, row_start: float) -> bool:
        """Whether a row key (epoch seconds) lies in [start, end)."""
        return self.start_ts <= row_start < self.end_ts


@dataclass(frozen=True, eq=False)
class TableRead:
    """One statistics read of one table, as the coordinator caches it.

    ``source``: the table (``month``, ``day``, ``hour`` or ``5minute``).
    ``window``: the UTC window the read was made for (``history_windows``).
    ``rows``: ``{statistic_id: [row, ...]}`` as returned, or None when the read
    failed. ``covered``: the statistics this read covers (``coverage``); only
    checked for the day and month tables, because the 5-minute and hour tables
    are read at every update and their ranges end at the service's coverage
    end (``coverage_end``). ``read_at``: the ``now`` of the update that made the read.
    """

    source: str
    window: Window
    rows: Mapping[str, Sequence[Row]] | None
    covered: frozenset[str] = frozenset()
    read_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.read_at is not None:
            aware(self.read_at, "read_at")

    @cached_property
    def _index(self) -> dict[str, tuple[list[float], list[float | None]]]:
        """Per statistic its row keys (sorted epoch seconds) and changes.

        A day or month row starts at local midnight (of the 1st); its key is
        the first whole UTC hour at or after that, the start of the statistics
        day it holds. Other rows are keyed by their start.
        """
        hourly_keys = self.source in HISTORY_SOURCES
        index: dict[str, tuple[list[float], list[float | None]]] = {}
        for statistic_id, rows in (self.rows or {}).items():
            pairs = sorted(
                (
                    (_ceil_hour(row["start"]) if hourly_keys else float(row["start"]), row.get("change"))
                    for row in rows
                ),
                key=lambda pair: pair[0],
            )
            index[statistic_id] = ([k for k, _ in pairs], [c for _, c in pairs])
        return index

    def changes(
        self, statistic_id: str, rng: Range, first: DefrostFirst | None = None
    ) -> list[float | None]:
        """The ``change`` of each row of ``statistic_id`` whose key lies in ``rng``.

        ``first`` (design D12) is the statistic's first hour and baseline, given for a
        defrost statistic: it counts from the end of its first hour. The row that holds
        the first hour (the hour row starting at it, or the day or month row containing
        it, when ``rng`` contains the first hour) is reduced by the baseline, so the
        first hour itself adds 0, and a 5-minute row that starts inside the first hour
        adds 0.
        """
        keys, changes = self._index.get(statistic_id, ([], []))
        low, high = bisect_left(keys, rng.start_ts), bisect_left(keys, rng.end_ts)
        result = list(changes[low:high])
        if first is None:
            return result
        hour, baseline = ts(first[0], "first hour"), float(first[1])
        if self.source == SOURCE_5MINUTE:
            return [
                0.0 if hour <= key < hour + HOUR_SECONDS else change
                for key, change in zip(keys[low:high], result)
            ]
        if not rng.contains(hour):
            return result
        if self.source == SOURCE_HOUR:
            holder = bisect_left(keys, hour)
            holds = holder < len(keys) and keys[holder] == hour
        else:
            holder = bisect_right(keys, hour) - 1
            holds = holder >= 0
        if holds and low <= holder < high:
            change = result[holder - low]
            result[holder - low] = None if change is None else change - baseline
        return result


@dataclass(frozen=True)
class CacheActions:
    """What an update reads: the tables in ``tables``, and the first hours when True.

    The metadata is not part of it: it is read at every update, before
    ``cache_actions`` (design D4).
    """

    tables: frozenset[str]
    first_hours: bool = False


def hourly_only(metadata: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """The statistic IDs that have only hourly statistics (external statistics).

    Input: the metadata from ``async_list_statistic_ids``. A statistic whose
    ``source`` is not ``recorder`` has no 5-minute rows; a missing ``source``
    counts as ``recorder``.
    """
    return frozenset(m["statistic_id"] for m in metadata if m.get("source", RECORDER) != RECORDER)


def last_row_ends(
    statistic_ids: Iterable[str],
    hourly_only_ids: Iterable[str],
    tables: Mapping[str, TableRead | None],
) -> dict[str, float | None]:
    """Per statistic the end (epoch seconds) of its last row in the table it is read from.

    Inputs: the mapped IDs, the hourly-only IDs and this update's reads. The
    ``hour`` table for hourly-only statistics, ``5minute`` otherwise. None when
    that read failed, was not made or holds no row of the statistic. Used for
    ``coverage`` and ``health``.
    """
    hourly = set(hourly_only_ids)
    result: dict[str, float | None] = {}
    for statistic_id in statistic_ids:
        table = tables.get(SOURCE_HOUR if statistic_id in hourly else SOURCE_5MINUTE)
        rows = None if table is None or table.rows is None else table.rows.get(statistic_id)
        result[statistic_id] = max((float(r["end"]) for r in rows), default=None) if rows else None
    return result


def coverage(
    statistic_ids: Iterable[str], window: Window, last_row_end: Mapping[str, Instant | None]
) -> frozenset[str]:
    """The statistics a read of ``window`` covers.

    Inputs: the mapped IDs, the read window, and ``last_row_ends`` taken from
    reads made before this one in the same update. Covered when, at the time
    of the read, the statistic's last row ended at or after the window's end.
    """
    end = window.end.timestamp()
    return frozenset(
        statistic_id
        for statistic_id in statistic_ids
        if (last := last_row_end.get(statistic_id)) is not None and ts(last) >= end
    )


def reads_hourly(statistic_ids: Iterable[str], hourly_only_ids: Iterable[str]) -> bool:
    """Whether a service or Overall reads today from the ``hour`` table.

    Inputs: the service's statistic IDs and the hourly-only IDs
    (``hourly_only``). True when one of its statistics is hourly-only; its
    other statistics are then read hourly too, so all end at the same instant.
    """
    return not set(statistic_ids).isdisjoint(hourly_only_ids)


def coverage_end(
    statistic_ids: Iterable[str],
    hourly_only_ids: Iterable[str],
    tables: Mapping[str, TableRead | None],
    now: datetime,
) -> datetime:
    """Where every period of a service or Overall ends (design D2).

    Inputs: the service's statistic IDs (output and electrical), the
    hourly-only IDs, this update's reads and ``now``. The earliest end of the
    last row among all its statistics, at most now: hourly rows when the
    service reads hourly (``reads_hourly``), 5-minute rows otherwise. So a
    statistic whose sensor is offline cuts the other counters of its service at
    the same instant, and no output is counted without matching electricity.
    ``NO_COVERAGE`` (every period unknown) when that read failed or was not
    made, or when a statistic has no row in it (none in the today window).
    """
    ids = list(statistic_ids)
    current = aware(now, "now").astimezone(UTC)
    table = tables.get(SOURCE_HOUR if reads_hourly(ids, hourly_only_ids) else SOURCE_5MINUTE)
    if not ids or table is None or table.rows is None:
        return NO_COVERAGE
    ends = []
    for statistic_id in ids:
        rows = table.rows.get(statistic_id)
        if not rows:
            return NO_COVERAGE
        ends.append(max(float(r["end"]) for r in rows))
    return min(datetime.fromtimestamp(min(ends), UTC), current)


# --- ranges ---------------------------------------------------------------


def cover(start: date, end: date, tz: tzinfo) -> list[Range]:
    """Adjacent ranges covering the completed statistics days [start, end).

    Days from ``start`` up to the next month start (when ``start`` is not a
    1st, as for a rolling start or an effective start), then one range of
    whole months, then the remaining days of the last month. Only complete
    months use the month table, so no month is ever counted partly.
    """
    out: list[Range] = []
    day = start
    if day >= end:
        return out
    if day.day != 1:
        stop = min(_next_month(day), end)
        out.append(Range(SOURCE_DAY, day_start(day, tz), day_start(stop, tz)))
        day = stop
    if day < end:
        months_end = date(end.year, end.month, 1)
        if months_end > day:
            out.append(Range(SOURCE_MONTH, day_start(day, tz), day_start(months_end, tz)))
            day = months_end
    if day < end:
        out.append(Range(SOURCE_DAY, day_start(day, tz), day_start(end, tz)))
    return out


def span(
    start: date, today: date, tz: tzinfo, end: datetime, source: str
) -> list[Range] | None:
    """Ranges from the start of day ``start`` to ``end``, today's part read from ``source``.

    None when ``start`` is after today, or when ``end`` (a coverage end) lies
    before today's start, so the period's rows are in no read table.
    """
    today_start = day_start(today, tz)
    if start > today or end < today_start:
        return None
    return cover(start, today, tz) + [Range(source, today_start, end.astimezone(UTC))]


def _natural_starts(today: date) -> dict[str, date]:
    last_year_day = min(today.day, calendar.monthrange(today.year - 1, today.month)[1])
    return {
        PERIOD_TODAY: today,
        PERIOD_MONTH_TO_DATE: today.replace(day=1),
        PERIOD_YEAR_TO_DATE: date(today.year, 1, 1),
        PERIOD_ROLLING_12_MONTHS: date(today.year - 1, today.month, last_year_day),
    }


def _floor(effective: Instant | None, tz: tzinfo) -> date | None:
    """The first statistics day an effective start allows (None: no limit)."""
    return None if effective is None else first_day_at_or_after(aware(effective, "effective"), tz)


def _end_and_source(now: datetime, end: datetime | None, hourly: bool) -> tuple[datetime, str]:
    """Where today's range ends (the coverage end, at most now) and the table it is read from."""
    current = aware(now, "now")
    source = SOURCE_HOUR if hourly else SOURCE_5MINUTE
    if end is None:
        return current, source
    return min(aware(end, "end"), current), source


def period_ranges(
    now: datetime,
    tz: tzinfo,
    effective: datetime | None = None,
    end: datetime | None = None,
    hourly: bool = False,
) -> dict[str, list[Range] | None]:
    """The ranges of each period, which telescope from the period's covered start to its end.

    Inputs: ``now``, the time zone, the service's effective start
    (``effective_start``), its ``coverage_end`` (``end``; None: now) and
    whether it reads hourly (``reads_hourly``). A period starts at the later
    of its natural start (the day start of today, of the 1st, of 1 January, or
    of the same calendar day one year earlier or the last day of that month)
    and the effective start; an effective start that is not a day start moves
    to the next one. It ends at the coverage end, at most now, reading today
    from the 5-minute table, or from the hour table when ``hourly``; completed
    days and months are unaffected. Ranges are disjoint and adjacent and each
    names its table; a start inside a month reads that month's days from the
    day table, never a partly counted month. None for a period that has not
    begun, or whose coverage end lies before today's start.
    """
    today = statistics_day(aware(now, "now"), tz)
    floor = _floor(effective, tz)
    end, source = _end_and_source(now, end, hourly)
    result: dict[str, list[Range] | None] = {}
    for name, natural in _natural_starts(today).items():
        start = natural if floor is None else max(natural, floor)
        result[name] = span(start, today, tz, end, source)
    return result


def period_starts(
    now: datetime,
    tz: tzinfo,
    effective: datetime | None = None,
    end: datetime | None = None,
    hourly: bool = False,
) -> dict[str, datetime | None]:
    """The covered start of each period in the time zone, None when the period is None.

    Inputs as ``period_ranges``. The covered start is the period's natural
    start, or the effective start where that cuts the period; it is the
    ``period_start`` attribute and the input of ``includes_estimated``.
    """
    return {
        name: None if ranges is None else ranges[0].start.astimezone(tz)
        for name, ranges in period_ranges(now, tz, effective, end, hourly).items()
    }


def effective_start(
    first_hours: Iterable[Instant | None], tz: tzinfo, now: datetime | None = None
) -> datetime | None:
    """The first day start at or after the latest first statistics hour.

    Input: the first statistics hour of every statistic of a service or
    Overall (aware datetimes or epoch seconds), the time zone and ``now``.
    13 Nov 14:00 gives 14 Nov 00:00; 13 Nov 00:00 stays. Compares instants, so
    a day whose local midnight does not exist works too. A None hour is a
    statistic whose first hour is not known yet (it has rows but no hourly
    row): it counts as starting ``now``, so the periods of its service have
    not begun until the next first-hours refresh; ``now`` is then required.
    Leave out a statistic that has no rows at all. Returned in the time zone;
    None when there are no hours.
    """
    hours = []
    for hour in first_hours:
        if hour is None:
            if now is None:
                raise ValueError("now is required for a first hour that is not known yet")
            hour = now
        hours.append(ts(hour, "first hour"))
    if not hours:
        return None
    return day_start(first_day_at_or_after(max(hours), tz), tz).astimezone(tz)


# --- energy and ratio -----------------------------------------------------


def period_energy(
    tables: Mapping[str, TableRead | None],
    statistic_ids: Iterable[str],
    ranges: Sequence[Range],
    firsts: DefrostFirsts | None = None,
) -> float | None:
    """Summed ``change`` (kWh) of ``statistic_ids`` over ``ranges``, or None.

    Inputs: the cached table reads, the IDs and a period's ranges. A row
    counts in a range when its key (``TableRead``) lies in [start, end). None
    when there is no ID, when a table a range needs was not read or its read
    failed, when a range is not inside the window its table was read for,
    when a day or month read does not cover one of the IDs, when a counted row
    has no ``change``, or when an ID has no rows in any read. A statistic with
    rows elsewhere but none in a range adds 0 there.

    ``firsts`` (design D12) gives the first hour and baseline of the defrost
    statistics among the IDs (``TableRead.changes``): such a statistic counts from
    the end of its first hour. IDs not in it, and a call without it, are unchanged.
    """
    ids = list(statistic_ids)
    firsts = firsts or {}
    if not ids:
        return None
    for rng in ranges:
        table = tables.get(rng.source)
        if table is None or table.rows is None or not table.window.contains(rng):
            return None
        if rng.source in HISTORY_SOURCES and not table.covered.issuperset(ids):
            return None
    read = [t.rows for t in tables.values() if t is not None and t.rows is not None]
    total = 0.0
    for statistic_id in ids:
        if not any(rows.get(statistic_id) for rows in read):
            return None
        for rng in ranges:
            for change in tables[rng.source].changes(statistic_id, rng, firsts.get(statistic_id)):  # type: ignore[union-attr]
                if change is None:
                    return None
                total += change
    return total


def ratio(
    output_kwh: float | None, electrical_kwh: float | None, factor: float = 1.0
) -> float | None:
    """Output energy over electrical energy times ``factor``, 2 decimals.

    Inputs: the two energies (kWh) and a unit factor (1.0 for W/W,
    ``BTU_PER_WH`` for BTU/Wh). None when an energy is None or the electrical
    energy is below 0.1 kWh (checked first); the factor multiplies the
    unrounded ratio before rounding.
    """
    if output_kwh is None or electrical_kwh is None or electrical_kwh < MIN_ELECTRICAL_KWH:
        return None
    return round(output_kwh / electrical_kwh * factor, 2)


def corrected_ratio(
    output_kwh: float | None,
    defrost_kwh: float | None,
    electrical_kwh: float | None,
    factor: float = 1.0,
) -> float | None:
    """Output minus defrost heat over electrical energy times ``factor``, 2 decimals (design D5).

    Inputs: the three energies (kWh) and a unit factor as ``ratio``. None when
    an energy is None, the electrical energy is below 0.1 kWh (checked first,
    the rule of ``ratio``), or the unrounded output minus defrost is 0 or less.
    The 0.1 kWh rule stays on electricity only: it guards against a tiny
    divisor, while a small positive corrected output is a real, low figure.
    """
    if (
        output_kwh is None
        or defrost_kwh is None
        or electrical_kwh is None
        or electrical_kwh < MIN_ELECTRICAL_KWH
    ):
        return None
    corrected = output_kwh - defrost_kwh
    if corrected <= 0:
        return None
    return round(corrected / electrical_kwh * factor, 2)


def defrost_start(first_hours: Iterable[Instant | None], now: Instant) -> datetime | None:
    """The point from which a service's defrost statistics all count (design D5, D12).

    Input: the first statistics hour of each defrost statistic of a service
    (aware datetimes or epoch seconds) and ``now``. A statistic counts from the
    end of its first hour (first hour plus one hour); the result is the latest
    of them, not moved to a day start (a UTC datetime). A None hour is a
    statistic with rows but no hourly row yet: it counts as ``now`` (no hour
    added). Leave out a statistic that has no rows at all. None when there are
    no hours.
    """
    hours = [
        ts(now, "now") if hour is None else ts(hour, "first hour") + HOUR_SECONDS for hour in first_hours
    ]
    if not hours:
        return None
    return datetime.fromtimestamp(max(hours), UTC)


def defrost_partial(covered_start: Instant | None, defrost_start: Instant | None) -> bool:
    """Whether a period or point starts before its defrost statistics do (design D5).

    Inputs: its covered start (``period_starts`` or a range start) and the
    ``defrost_start``. True when the covered start lies before it; False when
    either is None.
    """
    if covered_start is None or defrost_start is None:
        return False
    return ts(covered_start, "covered_start") < ts(defrost_start, "defrost_start")


def period_summary(
    tables: Mapping[str, TableRead | None],
    ranges: Sequence[Range] | None,
    output_ids: Iterable[str],
    electrical_ids: Iterable[str],
    factor: float = 1.0,
    defrost_ids: Iterable[str] = (),
    defrost_firsts: DefrostFirsts | None = None,
) -> dict[str, float | None]:
    """The sensor values of one period: output and electrical energy (kWh, 3 decimals) and efficiency.

    Inputs: the cached table reads, the period's ranges and the service's
    output and electrical IDs. The energies stay set when the ratio is unknown
    because of the 0.1 kWh rule; an energy is None when ``period_energy`` is,
    and all three are None when the period is None. ``factor`` is the unit
    factor of ``ratio``; the energies stay in kWh.

    With ``defrost_ids`` (design D5) the result also has ``defrost_energy``
    (``period_energy`` of those IDs, 3 decimals, None when unknown or the
    period is None) and ``efficiency_uncorrected`` (``ratio``), and
    ``efficiency`` is ``corrected_ratio``, so it is None whenever the defrost
    energy is. ``defrost_firsts`` are the defrost statistics' first hours and
    baselines (``period_energy``, design D12). Without defrost IDs the result is
    unchanged and has no new keys.
    """
    defrost = list(defrost_ids)
    if ranges is None:
        empty: dict[str, float | None] = {"output_energy": None, "electrical_energy": None, "efficiency": None}
        if defrost:
            empty.update({"defrost_energy": None, "efficiency_uncorrected": None})
        return empty
    output = period_energy(tables, output_ids, ranges)
    electrical = period_energy(tables, electrical_ids, ranges)
    result: dict[str, float | None] = {
        "output_energy": None if output is None else round(output, 3),
        "electrical_energy": None if electrical is None else round(electrical, 3),
        "efficiency": ratio(output, electrical, factor),
    }
    if defrost:
        defrost_kwh = period_energy(tables, defrost, ranges, defrost_firsts)
        result["efficiency"] = corrected_ratio(output, defrost_kwh, electrical, factor)
        result["defrost_energy"] = None if defrost_kwh is None else round(defrost_kwh, 3)
        result["efficiency_uncorrected"] = ratio(output, electrical, factor)
    return result


def includes_estimated(
    covered_start: datetime | None, measured_since: date | None, tz: tzinfo
) -> bool:
    """Whether a period or point includes estimated history.

    Inputs: its covered start (``period_starts``), the measured-since date and
    the time zone. True when the covered start lies before the start of the
    measured-since day; False without a date or a start.
    """
    if covered_start is None or measured_since is None:
        return False
    return aware(covered_start, "covered_start") < day_start(measured_since, tz)


# --- series ---------------------------------------------------------------


def _daily_plan(
    now: datetime,
    tz: tzinfo,
    effective: datetime | None,
    end: datetime | None = None,
    hourly: bool = False,
) -> list[tuple[date, list[Range]]]:
    """Per day of the daily series (oldest first) its date and ranges; today's ends at ``end``."""
    today = statistics_day(aware(now, "now"), tz)
    floor = _floor(effective, tz)
    end, source = _end_and_source(now, end, hourly)
    plan: list[tuple[date, list[Range]]] = []
    for back in range(DAILY_POINTS - 1, -1, -1):
        day = today - timedelta(days=back)
        if floor is not None and day < floor:
            continue
        ranges = span(day, today, tz, end, source) if back == 0 else cover(day, day + timedelta(days=1), tz)
        if ranges:
            plan.append((day, ranges))
    return plan


def _monthly_plan(
    now: datetime,
    tz: tzinfo,
    effective: datetime | None,
    end: datetime | None = None,
    hourly: bool = False,
) -> list[tuple[date, list[Range]]]:
    """Per month of the monthly series (oldest first) its 1st and ranges; the current one ends at ``end``."""
    today = statistics_day(aware(now, "now"), tz)
    floor = _floor(effective, tz)
    end, source = _end_and_source(now, end, hourly)
    this_month = today.replace(day=1)
    plan: list[tuple[date, list[Range]]] = []
    for back in range(MONTHLY_POINTS - 1, -1, -1):
        first = _add_months(this_month, -back)
        month_end = _next_month(first)
        start = first if floor is None else max(first, floor)
        if start >= month_end or start > today:
            continue
        ranges = span(start, today, tz, end, source) if back == 0 else cover(start, month_end, tz)
        if ranges:
            plan.append((first, ranges))
    return plan


def _points(
    plan: Sequence[tuple[date, list[Range]]],
    tables: Mapping[str, TableRead | None],
    output_ids: Iterable[str],
    electrical_ids: Iterable[str],
    measured_since: date | None,
    tz: tzinfo,
    factor: float = 1.0,
    defrost_ids: Iterable[str] = (),
    defrost_start: Instant | None = None,
    defrost_firsts: DefrostFirsts | None = None,
) -> list[dict[str, Any]]:
    output_ids, electrical_ids, defrost_ids = list(output_ids), list(electrical_ids), list(defrost_ids)
    points = []
    for start, ranges in plan:
        output = period_energy(tables, output_ids, ranges)
        electrical = period_energy(tables, electrical_ids, ranges)
        if defrost_ids:
            defrost_kwh = period_energy(tables, defrost_ids, ranges, defrost_firsts)
            efficiency = corrected_ratio(output, defrost_kwh, electrical, factor)
        else:
            efficiency = ratio(output, electrical, factor)
        if efficiency is None:
            continue  # no point, never 0
        point = {
            "start": day_start(start, tz).astimezone(tz).isoformat(),
            "efficiency": efficiency,
            "estimated": includes_estimated(ranges[0].start, measured_since, tz),
        }
        if defrost_ids:
            # The covered start is ranges[0].start, the same start as ``estimated`` (design D5).
            point["defrost_partial"] = defrost_partial(ranges[0].start, defrost_start)
        points.append(point)
    return points


def daily_series(
    tables: Mapping[str, TableRead | None],
    output_ids: Iterable[str],
    electrical_ids: Iterable[str],
    now: datetime,
    tz: tzinfo,
    effective: datetime | None = None,
    measured_since: date | None = None,
    end: datetime | None = None,
    hourly: bool = False,
    factor: float = 1.0,
    defrost_ids: Iterable[str] = (),
    defrost_start: Instant | None = None,
    defrost_firsts: DefrostFirsts | None = None,
) -> list[dict[str, Any]]:
    """Efficiency per statistics day for the last 31 days, today included so far.

    Inputs: the cached table reads, the service's IDs, ``now``, the time zone,
    its effective start, measured-since date, coverage end and whether it
    reads hourly (as ``period_ranges``). Points exist only where the
    efficiency is known and the day is not before the effective start; today's
    point ends at the coverage end, and there is none when that lies before
    today's start. ``start`` is the day's start;
    ``estimated`` is ``includes_estimated`` of its covered start. ``factor`` is
    the unit factor of ``ratio`` (1.0, or ``BTU_PER_WH`` for Cooling in BTU/Wh).

    With ``defrost_ids`` (design D5) a point's efficiency is
    ``corrected_ratio`` (no point when unknown, never 0) and the point also has
    ``defrost_partial``: ``defrost_partial`` of its covered start and the
    ``defrost_start``; ``defrost_firsts`` are the defrost statistics' first hours
    and baselines (``period_energy``, design D12). Without defrost IDs the
    points are unchanged.
    """
    plan = _daily_plan(now, tz, effective, end, hourly)
    return _points(
        plan, tables, output_ids, electrical_ids, measured_since, tz, factor, defrost_ids, defrost_start,
        defrost_firsts,
    )


def monthly_series(
    tables: Mapping[str, TableRead | None],
    output_ids: Iterable[str],
    electrical_ids: Iterable[str],
    now: datetime,
    tz: tzinfo,
    effective: datetime | None = None,
    measured_since: date | None = None,
    end: datetime | None = None,
    hourly: bool = False,
    factor: float = 1.0,
    defrost_ids: Iterable[str] = (),
    defrost_start: Instant | None = None,
    defrost_firsts: DefrostFirsts | None = None,
) -> list[dict[str, Any]]:
    """Efficiency per calendar month for the last 24 months, the current one so far.

    Inputs as ``daily_series``. A month cut by the effective start covers only
    the days from it (read from the day table); the current month ends at the
    coverage end. ``start`` is the start of the
    month's 1st; ``estimated`` compares the covered start (the 1st, or the
    effective start where it cuts the month) with the measured-since day.
    ``factor``, ``defrost_ids``, ``defrost_start`` and ``defrost_firsts`` as ``daily_series``.
    """
    plan = _monthly_plan(now, tz, effective, end, hourly)
    return _points(
        plan, tables, output_ids, electrical_ids, measured_since, tz, factor, defrost_ids, defrost_start,
        defrost_firsts,
    )


def history_windows(
    now: datetime,
    tz: tzinfo,
    effective_starts: Iterable[datetime | None] = (None,),
    hourly: bool = False,
    season_starts: Iterable[datetime] = (),
) -> dict[str, Window]:
    """The UTC window to read from each table so every period and series is covered.

    Inputs: ``now``, the time zone, the effective start of each configured
    service and Overall, and whether any of them has an hourly-only statistic.
    ``month`` and ``day``: the union (earliest start to latest end) of the
    ranges of the four periods and both series over all effective starts; a
    table no range needs is absent. ``season_starts`` are the covered starts of
    the running seasons (one per service with one): the ranges from each start to
    today are included too, so a season longer than the rolling 12 months is
    covered. ``5minute``, and ``hour`` only when
    ``hourly``: from the earlier of today's start and now minus 3 hours to
    now, because rows before today's start serve the staleness check and the
    coverage.
    """
    current = aware(now, "now")
    ranges: list[Range] = []
    for effective in effective_starts:
        for period in period_ranges(current, tz, effective).values():
            ranges.extend(period or [])
        for _, rs in _daily_plan(current, tz, effective) + _monthly_plan(current, tz, effective):
            ranges.extend(rs)
    today = statistics_day(current, tz)
    for season_start in season_starts:
        ranges.extend(cover(statistics_day(season_start, tz), today, tz))
    windows: dict[str, Window] = {}
    for rng in ranges:
        if rng.source not in HISTORY_SOURCES:
            continue
        known = windows.get(rng.source)
        windows[rng.source] = (
            Window(rng.start, rng.end)
            if known is None
            else Window(min(known.start, rng.start), max(known.end, rng.end))
        )
    now_utc = current.astimezone(UTC)
    today_start = day_start(statistics_day(current, tz), tz)
    recent = Window(min(today_start, now_utc - STALENESS_WINDOW), now_utc)
    windows[SOURCE_5MINUTE] = recent
    if hourly:
        windows[SOURCE_HOUR] = recent
    return windows


# --- cache ----------------------------------------------------------------


def cache_actions(
    tables: Mapping[str, TableRead | None],
    first_hours_read_at: datetime | None,
    needed: Mapping[str, Window],
    statistic_ids: Iterable[str],
    now: datetime,
    tz: tzinfo,
) -> CacheActions:
    """Which reads this update needs (design D4).

    Inputs: the cached table reads (empty at setup and after a reload), the
    time of the last successful first-hours read (None: never),
    the windows now needed (``history_windows``), all mapped statistic IDs,
    ``now`` and the time zone.

    First hours are read when never read successfully, or at the first update
    of a new statistics day. The metadata is not decided here: it is read at
    every update, before this call, so ``needed`` already reflects the current
    hourly-only statistics (the ``hour`` table is in it exactly when a service
    reads hourly). The ``5minute`` and ``hour`` tables are read at
    every update they are needed. A needed ``day`` or ``month`` table is read
    when it is not cached, its last read failed, the needed window is not
    inside the cached one, its last read did not cover every mapped statistic,
    or, for ``day``, the statistics day changed since that read and, for
    ``month``, the calendar month of the statistics day changed. When first
    hours are read, the coordinator recomputes the needed windows from the new
    effective starts and calls this again with the new read time; the second
    call returns the tables to read.
    """
    today = statistics_day(aware(now, "now"), tz)
    ids = frozenset(statistic_ids)
    first = first_hours_read_at is None or statistics_day(aware(first_hours_read_at, "first_hours_read_at"), tz) != today
    reads: set[str] = set()
    for source, window in needed.items():
        if source not in HISTORY_SOURCES:
            reads.add(source)
            continue
        cached = tables.get(source)
        if (
            cached is None
            or cached.rows is None
            or cached.read_at is None
            or not cached.window.contains(window)
            or not cached.covered.issuperset(ids)
        ):
            reads.add(source)
            continue
        read_day = statistics_day(cached.read_at, tz)
        if source == SOURCE_DAY and read_day != today:
            reads.add(source)
        elif source == SOURCE_MONTH and (read_day.year, read_day.month) != (today.year, today.month):
            reads.add(source)
    return CacheActions(tables=frozenset(reads), first_hours=first)


# --- health ---------------------------------------------------------------


def health(
    statistic_ids: Iterable[str],
    metadata: Iterable[Mapping[str, Any]],
    last_row_end: Mapping[str, Instant | None],
    now: datetime,
) -> dict[str, str]:
    """Classify each mapped statistic as ok, missing, not_energy, no_sum or stale.

    Inputs: the mapped IDs (a missing statistic is absent from ``metadata``),
    the metadata from ``async_list_statistic_ids`` (dicts with
    ``statistic_id``, ``has_sum``, ``unit_class``, ...), ``last_row_ends``
    (the end of each statistic's last 5-minute row, or last hourly row for an
    hourly-only statistic) and ``now``. Checked in this order: missing, not an
    energy unit class (a W statistic is not_energy even when it also lacks a
    sum, as that names the cause), no running sum, then stale: the last row
    ended more than 2 hours before ``now``, or there is no row.
    """
    by_id = {m["statistic_id"]: m for m in metadata}
    current = ts(now, "now")
    result: dict[str, str] = {}
    for statistic_id in statistic_ids:
        meta = by_id.get(statistic_id)
        last = last_row_end.get(statistic_id)
        last_ts = None if last is None else ts(last, "last row end")
        if meta is None:
            result[statistic_id] = HEALTH_MISSING
        elif meta.get("unit_class") != "energy":
            result[statistic_id] = HEALTH_NOT_ENERGY
        elif not meta.get("has_sum"):
            result[statistic_id] = HEALTH_NO_SUM
        elif last_ts is None or current - last_ts > STALE_AFTER.total_seconds():
            result[statistic_id] = HEALTH_STALE
        else:
            result[statistic_id] = HEALTH_OK
    return result
