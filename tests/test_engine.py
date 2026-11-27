"""Tests of the pure engine (pytest, without Home Assistant): the read plan of every update.

A fake reader plays the recorder: constant-rate hourly counters, grouped into
the 5-minute, hour, day and month tables the way ``statistics_during_period``
does. ``engine.py`` is loaded without executing the package ``__init__`` (which
imports Home Assistant): a bare package module with the package path is
registered, so the engine's relative imports of its pure siblings work.
"""

import ast
import asyncio
from datetime import UTC, date, datetime, timedelta
import importlib
from itertools import pairwise
import json
import math
from pathlib import Path
import sys
import types
from zoneinfo import ZoneInfo

import pytest

PACKAGE = (
    Path(__file__).resolve().parents[1] / "custom_components" / "heatpump_efficiency"
)
_pkg = types.ModuleType("hpe_engine_pkg")
_pkg.__path__ = [str(PACKAGE)]
sys.modules["hpe_engine_pkg"] = _pkg
eff = importlib.import_module("hpe_engine_pkg.efficiency")
engine = importlib.import_module("hpe_engine_pkg.engine")

TZ = ZoneInfo("Europe/Amsterdam")
H = 3600


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def midnight(year, month, day) -> float:
    """Epoch seconds of local midnight in Europe/Amsterdam."""
    return datetime(year, month, day, tzinfo=TZ).timestamp()


_MIDNIGHTS: dict[date, float] = {}


def local_midnight(day: date) -> float:
    """``midnight`` of a date, cached: the fake reader groups up to two years of days per read."""
    ts = _MIDNIGHTS.get(day)
    if ts is None:
        ts = _MIDNIGHTS[day] = datetime(
            day.year, day.month, day.day, tzinfo=TZ
        ).timestamp()
    return ts


def is_first_hours_read(source, statistic_ids, window, now) -> bool:
    """Whether a read is one of ``read_first_hours``.

    That is the month read over ``first_hours_window`` (it ends now or, bounded with seasons,
    starts at ``HISTORY_FLOOR``; the main month read ends at a month start) or a day or hour
    read of one statistic.
    """
    return len(statistic_ids) == 1 or (
        source == "month"
        and (window.end == now or window.start == engine.HISTORY_FLOOR)
    )


class Series:
    """A counter with a constant rate (kWh per hour) from its first hour.

    ``base`` is added to the running sum (an external or imported counter that does not start
    at 0): as in Home Assistant, the first row of a table (the one holding the first hour)
    carries it in its ``change``, which is computed against a previous sum of 0.
    """

    def __init__(
        self,
        first: datetime,
        rate: float,
        source: str = "recorder",
        lag: int = 0,
        base: float = 0.0,
    ):
        self.first = first.timestamp()
        self.rate = rate
        self.source = source
        self.lag = lag  # seconds the statistics are behind
        self.base = base
        self.gap: tuple[float, float] | None = (
            None  # [start, end) epoch seconds without hourly rows
        )


class FakeStats:
    """The reader of the engine over synthetic statistics."""

    def __init__(self):
        self.now: datetime = utc(2026, 11, 17, 10, 20, 30)
        self.series: dict[str, Series] = {}
        self.log: list[dict] = []
        self.meta_log: list[frozenset] = []
        self.fail: set[str] = set()  # tables whose reads raise
        self.fail_single = False  # reads of one statistic (first hours) raise

    # --- the reader interface -------------------------------------------
    async def read(self, source, statistic_ids, window, units, types):
        self.log.append(
            {
                "source": source,
                "ids": frozenset(statistic_ids),
                "window": window,
                "units": dict(units),
                "types": set(types),
            }
        )
        # ``fail`` breaks the main reads; ``fail_single`` the first-hours reads.
        first_hours = is_first_hours_read(source, statistic_ids, window, self.now)
        if (source in self.fail and not first_hours) or (
            self.fail_single and first_hours
        ):
            raise RuntimeError("boom")
        now = self.now.timestamp()
        return {
            sid: rows
            for sid in sorted(statistic_ids)
            if (rows := self._rows(self.series[sid], source, window, now))
        }

    async def metadata(self, statistic_ids):
        self.meta_log.append(frozenset(statistic_ids))
        return [
            {
                "statistic_id": sid,
                "source": self.series[sid].source,
                "has_sum": True,
                "unit_class": "energy",
            }
            for sid in sorted(statistic_ids)
            if sid in self.series
        ]

    # --- the synthetic tables ---------------------------------------------
    def _hours(self, series, lo, hi, now):
        limit = math.floor((now - series.lag) / H) * H
        start = max(series.first, math.ceil(lo / H) * H)
        hours = range(int(start), int(min(hi, limit)), H)
        if series.gap is None:
            return hours
        return [s for s in hours if not series.gap[0] <= s < series.gap[1]]

    def _rows(self, series, source, window, now):
        lo, hi = window.start.timestamp(), window.end.timestamp()
        rate = series.rate
        if source == "hour":
            # ``sum``: the running counter at the end of the row (rate per hour since the first hour).
            return [
                {
                    "start": float(s),
                    "end": float(s + H),
                    "change": rate + (series.base if s == series.first else 0.0),
                    "sum": series.base + rate * ((s - series.first) / H + 1),
                }
                for s in self._hours(series, lo, hi, now)
            ]
        if source == "5minute":
            if series.source != "recorder":
                return []
            limit = math.floor((now - series.lag) / 300) * 300
            first = max(series.first, math.ceil(lo / 300) * 300)
            return [
                {
                    "start": float(s),
                    "end": float(s + 300),
                    "change": rate / 12 + (series.base if s == series.first else 0.0),
                }
                for s in range(int(first), int(min(hi, limit)), 300)
            ]
        # Day and month rows: the hourly rows grouped by the local date (or month) of their
        # start, aligned like statistics_during_period (start to the local day or 1st, end to
        # the next one). Each group counts its whole hours instead of iterating them.
        first_day = datetime.fromtimestamp(lo, TZ).date()
        last_day = datetime.fromtimestamp(hi, TZ).date()
        if source == "day":
            starts = [
                first_day + timedelta(days=k)
                for k in range((last_day - first_day).days + 2)
            ]
        else:
            starts, month = [], date(first_day.year, first_day.month, 1)
            while month <= date(last_day.year, last_day.month, 1):
                starts.append(month)
                month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
            starts.append(month)
        limit = math.floor((now - series.lag) / H) * H
        rows = []
        for a, b in pairwise(starts):
            group_start, group_end = local_midnight(a), local_midnight(b)
            count = math.ceil(min(group_end, limit) / H) - math.ceil(
                max(group_start, series.first) / H
            )
            if count > 0:
                holds_first = group_start <= series.first < group_end
                rows.append(
                    {
                        "start": group_start,
                        "end": group_start,
                        "change": count * rate + (series.base if holds_first else 0.0),
                    }
                )
        return rows


def kwh(rate: float, start: float, end: float) -> float:
    return round(rate * (end - start) / H, 3)


FIRST = utc(2025, 1, 1)
OUT_H, EL_H = "sensor.hp_heat_heating", "sensor.hp_electric_heating"
OUT_W, EL_W = "sensor.hp_heat_water", "sensor.hp_electric_water"
OUT_A, EL_A = "sensor.hp_heat_all", "external:hp_electric_all"
MAPPING = {
    "heating": {"output": [OUT_H], "electricity": [EL_H]},
    "hot_water": {"output": [OUT_W], "electricity": [EL_W]},
}
MAPPING_OVERALL = {**MAPPING, "overall": {"output": [OUT_A], "electricity": [EL_A]}}


def make_stats() -> FakeStats:
    stats = FakeStats()
    for sid, rate in (
        (OUT_H, 2.0),
        (EL_H, 0.5),
        (OUT_W, 1.0),
        (EL_W, 0.25),
        (OUT_A, 3.0),
    ):
        stats.series[sid] = Series(FIRST, rate)
    stats.series[EL_A] = Series(FIRST, 0.75, source="external")
    return stats


class Harness:
    """Runs updates against a fake reader and the engine state of one entry."""

    def __init__(self, stats: FakeStats, mapping=MAPPING):
        self.stats = stats
        self.mapping = mapping
        self.state = engine.EngineState()

    def update(self, now: datetime):
        """Run one update; return (result, main reads, first-hour reads)."""
        self.stats.now = now
        start = len(self.stats.log)
        meta_start = len(self.stats.meta_log)
        result = asyncio.run(
            engine.async_update(self.state, self.mapping, self.stats, now, TZ)
        )
        calls = self.stats.log[start:]
        first = [
            c
            for c in calls
            if is_first_hours_read(c["source"], c["ids"], c["window"], now)
        ]
        main = [c for c in calls if c not in first]
        self.metadata_reads = len(self.stats.meta_log) - meta_start
        return result, main, first

    def expected_plan(self, now: datetime) -> eff.CacheActions:
        """Return the first cache_actions call of the design D4 protocol.

        It comes after this update's metadata read (the last good metadata when it fails), on
        the old cache.
        """
        services = engine.services_of(self.mapping)
        ids = frozenset().union(*(s.all_ids for s in services))
        try:
            metadata = asyncio.run(self.stats.metadata(ids))
        except Exception:  # noqa: BLE001
            metadata = self.state.metadata
        hourly = eff.hourly_only(metadata)
        needed = engine.needed_windows(services, self.state, hourly, now, TZ)
        return eff.cache_actions(
            self.state.tables, self.state.first_hours_read_at, needed, ids, now, TZ
        )

    def needed(self, now: datetime) -> dict:
        """The windows the engine needs for the current state (``needed_windows``)."""
        services = engine.services_of(self.mapping)
        return engine.needed_windows(
            services, self.state, eff.hourly_only(self.state.metadata), now, TZ
        )


def sources(calls) -> set[str]:
    return {c["source"] for c in calls}


