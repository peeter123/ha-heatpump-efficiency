"""Pure per-update orchestration of the heat pump efficiency integration.

Standard library only (the reader's methods are coroutines, so ``async_update``
is one too; nothing here imports asyncio); the only imports from the package
are the pure siblings ``efficiency``, ``seasons`` and ``validation``. Nothing here imports Home Assistant, so the read plan of every
update is unit-tested with a fake reader. ``coordinator.py`` is the thin glue:
a reader that calls ``statistics_during_period`` and ``async_list_statistic_ids``
and one call to ``async_update``.

Reader interface (``Reader``)::

    async def read(source, statistic_ids, window, units, types) -> {id: [row, ...]}
    async def metadata(statistic_ids) -> [metadata dict, ...]

``source`` is the ``period`` argument of ``statistics_during_period``
(``month``, ``day``, ``hour`` or ``5minute``) and ``window`` a half-open UTC
``efficiency.Window``. ``units`` and ``types`` are ``READ_UNITS`` and
``READ_TYPES`` (energy in kWh, the ``change``), except for the season boundary
reads, which pass ``BOUNDARY_UNITS`` and ``BOUNDARY_TYPES`` (the ``sum``).
Either method may raise; the engine catches that per read.

One update (``async_update``):

1. The metadata is read (every update; a failed read keeps the last good
   metadata), which gives the hourly-only statistics and so whether the
   ``hour`` table is needed. ``cache_actions`` decides the reads. When it asks
   for first hours (setup, and the first update of a new statistics day) they
   are read (``read_first_hours``: a ``month`` read over ``first_hours_window``,
   then a ``day`` and an ``hour`` read inside the first month and day), the
   effective starts and windows are recomputed, and ``cache_actions`` is called
   again; its tables are read. Without a season the ``month`` read starts one
   month before the month window without an effective start; with a season it
   starts at ``HISTORY_FLOOR`` (the whole history at the first successful read
   after a load, later only up to the month of the latest known first hour).
   ``5minute`` (and ``hour``) first, then the history tables with the coverage
   taken from those last row ends.
2. A failed read is stored as a ``TableRead`` with ``rows=None`` and its error is
   kept in ``EngineState.errors``; it never raises out of the update. Periods
   that need it are ``None`` (``efficiency.period_energy``).
3. ``compute`` gives per service and Overall the four period results and the
   daily and monthly series, all ending at the service's coverage end. Every
   service is unknown until the metadata has been read successfully once
   (whether a statistic is hourly-only is not known before).
4. Seasons (design D3, D4, D5). Per service with a season (Heating and Overall:
   the heating season, Cooling: the cooling season; Hot water has none) the
   running season is summed from the cached tables, like year to date, and a
   finished season from the boundary readings (``EngineState.boundaries``): one
   ``hour`` read of the ``sum`` per boundary instant for all statistics that need
   it. ``boundary_actions`` (pure) decides which boundaries are read; they are read
   after the tables, at the end of the update. A failed read or a statistic without
   a reading makes only the seasons that need it unknown. A failed read is read
   again at the next update, a ``pending`` reading once the statistic's last row
   ends at or after the boundary; a ``no_row`` reading is final (design D4).
   Cooling's periods, series and seasons carry the unit factor (``Service.factor``).
5. Defrost statistics (Heating and Hot water, design D4) are a correction, not an
   input: they never move a service's effective start or widen its windows
   (``Service.ids``), but they are read with the others (``Service.all_ids``) and
   a service whose defrost statistic is behind or missing is unknown. The
   corrected results carry ``defrost_energy``, ``efficiency_uncorrected`` and
   ``defrost_since``. The first hours are read per group (output and electrical,
   defrost), each bounded by its own group's known first hours.
   A defrost statistic counts from the end of its first hour, with the ``change`` of
   its first hourly row as its baseline (design D12): ``read_first_hours`` returns the
   baselines with the first hours, ``EngineState.baselines`` keeps them, and they are
   applied to the defrost statistics only (``period_energy``, the boundary readings).
6. A failed first-hours read is retried at every update. Until the first
   successful read it makes the services of the affected IDs unknown; after
   that the last good first hours are kept (a backfill that moves a first hour
   shows once a refresh succeeds).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Protocol

from . import efficiency as eff, seasons as sea, validation as val

READ_UNITS: Mapping[str, str] = {
    "energy": "kWh"
}  # units=None would convert to the entity's unit
READ_TYPES: frozenset[str] = frozenset({"change"})

ERROR_FIRST_HOURS = "first_hours"
ERROR_METADATA = "metadata"
ERROR_BOUNDARIES = "boundaries"
HISTORY_FLOOR = datetime(
    2000, 1, 1, tzinfo=eff.UTC
)  # before any Home Assistant statistics
BOUNDARY_UNITS: Mapping[str, str] = {"energy": "kWh"}
BOUNDARY_TYPES: frozenset[str] = frozenset({"sum"})
# Why a statistic has no reading at a boundary (design D4, group 3 review).
PENDING = (
    "pending"  # its last row ended before the boundary, or it has no 5-minute rows
)
NO_ROW = "no_row"  # covered, but no hourly row in the window before the boundary
# The season kind of each service; Hot water has none (design D7).
SEASON_KINDS: Mapping[str, str] = {
    val.SERVICE_HEATING: sea.HEATING,
    val.SERVICE_OVERALL: sea.HEATING,
    val.SERVICE_COOLING: sea.COOLING,
}
RECENT_SOURCES = (
    eff.SOURCE_5MINUTE,
    eff.SOURCE_HOUR,
)  # read at every update, before history


class Reader(Protocol):
    """What the engine needs from Home Assistant."""

    async def read(
        self,
        source: str,
        statistic_ids: frozenset[str],
        window: eff.Window,
        units: Mapping[str, str],
        types: frozenset[str],
    ) -> Mapping[str, Sequence[eff.Row]]:
        """Return the rows of ``statistic_ids`` in ``source`` for the half-open ``window``."""

    async def metadata(
        self, statistic_ids: frozenset[str]
    ) -> Sequence[Mapping[str, Any]]:
        """Return the statistics metadata of ``statistic_ids`` (absent when it does not exist)."""


@dataclass(frozen=True)
class Service:
    """One configured service or Overall of the mapping."""

    key: str
    output_ids: tuple[str, ...]
    electrical_ids: tuple[str, ...]
    measured_since: date | None
    season_kind: str | None = (
        None  # ``seasons.HEATING`` or ``seasons.COOLING``; None: no season
    )
    season_dates: tuple[str, str] | None = (
        None  # the ``MM-DD`` start and end of that kind
    )
    factor: float = (
        1.0  # unit factor of the efficiency (``BTU_PER_WH`` for Cooling in BTU/Wh)
    )
    defrost_ids: tuple[
        str, ...
    ] = ()  # defrost heat statistics subtracted from the output (design D4)

    @property
    def ids(self) -> frozenset[str]:
        """Output and electrical statistics: they decide the effective start and the windows."""
        return frozenset(self.output_ids) | frozenset(self.electrical_ids)

    @property
    def all_ids(self) -> frozenset[str]:
        """``ids`` plus the defrost statistics: everything that is read for the service."""
        return self.ids | frozenset(self.defrost_ids)


@dataclass(frozen=True)
class BoundaryRead:
    """One cached boundary read (design D4).

    ``readings``: ``{statistic_id: sum}`` of every statistic that has a reading,
    computed at the read (``reading_or_reason``), or None when the read failed.
    ``first_hours``: those statistics' first statistics hours at the read, so a
    moved first hour is noticed. ``read_at``: the ``now`` of the update that read it.
    ``reasons``: ``{statistic_id: PENDING or NO_ROW}`` of every statistic read
    without a reading.
    """

    readings: Mapping[str, float] | None
    first_hours: Mapping[str, datetime | None]
    read_at: datetime
    reasons: Mapping[str, str] = field(default_factory=dict)


@dataclass
class EngineState:
    """The cache and the diagnostics of one entry; lost on reload by design."""

    tables: dict[str, eff.TableRead] = field(default_factory=dict)
    first_hours: dict[str, datetime | None] = field(default_factory=dict)
    # Per statistic with a first hour the ``change`` of its first hourly row (design D12);
    # refreshed with ``first_hours`` and used for the defrost statistics only.
    baselines: dict[str, float] = field(default_factory=dict)
    first_hours_read_at: datetime | None = None
    metadata: list[Mapping[str, Any]] = field(default_factory=list)
    metadata_ok: bool = False  # the metadata has been read successfully at least once
    boundaries: dict[datetime, BoundaryRead] = field(
        default_factory=dict
    )  # season boundary reads
    windows: dict[str, eff.Window] = field(
        default_factory=dict
    )  # last window requested per table
    errors: dict[str, str | None] = field(
        default_factory=dict
    )  # last error per read, None if ok
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PeriodResult:
    """The values of one period sensor."""

    output_energy: float | None
    electrical_energy: float | None
    efficiency: float | None
    period_start: str | None
    includes_estimated: bool
    # The defrost correction (design D4); the defaults mean no correction.
    defrost_energy: float | None = None
    efficiency_uncorrected: float | None = None
    defrost_since: str | None = (
        None  # ISO in the time zone; set when the period starts before the defrost statistics
    )
    corrected: bool = False  # the service has defrost statistics


@dataclass(frozen=True)
class SeasonResult:
    """The values of one season sensor (design D3, D7).

    The shown season is the current one while a season runs and the last one
    between seasons. ``efficiency`` and the energies are None when unknown or when
    no season has begun (``period_start`` and ``season_end`` are then None too).
    ``period_start`` is the covered start and ``season_end`` the natural end (ISO,
    in the time zone). ``points`` is the whole history, oldest first
    (``seasons.season_points``).
    """

    efficiency: float | None
    output_energy: float | None
    electrical_energy: float | None
    period_start: str | None
    season_end: str | None
    includes_estimated: bool
    complete: bool
    ended: bool
    points: list[dict[str, Any]]
    defrost_energy: float | None = None
    efficiency_uncorrected: float | None = None
    defrost_since: str | None = None
    corrected: bool = False


@dataclass(frozen=True)
class ServiceResult:
    """The four periods and both series of one service or Overall, and its season."""

    periods: dict[str, PeriodResult]
    daily: list[dict[str, Any]]
    monthly: list[dict[str, Any]]
    effective_start: str | None
    season: SeasonResult | None = (
        None  # None for a service without a season (Hot water)
    )
    defrost_ids: tuple[str, ...] = ()  # diagnostics (design D8)
    defrost_start: str | None = (
        None  # ISO in the time zone: from when all defrost statistics have data
    )


@dataclass(frozen=True)
class EngineResult:
    """What one update computed; the coordinator's data."""

    services: dict[str, ServiceResult]
    now: datetime
    plan: eff.CacheActions
    # Inputs of the statistics health check (issues, group 4).
    last_row_ends: dict[str, float | None]
    hourly_only: frozenset[str]
    metadata: tuple[Mapping[str, Any], ...]


