"""Pure season arithmetic for the heat pump efficiency integration.

Standard library only (plus the pure ``efficiency`` module): nothing here
imports Home Assistant. Every datetime argument must be timezone aware.

A season runs from the start of its start day to the end of its end day, as
statistics days (``efficiency.day_start``), recurring every year; its UTC range
is [day_start(start day), day_start(end day + 1 day)), so it telescopes with
days and months. A season whose start (month, day) is after its end's crosses
the new year.

Boundary readings. A finished season is computed from the running ``sum`` of
each statistic at its two boundary instants instead of from days: the reading
at ``b`` is the ``sum`` of the newest hourly row that starts before ``b``. The
hourly ``change`` is a row's ``sum`` minus the previous row's, so the
difference of two readings equals the sum of the hourly changes between them,
which is what the day and month rows add up to.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from . import efficiency as eff

BOUNDARY_WINDOW = timedelta(days=31)  # how far before a boundary its hourly rows are read

HEATING = "heating"
COOLING = "cooling"
DATE_KEYS = ("heating_start", "heating_end", "cooling_start", "cooling_end")


def default_seasons(latitude: float) -> dict[str, str]:
    """The default season dates (``MM-DD`` strings) for a latitude.

    Input: the latitude in degrees (Home Assistant's 0 means not set and counts
    as northern). Latitude >= 0: heating 10-01 to 04-30, cooling 06-01 to
    09-30. Below 0: heating 04-01 to 10-31, cooling 12-01 to 02-28.
    """
    if latitude >= 0:
        return {
            "heating_start": "10-01",
            "heating_end": "04-30",
            "cooling_start": "06-01",
            "cooling_end": "09-30",
        }
    return {
        "heating_start": "04-01",
        "heating_end": "10-31",
        "cooling_start": "12-01",
        "cooling_end": "02-28",
    }


def _parse(month_day: str) -> tuple[int, int]:
    """A ``MM-DD`` string as (month, day)."""
    month, day = month_day.split("-")
    return int(month), int(day)


@dataclass(frozen=True)
class Season:
    """A season as local dates: ``start_day`` and ``end_day`` (inclusive)."""

    start_day: date
    end_day: date

    @classmethod
    def starting(cls, start_md: str, end_md: str, year: int) -> Season:
        """The season whose start day lies in ``year``.

        Inputs: the ``MM-DD`` start and end and the year of the start. The end
        falls in the next year when the start's (month, day) is after the end's.
        An end on 28 February includes 29 February when the end year is a leap
        year.
        """
        start_month, start_dom = _parse(start_md)
        end_month, end_dom = _parse(end_md)
        end_year = year if (start_month, start_dom) <= (end_month, end_dom) else year + 1
        if (end_month, end_dom) == (2, 28) and calendar.isleap(end_year):
            end_dom = 29
        return cls(date(year, start_month, start_dom), date(end_year, end_month, end_dom))

    def start(self, tz: tzinfo) -> datetime:
        """The natural start: the UTC start of the start day (input: time zone)."""
        return eff.day_start(self.start_day, tz)

    def end(self, tz: tzinfo) -> datetime:
        """The natural end (exclusive): the UTC start of the day after the end day."""
        return eff.day_start(self.end_day + timedelta(days=1), tz)


@dataclass(frozen=True)
class SeasonInfo:
    """One season of a history (UTC datetimes).

    ``natural_start`` and ``natural_end`` come from the dates; ``covered_start``
    is the later of the natural start and the effective start. ``complete``:
    covered start == natural start. ``ended``: natural end <= today's start.
    """

    season: Season
    natural_start: datetime
    natural_end: datetime
    covered_start: datetime
    complete: bool
    ended: bool


def seasons_since(
    start_md: str,
    end_md: str,
    effective: datetime | None,
    now: datetime,
    tz: tzinfo,
) -> list[SeasonInfo]:
    """Every season of the history up to the current or last one, oldest first.

    Inputs: the ``MM-DD`` start and end of the season kind, the service's
    effective start (``efficiency.effective_start``), ``now`` and the time
    zone. From the season that contains the effective start's statistics day
    (or, when that lies between seasons, the first one starting after it) up to
    the season that contains today or ended last. Empty when the effective
    start is None or no season has begun. Today is ``efficiency.statistics_day``
    of ``now``.
    """
    if effective is None:
        return []
    today = eff.statistics_day(eff.aware(now, "now"), tz)
    floor = eff.first_day_at_or_after(eff.aware(effective, "effective"), tz)
    today_start = eff.day_start(today, tz)
    result: list[SeasonInfo] = []
    for year in range(floor.year - 1, today.year + 1):
        season = Season.starting(start_md, end_md, year)
        if season.end_day < floor or season.start_day > today:
            continue
        covered_day = max(season.start_day, floor)
        if covered_day > today:
            continue
        natural_end = season.end(tz)
        result.append(
            SeasonInfo(
                season=season,
                natural_start=season.start(tz),
                natural_end=natural_end,
                covered_start=eff.day_start(covered_day, tz),
                complete=covered_day == season.start_day,
                ended=natural_end <= today_start,
            )
        )
    return result


def running_ranges(
    info: SeasonInfo,
    now: datetime,
    tz: tzinfo,
    end: datetime | None = None,
    hourly: bool = False,
) -> list[eff.Range] | None:
    """The ranges of a season that has not ended, as ``efficiency.period_ranges`` does for a year.

    Inputs: the season (``seasons_since``), ``now``, the time zone, the
    service's ``coverage_end`` (None: now) and whether it reads hourly. From
    the covered start to the coverage end (at most now), today read from the
    5-minute table or the hour table. None for an ended season, or when the
    coverage end lies before today's start.
    """
    if info.ended:
        return None
    current = eff.aware(now, "now")
    today = eff.statistics_day(current, tz)
    stop = current if end is None else min(eff.aware(end, "end"), current)
    source = eff.SOURCE_HOUR if hourly else eff.SOURCE_5MINUTE
    start_day = eff.statistics_day(info.covered_start, tz)
    return eff.span(start_day, today, tz, stop, source)


def boundary_instants(info: SeasonInfo) -> tuple[datetime, datetime]:
    """The two instants a finished season is read at: its covered start and natural end."""
    return info.covered_start, info.natural_end


def boundary_reading(
    rows: Iterable[Mapping[str, Any]] | None,
    first_hour: eff.Instant | None,
    last_row_end: float | None,
    boundary: datetime,
    baseline: float | None = None,
) -> float | None:
    """One statistic's reading (running ``sum``, kWh) at a boundary instant.

    Inputs: the statistic's hourly rows of the window before the boundary
    (dicts with epoch ``start`` and ``sum``; None when the read failed), its
    first statistics hour (aware datetime, epoch seconds or None), the end of
    its last row (epoch seconds or None) and the boundary instant. None when
    not covered: the last row end is None or before the boundary. Otherwise
    the baseline of a defrost statistic (design D12: the ``change``, here the
    ``sum``, of its first hourly row; 0.0 without one) when the first statistics
    hour is at or after the boundary; else the
    ``sum`` of the newest row that starts before the boundary, or None when
    there is none (or it has no sum).
    """
    b = eff.ts(boundary, "boundary")
    if last_row_end is None or float(last_row_end) < b:
        return None
    if first_hour is not None and eff.ts(first_hour, "first hour") >= b:
        return 0.0 if baseline is None else float(baseline)
    newest = None
    for row in rows or ():
        start = float(row["start"])
        if start < b and (newest is None or start > float(newest["start"])):
            newest = row
    if newest is None or newest.get("sum") is None:
        return None
    return float(newest["sum"])


def season_energy(
    start_readings: Mapping[str, float | None],
    end_readings: Mapping[str, float | None],
    statistic_ids: Iterable[str],
) -> float | None:
    """A finished season's energy (kWh) of ``statistic_ids`` from its two readings.

    Inputs: the readings at the covered start and at the natural end per
    statistic ID, and the IDs. The sum of end minus start per ID; None when
    there is no ID or any reading is missing or None.
    """
    ids = list(statistic_ids)
    if not ids:
        return None
    total = 0.0
    for statistic_id in ids:
        start = start_readings.get(statistic_id)
        end = end_readings.get(statistic_id)
        if start is None or end is None:
            return None
        total += end - start
    return total


def season_points(
    infos: Sequence[SeasonInfo],
    energies: Sequence[tuple[float | None, float | None]],
    measured_since: date | None,
    tz: tzinfo,
    factor: float = 1.0,
    defrost: Sequence[float | None] | None = None,
    defrost_start: eff.Instant | None = None,
) -> list[dict[str, Any]]:
    """The season history, oldest first, one point per season (a season is never dropped).

    Inputs: the seasons (``seasons_since``), per season its (output,
    electrical) energy in kWh or None (from ``season_energy`` for a finished
    season, ``efficiency.period_energy`` for the running one), the
    measured-since date, the time zone and the unit factor of ``efficiency.ratio``.
    Each point: ``start`` (covered start, ISO in the time zone), ``end``
    (natural end, ISO), ``efficiency`` (None when unknown), ``output_energy``
    and ``electrical_energy`` (kWh, 3 decimals, None when unknown),
    ``estimated`` (``efficiency.includes_estimated`` of the covered start),
    ``complete`` and ``ended``.

    ``defrost`` (design D5) is one defrost energy in kWh per season (None for
    an unknown one; ``season_energy`` of the defrost IDs for a finished
    season, ``efficiency.period_energy`` for the running one), or None for a
    service without defrost statistics: the points are then unchanged. With it each point also has ``defrost_energy`` (kWh, 3
    decimals, None when unknown) and ``defrost_partial``
    (``efficiency.defrost_partial`` of the covered start and ``defrost_start``),
    and ``efficiency`` is ``efficiency.corrected_ratio``.
    """
    if len(infos) != len(energies):
        raise ValueError("one energy pair per season")
    if defrost is not None and len(defrost) != len(infos):
        raise ValueError("one defrost energy per season")
    points = []
    for index, (info, (output, electrical)) in enumerate(zip(infos, energies)):
        point = {
            "start": info.covered_start.astimezone(tz).isoformat(),
            "end": info.natural_end.astimezone(tz).isoformat(),
            "efficiency": eff.ratio(output, electrical, factor),
            "output_energy": None if output is None else round(output, 3),
            "electrical_energy": None if electrical is None else round(electrical, 3),
            "estimated": eff.includes_estimated(info.covered_start, measured_since, tz),
            "complete": info.complete,
            "ended": info.ended,
        }
        if defrost is not None:
            defrost_kwh = defrost[index]
            point["efficiency"] = eff.corrected_ratio(output, defrost_kwh, electrical, factor)
            point["defrost_energy"] = None if defrost_kwh is None else round(defrost_kwh, 3)
            point["defrost_partial"] = eff.defrost_partial(info.covered_start, defrost_start)
        points.append(point)
    return points