class TestReadPlan:
    def assert_plan(self, harness, now, expect_main, expect_first):
        """Run one update and check its reads against the expectation and the D4 protocol.

        The tables read equal the independent expectation and ``result.plan.tables``
        (the second ``cache_actions`` call when first hours were read); first hours are
        read exactly when ``cache_actions`` asked for them on the old cache; and every
        table is read over the window ``needed_windows`` gives after the update.
        """
        before = harness.expected_plan(now)  # asked before the update, on the old cache
        result, main, first = harness.update(now)
        assert sources(main) == expect_main, now
        assert result.plan.tables == frozenset(expect_main), now
        assert bool(first) == expect_first, now
        assert before.first_hours == expect_first, now
        if not expect_first:
            assert before.tables == frozenset(expect_main), now
        needed = harness.needed(now)
        for call in main:
            assert call["window"] == needed[call["source"]], (now, call["source"])
        return result, main, first

    def assert_unknown(self, service):
        for period, p in service.periods.items():
            assert (
                p.efficiency,
                p.output_energy,
                p.electrical_energy,
                p.period_start,
            ) == (None,) * 4, period
        assert (service.daily, service.monthly) == ([], [])

    def test_setup_normal_update_and_ten_updates(self):
        stats = make_stats()
        h = Harness(stats)
        now = utc(2026, 11, 17, 10, 20, 30)
        result, _main, _first = self.assert_plan(
            h, now, {"5minute", "month", "day"}, True
        )
        assert h.metadata_reads == 1
        # Values from the model: all periods end at the last compiled 5-minute row.
        end = utc(2026, 11, 17, 10, 20).timestamp()
        heating = result.services["heating"]
        assert heating.periods["today"].output_energy == kwh(
            2.0, midnight(2026, 11, 17), end
        )
        assert heating.periods["month_to_date"].electrical_energy == kwh(
            0.5, midnight(2026, 11, 1), end
        )
        assert heating.periods["year_to_date"].output_energy == kwh(
            2.0, midnight(2026, 1, 1), end
        )
        assert heating.periods["rolling_12_months"].output_energy == kwh(
            2.0, midnight(2025, 11, 17), end
        )
        assert heating.periods["today"].efficiency == 4.0
        assert result.services["hot_water"].periods["year_to_date"].efficiency == 4.0
        assert len(heating.daily) == 31
        assert len(heating.monthly) == 23  # Jan 2025 .. Nov 2026 (Dec 2024 has no data)
        # Ten more updates within the day read only today's statistics and the metadata (design
        # D4: the metadata is read at every update, the history once).
        for step in range(1, 11):
            now = utc(2026, 11, 17, 10, 20, 30) + timedelta(minutes=5 * step)
            self.assert_plan(h, now, {"5minute"}, False)
            assert h.metadata_reads == 1, step

    def test_first_update_after_midnight_and_first_of_month(self):
        h = Harness(make_stats())
        self.assert_plan(
            h, utc(2026, 11, 17, 22, 55, 30), {"5minute", "month", "day"}, True
        )
        # 00:00:30 local on 18 November: a new day, the month is unchanged.
        now = utc(2026, 11, 17, 23, 0, 30)
        result, _main, _first = self.assert_plan(h, now, {"5minute", "day"}, True)
        assert h.metadata_reads == 1
        # Today is empty, yesterday is a completed day: nothing counted twice or missed.
        end = utc(2026, 11, 17, 23, 0).timestamp()
        heating = result.services["heating"].periods
        assert heating["today"].electrical_energy == 0.0
        assert heating["today"].efficiency is None
        assert heating["month_to_date"].output_energy == kwh(
            2.0, midnight(2026, 11, 1), end
        )
        assert heating["year_to_date"].output_energy == kwh(
            2.0, midnight(2026, 1, 1), end
        )
        # Then 30 November 23:55:30 local (a new day) and 1 December 00:00:30 local: a new month too.
        self.assert_plan(h, utc(2026, 11, 30, 22, 55, 30), {"5minute", "day"}, True)
        now = utc(2026, 11, 30, 23, 0, 30)
        result, _main, _first = self.assert_plan(
            h, now, {"5minute", "month", "day"}, True
        )
        heating = result.services["heating"].periods
        end = utc(2026, 11, 30, 23, 0).timestamp()
        assert heating["year_to_date"].output_energy == kwh(
            2.0, midnight(2026, 1, 1), end
        )
        assert (
            heating["month_to_date"].output_energy == 0.0
        )  # December has not counted yet
        assert (
            heating["month_to_date"].period_start
            == datetime(2026, 12, 1, tzinfo=TZ).isoformat()
        )

    def test_moved_effective_start(self):
        stats = make_stats()
        stats.series[EL_H] = Series(
            utc(2026, 11, 13, 14), 0.5
        )  # first hour 13 November 14:00
        h = Harness(stats, {"heating": MAPPING["heating"]})
        now = utc(2026, 11, 17, 10, 20, 30)
        result, _main, _ = self.assert_plan(
            h, now, {"5minute", "day"}, True
        )  # no whole month in range
        heating = result.services["heating"]
        assert heating.effective_start == datetime(2026, 11, 14, tzinfo=TZ).isoformat()
        assert (
            heating.periods["year_to_date"].period_start
            == datetime(2026, 11, 14, tzinfo=TZ).isoformat()
        )
        end = utc(2026, 11, 17, 10, 20).timestamp()
        assert heating.periods["year_to_date"].output_energy == kwh(
            2.0, midnight(2026, 11, 14), end
        )
        # A backfill moves the first statistics hour; the same day keeps the cached first hours.
        stats.series[EL_H] = Series(FIRST, 0.5)
        result, _main, _first = self.assert_plan(
            h, now + timedelta(minutes=5), {"5minute"}, False
        )
        assert (
            result.services["heating"].periods["year_to_date"].period_start
            == heating.periods["year_to_date"].period_start
        )
        # The first update of the next day reads the first hours again, the windows grow, the
        # history is read again for the new start and year to date starts on 1 January.
        now = utc(2026, 11, 18, 10, 20, 30)
        result, _main, _first = self.assert_plan(
            h, now, {"5minute", "month", "day"}, True
        )
        heating = result.services["heating"]
        assert (
            heating.periods["year_to_date"].period_start
            == datetime(2026, 1, 1, tzinfo=TZ).isoformat()
        )
        end = utc(2026, 11, 18, 10, 20).timestamp()
        assert heating.periods["year_to_date"].output_energy == kwh(
            2.0, midnight(2026, 1, 1), end
        )

    def test_retried_uncovered_read(self):
        stats = make_stats()
        h = Harness(stats)
        self.assert_plan(
            h, utc(2026, 11, 18, 10, 20, 30), {"5minute", "month", "day"}, True
        )
        # Midnight with the hot water electricity an hour behind: the day read is not covered.
        stats.series[EL_W].lag = H
        now = utc(2026, 11, 18, 23, 0, 30)
        result, _main, _ = self.assert_plan(h, now, {"5minute", "day"}, True)
        assert result.services["hot_water"].periods["month_to_date"].efficiency is None
        assert (
            result.services["hot_water"].periods["month_to_date"].electrical_energy
            is None
        )
        assert result.services["hot_water"].periods["year_to_date"].efficiency is None
        assert (
            result.services["heating"].periods["month_to_date"].efficiency is not None
        )
        # Still behind: the day read is retried at the next update, and the one after.
        for minutes in (5, 10):
            now2 = now + timedelta(minutes=minutes)
            result, _main, _first = self.assert_plan(h, now2, {"5minute", "day"}, False)
            assert (
                result.services["hot_water"].periods["month_to_date"].efficiency is None
            )
        # Caught up: read once more, then reported, and then not read again.
        stats.series[EL_W].lag = 0
        now3 = now + timedelta(minutes=15)
        result, _main, _ = self.assert_plan(h, now3, {"5minute", "day"}, False)
        assert result.services["hot_water"].periods["month_to_date"].efficiency == 4.0
        self.assert_plan(h, now3 + timedelta(minutes=5), {"5minute"}, False)

    def test_failed_read_gives_unknown_periods_and_is_retried(self):
        stats = make_stats()
        stats.fail = {"month"}
        h = Harness(stats)
        now = utc(2026, 11, 17, 10, 20, 30)
        result, _main, _ = self.assert_plan(
            h, now, {"5minute", "month", "day"}, True
        )  # does not raise
        periods = result.services["heating"].periods
        assert periods["year_to_date"].efficiency is None
        assert periods["year_to_date"].output_energy is None
        assert periods["rolling_12_months"].efficiency is None
        assert periods["today"].efficiency == 4.0
        assert periods["month_to_date"].efficiency == 4.0
        assert h.state.errors["month"].startswith("RuntimeError")
        assert h.state.tables["month"].rows is None
        # Retried at the next update, not before; then it recovers.
        stats.fail = set()
        result, _main, _ = self.assert_plan(
            h, now + timedelta(minutes=5), {"5minute", "month"}, False
        )
        assert result.services["heating"].periods["year_to_date"].efficiency == 4.0
        assert h.state.errors["month"] is None

    def test_first_hours_failure_makes_the_service_unknown_and_is_retried(self):
        stats = make_stats()
        stats.fail_single = True
        h = Harness(stats)
        now = utc(2026, 11, 17, 10, 20, 30)
        result, _, _ = self.assert_plan(h, now, {"5minute", "month", "day"}, True)
        for service in result.services.values():
            self.assert_unknown(service)
        assert h.state.first_hours_read_at is None
        assert h.state.errors["first_hours"]
        stats.fail_single = False
        # Retried at once. The first hours (1 January 2025 01:00 local) cut January 2025,
        # so the day window now reaches back to 2 January 2025 and the days are read again.
        result, _main, _first = self.assert_plan(
            h, now + timedelta(minutes=5), {"5minute", "day"}, True
        )
        assert result.services["heating"].periods["today"].efficiency == 4.0
        assert h.state.errors["first_hours"] is None

    def test_every_read_passes_kwh_units_and_change(self):
        stats = make_stats()
        h = Harness(stats, MAPPING_OVERALL)
        self.assert_plan(
            h, utc(2026, 11, 17, 10, 20, 30), {"5minute", "hour", "month", "day"}, True
        )
        self.assert_plan(
            h, utc(2026, 11, 17, 23, 0, 30), {"5minute", "hour", "day"}, True
        )
        self.assert_plan(h, utc(2026, 11, 17, 23, 5, 30), {"5minute", "hour"}, False)
        assert stats.log
        for call in stats.log:
            assert call["units"] == {"energy": "kWh"}, call["source"]
            assert call["types"] == {"change"}, call["source"]

    def test_external_statistic_is_read_hourly(self):
        stats = make_stats()
        h = Harness(stats, MAPPING_OVERALL)
        result, main, _ = self.assert_plan(
            h, utc(2026, 11, 17, 10, 20, 30), {"5minute", "hour", "month", "day"}, True
        )
        by = {c["source"]: c for c in main}
        assert by["5minute"]["ids"] == frozenset({OUT_H, EL_H, OUT_W, EL_W, OUT_A})
        assert by["hour"]["ids"] == frozenset({OUT_A, EL_A})
        # Overall ends at its last hourly row (10:00); the other services at 10:20.
        overall = result.services["overall"].periods["today"]
        assert overall.output_energy == kwh(
            3.0, midnight(2026, 11, 17), utc(2026, 11, 17, 10).timestamp()
        )
        heating = result.services["heating"].periods["today"]
        assert heating.output_energy == kwh(
            2.0, midnight(2026, 11, 17), utc(2026, 11, 17, 10, 20).timestamp()
        )
        assert overall.efficiency == 4.0

    def test_new_statistic_without_an_hourly_row_is_unknown_until_the_next_day(self):
        # Spec "New statistic without an hourly row": the electricity statistic starts today at
        # 09:00 local and has only 5-minute rows when the integration is set up at 09:20.
        stats = make_stats()
        stats.series[EL_H] = Series(utc(2026, 11, 17, 8), 0.5)
        h = Harness(stats, {"heating": MAPPING["heating"]})
        result, _, _ = self.assert_plan(
            h, utc(2026, 11, 17, 8, 20, 30), {"5minute", "month", "day"}, True
        )
        assert h.state.first_hours[EL_H] is None
        self.assert_unknown(result.services["heating"])
        # Hourly rows exist later that day, but the first hours are read again only tomorrow.
        result, _, _ = self.assert_plan(
            h, utc(2026, 11, 17, 14, 20, 30), {"5minute"}, False
        )
        self.assert_unknown(result.services["heating"])
        # The next day's refresh finds 09:00 yesterday: the periods start today, and no history
        # table is needed any more.
        now = utc(2026, 11, 18, 10, 20, 30)
        result, _, _ = self.assert_plan(h, now, {"5minute"}, True)
        assert h.state.first_hours[EL_H] == utc(2026, 11, 17, 8)
        heating = result.services["heating"]
        end = utc(2026, 11, 18, 10, 20).timestamp()
        for period, p in heating.periods.items():
            assert p.period_start == datetime(2026, 11, 18, tzinfo=TZ).isoformat(), (
                period
            )
            assert p.output_energy == kwh(2.0, midnight(2026, 11, 18), end), period
            assert p.efficiency == 4.0, period
        assert [p["start"] for p in heating.daily] == [
            datetime(2026, 11, 18, tzinfo=TZ).isoformat()
        ]
        assert [p["start"] for p in heating.monthly] == [
            datetime(2026, 11, 1, tzinfo=TZ).isoformat()
        ]

    def test_new_statistic_without_any_row_stays_unknown(self):
        stats = make_stats()
        stats.series[EL_H] = Series(utc(2099, 1, 1), 0.5)  # no rows at all
        h = Harness(stats, {"heating": MAPPING["heating"]})
        result, _, _ = self.assert_plan(
            h, utc(2026, 11, 17, 10, 20, 30), {"5minute", "month", "day"}, True
        )
        assert h.state.first_hours[EL_H] is None
        self.assert_unknown(result.services["heating"])

    def test_every_service_is_unknown_until_the_metadata_has_been_read(self):
        stats = make_stats()
        read_metadata = stats.metadata

        async def failing(statistic_ids):
            raise RuntimeError("database busy")

        stats.metadata = failing
        h = Harness(stats, MAPPING_OVERALL)
        now = utc(2026, 11, 17, 10, 20, 30)
        # Without metadata the external statistic is not known to be hourly-only: no hour read.
        result, _, _ = self.assert_plan(h, now, {"5minute", "month", "day"}, True)
        assert not h.state.metadata_ok
        assert h.state.errors["metadata"].startswith("RuntimeError")
        assert h.state.first_hours_read_at == now  # depends on the first hours alone
        for service in result.services.values():
            self.assert_unknown(service)
        # Read again at the next update (as at every update); the first hours are not. The day and
        # month reads did not cover the external statistic (it had no 5-minute rows), so they
        # are read again, and the hour table is now needed.
        stats.metadata = read_metadata
        result, _, _ = self.assert_plan(
            h, now + timedelta(minutes=5), {"5minute", "hour", "month", "day"}, False
        )
        assert h.state.metadata_ok
        assert h.state.errors["metadata"] is None
        assert result.services["heating"].periods["today"].efficiency == 4.0
        assert result.services["overall"].periods["today"].efficiency == 4.0
        # A later failure keeps the metadata read before and records the error, within the day
        # and at the first update of a new day.
        stats.metadata = failing
        good = list(h.state.metadata)
        for later, tables, first in (
            (now + timedelta(minutes=10), {"5minute", "hour"}, False),
            (utc(2026, 11, 17, 23, 0, 30), {"5minute", "hour", "day"}, True),
        ):
            result, _, _ = self.assert_plan(h, later, tables, first)
            assert h.state.metadata_ok
            assert h.state.metadata == good
            assert h.state.errors["metadata"].startswith("RuntimeError")
            assert h.state.first_hours_read_at == (later if first else now)
            assert result.services["overall"].periods["month_to_date"].efficiency == 4.0
            assert result.services["heating"].periods["month_to_date"].efficiency == 4.0

    def test_hourly_only_statistic_changes_within_the_day(self):
        # The metadata is read at every update, so an external statistic that becomes a recorder
        # statistic (or the reverse) changes the reads at the next update: the hour table is
        # dropped and read again through needed_windows and cache_actions, without a first-hours
        # refresh or a history read.
        stats = make_stats()
        h = Harness(stats, MAPPING_OVERALL)
        now = utc(2026, 11, 17, 10, 20, 30)
        self.assert_plan(h, now, {"5minute", "hour", "month", "day"}, True)
        stats.series[
            EL_A
        ].source = "recorder"  # now has 5-minute rows and recorder metadata
        result, main, _ = self.assert_plan(
            h, now + timedelta(minutes=5), {"5minute"}, False
        )
        assert h.metadata_reads == 1
        assert result.hourly_only == frozenset()
        assert "hour" not in h.state.tables
        assert EL_A in main[0]["ids"]
        overall = result.services["overall"].periods["today"]
        assert overall.output_energy == kwh(
            3.0, midnight(2026, 11, 17), utc(2026, 11, 17, 10, 25).timestamp()
        )
        stats.series[EL_A].source = "external"
        result, main, _ = self.assert_plan(
            h, now + timedelta(minutes=10), {"5minute", "hour"}, False
        )
        assert result.hourly_only == frozenset({EL_A})
        by = {c["source"]: c for c in main}
        assert by["hour"]["ids"] == frozenset({OUT_A, EL_A})
        assert EL_A not in by["5minute"]["ids"]
        overall = result.services["overall"].periods["today"]
        assert overall.output_energy == kwh(
            3.0, midnight(2026, 11, 17), utc(2026, 11, 17, 10).timestamp()
        )

    def test_sensor_offline_cuts_every_period_of_its_service(self):
        # Spec "Sensor offline": the heating electricity has no statistics since 08:20 local
        # and it is 10:20 local.
        stats = make_stats()
        h = Harness(stats)
        self.assert_plan(
            h, utc(2026, 11, 17, 7, 0, 30), {"5minute", "month", "day"}, True
        )
        stats.series[EL_H].lag = 2 * H
        now = utc(2026, 11, 17, 9, 20, 30)
        result, _, _ = self.assert_plan(h, now, {"5minute"}, False)
        cut = utc(2026, 11, 17, 7, 20).timestamp()  # 08:20 local
        heating = result.services["heating"]
        for period, start in (
            ("today", midnight(2026, 11, 17)),
            ("month_to_date", midnight(2026, 11, 1)),
            ("year_to_date", midnight(2026, 1, 1)),
            ("rolling_12_months", midnight(2025, 11, 17)),
        ):
            assert heating.periods[period].output_energy == kwh(2.0, start, cut), period
            assert heating.periods[period].electrical_energy == kwh(0.5, start, cut), (
                period
            )
            assert heating.periods[period].efficiency == 4.0, period
        assert heating.daily[-1]["efficiency"] == 4.0
        # The other service is not cut.
        hot_water = result.services["hot_water"].periods["today"]
        assert hot_water.output_energy == kwh(
            1.0, midnight(2026, 11, 17), utc(2026, 11, 17, 9, 20).timestamp()
        )

    def test_no_services_makes_no_reads(self):
        stats = make_stats()
        h = Harness(stats, {})
        result, main, first = h.update(utc(2026, 11, 17, 10, 20, 30))
        assert (main, first, result.services) == ([], [], {})