def _describe(err: BaseException) -> str:
    return f"{type(err).__name__}: {err}"


def error_changes(
    previous: Mapping[str, str | None], current: Mapping[str, str | None]
) -> list[tuple[str, str | None, str | None]]:
    """The reads whose error appeared, changed or cleared: (key, old, new), sorted by key."""
    return [
        (key, previous.get(key), current.get(key))
        for key in sorted(set(previous) | set(current))
        if previous.get(key) != current.get(key)
    ]


def services_of(mapping: Mapping[str, Any]) -> list[Service]:
    """The configured services (output and electricity both mapped), in form order.

    A service with a season kind gets the dates of that kind from the ``seasons``
    section; without valid dates (an entry that has none) it gets no season.
    Cooling gets the BTU/Wh factor when its unit says so; the others 1.0. Heating and
    Hot water get their own defrost statistics, Overall the union of both in form
    order, Cooling none (design D4).
    """
    result = []
    seasons = mapping.get(val.SECTION_SEASONS) or {}
    dates_valid = val.season_dates_valid(mapping)
    btu = val.cooling_unit(mapping) == val.UNIT_BTU_PER_WH
    for key in val.configured_services(mapping):
        kind = SEASON_KINDS.get(key)
        if key == val.SERVICE_OVERALL:
            defrost = tuple(
                dict.fromkeys(
                    i for s in val.DEFROST_SERVICES for i in val.defrost_ids(mapping, s)
                )
            )
        else:
            defrost = tuple(val.defrost_ids(mapping, key))
        entry = mapping[key]
        since = None
        if raw := entry.get(val.FIELD_MEASURED_SINCE):
            try:
                since = date.fromisoformat(str(raw))
            except ValueError:
                since = None
        result.append(
            Service(
                key,
                tuple(entry[val.FIELD_OUTPUT]),
                tuple(entry[val.FIELD_ELECTRICITY]),
                since,
                kind if dates_valid else None,
                (seasons[f"{kind}_start"], seasons[f"{kind}_end"])
                if dates_valid and kind
                else None,
                eff.BTU_PER_WH if key == val.SERVICE_COOLING and btu else 1.0,
                defrost,
            )
        )
    return result


def mapped_ids(mapping: Mapping[str, Any]) -> list[str]:
    """Every statistic of every configured service, sorted (design D9).

    Output, electrical and defrost statistics (``Service.all_ids``) of each service
    from ``services_of``, so a defrost statistic gets the health check like any other.
    A defrost value that corrects nothing (no service uses it) is not included; one in
    an unconfigured Heating or Hot water section is, through Overall.
    """
    return sorted(frozenset().union(*(s.all_ids for s in services_of(mapping))))


# --- first statistics hours ------------------------------------------------


def _month_after(day: date) -> date:
    return (
        date(day.year + 1, 1, 1)
        if day.month == 12
        else date(day.year, day.month + 1, 1)
    )


def _local_midnight(day: date, tz: tzinfo) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(eff.UTC)


async def _first_hour(
    reader: Reader, statistic_id: str, month_rows: Sequence[eff.Row] | None, tz: tzinfo
) -> tuple[datetime, float | None] | None:
    """The first hourly row start of one statistic and its ``change`` (design D12), or None.

    Read from its first month row, then its first day row and that day's hourly rows. The
    change of the first hourly row is the statistic's baseline: Home Assistant computes it
    against a previous sum of 0, so it equals that row's sum. None for a statistic without a
    month row; the baseline is None when that row has no change.
    """
    if not month_rows:
        return None
    ids = frozenset({statistic_id})
    month_start = datetime.fromtimestamp(
        min(float(r["start"]) for r in month_rows), eff.UTC
    )
    first_day = month_start.astimezone(tz).date()
    days = (
        await reader.read(
            eff.SOURCE_DAY,
            ids,
            eff.Window(month_start, _local_midnight(_month_after(first_day), tz)),
            READ_UNITS,
            READ_TYPES,
        )
    ).get(statistic_id)
    if not days:
        raise LookupError("a month row has no day row")
    day_start = datetime.fromtimestamp(min(float(r["start"]) for r in days), eff.UTC)
    day = day_start.astimezone(tz).date()
    hours = (
        await reader.read(
            eff.SOURCE_HOUR,
            ids,
            eff.Window(day_start, _local_midnight(day + timedelta(days=1), tz)),
            READ_UNITS,
            READ_TYPES,
        )
    ).get(statistic_id)
    if not hours:
        raise LookupError("a day row has no hour row")
    first = min(hours, key=lambda r: float(r["start"]))
    change = first.get("change")
    return datetime.fromtimestamp(
        float(first["start"]), eff.UTC
    ), None if change is None else float(change)


def first_hours_window(
    now: datetime,
    tz: tzinfo,
    full_history: bool = False,
    known: Mapping[str, datetime | None] | None = None,
) -> eff.Window:
    """The window of the first-hours ``month`` read (design D3, D4).

    Inputs: ``now``, the time zone, ``full_history`` and ``known`` (the first hours
    of the last successful read since the load; None before it). Without
    ``full_history``: from the start of the ``month`` window that
    ``history_windows`` gives without an effective start (the oldest month any
    period or series can need) to now. A statistic whose first hour lies before
    that start is reported as that start (its first hourly row in the window), which
    changes no period or series: its effective start is then not after any period's
    or point's start. The window starts one calendar month earlier (the statistics-day
    start of the 1st of the previous month), so a statistic that lacks the first hourly
    row at the month window's start still has its first hour inside the window and
    does not move the effective start of the oldest monthly point.

    ``full_history`` (seasons are configured): the window starts at ``HISTORY_FLOOR``,
    so a first hour older than the series is known and the season history starts at
    the real start of the statistics. Home Assistant builds the ``month`` rows from
    the hourly rows of the window, so the whole history is read only when no first
    hour is known (the first successful read after a load): later the window ends
    at the end of the local month of the latest known first hour (at most now),
    which still sees a backfill that moves a first hour earlier. A statistic
    without a row in that bounded window is read again over the whole history
    (``read_first_hours``).
    """
    current = now.astimezone(eff.UTC)
    if full_history:
        start = min(HISTORY_FLOOR, current)
        hours = [hour for hour in (known or {}).values() if hour is not None]
        if not hours:
            return eff.Window(start, current)
        month_after = _month_after(max(hours).astimezone(tz).date())
        return eff.Window(start, min(eff.day_start(month_after, tz), current))
    windows = eff.history_windows(now, tz)
    start = windows.get(
        eff.SOURCE_MONTH, windows.get(eff.SOURCE_DAY, windows[eff.SOURCE_5MINUTE])
    ).start
    first = eff.statistics_day(start, tz).replace(day=1)
    previous = (
        date(first.year - 1, 12, 1)
        if first.month == 1
        else date(first.year, first.month - 1, 1)
    )
    return eff.Window(min(eff.day_start(previous, tz), current), current)