# --- seasons (design D3, D4, D5) -----------------------------------------------

NORTH = {
    "heating_start": "10-01",
    "heating_end": "04-30",
    "cooling_start": "06-01",
    "cooling_end": "09-30",
}
OUT_C, EL_C = "sensor.hp_heat_cooling", "sensor.hp_electric_cooling"
SEASON_MAPPING = {**MAPPING, "seasons": NORTH}


def season_stats() -> FakeStats:
    stats = make_stats()
    for sid, rate in ((OUT_C, 3.0), (EL_C, 1.0)):
        stats.series[sid] = Series(FIRST, rate)
    return stats


def boundary_reads(calls) -> list[datetime]:
    """The ends of the boundary reads (``sum`` reads of the ``hour`` table), in order."""
    return [c["window"].end for c in calls if c["types"] == {"sum"}]


def local(year, month, day) -> datetime:
    return datetime(year, month, day, tzinfo=TZ)


class TestSeason:
    def shown(self, result, key="heating"):
        return result.services[key].season

    def test_pure_rules_of_boundary_actions(self):
        now = utc(2027, 7, 15, 10)
        b = local(2026, 5, 1).astimezone(UTC)
        ids = frozenset({OUT_H, EL_H})
        first = {OUT_H: FIRST, EL_H: FIRST}
        ok = engine.BoundaryRead({OUT_H: 1.0, EL_H: 2.0}, first, now)
        needed = {b: ids}
        assert engine.boundary_actions({}, needed, first, now, TZ) == [
            b
        ]  # new boundary
        assert engine.boundary_actions({b: ok}, needed, first, now, TZ) == []
        failed = engine.BoundaryRead(None, first, now)
        assert engine.boundary_actions({b: failed}, needed, first, now, TZ) == [b]
        # A pending reading is read again only at an update where its statistic's last row ends
        # at or after the boundary (none without rows, or before it); a no-row reading is final.
        pending = engine.BoundaryRead({OUT_H: 1.0}, first, now, {EL_H: engine.PENDING})
        assert engine.boundary_actions({b: pending}, needed, first, now, TZ) == []
        behind = {OUT_H: now.timestamp(), EL_H: b.timestamp() - 1}
        caught_up = {OUT_H: now.timestamp(), EL_H: b.timestamp()}
        assert (
            engine.boundary_actions(
                {b: pending},
                needed,
                first,
                now,
                TZ,
                {OUT_H: now.timestamp(), EL_H: None},
            )
            == []
        )
        assert (
            engine.boundary_actions({b: pending}, needed, first, now, TZ, behind) == []
        )
        assert engine.boundary_actions(
            {b: pending}, needed, first, now, TZ, caught_up
        ) == [b]
        no_row = engine.BoundaryRead({OUT_H: 1.0}, first, now, {EL_H: engine.NO_ROW})
        assert (
            engine.boundary_actions({b: no_row}, needed, first, now, TZ, caught_up)
            == []
        )
        assert engine.boundary_actions(
            {b: failed}, needed, first, now, TZ, caught_up
        ) == [b]
        moved = {OUT_H: FIRST, EL_H: FIRST + timedelta(days=1)}
        assert engine.boundary_actions({b: ok}, needed, moved, now, TZ) == [
            b
        ]  # first hour moved
        assert engine.boundary_actions(
            {b: no_row}, needed, moved, now, TZ, caught_up
        ) == [b]
        # Read on the boundary's own day: read again at the first update of the next day only.
        early = engine.BoundaryRead(
            {OUT_H: 1.0, EL_H: 2.0}, first, utc(2026, 4, 30, 22, 0, 30)
        )
        assert (
            engine.boundary_actions({b: early}, needed, first, utc(2026, 5, 1, 12), TZ)
            == []
        )
        assert engine.boundary_actions(
            {b: early}, needed, first, utc(2026, 5, 1, 22, 0, 30), TZ
        ) == [b]

    def test_ten_updates_in_a_day_read_each_finished_season_boundary_once(self):
        h = Harness(season_stats(), SEASON_MAPPING)
        first_now = utc(2027, 7, 15, 10, 20, 30)  # between seasons
        result, main, _ = h.update(first_now)
        reads = boundary_reads(main)
        # Seasons of 2024/25 (cut at 2 January 2025, the first day start after the first hour), 2025/26 and 2026/27: two boundaries each.
        expected = {
            local(2025, 1, 2),
            local(2025, 5, 1),
            local(2025, 10, 1),
            local(2026, 5, 1),
            local(2026, 10, 1),
            local(2027, 5, 1),
        }
        assert set(reads) == {d.astimezone(UTC) for d in expected}
        assert len(reads) == 6
        points = self.shown(result).points
        assert len(points) == 3
        assert [p["ended"] for p in points] == [True] * 3
        for step in range(1, 11):
            _, main, _ = h.update(first_now + timedelta(minutes=5 * step))
            assert boundary_reads(main) == [], step
        # The next day reads none either: every read was made at least a day after its boundary.
        _, main, _ = h.update(first_now + timedelta(days=1))
        assert boundary_reads(main) == []

    def test_failed_boundary_read_is_retried_at_the_next_update(self):
        stats = season_stats()
        stats.fail = {"hour"}  # only the boundary reads use the hour table here
        h = Harness(stats, SEASON_MAPPING)
        now = utc(2027, 7, 15, 10, 20, 30)
        result, main, _ = h.update(now)
        assert len(boundary_reads(main)) == 6
        assert "RuntimeError" in h.state.errors["boundaries"]
        season = self.shown(result)
        assert len(season.points) == 3  # the points are kept, their figures unknown
        assert [p["efficiency"] for p in season.points] == [None] * 3
        assert season.efficiency is None
        assert (
            result.services["heating"].periods["year_to_date"].efficiency == 4.0
        )  # periods unaffected
        result, main, _ = h.update(now + timedelta(minutes=5))
        assert len(boundary_reads(main)) == 6  # every failed boundary again
        stats.fail = set()
        result, main, _ = h.update(now + timedelta(minutes=10))
        assert len(boundary_reads(main)) == 6
        assert h.state.errors["boundaries"] is None
        assert [p["efficiency"] for p in self.shown(result).points] == [4.0] * 3
        _, main, _ = h.update(now + timedelta(minutes=15))
        assert boundary_reads(main) == []

    def test_first_update_after_a_season_ends(self):
        h = Harness(season_stats(), SEASON_MAPPING)
        result, main, _ = h.update(
            utc(2026, 4, 30, 21, 55, 30)
        )  # 23:55:30 local on 30 April
        season = self.shown(result)
        assert (season.ended, season.complete) == (False, True)
        assert season.period_start == local(2025, 10, 1).isoformat()
        assert season.output_energy == kwh(
            2.0, midnight(2025, 10, 1), utc(2026, 4, 30, 21, 55).timestamp()
        )
        # 00:00:30 local on 1 May: the season is over and its figure is the whole season.
        result, main, _ = h.update(utc(2026, 4, 30, 22, 0, 30))
        season = self.shown(result)
        assert (season.ended, season.complete, season.includes_estimated) == (
            True,
            True,
            False,
        )
        assert season.period_start == local(2025, 10, 1).isoformat()
        assert season.season_end == local(2026, 5, 1).isoformat()
        whole = (midnight(2025, 10, 1), midnight(2026, 5, 1))
        assert season.output_energy == kwh(2.0, *whole)
        assert season.electrical_energy == kwh(0.5, *whole)
        assert season.efficiency == 4.0
        assert season.points[-1]["efficiency"] == 4.0
        # Only the two boundaries of the season that just ended were read, then the end once more
        # on the first update of the next day (its hourly row is certainly compiled), then no more.
        assert {
            d.astimezone(UTC) for d in (local(2025, 10, 1), local(2026, 5, 1))
        } == set(boundary_reads(main))
        _, main, _ = h.update(utc(2026, 4, 30, 23, 0, 30))
        assert boundary_reads(main) == []
        result, main, _ = h.update(utc(2026, 5, 1, 22, 0, 30))
        assert boundary_reads(main) == [local(2026, 5, 1).astimezone(UTC)]
        assert self.shown(result).output_energy == kwh(2.0, *whole)
        _, main, _ = h.update(utc(2026, 5, 1, 23, 0, 30))
        assert boundary_reads(main) == []

    def test_season_unknown_when_a_boundary_reading_is_not_covered(self):
        stats = season_stats()
        h = Harness(stats, SEASON_MAPPING)
        h.update(utc(2026, 4, 30, 21, 55, 30))
        stats.series[EL_H].lag = (
            2 * H
        )  # its last 5-minute row ends at 22:00, before the boundary
        now = utc(2026, 4, 30, 22, 0, 30)
        result, main, _ = h.update(now)
        season = self.shown(result)
        assert season.ended
        assert season.efficiency is None
        assert season.electrical_energy is None
        assert len(season.points) == 2
        assert season.points[-1]["efficiency"] is None
        assert (
            season.points[0]["efficiency"] == 4.0
        )  # the earlier season needs other boundaries
        assert h.state.boundaries[local(2026, 5, 1).astimezone(UTC)].reasons == {
            EL_H: engine.PENDING
        }
        for step in (
            1,
            2,
        ):  # pending: not read again while its last row still ends before the boundary
            result, main, _ = h.update(now + timedelta(minutes=5 * step))
            assert boundary_reads(main) == []
            assert self.shown(result).efficiency is None
        stats.series[EL_H].lag = 0  # caught up: read again once
        result, main, _ = h.update(now + timedelta(minutes=15))
        assert boundary_reads(main) == [local(2026, 5, 1).astimezone(UTC)]
        assert self.shown(result).efficiency == 4.0
        _, main, _ = h.update(now + timedelta(minutes=20))
        assert boundary_reads(main) == []

    def test_reading_or_reason(self):
        b = local(2026, 5, 1).astimezone(UTC)
        rows = [{"start": b.timestamp() - H, "sum": 7.0}]
        after, before = b.timestamp() + H, b.timestamp() - 1
        assert engine.reading_or_reason(rows, FIRST, after, b) == 7.0
        assert (
            engine.reading_or_reason(None, b, after, b) == 0.0
        )  # first hour at the boundary
        assert (
            engine.reading_or_reason(rows, FIRST, None, b) == engine.PENDING
        )  # no 5-minute rows
        assert engine.reading_or_reason(rows, FIRST, before, b) == engine.PENDING
        assert engine.reading_or_reason([], FIRST, after, b) == engine.NO_ROW
        assert engine.reading_or_reason(None, FIRST, after, b) == engine.NO_ROW

    def test_gap_of_more_than_31_days_before_a_boundary_is_read_once(self):
        stats = season_stats()
        b = local(2025, 5, 1)
        stats.series[EL_H].gap = (
            b.timestamp() - 40 * 86400,
            b.timestamp(),
        )  # no hourly rows for 40 days
        h = Harness(stats, SEASON_MAPPING)
        now = utc(2027, 7, 15, 10, 20, 30)
        result, main, _ = h.update(now)
        assert len(boundary_reads(main)) == 6
        assert h.state.boundaries[b.astimezone(UTC)].reasons == {EL_H: engine.NO_ROW}
        assert [p["efficiency"] for p in self.shown(result).points] == [None, 4.0, 4.0]
        for step in range(
            1, 6
        ):  # not read again: no_row cannot improve by reading again
            result, main, _ = h.update(now + timedelta(minutes=5 * step))
            assert boundary_reads(main) == [], step
            assert [p["efficiency"] for p in self.shown(result).points] == [
                None,
                4.0,
                4.0,
            ]
        _, main, _ = h.update(
            now + timedelta(days=1)
        )  # nor at the next day's first-hours refresh
        assert boundary_reads(main) == []

    def test_dead_statistic_reads_no_boundary_at_each_update(self):
        stats = season_stats()
        stats.series[EL_H].lag = 3 * 86400  # no 5-minute rows today: no last row end
        h = Harness(stats, SEASON_MAPPING)
        now = utc(2027, 7, 15, 10, 20, 30)
        result, main, _ = h.update(now)
        assert len(boundary_reads(main)) == 6  # new boundaries
        assert {read.reasons.get(EL_H) for read in h.state.boundaries.values()} == {
            engine.PENDING
        }
        assert [p["efficiency"] for p in self.shown(result).points] == [None] * 3
        for step in range(1, 4):
            result, main, _ = h.update(now + timedelta(minutes=5 * step))
            assert boundary_reads(main) == [], step
        # Rows again, ending at or after every boundary: each is read once more, then no more.
        stats.series[EL_H].lag = 0
        result, main, _ = h.update(now + timedelta(minutes=20))
        assert len(boundary_reads(main)) == 6
        assert [p["efficiency"] for p in self.shown(result).points] == [4.0] * 3
        _, main, _ = h.update(now + timedelta(minutes=25))
        assert boundary_reads(main) == []

    def test_failed_next_day_re_read_keeps_the_good_readings(self):
        stats = season_stats()
        h = Harness(stats, SEASON_MAPPING)
        h.update(utc(2026, 4, 30, 21, 55, 30))
        result, _, _ = h.update(
            utc(2026, 4, 30, 22, 0, 30)
        )  # the season has just ended
        assert self.shown(result).efficiency == 4.0
        b = local(2026, 5, 1).astimezone(UTC)
        stats.fail = {"hour"}  # only the boundary reads use the hour table here
        result, main, _ = h.update(
            utc(2026, 5, 1, 22, 0, 30)
        )  # the next-day re-read fails
        assert boundary_reads(main) == [b]
        assert "RuntimeError" in h.state.errors["boundaries"]
        assert self.shown(result).efficiency == 4.0  # the earlier readings are kept
        stats.fail = set()
        result, main, _ = h.update(
            utc(2026, 5, 1, 22, 5, 30)
        )  # still retried at the next update
        assert boundary_reads(main) == [b]
        assert h.state.errors["boundaries"] is None
        assert self.shown(result).efficiency == 4.0
        _, main, _ = h.update(utc(2026, 5, 1, 22, 10, 30))
        assert boundary_reads(main) == []

    def test_after_failed_read_keeps_good_readings_only_with_the_same_first_hours(self):
        now = utc(2026, 5, 1, 22, 0, 30)
        first = {OUT_H: FIRST, EL_H: FIRST}
        good = engine.BoundaryRead(
            {OUT_H: 1.0, EL_H: 2.0}, first, utc(2026, 4, 30, 22, 0, 30)
        )
        assert engine.after_failed_read(good, dict(first), now) is good
        moved = {OUT_H: FIRST, EL_H: FIRST - timedelta(days=30)}
        for cached, hours in (
            (good, moved),
            (None, first),
            (engine.BoundaryRead(None, first, now), first),
        ):
            read = engine.after_failed_read(cached, hours, now)
            assert read.readings is None
            assert (dict(read.first_hours), read.read_at) == (hours, now)

    def test_running_season_energy_comes_from_the_windows(self):
        # On 1 March 2027 a heating season from 15 October needs the days of October 2026, which
        # no period or series reads: only the running season's start brings them into the windows.
        h = Harness(
            season_stats(), {**MAPPING, "seasons": {**NORTH, "heating_start": "10-15"}}
        )
        now = utc(2027, 3, 1, 10, 20, 30)
        result, _, _ = h.update(now)
        season = self.shown(result)
        assert (season.ended, season.period_start) == (
            False,
            local(2026, 10, 15).isoformat(),
        )
        assert season.output_energy == kwh(
            2.0, midnight(2026, 10, 15), utc(2027, 3, 1, 10, 20).timestamp()
        )
        assert season.efficiency == 4.0
        assert h.state.windows["day"].start <= local(2026, 10, 15)
        services = engine.services_of(h.mapping)
        starts = [
            engine.resolve_effective(s, h.state.first_hours, TZ)[0] for s in services
        ]
        assert eff.history_windows(now, TZ, starts)["day"].start > local(2026, 10, 15)

    def test_running_season_is_read_from_the_tables_and_its_start_is_in_the_windows(
        self,
    ):
        h = Harness(season_stats(), SEASON_MAPPING)
        now = utc(2027, 1, 15, 10, 20, 30)
        result, main, _ = h.update(now)
        season = self.shown(result)
        end = utc(2027, 1, 15, 10, 20).timestamp()
        assert (season.ended, season.complete) == (False, True)
        assert season.output_energy == kwh(2.0, midnight(2026, 10, 1), end)
        assert season.period_start == local(2026, 10, 1).isoformat()
        assert season.season_end == local(2027, 5, 1).isoformat()
        # Seasons of 2024/25 and 2025/26 were read from boundaries, the running one was not.
        assert len(boundary_reads(main)) == 4
        assert len(season.points) == 3
        assert self.shown(result, "hot_water") is None
        # A running season longer than the rolling 12 months starts before it: windows include it.
        early = eff.history_windows(
            utc(2027, 1, 15, 10), TZ, [local(2026, 12, 1)], False, [local(2025, 12, 1)]
        )
        assert early["month"].start == eff.day_start(date(2025, 12, 1), TZ)
        plain = eff.history_windows(utc(2027, 1, 15, 10), TZ, [local(2026, 12, 1)])
        assert plain["month"].start > early["month"].start

    def test_between_seasons_and_before_a_season_has_begun(self):
        stats = season_stats()
        stats.series[OUT_C] = Series(utc(2026, 11, 13, 14), 3.0)
        stats.series[EL_C] = Series(utc(2026, 11, 13, 14), 1.0)
        mapping = {
            **SEASON_MAPPING,
            "cooling": {"output": [OUT_C], "electricity": [EL_C]},
        }
        h = Harness(stats, mapping)
        result, _main, _ = h.update(utc(2026, 11, 17, 10, 20, 30))
        cooling = self.shown(result, "cooling")
        assert (cooling.efficiency, cooling.period_start, cooling.points) == (
            None,
            None,
            [],
        )
        assert (
            self.shown(result, "heating").period_start == local(2026, 10, 1).isoformat()
        )
        # Between seasons (15 July 2027, heating 10-01 to 04-30) the last finished season is shown.
        result, _, _ = Harness(season_stats(), SEASON_MAPPING).update(
            utc(2027, 7, 15, 10, 20, 30)
        )
        heating = self.shown(result)
        assert heating.period_start == local(2026, 10, 1).isoformat()
        assert heating.season_end == local(2027, 5, 1).isoformat()  # the natural end
        assert (heating.ended, heating.complete) == (True, True)
        whole = (midnight(2026, 10, 1), midnight(2027, 5, 1))
        assert heating.output_energy == kwh(2.0, *whole)
        assert heating.electrical_energy == kwh(0.5, *whole)
        assert heating.efficiency == 4.0
        assert heating.points[-1]["start"] == heating.period_start

    def test_cooling_factor_applies_to_cooling_only(self):
        mapping = {
            **SEASON_MAPPING,
            "overall": MAPPING_OVERALL["overall"],
            "cooling": {"output": [OUT_C], "electricity": [EL_C], "unit": "btu_per_wh"},
        }
        h = Harness(season_stats(), mapping)
        result, _main, _ = h.update(utc(2026, 11, 17, 10, 20, 30))
        expected = round(3.0 * eff.BTU_PER_WH, 2)  # 10.24
        cooling = result.services["cooling"]
        for period in eff.PERIODS:
            assert cooling.periods[period].efficiency == expected, period
        assert cooling.periods["today"].output_energy == kwh(
            3.0, midnight(2026, 11, 17), utc(2026, 11, 17, 10, 20).timestamp()
        )
        assert {p["efficiency"] for p in cooling.daily + cooling.monthly} == {expected}
        season = cooling.season
        assert [p["efficiency"] for p in season.points] == [
            expected,
            expected,
        ]  # 2025 and 2026 seasons
        assert season.efficiency == expected
        assert season.output_energy == kwh(
            3.0, midnight(2026, 6, 1), midnight(2026, 10, 1)
        )  # still kWh
        for key, plain in (("heating", 4.0), ("overall", 4.0)):
            service = result.services[key]
            assert service.periods["year_to_date"].efficiency == plain, key
            assert {p["efficiency"] for p in service.daily} == {plain}, key
            assert service.season.efficiency == plain, key
        assert result.services["hot_water"].periods["year_to_date"].efficiency == 4.0
        # Without the unit nothing is converted.
        plain_h = Harness(
            season_stats(),
            {**mapping, "cooling": {"output": [OUT_C], "electricity": [EL_C]}},
        )
        unconverted = plain_h.update(utc(2026, 11, 17, 10, 20, 30))[0].services[
            "cooling"
        ]
        assert unconverted.periods["year_to_date"].efficiency == 3.0
        assert unconverted.season.efficiency == 3.0

    def test_service_without_valid_season_dates_has_no_season_and_no_boundary_reads(
        self,
    ):
        h = Harness(season_stats(), MAPPING)  # no seasons section
        result, main, _ = h.update(utc(2027, 7, 15, 10, 20, 30))
        assert boundary_reads(main) == []
        assert result.services["heating"].season is None
        broken = {**MAPPING, "seasons": {**NORTH, "heating_end": "04-31"}}
        assert engine.services_of(broken)[0].season_dates is None

    def test_factor_argument_of_the_series_defaults_to_one(self):
        h = Harness(
            season_stats(),
            {**SEASON_MAPPING, "cooling": {"output": [OUT_C], "electricity": [EL_C]}},
        )
        h.update(utc(2026, 11, 17, 10, 20, 30))
        args = (h.state.tables, [OUT_C], [EL_C], utc(2026, 11, 17, 10, 20, 30), TZ)
        assert {p["efficiency"] for p in eff.daily_series(*args)} == {3.0}
        assert {
            p["efficiency"] for p in eff.monthly_series(*args, factor=eff.BTU_PER_WH)
        } == {10.24}