async def read_first_hours(
    reader: Reader,
    statistic_ids: Iterable[str],
    now: datetime,
    tz: tzinfo,
    full_history: bool = False,
    known: Mapping[str, datetime | None] | None = None,
) -> tuple[dict[str, datetime | None], dict[str, float], dict[str, str]]:
    """The first statistics hour and baseline per ID, and the error per ID that could not be read.

    Inputs: the reader, the mapped IDs, ``now``, the time zone, ``full_history`` and
    ``known`` (``first_hours_window``). One ``month`` read for all IDs over
    ``first_hours_window``; when that window is bounded (``full_history`` with known
    first hours), one more ``month`` read over the whole history for the IDs without
    a row in it. Then per ID a ``day`` read in its first month and an ``hour`` read
    in its first day. An ID without any hourly row maps to None (a successful
    read); an ID whose reads failed is only in the errors. The baselines (design D12) are
    the ``change`` of each first hourly row, from that same hour read (no extra read);
    an ID without a first hour has none.
    """
    ids = frozenset(statistic_ids)
    if not ids:
        return {}, {}, {}
    window = first_hours_window(now, tz, full_history, known)
    try:
        months = dict(
            await reader.read(eff.SOURCE_MONTH, ids, window, READ_UNITS, READ_TYPES)
        )
    except Exception as err:  # noqa: BLE001 - a failed read is data, not an exception
        return {}, {}, {statistic_id: _describe(err) for statistic_id in sorted(ids)}
    errors: dict[str, str] = {}
    full = first_hours_window(now, tz, full_history)
    missing = frozenset(i for i in ids if not months.get(i))
    if window != full and missing:
        try:
            months.update(
                await reader.read(
                    eff.SOURCE_MONTH, missing, full, READ_UNITS, READ_TYPES
                )
            )
        except Exception as err:  # noqa: BLE001
            errors.update(
                {statistic_id: _describe(err) for statistic_id in sorted(missing)}
            )
    hours: dict[str, datetime | None] = {}
    baselines: dict[str, float] = {}
    for statistic_id in sorted(ids - frozenset(errors)):
        try:
            first = await _first_hour(
                reader, statistic_id, months.get(statistic_id), tz
            )
        except Exception as err:  # noqa: BLE001
            errors[statistic_id] = _describe(err)
            continue
        hours[statistic_id] = None if first is None else first[0]
        if first is not None and first[1] is not None:
            baselines[statistic_id] = first[1]
    return hours, baselines, errors


# --- seasons: which boundaries are read and when --------------------------------


def season_infos(
    service: Service, effective: datetime | None, now: datetime, tz: tzinfo
) -> list[sea.SeasonInfo]:
    """The seasons of a service's history (``seasons.seasons_since``); empty without a season."""
    if service.season_dates is None:
        return []
    return sea.seasons_since(
        service.season_dates[0], service.season_dates[1], effective, now, tz
    )


def boundaries_needed(
    services: Sequence[Service],
    first_hours: Mapping[str, datetime | None],
    last_row_end: Mapping[str, float | None],
    now: datetime,
    tz: tzinfo,
) -> dict[datetime, frozenset[str]]:
    """Per boundary instant the statistics whose reading a finished season needs.

    Inputs: the services, the first hours, this update's ``last_row_ends`` and
    ``now``. Every finished season of every service whose first hours are all
    known needs its covered start and natural end (``seasons.boundary_instants``)
    for all statistics of the service, the defrost statistics included. A boundary shared by services reads the
    union of their statistics.
    """
    needed: dict[datetime, set[str]] = {}
    for service in services:
        effective, known = resolve_effective(
            service, first_hours, tz, last_row_end, now
        )
        if not known:
            continue
        for info in season_infos(service, effective, now, tz):
            if info.ended:
                for instant in sea.boundary_instants(info):
                    needed.setdefault(instant, set()).update(service.all_ids)
    return {instant: frozenset(ids) for instant, ids in needed.items()}


def reading_or_reason(
    rows: Iterable[Mapping[str, Any]] | None,
    first_hour: datetime | None,
    last_row_end: float | None,
    boundary: datetime,
    baseline: float | None = None,
) -> float | str:
    """One statistic's reading at a boundary, or why it has none (design D4).

    Inputs as ``seasons.boundary_reading`` (``baseline``: a defrost statistic's, design D12;
    None for the others). The reading when there is one; else
    ``PENDING`` when the statistic's last row ended before the boundary or it has
    none (no 5-minute or hour rows at this update), ``NO_ROW`` when it is covered
    but has no hourly row (with a ``sum``) in the window before the boundary while
    its first statistics hour lies before it.
    """
    reading = sea.boundary_reading(rows, first_hour, last_row_end, boundary, baseline)
    if reading is not None:
        return reading
    if last_row_end is None or float(last_row_end) < eff.ts(boundary, "boundary"):
        return PENDING
    return NO_ROW


def boundary_actions(
    boundaries: Mapping[datetime, BoundaryRead],
    needed: Mapping[datetime, frozenset[str]],
    first_hours: Mapping[str, datetime | None],
    now: datetime,
    tz: tzinfo,
    last_row_end: Mapping[str, float | None] | None = None,
) -> list[datetime]:
    """The boundary instants to read at this update, oldest first (design D4).

    Inputs: the cached boundary reads, the needed boundaries (``boundaries_needed``),
    the current first hours, ``now``, the time zone and this update's
    ``last_row_ends`` (None: no statistic has rows). A boundary is read when it is
    not cached; when its read failed (at every update until it works); when a needed
    statistic's reading is ``PENDING`` and its last row now ends at or after the
    boundary; when the read was made before the end of the boundary's own
    statistics day and a day has passed since (the first update of the next day,
    when the hourly row before the boundary is certainly compiled); and when a
    needed statistic's first hour is not the one the read saw. A ``NO_ROW`` reading
    is final, like a good one, and a read made on or after the day after the
    boundary is not repeated.
    """
    current = eff.aware(now, "now")
    ends = last_row_end or {}
    reads = []
    for instant in sorted(needed):
        cached = boundaries.get(instant)
        ids = needed[instant]
        if cached is None or cached.readings is None:
            reads.append(instant)
            continue
        b = eff.ts(instant, "boundary")
        settled = eff.day_start(eff.statistics_day(instant, tz) + timedelta(days=1), tz)
        if (
            any(i not in cached.readings and i not in cached.reasons for i in ids)
            or any(
                cached.reasons.get(i) == PENDING
                and ends.get(i) is not None
                and float(ends[i]) >= b
                for i in ids
            )
            or any(
                i not in cached.first_hours
                or cached.first_hours[i] != first_hours.get(i)
                for i in ids
            )
            or cached.read_at < settled <= current
        ):
            reads.append(instant)
    return reads