class TestFirstHours:
    def test_first_hours_from_a_month_day_and_hour_read(self):
        stats = make_stats()
        stats.series[EL_H] = Series(utc(2026, 11, 13, 14), 0.5)
        now = utc(2026, 11, 17, 10)
        stats.now = now
        hours, baselines, errors = asyncio.run(
            engine.read_first_hours(stats, [OUT_H, EL_H], now, TZ)
        )
        assert errors == {}
        assert hours[EL_H] == utc(2026, 11, 13, 14)
        assert hours[OUT_H] == FIRST
        # The baseline is the change of the first hourly row, from the same hour read.
        assert baselines == {OUT_H: 2.0, EL_H: 0.5}
        # One month read for both statistics, from one calendar month before the start of the
        # month window without an effective start (1 December 2024, the oldest month of the
        # monthly series), so 1 November 2024, to now.
        months = [c for c in stats.log if c["source"] == "month"]
        assert len(months) == 1
        assert months[0]["ids"] == frozenset({OUT_H, EL_H})
        assert months[0]["window"] == engine.first_hours_window(now, TZ)
        assert eff.history_windows(now, TZ)["month"].start == datetime(
            2024, 12, 1, tzinfo=TZ
        )
        assert months[0]["window"].start == datetime(2024, 11, 1, tzinfo=TZ)
        assert months[0]["window"].end == now

    def test_statistic_older_than_the_month_window_changes_no_period_or_series(self):
        stats = make_stats()
        old = utc(2020, 3, 1)
        stats.series[OUT_H] = Series(old, 2.0)
        stats.series[EL_H] = Series(old, 0.5)
        h = Harness(stats, {"heating": MAPPING["heating"]})
        now = utc(2026, 11, 17, 10, 20, 30)
        result, _, _ = h.update(now)
        start = engine.first_hours_window(now, TZ).start
        for statistic_id in (OUT_H, EL_H):
            assert h.state.first_hours[statistic_id] <= start
        # The same cache with the true first hours, as a read from 2000 would give them.
        truth = engine.EngineState(
            **{**vars(h.state), "first_hours": {OUT_H: old, EL_H: old}}
        )
        expected = engine.compute(
            truth, engine.services_of(h.mapping), result.plan, now, TZ
        )
        got, want = result.services["heating"], expected.services["heating"]
        assert got.periods == want.periods
        assert got.daily == want.daily
        assert got.monthly == want.monthly
        assert len(got.monthly) == 24
        assert engine.needed_windows(
            engine.services_of(h.mapping), truth, frozenset(), now, TZ
        ) == h.needed(now)

    def test_missing_first_row_at_the_month_window_start_does_not_move_the_effective_start(
        self,
    ):
        stats = make_stats()
        first = utc(
            2024, 11, 15
        )  # in the month before the month window start (1 December 2024)
        for statistic_id, rate in ((OUT_H, 2.0), (EL_H, 0.5)):
            stats.series[statistic_id] = Series(first, rate)
            # No hourly rows from 1 December 00:00 local until 2 December 00:00 local.
            stats.series[statistic_id].gap = (
                midnight(2024, 12, 1),
                midnight(2024, 12, 2),
            )
        h = Harness(stats, {"heating": MAPPING["heating"]})
        result, _, _ = h.update(utc(2026, 11, 17, 10, 20, 30))
        assert h.state.first_hours[EL_H] == first
        heating = result.services["heating"]
        # The first day start at or after 15 November 2024 00:00 UTC; not 3 December.
        assert heating.effective_start == datetime(2024, 11, 16, tzinfo=TZ).isoformat()
        assert (
            heating.monthly[0]["start"] == datetime(2024, 12, 1, tzinfo=TZ).isoformat()
        )

    def test_first_hours_window_choice_with_seasons(self):
        now = utc(2026, 11, 17, 10)
        full = eff.Window(engine.HISTORY_FLOOR, now)
        # No first hour known yet (the first read after a load): the whole history.
        for known in (None, {}, {OUT_H: None}):
            assert engine.first_hours_window(now, TZ, True, known) == full, known
        # Later: up to the end of the local month of the latest known first hour.
        known = {
            OUT_H: utc(2020, 3, 1),
            EL_H: utc(2021, 6, 30, 22, 30),
            OUT_W: None,
        }  # 1 July 2021 00:30 local
        assert engine.first_hours_window(now, TZ, True, known) == eff.Window(
            engine.HISTORY_FLOOR, local(2021, 8, 1).astimezone(UTC)
        )
        assert (
            engine.first_hours_window(now, TZ, True, {OUT_H: utc(2026, 11, 13, 14)})
            == full
        )  # at most now
        # Without a season the archived window, whatever is known.
        assert engine.first_hours_window(
            now, TZ, False, known
        ) == engine.first_hours_window(now, TZ)

    def test_bounded_first_hours_read_and_its_fallback_to_the_whole_history(self):
        stats = make_stats()
        now = utc(2026, 11, 17, 10)
        stats.now = now
        known = {OUT_H: FIRST, EL_H: FIRST}
        stats.series[OUT_H] = Series(
            utc(2020, 3, 1), 2.0
        )  # a backfill moved it earlier
        stats.series[EL_H] = Series(
            utc(2026, 3, 1), 0.5
        )  # its earliest rows were removed
        hours, baselines, errors = asyncio.run(
            engine.read_first_hours(stats, [OUT_H, EL_H], now, TZ, True, known)
        )
        assert errors == {}
        assert baselines == {OUT_H: 2.0, EL_H: 0.5}
        assert hours == {OUT_H: utc(2020, 3, 1), EL_H: utc(2026, 3, 1)}
        months = [c for c in stats.log if c["source"] == "month"]
        bounded = eff.Window(
            engine.HISTORY_FLOOR, local(2025, 2, 1).astimezone(UTC)
        )  # January 2025 included
        assert [(c["ids"], c["window"]) for c in months] == [
            (frozenset({OUT_H, EL_H}), bounded),
            (
                frozenset({EL_H}),
                eff.Window(engine.HISTORY_FLOOR, now),
            ),  # no row in the bounded window
        ]

    def test_engine_reads_the_whole_history_once_then_bounded(self):
        stats = season_stats()
        h = Harness(stats, SEASON_MAPPING)
        _, _, first = h.update(utc(2026, 11, 17, 10, 20, 30))
        assert [c["window"] for c in first if c["source"] == "month"] == [
            eff.Window(engine.HISTORY_FLOOR, utc(2026, 11, 17, 10, 20, 30))
        ]
        now = utc(2026, 11, 18, 10, 20, 30)  # the next day's refresh
        _, _, first = h.update(now)
        assert [c["window"] for c in first if c["source"] == "month"] == [
            eff.Window(engine.HISTORY_FLOOR, local(2025, 2, 1).astimezone(UTC))
        ]
        assert set(h.state.first_hours.values()) == {FIRST}

    def test_statistic_without_rows_is_none(self):
        stats = make_stats()
        stats.series[EL_H] = Series(utc(2099, 1, 1), 0.5)  # no rows yet
        hours, baselines, errors = asyncio.run(
            engine.read_first_hours(stats, [EL_H], utc(2026, 11, 17, 10), TZ)
        )
        assert (hours, baselines, errors) == (
            {EL_H: None},
            {},
            {},
        )  # no first hour, no baseline