def after_failed_read(
    cached: BoundaryRead | None,
    first_hours: Mapping[str, datetime | None],
    now: datetime,
) -> BoundaryRead:
    """The cache entry of a boundary whose read failed at this update (design D4).

    Inputs: the earlier entry (None when there is none), the first hours of the
    boundary's statistics at this update and ``now``. An earlier entry with readings
    that saw the same first hours is kept (a re-read for the next-day rule or for a
    pending reading): its good readings stay, and the rule that asked for the read
    asks again at the next update. Otherwise (no entry, a failed one, or changed
    first hours) a failed read without readings, read again at the next update.
    """
    if (
        cached is not None
        and cached.readings is not None
        and dict(cached.first_hours) == dict(first_hours)
    ):
        return cached
    return BoundaryRead(None, dict(first_hours), now)


async def _refresh_boundaries(
    state: EngineState,
    reader: Reader,
    services: Sequence[Service],
    last_row_end: Mapping[str, float | None],
    now: datetime,
    tz: tzinfo,
) -> None:
    """Read the boundaries ``boundary_actions`` asks for and drop the ones no longer needed.

    One ``hour`` read of the ``sum`` per boundary over the 31 days before it, for all
    statistics that need it; per statistic a reading or a reason (``reading_or_reason``,
    with its last row end at this update). A failed read is cached by
    ``after_failed_read`` and its error kept in ``errors``; it never raises.
    """
    needed = boundaries_needed(services, state.first_hours, last_row_end, now, tz)
    defrost = frozenset().union(*(frozenset(s.defrost_ids) for s in services))
    for instant in [i for i in state.boundaries if i not in needed]:
        del state.boundaries[instant]
    errors = []
    for instant in boundary_actions(
        state.boundaries, needed, state.first_hours, now, tz, last_row_end
    ):
        ids = needed[instant]
        first_hours = {i: state.first_hours.get(i) for i in sorted(ids)}
        window = eff.Window(instant - sea.BOUNDARY_WINDOW, instant)
        try:
            rows = await reader.read(
                eff.SOURCE_HOUR, ids, window, BOUNDARY_UNITS, BOUNDARY_TYPES
            )
        except Exception as err:  # noqa: BLE001 - a failed read is data, not an exception
            errors.append(f"{instant.isoformat()}: {_describe(err)}")
            state.boundaries[instant] = after_failed_read(
                state.boundaries.get(instant), first_hours, now
            )
            continue
        values = {
            i: reading_or_reason(
                rows.get(i),
                # A statistic with rows but no hourly row yet counts as starting now (design D4);
                # the cache keeps the raw first hour, so the next day's refresh reads it again.
                now
                if first_hours[i] is None and last_row_end.get(i) is not None
                else first_hours[i],
                last_row_end.get(i),
                instant,
                state.baselines.get(i)
                if i in defrost
                else None,  # only a defrost statistic has one (D12)
            )
            for i in sorted(ids)
        }
        state.boundaries[instant] = BoundaryRead(
            {i: v for i, v in values.items() if not isinstance(v, str)},
            first_hours,
            now,
            {i: v for i, v in values.items() if isinstance(v, str)},
        )
    state.errors[ERROR_BOUNDARIES] = "; ".join(errors) or None


# --- the update --------------------------------------------------------------


def resolve_effective(
    service: Service,
    first_hours: Mapping[str, datetime | None],
    tz: tzinfo,
    last_row_end: Mapping[str, float | None] | None = None,
    now: datetime | None = None,
) -> tuple[datetime | None, bool]:
    """The service's effective start and whether every first hour has been read.

    A statistic whose first-hours read found no hourly row (None) and that has
    rows in this update's 5-minute or hour read (``last_row_end``, with ``now``)
    counts as starting now (``effective_start``), so its service's periods have not
    begun until the next first-hours refresh. Without such rows it has no rows at
    all and is left out: ``coverage_end`` and ``period_energy`` make its service
    unknown. Without ``last_row_end`` (the read windows) it is left out too, which
    only widens the windows. A statistic whose first hour could not be read is not
    known: its service must be unknown, because an unlimited period would be
    partial. The start is taken from the output and electrical statistics only (a
    defrost statistic never moves it), but every statistic of the service, the
    defrost ones included, must be known (``defrost_start`` needs them).
    """
    known = all(statistic_id in first_hours for statistic_id in service.all_ids)
    hours: list[datetime | None] = []
    for statistic_id in sorted(service.ids):
        hour = first_hours.get(statistic_id)
        if hour is not None:
            hours.append(hour)
        elif (
            statistic_id in first_hours
            and last_row_end is not None
            and last_row_end.get(statistic_id) is not None
        ):
            hours.append(None)  # rows, but no hourly row yet: starts now
    return eff.effective_start(hours, tz, now), known


def needed_windows(
    services: Sequence[Service],
    state: EngineState,
    hourly_only_ids: frozenset[str],
    now: datetime,
    tz: tzinfo,
) -> dict[str, eff.Window]:
    """The windows to read per table, from the effective starts (``history_windows``)."""
    starts = [
        resolve_effective(service, state.first_hours, tz)[0] for service in services
    ]
    hourly = any(
        eff.reads_hourly(service.all_ids, hourly_only_ids) for service in services
    )
    # The month and day windows include each service's running season (design D3).
    running = []
    for service, start in zip(services, starts, strict=True):
        infos = season_infos(service, start, now, tz)
        if infos and not infos[-1].ended:
            running.append(infos[-1].covered_start)
    return eff.history_windows(now, tz, starts or (None,), hourly, running)


def _read_ids(
    source: str,
    services: Sequence[Service],
    all_ids: frozenset[str],
    hourly_only_ids: frozenset[str],
) -> frozenset[str]:
    """The statistics to read from a table.

    ``5minute``: those that have 5-minute rows. ``hour``: every statistic of a
    service that reads hourly (``reads_hourly``; its periods end at the hourly
    coverage end). History tables: all.
    """
    if source == eff.SOURCE_5MINUTE:
        return all_ids - hourly_only_ids
    if source == eff.SOURCE_HOUR:
        return frozenset().union(
            *(
                s.all_ids
                for s in services
                if eff.reads_hourly(s.all_ids, hourly_only_ids)
            )
        )
    return all_ids