class TestImport:
    def test_pure_modules_import_only_the_standard_library_and_pure_siblings(self):
        for name, siblings in (
            ("engine.py", {"efficiency", "seasons", "validation"}),
            ("sensor_model.py", {"efficiency", "validation"}),
            ("repairs_model.py", {"efficiency"}),
        ):
            tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        assert node.level == 1, name
                        assert node.module is None, name
                        assert {a.name for a in node.names} <= siblings, name
                    else:
                        modules.add(node.module.split(".")[0])
            assert "homeassistant" not in modules, name
            assert modules <= set(sys.stdlib_module_names), name

    def test_glue_passes_units_and_types_through(self):
        source = (PACKAGE / "coordinator.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and any(
                isinstance(a, ast.Name) and a.id == "statistics_during_period"
                for a in n.args
            )
        ]
        assert len(calls) == 1
        names = [ast.unparse(a) for a in calls[0].args]
        assert "dict(units)" in names
        assert "set(types)" in names
        assert dict(engine.READ_UNITS) == {"energy": "kWh"}
        assert set(engine.READ_TYPES) == {"change"}
        assert "update_interval=timedelta" not in source
        assert "update_interval=None" in source


class TestErrorChanges:
    def test_only_appeared_changed_and_cleared_errors_are_reported(self):
        previous = {
            "month": None,
            "day": "A: x",
            "metadata": "M: y",
            "first_hours": None,
        }
        current = {
            "month": "E: z",
            "day": "A: x",
            "metadata": None,
            "first_hours": None,
            "new": None,
        }
        assert engine.error_changes(previous, current) == [
            ("metadata", "M: y", None),
            ("month", None, "E: z"),
        ]
        assert engine.error_changes(current, current) == []
        assert engine.error_changes({}, {"a": "b"}) == [("a", None, "b")]