async def _refresh_metadata(
    state: EngineState, reader: Reader, all_ids: frozenset[str]
) -> None:
    """Read the metadata (every update, design D4); a failure keeps the last good metadata.

    ``metadata_ok`` is set by the first successful read and stays set; the error
    of a failed read is kept in ``errors``.
    """
    try:
        state.metadata = list(await reader.metadata(all_ids))
        state.metadata_ok = True
        state.errors[ERROR_METADATA] = None
    except Exception as err:  # noqa: BLE001 - a failed read is data, not an exception
        state.errors[ERROR_METADATA] = _describe(err)


async def _refresh_first_hours(
    state: EngineState,
    reader: Reader,
    base_ids: frozenset[str],
    defrost_ids: frozenset[str],
    now: datetime,
    tz: tzinfo,
    full_history: bool = False,
) -> None:
    """Read the first hours per group; keep the old value of every ID that failed.

    The groups are the output and electrical IDs (``base_ids``) and the defrost IDs
    (``defrost_ids``, the ones not in the first group), each read with the
    first hours known for its own group (``first_hours_window``): a recent defrost
    statistic would otherwise make the bounded window reach the current month and
    stream the whole hourly history of every other statistic (design D4).

    ``first_hours_read_at`` moves only when every ID of both groups was read, so a
    failure is retried at every update. Until an ID has been read once its services are
    unknown; after that its last good first hour is kept (a backfill that moves
    a first hour shows once a refresh succeeds). A statistic that exists again later in the day
    keeps the entry of this read (None when it had no rows) until the next
    first-hours refresh, so its service stays not begun or unknown until then.
    With ``full_history`` the read covers the whole history until a read has
    succeeded for every ID, and is bounded by the first hours known since
    (``first_hours_window``).
    """
    read_before = state.first_hours_read_at is not None
    all_errors: dict[str, str] = {}
    for group in (base_ids, defrost_ids):
        known = (
            {i: h for i, h in state.first_hours.items() if i in group}
            if read_before
            else None
        )
        hours, baselines, errors = await read_first_hours(
            reader, group, now, tz, full_history, known
        )
        state.first_hours.update(hours)
        for (
            statistic_id,
            hour,
        ) in hours.items():  # refreshed with the first hours (design D12)
            if hour is None or statistic_id not in baselines:
                state.baselines.pop(statistic_id, None)
            else:
                state.baselines[statistic_id] = baselines[statistic_id]
        all_errors.update(errors)
    state.errors[ERROR_FIRST_HOURS] = (
        "; ".join(
            f"{statistic_id}: {text}"
            for statistic_id, text in sorted(all_errors.items())
        )
        or None
    )
    if not all_errors:
        state.first_hours_read_at = now


async def _read_table(
    state: EngineState,
    reader: Reader,
    source: str,
    ids: frozenset[str],
    window: eff.Window,
    last_row_end: Mapping[str, float | None] | None,
    now: datetime,
) -> None:
    """Read one table over ``window`` and cache it; a failure is cached as a failed read.

    ``last_row_end`` (``last_row_ends`` of the mapped IDs, from reads made earlier in
    this update) gives the coverage of a history table; None for the recent tables.
    """
    state.windows[source] = window
    rows: Mapping[str, Sequence[eff.Row]] | None
    try:
        rows = (
            await reader.read(source, ids, window, READ_UNITS, READ_TYPES)
            if ids
            else {}
        )
        state.errors[source] = None
    except Exception as err:  # noqa: BLE001
        rows = None
        state.errors[source] = _describe(err)
    covered = frozenset()
    if rows is not None and last_row_end is not None:
        covered = eff.coverage(list(last_row_end), window, last_row_end)
    state.tables[source] = eff.TableRead(source, window, rows, covered, now)


async def async_update(
    state: EngineState,
    mapping: Mapping[str, Any],
    reader: Reader,
    now: datetime,
    tz: tzinfo,
) -> EngineResult:
    """Run one update: decide the reads (``cache_actions``), make them, compute the result.

    Inputs: the cache state (mutated), the normalized mapping, the reader, ``now``
    (aware) and the time zone. Never raises for a failed read.
    """
    services = services_of(mapping)
    all_ids: frozenset[str] = frozenset().union(*(s.all_ids for s in services))
    if not services:
        return _empty(now)
    # The metadata first: it decides which statistics are hourly-only, and so whether
    # the hour table is needed and which statistics each recent table reads.
    await _refresh_metadata(state, reader, all_ids)
    hourly_only_ids = eff.hourly_only(state.metadata)
    needed = needed_windows(services, state, hourly_only_ids, now, tz)
    actions = eff.cache_actions(
        state.tables, state.first_hours_read_at, needed, all_ids, now, tz
    )
    if actions.first_hours:
        # With seasons the first hours reach back to the real start of the statistics
        # (the whole history once per load, then bounded; ``first_hours_window``).
        full_history = any(service.season_dates is not None for service in services)
        base_ids: frozenset[str] = frozenset().union(*(s.ids for s in services))
        await _refresh_first_hours(
            state, reader, base_ids, all_ids - base_ids, now, tz, full_history
        )
        needed = needed_windows(services, state, hourly_only_ids, now, tz)
        actions = eff.cache_actions(
            state.tables, state.first_hours_read_at, needed, all_ids, now, tz
        )
    # Drop tables no longer needed (the hour table once no service is hourly-only).
    for source in [s for s in state.tables if s not in needed]:
        del state.tables[source]
    for source in RECENT_SOURCES:
        if source in actions.tables:
            ids = _read_ids(source, services, all_ids, hourly_only_ids)
            await _read_table(state, reader, source, ids, needed[source], None, now)
    last_ends = eff.last_row_ends(all_ids, hourly_only_ids, state.tables)
    for source in eff.HISTORY_SOURCES:
        if source in actions.tables:
            await _read_table(
                state, reader, source, all_ids, needed[source], last_ends, now
            )
    if state.metadata_ok:
        await _refresh_boundaries(state, reader, services, last_ends, now, tz)
    state.updated_at = now
    return compute(state, services, actions, now, tz)


def _empty(now: datetime) -> EngineResult:
    return EngineResult({}, now, eff.CacheActions(frozenset()), {}, frozenset(), ())


def compute(
    state: EngineState,
    services: Sequence[Service],
    actions: eff.CacheActions,
    now: datetime,
    tz: tzinfo,
) -> EngineResult:
    """The period results and series of every service from the cached reads.

    Every service is unknown until the metadata has been read successfully once
    (``metadata_ok``): before that an hourly-only statistic would be taken for a
    recorder statistic.
    """
    all_ids: frozenset[str] = frozenset().union(*(s.all_ids for s in services))
    hourly_only_ids = eff.hourly_only(state.metadata)
    last_ends = eff.last_row_ends(all_ids, hourly_only_ids, state.tables)
    results: dict[str, ServiceResult] = {}
    for service in services:
        effective, known = resolve_effective(
            service, state.first_hours, tz, last_ends, now
        )
        results[service.key] = (
            _service_result(
                state, service, effective, hourly_only_ids, last_ends, now, tz
            )
            if known and state.metadata_ok
            else _unknown_result(service)
        )
    return EngineResult(
        results,
        now,
        actions,
        last_ends,
        hourly_only_ids,
        tuple(state.metadata),
    )


def _unknown_result(service: Service) -> ServiceResult:
    corrected = bool(service.defrost_ids)
    unknown = PeriodResult(None, None, None, None, False, corrected=corrected)
    season = (
        None
        if service.season_dates is None
        else _season_result([], [], corrected=corrected)
    )
    return ServiceResult(
        dict.fromkeys(eff.PERIODS, unknown), [], [], None, season, service.defrost_ids
    )


def _readings_at(state: EngineState, instant: datetime) -> Mapping[str, float | None]:
    """The cached readings at a boundary; empty when it was not read or the read failed."""
    cached = state.boundaries.get(instant)
    return {} if cached is None or cached.readings is None else cached.readings


def _season_result(
    infos: Sequence[sea.SeasonInfo],
    points: list[dict[str, Any]],
    uncorrected: float | None = None,
    defrost_since: datetime | None = None,
    tz: tzinfo | None = None,
    corrected: bool = False,
) -> SeasonResult:
    """The season sensor values: the last season of the history is the one shown.

    ``uncorrected`` is the last season's efficiency without the defrost correction,
    ``defrost_since`` the defrost start (the ``defrost_since`` of the result only when
    the shown point is ``defrost_partial``); both only for a service with defrost IDs.
    """
    if not infos:
        return SeasonResult(
            None, None, None, None, None, False, False, False, [], corrected=corrected
        )
    info, point = infos[-1], points[-1]
    since = None
    if (
        corrected
        and defrost_since is not None
        and tz is not None
        and point.get("defrost_partial")
    ):
        since = defrost_since.astimezone(tz).isoformat()
    return SeasonResult(
        point["efficiency"],
        point["output_energy"],
        point["electrical_energy"],
        point["start"],
        point["end"],
        point["estimated"],
        info.complete,
        info.ended,
        points,
        point.get("defrost_energy"),
        uncorrected,
        since,
        corrected,
    )


def _defrost_start(
    service: Service,
    first_hours: Mapping[str, datetime | None],
    last_row_end: Mapping[str, float | None],
    now: datetime,
) -> datetime | None:
    """From when all the service's defrost statistics have data (``efficiency.defrost_start``).

    As ``resolve_effective`` takes the first hours: a known hour as is; a statistic with
    rows in this update's reads but no hourly row yet counts as starting now; one
    without rows is left out. None without defrost IDs or hours.
    """
    hours: list[datetime | None] = []
    for statistic_id in sorted(service.defrost_ids):
        hour = first_hours.get(statistic_id)
        if hour is not None:
            hours.append(hour)
        elif statistic_id in first_hours and last_row_end.get(statistic_id) is not None:
            hours.append(None)
    return eff.defrost_start(hours, now)


def _defrost_firsts(
    state: EngineState, service: Service
) -> dict[str, tuple[datetime, float]]:
    """The first hour and baseline of the service's defrost statistics (design D12).

    Only a defrost statistic with a known first hour and baseline; the baseline is applied
    to these statistics only, so a service without defrost IDs is unchanged.
    """
    return {
        statistic_id: (hour, state.baselines[statistic_id])
        for statistic_id in service.defrost_ids
        if (hour := state.first_hours.get(statistic_id)) is not None
        and statistic_id in state.baselines
    }


def _service_season(
    state: EngineState,
    service: Service,
    effective: datetime | None,
    end: datetime,
    hourly: bool,
    defrost_start: datetime | None,
    now: datetime,
    tz: tzinfo,
) -> SeasonResult | None:
    """A service's season result: the running season from the tables, finished ones from readings.

    With defrost IDs each season's defrost energy is added: ``seasons.season_energy`` of
    the boundary readings for a finished season (0.0 before the defrost statistic's
    first hour, ``seasons.boundary_reading``; its baseline when the season starts before it),
    ``efficiency.period_energy`` of the tables for the running one (counting from the end of
    the first hour, design D12). Without them the points are unchanged.
    """
    if service.season_dates is None:
        return None
    infos = season_infos(service, effective, now, tz)
    firsts = _defrost_firsts(state, service)
    energies: list[tuple[float | None, float | None]] = []
    defrost: list[float | None] = []
    for info in infos:
        if info.ended:
            start_readings = _readings_at(state, info.covered_start)
            end_readings = _readings_at(state, info.natural_end)
            energies.append(
                (
                    sea.season_energy(start_readings, end_readings, service.output_ids),
                    sea.season_energy(
                        start_readings, end_readings, service.electrical_ids
                    ),
                )
            )
            defrost.append(
                sea.season_energy(start_readings, end_readings, service.defrost_ids)
            )
        else:
            ranges = sea.running_ranges(info, now, tz, end, hourly)
            energies.append(
                (None, None)
                if ranges is None
                else (
                    eff.period_energy(state.tables, service.output_ids, ranges),
                    eff.period_energy(state.tables, service.electrical_ids, ranges),
                )
            )
            defrost.append(
                None
                if ranges is None
                else eff.period_energy(
                    state.tables, service.defrost_ids, ranges, firsts
                )
            )
    if not service.defrost_ids:
        return _season_result(
            infos,
            sea.season_points(
                infos, energies, service.measured_since, tz, service.factor
            ),
        )
    points = sea.season_points(
        infos,
        energies,
        service.measured_since,
        tz,
        service.factor,
        defrost,
        defrost_start,
    )
    uncorrected = eff.ratio(*energies[-1], service.factor) if energies else None
    return _season_result(infos, points, uncorrected, defrost_start, tz, True)