class TestDiagnostics:
    def test_diagnostics_are_json_safe_and_show_windows_energies_and_errors(self):
        stats = make_stats()
        stats.fail = {"month"}
        h = Harness(stats)
        result, _, _ = h.update(utc(2026, 11, 17, 10, 20, 30))
        data = engine.diagnostics_data(h.state, result)
        json.dumps(data)
        assert set(data["windows"]) == {"5minute", "month", "day"}
        assert "RuntimeError" in data["errors"]["month"]
        assert data["errors"]["day"] is None
        assert data["energies"]["heating"]["today"]["efficiency"] == 4.0
        assert len(data["metadata"]) == 4
        assert not data["tables"]["month"]["ok"]
        assert engine.diagnostics_data(engine.EngineState(), None)["energies"] == {}

    def test_diagnostics_hold_boundary_reads_and_season_points(self):
        state = engine.EngineState()
        instant = utc(2026, 10, 1)
        state.boundaries[instant] = engine.BoundaryRead(
            {"sensor.a": 5.0},
            {"sensor.a": utc(2025, 1, 1)},
            utc(2026, 11, 17),
            {"sensor.b": engine.PENDING},
        )
        season = engine.SeasonResult(
            3.6, 9.0, 2.5, "s", "e", False, True, False, [{"start": "s"}]
        )
        result = engine.EngineResult(
            {"heating": engine.ServiceResult({}, [], [], None, season)},
            utc(2026, 11, 17),
            None,
            {},
            frozenset(),
            [],
        )
        data = engine.diagnostics_data(state, result)
        json.dumps(data)
        read = data["boundaries"][instant.isoformat()]
        assert read["readings"] == {"sensor.a": 5.0}
        assert read["reasons"] == {"sensor.b": "pending"}
        assert read["read_at"] == utc(2026, 11, 17).isoformat()
        assert data["seasons"]["heating"]["points"] == [{"start": "s"}]
        assert engine.diagnostics_data(engine.EngineState(), None)["seasons"] == {}


# --- the defrost correction (add-defrost-correction, design D4, D5, D6) ----------

DEF_H, DEF_W = "sensor.hp_defrost_heating", "sensor.hp_defrost_water"
DEFROST_FIRST = utc(2026, 11, 18, 9)  # 18 November 2026 10:00 local
COUNTED_FROM = DEFROST_FIRST + timedelta(
    hours=1
)  # a defrost statistic counts from the end of its first hour
MAPPING_DEFROST = {
    "heating": {**MAPPING["heating"], "defrost_heat": [DEF_H]},
    "hot_water": MAPPING["hot_water"],
}


def defrost_stats(first=DEFROST_FIRST, rate=0.1, source="recorder") -> FakeStats:
    stats = season_stats()
    stats.series[DEF_H] = Series(first, rate, source)
    return stats


def corrected(output, defrost, electrical, factor=1.0):
    return round((output - defrost) / electrical * factor, 2)