def _service_result(
    state: EngineState,
    service: Service,
    effective: datetime | None,
    hourly_only_ids: frozenset[str],
    last_row_end: Mapping[str, float | None],
    now: datetime,
    tz: tzinfo,
) -> ServiceResult:
    hourly = eff.reads_hourly(service.all_ids, hourly_only_ids)
    end = eff.coverage_end(service.all_ids, hourly_only_ids, state.tables, now)
    ranges = eff.period_ranges(now, tz, effective, end, hourly)
    starts = eff.period_starts(now, tz, effective, end, hourly)
    corrected = bool(service.defrost_ids)
    defrost_start = _defrost_start(service, state.first_hours, last_row_end, now)
    firsts = _defrost_firsts(state, service)
    periods: dict[str, PeriodResult] = {}
    for period in eff.PERIODS:
        summary = eff.period_summary(
            state.tables,
            ranges[period],
            service.output_ids,
            service.electrical_ids,
            service.factor,
            service.defrost_ids,
            firsts,
        )
        start = starts[period]
        since = None
        if corrected and eff.defrost_partial(start, defrost_start):
            since = defrost_start.astimezone(tz).isoformat()
        periods[period] = PeriodResult(
            summary["output_energy"],
            summary["electrical_energy"],
            summary["efficiency"],
            None if start is None else start.isoformat(),
            eff.includes_estimated(start, service.measured_since, tz),
            summary.get("defrost_energy"),
            summary.get("efficiency_uncorrected"),
            since,
            corrected,
        )
    args = (
        state.tables,
        service.output_ids,
        service.electrical_ids,
        now,
        tz,
        effective,
        service.measured_since,
        end,
        hourly,
        service.factor,
        service.defrost_ids,
        defrost_start,
        firsts,
    )
    return ServiceResult(
        periods,
        eff.daily_series(*args),
        eff.monthly_series(*args),
        None if effective is None else effective.isoformat(),
        _service_season(state, service, effective, end, hourly, defrost_start, now, tz),
        service.defrost_ids,
        None if defrost_start is None else defrost_start.astimezone(tz).isoformat(),
    )


# --- diagnostics ---------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def diagnostics_data(state: EngineState, result: EngineResult | None) -> dict[str, Any]:
    """Return the JSON-safe diagnostics.

    The data: metadata, last windows, cached energies, the defrost IDs, start, first hours
    and baselines per service, boundary reads, season points and last errors.

    Inputs: the engine state and the last result (None before the first update).
    """
    tables = {
        source: {
            "window": {
                "start": _iso(table.window.start),
                "end": _iso(table.window.end),
            },
            "read_at": _iso(table.read_at),
            "ok": table.rows is not None,
            "covered": sorted(table.covered),
            "rows": {}
            if table.rows is None
            else {k: len(v) for k, v in sorted(table.rows.items())},
        }
        for source, table in sorted(state.tables.items())
    }
    energies = {
        key: {
            period: {
                "output_energy": p.output_energy,
                "electrical_energy": p.electrical_energy,
                "efficiency": p.efficiency,
                "period_start": p.period_start,
                "includes_estimated": p.includes_estimated,
                **(
                    {
                        "defrost_energy": p.defrost_energy,
                        "efficiency_uncorrected": p.efficiency_uncorrected,
                        "defrost_since": p.defrost_since,
                    }
                    if p.corrected
                    else {}
                ),
            }
            for period, p in service.periods.items()
        }
        for key, service in ({} if result is None else result.services).items()
    }
    defrost = {
        key: {
            "ids": list(service.defrost_ids),
            "since": service.defrost_start,
            # Each defrost statistic's baseline next to its first hour (design D12).
            **(
                {
                    "first_hours": {
                        i: _iso(state.first_hours.get(i))
                        for i in sorted(service.defrost_ids)
                    },
                    "baselines": {
                        i: state.baselines.get(i) for i in sorted(service.defrost_ids)
                    },
                }
                if service.defrost_ids
                else {}
            ),
        }
        for key, service in ({} if result is None else result.services).items()
    }
    boundaries = {
        _iso(instant): {
            "readings": None
            if read.readings is None
            else dict(sorted(read.readings.items())),
            "reasons": dict(sorted(read.reasons.items())),
            "first_hours": {k: _iso(v) for k, v in sorted(read.first_hours.items())},
            "read_at": _iso(read.read_at),
        }
        for instant, read in sorted(state.boundaries.items())
    }
    seasons = {
        key: {
            "efficiency": service.season.efficiency,
            "period_start": service.season.period_start,
            "season_end": service.season.season_end,
            "complete": service.season.complete,
            "ended": service.season.ended,
            "points": list(service.season.points),
            **(
                {
                    "defrost_energy": service.season.defrost_energy,
                    "efficiency_uncorrected": service.season.efficiency_uncorrected,
                    "defrost_since": service.season.defrost_since,
                }
                if service.season.corrected
                else {}
            ),
        }
        for key, service in ({} if result is None else result.services).items()
        if service.season is not None
    }
    return {
        "metadata": [dict(m) for m in state.metadata],
        "first_hours": {k: _iso(v) for k, v in sorted(state.first_hours.items())},
        "first_hours_read_at": _iso(state.first_hours_read_at),
        "updated_at": _iso(state.updated_at),
        "windows": {
            source: {"start": _iso(w.start), "end": _iso(w.end)}
            for source, w in sorted(state.windows.items())
        },
        "tables": tables,
        "energies": energies,
        "defrost": defrost,
        "boundaries": boundaries,
        "seasons": seasons,
        "errors": dict(sorted(state.errors.items())),
    }