class TestDefrost:
    def assert_corrected_unknown(self, service):
        for period, p in service.periods.items():
            assert p.efficiency is None, period
            assert p.output_energy is None, period
            assert p.defrost_energy is None, period
        assert (service.daily, service.monthly) == ([], [])

    def test_services_of_gives_each_service_its_own_defrost_statistics(self):
        mapping = {
            "heating": {**MAPPING["heating"], "defrost_heat": [DEF_H]},
            "hot_water": {**MAPPING["hot_water"], "defrost_heat": [DEF_W, DEF_H]},
            "cooling": {"output": [OUT_C], "electricity": [EL_C]},
            "overall": {
                "output": [OUT_A],
                "electricity": [EL_A],
                "defrost_heat": ["sensor.ignored"],
            },
        }
        by = {s.key: s for s in engine.services_of(mapping)}
        assert by["heating"].defrost_ids == (DEF_H,)
        assert by["hot_water"].defrost_ids == (DEF_W, DEF_H)
        assert by["overall"].defrost_ids == (
            DEF_H,
            DEF_W,
        )  # the union, form order, de-duplicated
        assert by["cooling"].defrost_ids == ()
        assert by["heating"].ids == frozenset({OUT_H, EL_H})
        assert by["heating"].all_ids == frozenset({OUT_H, EL_H, DEF_H})
        assert engine.val.defrost_ids(mapping, "overall") == []
        assert engine.val.defrost_ids(mapping, "cooling") == []
        assert engine.val.defrost_ids(mapping, "heating") == [DEF_H]
        # A section with a defrost statistic only configures nothing.
        only = {
            "heating": {"defrost_heat": [DEF_H]},
            "overall": MAPPING_OVERALL["overall"],
        }
        assert [s.key for s in engine.services_of(only)] == ["overall"]
        assert engine.services_of(only)[0].defrost_ids == (DEF_H,)

    def test_year_to_date_starts_before_the_defrost_statistic_and_is_flagged(self):
        h = Harness(defrost_stats(), MAPPING_DEFROST)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        plain = Harness(defrost_stats(), MAPPING)
        reference, _, _ = plain.update(utc(2026, 11, 22, 10, 20, 30))
        heating = result.services["heating"]
        # The defrost statistic moves neither the effective start nor the period start.
        assert heating.effective_start == reference.services["heating"].effective_start
        ytd = heating.periods["year_to_date"]
        assert ytd.period_start == datetime(2026, 1, 1, tzinfo=TZ).isoformat()
        end = utc(2026, 11, 22, 10, 20).timestamp()
        out, el = (
            kwh(2.0, midnight(2026, 1, 1), end),
            kwh(0.5, midnight(2026, 1, 1), end),
        )
        defrost = kwh(
            0.1, COUNTED_FROM.timestamp(), end
        )  # counted from the end of its first hour only
        assert (ytd.output_energy, ytd.electrical_energy, ytd.defrost_energy) == (
            out,
            el,
            defrost,
        )
        assert ytd.efficiency == pytest.approx(
            corrected(out, defrost, el), rel=0, abs=0.011
        )
        assert ytd.efficiency_uncorrected == 4.0
        assert ytd.corrected
        since = COUNTED_FROM.astimezone(TZ).isoformat()  # 18 November 11:00 local
        assert ytd.defrost_since == since
        assert heating.defrost_start == since
        assert heating.defrost_ids == (DEF_H,)
        for period in ("month_to_date", "rolling_12_months"):
            assert heating.periods[period].defrost_since == since, period
        # Today starts after the defrost statistic: no flag, the heat is subtracted in full.
        today = heating.periods["today"]
        assert today.defrost_since is None
        assert today.defrost_energy == kwh(0.1, midnight(2026, 11, 22), end)
        assert today.efficiency == pytest.approx(3.8, rel=0, abs=0.011)
        # Hot water has no defrost statistic and is unchanged.
        hot_water = result.services["hot_water"]
        assert not hot_water.periods["year_to_date"].corrected
        assert (
            hot_water.periods["year_to_date"]
            == reference.services["hot_water"].periods["year_to_date"]
        )
        # Points: the daily point of 17 November is flagged, the one of 18 November (10:00 is
        # inside it) too, 19 November is not; December has no point yet, November is partial.
        daily = {p["start"][:10]: p for p in heating.daily}
        assert daily["2026-11-17"]["defrost_partial"]
        assert daily["2026-11-18"]["defrost_partial"]
        assert not daily["2026-11-19"]["defrost_partial"]
        monthly = {p["start"][:7]: p for p in heating.monthly}
        assert monthly["2026-11"]["defrost_partial"]
        assert monthly["2026-10"]["defrost_partial"]
        assert daily["2026-11-19"]["efficiency"] == pytest.approx(3.8, rel=0, abs=0.011)
        assert daily["2026-11-17"]["efficiency"] == 4.0  # 0 kWh before the first hour

    def test_defrost_statistic_without_data_makes_heating_and_overall_unknown(self):
        stats = defrost_stats(first=utc(2099, 1, 1))  # no rows at all
        mapping = {**MAPPING_OVERALL, "heating": MAPPING_DEFROST["heating"]}
        h = Harness(stats, mapping)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        assert h.state.first_hours[DEF_H] is None
        self.assert_corrected_unknown(result.services["heating"])
        self.assert_corrected_unknown(result.services["overall"])
        # Never a fallback to the uncorrected figure; Hot water has no defrost statistic.
        assert result.services["hot_water"].periods["today"].efficiency == 4.0

    def test_defrost_sensor_offline_ends_every_heating_period(self):
        stats = defrost_stats(first=utc(2026, 11, 10))
        h = Harness(stats, MAPPING_DEFROST)
        h.update(utc(2026, 11, 17, 7, 0, 30))
        stats.series[DEF_H].lag = 2 * H
        result, _, _ = h.update(utc(2026, 11, 17, 9, 20, 30))
        cut = utc(2026, 11, 17, 7, 20).timestamp()  # 08:20 local
        heating = result.services["heating"]
        first = utc(2026, 11, 10).timestamp()
        for period, start in (
            ("today", midnight(2026, 11, 17)),
            ("month_to_date", midnight(2026, 11, 1)),
            ("year_to_date", midnight(2026, 1, 1)),
            ("rolling_12_months", midnight(2025, 11, 17)),
        ):
            p = heating.periods[period]
            assert p.output_energy == kwh(2.0, start, cut), period
            assert p.electrical_energy == kwh(0.5, start, cut), period
            assert p.defrost_energy == kwh(0.1, max(start, first + H), cut), period
        hot_water = result.services["hot_water"].periods["today"]
        assert hot_water.output_energy == kwh(
            1.0, midnight(2026, 11, 17), utc(2026, 11, 17, 9, 20).timestamp()
        )

    def test_external_defrost_statistic_makes_heating_read_hourly(self):
        stats = defrost_stats(first=utc(2026, 11, 10), source="external")
        h = Harness(stats, MAPPING_DEFROST)
        result, main, _ = h.update(utc(2026, 11, 17, 13, 20, 30))
        by = {c["source"]: c for c in main}
        assert by["hour"]["ids"] == frozenset({OUT_H, EL_H, DEF_H})
        assert DEF_H not in by["5minute"]["ids"]
        heating = result.services["heating"].periods["today"]
        hour_end = utc(
            2026, 11, 17, 13
        ).timestamp()  # the last hourly row; hot water ends at 13:20
        assert heating.output_energy == kwh(2.0, midnight(2026, 11, 17), hour_end)
        assert heating.defrost_energy == kwh(0.1, midnight(2026, 11, 17), hour_end)
        assert result.services["hot_water"].periods["today"].output_energy == kwh(
            1.0, midnight(2026, 11, 17), utc(2026, 11, 17, 13, 20).timestamp()
        )

    def test_day_read_before_the_defrost_statistic_caught_up_is_read_again(self):
        stats = defrost_stats(first=utc(2026, 11, 10))
        h = Harness(stats, MAPPING_DEFROST)
        h.update(utc(2026, 11, 18, 10, 20, 30))
        stats.series[DEF_H].lag = H
        now = utc(2026, 11, 18, 23, 0, 30)  # midnight local
        result, main, _ = h.update(now)
        assert sources(main) == {"5minute", "day"}
        month = result.services["heating"].periods["month_to_date"]
        assert month.defrost_energy is None
        assert month.efficiency is None  # never the uncorrected figure
        # The periods end at the defrost statistic's last row, before today's start: unknown.
        assert (month.output_energy, month.electrical_energy, month.period_start) == (
            None,
        ) * 3
        for minutes in (5, 10):
            result, main, _ = h.update(now + timedelta(minutes=minutes))
            assert sources(main) == {"5minute", "day"}
            assert (
                result.services["heating"].periods["month_to_date"].efficiency is None
            )
        stats.series[DEF_H].lag = 0
        result, main, _ = h.update(now + timedelta(minutes=15))
        assert sources(main) == {"5minute", "day"}
        assert result.services["heating"].periods[
            "month_to_date"
        ].efficiency == pytest.approx(
            3.9, rel=0, abs=0.02
        )  # defrost counts from 10 November
        _, main, _ = h.update(now + timedelta(minutes=20))
        assert sources(main) == {"5minute"}

    def test_finished_season_before_the_defrost_statistic_has_no_defrost_energy(self):
        mapping = {**SEASON_MAPPING, "heating": MAPPING_DEFROST["heating"]}
        h = Harness(defrost_stats(), mapping)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        season = result.services["heating"].season
        assert len(season.points) == 3
        for point in season.points[
            :2
        ]:  # 2024/25 and 2025/26 finished before 18 November 2026
            assert point["ended"]
            assert point["defrost_energy"] == 0.0
            assert point["defrost_partial"]
            assert point["efficiency"] == 4.0  # equals the uncorrected efficiency
        # The running season reads the tables: the defrost heat since 18 November 10:00.
        end = utc(2026, 11, 22, 10, 20).timestamp()
        assert season.corrected
        assert season.defrost_energy == kwh(0.1, COUNTED_FROM.timestamp(), end)
        assert season.efficiency_uncorrected == 4.0
        assert season.defrost_since == COUNTED_FROM.astimezone(TZ).isoformat()
        out = kwh(2.0, midnight(2026, 10, 1), end)
        el = kwh(0.5, midnight(2026, 10, 1), end)
        assert season.efficiency == pytest.approx(
            corrected(out, season.defrost_energy, el), rel=0, abs=0.011
        )
        # Boundary readings carry the defrost statistic like the others.
        for read in h.state.boundaries.values():
            assert DEF_H in read.readings

    def test_overall_subtracts_both_sections_and_cooling_is_unchanged(self):
        stats = defrost_stats(first=utc(2026, 11, 10))
        stats.series[DEF_W] = Series(utc(2026, 11, 10), 0.05)
        mapping = {
            "heating": MAPPING_DEFROST["heating"],
            "hot_water": {**MAPPING["hot_water"], "defrost_heat": [DEF_W]},
            "cooling": {"output": [OUT_C], "electricity": [EL_C]},
            "overall": MAPPING_OVERALL["overall"],
        }
        h = Harness(stats, mapping)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        overall = result.services["overall"]
        assert overall.defrost_ids == (DEF_H, DEF_W)
        today = overall.periods["today"]
        end = utc(2026, 11, 22, 10).timestamp()  # Overall reads hourly
        assert today.output_energy == kwh(3.0, midnight(2026, 11, 22), end)
        assert today.defrost_energy == round(
            kwh(0.1, midnight(2026, 11, 22), end)
            + kwh(0.05, midnight(2026, 11, 22), end),
            3,
        )
        assert today.efficiency_uncorrected == 4.0
        assert today.efficiency == 3.8  # (3.0 - 0.15) / 0.75
        assert result.services["heating"].periods["today"].efficiency == 3.8
        assert (
            result.services["hot_water"].periods["today"].efficiency == 3.8
        )  # (1.0 - 0.05) / 0.25
        cooling = result.services["cooling"]
        assert cooling.defrost_ids == ()
        assert not cooling.periods["today"].corrected
        assert cooling.periods["today"].defrost_energy is None
        assert cooling.periods["today"].efficiency == 3.0
        assert "defrost_partial" not in cooling.daily[-1]

    def test_defrost_statistic_with_only_5_minute_rows_counts_from_today(self):
        stats = defrost_stats(first=utc(2026, 11, 17, 8))
        h = Harness(stats, MAPPING_DEFROST)
        now = utc(2026, 11, 17, 8, 20, 30)
        result, _, _ = h.update(now)
        assert h.state.first_hours[DEF_H] is None  # no hourly row yet
        heating = result.services["heating"]
        since = now.astimezone(TZ).isoformat()
        end = utc(2026, 11, 17, 8, 20).timestamp()
        for period, p in heating.periods.items():
            assert p.efficiency is not None, period  # known, not unknown
            assert p.defrost_since == since, period
            assert p.defrost_energy == kwh(
                0.1, utc(2026, 11, 17, 8).timestamp(), end
            ), period
        assert heating.defrost_start == since
        assert all(p["defrost_partial"] for p in heating.daily)
        assert all(p["defrost_partial"] for p in heating.monthly)

    def test_first_hours_refresh_reads_each_group_bounded_by_its_own_first_hour(self):
        mapping = {**SEASON_MAPPING, "heating": MAPPING_DEFROST["heating"]}
        stats = defrost_stats()
        h = Harness(stats, mapping)
        _, _, first = h.update(
            utc(2026, 11, 22, 10, 20, 30)
        )  # the whole history, per group
        months = [(c["ids"], c["window"]) for c in first if c["source"] == "month"]
        now = utc(2026, 11, 22, 10, 20, 30)
        assert sorted(months, key=lambda m: len(m[0])) == [
            (frozenset({DEF_H}), eff.Window(engine.HISTORY_FLOOR, now)),
            (
                frozenset({OUT_H, EL_H, OUT_W, EL_W}),
                eff.Window(engine.HISTORY_FLOOR, now),
            ),
        ]
        _, _, first = h.update(utc(2026, 11, 23, 10, 20, 30))  # the next day's refresh
        months = [(c["ids"], c["window"]) for c in first if c["source"] == "month"]
        assert sorted(months, key=lambda m: len(m[0])) == [
            (
                frozenset({DEF_H}),
                eff.Window(engine.HISTORY_FLOOR, utc(2026, 11, 23, 10, 20, 30)),
            ),  # its month, at most now
            (
                frozenset({OUT_H, EL_H, OUT_W, EL_W}),
                eff.Window(engine.HISTORY_FLOOR, local(2025, 2, 1).astimezone(UTC)),
            ),
        ]  # the recent defrost statistic does not widen the window of the others
        assert h.state.first_hours[DEF_H] == DEFROST_FIRST

    def test_first_hours_read_at_moves_only_when_both_groups_succeed(self):
        class FailDefrost(FakeStats):
            fail_defrost = False

            async def read(self, source, statistic_ids, window, units, types):
                if self.fail_defrost and set(statistic_ids) <= {DEF_H}:
                    self.log.append(
                        {
                            "source": source,
                            "ids": frozenset(statistic_ids),
                            "window": window,
                            "units": dict(units),
                            "types": set(types),
                        }
                    )
                    raise RuntimeError("boom")
                return await super().read(source, statistic_ids, window, units, types)

        stats = FailDefrost()
        stats.series.update(defrost_stats().series)
        h = Harness(stats, MAPPING_DEFROST)
        day1 = utc(2026, 11, 22, 10, 20, 30)
        h.update(day1)
        assert h.state.first_hours_read_at == day1
        stats.fail_defrost = True
        day2 = utc(2026, 11, 23, 10, 20, 30)
        h.update(day2)
        assert h.state.first_hours_read_at == day1  # the defrost group failed
        assert DEF_H in h.state.errors[engine.ERROR_FIRST_HOURS]
        assert h.state.first_hours[DEF_H] == DEFROST_FIRST  # the last good hour is kept
        stats.fail_defrost = False
        later = day2 + timedelta(minutes=5)
        _, _, first = h.update(later)
        assert first  # retried at the next update
        assert h.state.first_hours_read_at == later
        assert h.state.errors[engine.ERROR_FIRST_HOURS] is None

    def test_ten_updates_in_a_day_read_the_finished_seasons_at_most_once(self):
        mapping = {**SEASON_MAPPING, "heating": MAPPING_DEFROST["heating"]}
        h = Harness(defrost_stats(first=utc(2026, 11, 18, 9)), mapping)
        first_now = utc(2027, 7, 15, 10, 20, 30)  # between seasons
        result, main, _ = h.update(first_now)
        assert len(boundary_reads(main)) == 6
        for read in h.state.boundaries.values():
            if OUT_H in (read.readings or {}):
                assert DEF_H in read.readings
        assert len(result.services["heating"].season.points) == 3
        for step in range(1, 11):
            _, main, _ = h.update(first_now + timedelta(minutes=5 * step))
            assert boundary_reads(main) == [], step
        _, main, _ = h.update(first_now + timedelta(days=1))
        assert boundary_reads(main) == []

    def test_defrost_statistic_without_an_hourly_row_keeps_finished_seasons_known(self):
        stats = defrost_stats(first=utc(2027, 7, 15, 9))  # only 5-minute rows at 09:20
        mapping = {**SEASON_MAPPING, "heating": MAPPING_DEFROST["heating"]}
        h = Harness(stats, mapping)
        result, main, _ = h.update(utc(2027, 7, 15, 9, 20, 30))
        assert h.state.first_hours[DEF_H] is None
        season = result.services["heating"].season
        assert season.efficiency is not None
        assert season.efficiency == 4.0
        assert len(season.points) == 3
        for point in season.points:
            assert point["defrost_energy"] == 0.0
            assert point["defrost_partial"]
            assert point["efficiency"] == 4.0
        # The raw first hour is cached: the next day's refresh reads the boundaries again.
        result, main, _ = h.update(utc(2027, 7, 16, 9, 20, 30))
        assert h.state.first_hours[DEF_H] == utc(2027, 7, 15, 9)
        assert len(boundary_reads(main)) == 6
        for point in result.services["heating"].season.points:
            assert point["defrost_energy"] == 0.0
            assert point["efficiency"] == 4.0

    def test_defrost_statistic_whose_sum_does_not_start_at_0(self):
        # An external counter whose first statistics hour (18 November 10:00 local) has a sum of
        # 500.0 kWh: the first sum is the baseline, so periods subtract only what it counted after.
        rate = 0.1
        stats = defrost_stats(source="external")
        stats.series[DEF_H] = Series(DEFROST_FIRST, rate, "external", base=500.0 - rate)
        h = Harness(stats, MAPPING_DEFROST)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        assert h.state.baselines[DEF_H] == 500.0
        heating = result.services["heating"]
        end = utc(
            2026, 11, 22, 10
        ).timestamp()  # Heating reads hourly (an external defrost statistic)
        counted = kwh(rate, COUNTED_FROM.timestamp(), end)
        since = COUNTED_FROM.astimezone(TZ).isoformat()
        for period in ("month_to_date", "year_to_date", "rolling_12_months"):
            p = heating.periods[period]
            assert p.defrost_energy == counted, period
            assert p.defrost_since == since, period
            assert p.efficiency_uncorrected - p.efficiency == pytest.approx(
                p.defrost_energy / p.electrical_energy * 1.0, rel=0, abs=0.011
            )
        assert heating.periods["today"].defrost_energy == kwh(
            rate, midnight(2026, 11, 22), end
        )
        assert heating.periods["today"].defrost_since is None
        # The day of the first hour: the 13 hours after it (11:00 to 24:00 local), not 500 kWh.
        daily = {p["start"][:10]: p for p in heating.daily}
        assert daily["2026-11-18"]["efficiency"] == round(
            (48.0 - 1.3) / 12.0, 2
        )  # 3.89
        assert daily["2026-11-18"]["defrost_partial"]
        assert not daily["2026-11-19"]["defrost_partial"]
        assert heating.defrost_start == since

    def test_finished_season_spanning_the_defrost_counters_start(self):
        # First hour 15 November 2025 10:00 local with a first sum of 500.0 kWh; the sum is 520.0
        # kWh at the end of the season 1 October 2025 to 30 April 2026: 20.0 kWh of defrost heat.
        first = utc(2025, 11, 15, 9)
        rate = (
            20.0 / 3996
        )  # 3996 hours from the end of the first hour to the season's end
        stats = defrost_stats()
        stats.series[DEF_H] = Series(first, rate, "recorder", base=500.0 - rate)
        mapping = {**SEASON_MAPPING, "heating": MAPPING_DEFROST["heating"]}
        h = Harness(stats, mapping)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        season = result.services["heating"].season
        point = next(p for p in season.points if p["start"].startswith("2025-10-01"))
        assert point["ended"]
        assert point["defrost_energy"] == 20.0
        assert point["defrost_partial"]
        assert point["efficiency"] == round(
            (point["output_energy"] - 20.0) / point["electrical_energy"], 2
        )
        # The boundary readings: the baseline where the counter had not started, the sum at the end.
        readings = {
            instant: read.readings[DEF_H]
            for instant, read in h.state.boundaries.items()
        }
        assert readings[local(2025, 10, 1).astimezone(UTC)] == 500.0
        assert readings[local(2026, 5, 1).astimezone(UTC)] == pytest.approx(
            520.0, rel=0, abs=1e-7
        )

    def test_a_5_minute_row_inside_the_first_hour_counts_0(self):
        # The defrost statistic's first hour is today 09:00 local (08:00 UTC); at 11:20 local its
        # 5-minute rows of that hour add 0 and the rest of today counts.
        stats = defrost_stats(first=utc(2026, 11, 22, 8))
        h = Harness(stats, MAPPING_DEFROST)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        assert h.state.first_hours[DEF_H] == utc(2026, 11, 22, 8)
        today = result.services["heating"].periods["today"]
        assert today.defrost_energy == kwh(
            0.1, utc(2026, 11, 22, 9).timestamp(), utc(2026, 11, 22, 10, 20).timestamp()
        )
        assert today.defrost_since == utc(2026, 11, 22, 9).astimezone(TZ).isoformat()

    def test_defrost_of_a_service_that_is_not_configured(self):
        # Only Overall is configured; a Heating defrost statistic is subtracted from Overall.
        mapping = {
            "heating": {"defrost_heat": [DEF_H]},
            "overall": MAPPING_OVERALL["overall"],
        }
        stats = defrost_stats(first=utc(2026, 11, 10))
        h = Harness(stats, mapping)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        assert list(result.services) == ["overall"]  # no Heating sensors
        overall = result.services["overall"]
        assert overall.defrost_ids == (DEF_H,)
        end = utc(2026, 11, 22, 10).timestamp()  # Overall reads hourly
        today = overall.periods["today"]
        out, el = (
            kwh(3.0, midnight(2026, 11, 22), end),
            kwh(0.75, midnight(2026, 11, 22), end),
        )
        defrost = kwh(0.1, midnight(2026, 11, 22), end)
        assert (today.output_energy, today.electrical_energy, today.defrost_energy) == (
            out,
            el,
            defrost,
        )
        assert today.efficiency == pytest.approx(
            corrected(out, defrost, el), rel=0, abs=0.011
        )
        assert today.efficiency_uncorrected == 4.0
        assert today.corrected
        ytd = overall.periods["year_to_date"]
        assert ytd.defrost_energy == kwh(0.1, utc(2026, 11, 10, 1).timestamp(), end)
        assert ytd.defrost_since == utc(2026, 11, 10, 1).astimezone(TZ).isoformat()

    def test_baselines_are_refreshed_with_the_first_hours(self):
        stats = defrost_stats()
        h = Harness(stats, MAPPING_DEFROST)
        h.update(utc(2026, 11, 22, 10, 20, 30))
        assert h.state.baselines[DEF_H] == 0.1
        assert h.state.baselines[OUT_H] == 2.0
        # A backfill changes the first sum without moving the first hour: seen at the next refresh.
        stats.series[DEF_H] = Series(DEFROST_FIRST, 0.1, base=40.0)
        h.update(utc(2026, 11, 22, 10, 25, 30))
        assert (
            h.state.baselines[DEF_H] == 0.1
        )  # the same day keeps the cached first hours
        h.update(utc(2026, 11, 23, 10, 20, 30))
        assert h.state.baselines[DEF_H] == 40.1

    def test_mapping_without_defrost_statistics_gives_the_same_reads_and_results(self):
        # An empty defrost field, and a defrost series that is not mapped, change nothing.
        empty = {
            "heating": {**MAPPING["heating"], "defrost_heat": []},
            "hot_water": {**MAPPING["hot_water"], "defrost_heat": []},
            "overall": MAPPING_OVERALL["overall"],
            "seasons": NORTH,
        }
        plain = {**MAPPING_OVERALL, "seasons": NORTH}
        assert [s.defrost_ids for s in engine.services_of(empty)] == [(), (), ()]
        runs = []
        for mapping in (plain, empty):
            stats = defrost_stats()  # the unmapped defrost series is there in both
            h = Harness(stats, mapping)
            outputs = []
            for now in (
                utc(2026, 11, 22, 10, 20, 30),
                utc(2026, 11, 22, 10, 25, 30),
                utc(2026, 11, 23, 10, 20, 30),
                utc(2026, 12, 1, 0, 0, 30),
            ):
                result, main, first = h.update(now)
                outputs.append(
                    (
                        result.services,
                        main,
                        first,
                        result.plan,
                        h.state.first_hours_read_at,
                    )
                )
            runs.append(outputs)
        assert runs[0] == runs[1]
        result = runs[0][0][0]
        for key, service in result.items():
            assert (service.defrost_ids, service.defrost_start) == ((), None), key
            for p in service.periods.values():
                assert (
                    p.defrost_energy,
                    p.efficiency_uncorrected,
                    p.defrost_since,
                    p.corrected,
                ) == (None, None, None, False)
            for point in (*service.daily, *service.monthly):
                assert "defrost_partial" not in point
            if service.season is not None:
                assert not service.season.corrected
                for point in service.season.points:
                    assert "defrost_energy" not in point
                    assert "defrost_partial" not in point

    def test_mapped_ids_include_the_defrost_statistics(self):
        assert engine.mapped_ids(MAPPING_DEFROST) == sorted(
            {OUT_H, EL_H, OUT_W, EL_W, DEF_H}
        )
        # Defrost in an unconfigured Heating section is included through Overall.
        mapping = {
            "heating": {"defrost_heat": [DEF_H]},
            "overall": MAPPING_OVERALL["overall"],
        }
        assert DEF_H in engine.mapped_ids(mapping)
        # Without a configured service that uses it, a defrost value is not checked.
        assert engine.mapped_ids({"heating": {"defrost_heat": [DEF_H]}}) == []
        assert engine.mapped_ids(MAPPING) == sorted({OUT_H, EL_H, OUT_W, EL_W})

    def test_diagnostics_show_the_defrost_ids_start_and_energies(self):
        mapping = {**SEASON_MAPPING, "heating": MAPPING_DEFROST["heating"]}
        h = Harness(defrost_stats(), mapping)
        result, _, _ = h.update(utc(2026, 11, 22, 10, 20, 30))
        data = engine.diagnostics_data(h.state, result)
        json.dumps(data)
        since = COUNTED_FROM.astimezone(TZ).isoformat()
        # Each defrost statistic's baseline next to its first hour (design D12): the change of its first row.
        assert data["defrost"]["heating"] == {
            "ids": [DEF_H],
            "since": since,
            "first_hours": {DEF_H: DEFROST_FIRST.isoformat()},
            "baselines": {DEF_H: 0.1},
        }
        assert data["defrost"]["hot_water"] == {"ids": [], "since": None}
        year = data["energies"]["heating"]["year_to_date"]
        assert year["defrost_since"] == since
        assert year["defrost_energy"] is not None
        live = result.services["heating"].periods["year_to_date"]
        assert year["defrost_energy"] == live.defrost_energy
        assert year["efficiency_uncorrected"] == live.efficiency_uncorrected
        assert "defrost_energy" not in data["energies"]["hot_water"]["year_to_date"]
        assert data["seasons"]["heating"]["defrost_since"] == since
        assert data["seasons"]["heating"]["defrost_energy"] is not None
        assert "efficiency_uncorrected" in data["seasons"]["heating"]
