"""Tests for the pure efficiency module (standard library only).

The module is loaded by file path so these tests do not need Home Assistant or
a package __init__.py.
"""

import ast
from datetime import UTC, date, datetime, timedelta
import importlib.util
from itertools import pairwise
import math
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "heatpump_efficiency"
    / "efficiency.py"
)
_spec = importlib.util.spec_from_file_location("efficiency_under_test", MODULE_PATH)
eff = importlib.util.module_from_spec(_spec)
sys.modules["efficiency_under_test"] = eff
_spec.loader.exec_module(eff)

TZ = ZoneInfo("Europe/Amsterdam")
KOLKATA = ZoneInfo("Asia/Kolkata")
SANTIAGO = ZoneInfo("America/Santiago")
FAR = eff.Window(datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))
SOURCES = {"month": "month", "day": "day", "five": "5minute", "hour": "hour"}


def local(y, m, d, hh=0, mm=0, tz=TZ):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def row(start: datetime, change, minutes=5):
    return {
        "start": start.timestamp(),
        "end": (start.astimezone(UTC) + timedelta(minutes=minutes)).timestamp(),
        "change": change,
    }


def month_row(y, m, change):
    return row(local(y, m, 1), change)


def day_row(y, m, d, change):
    return row(local(y, m, d), change)


def tables(covered=None, window=FAR, read_at=None, **by_source):
    """{source: TableRead}: keyword month, day, five or hour gives {id: [rows]}, or None for a failed read.

    Unless ``covered`` is given, every read covers every ID that appears in any
    of the given rows.
    """
    if covered is None:
        covered = set()
        for rows_ in by_source.values():
            covered.update(rows_ or {})
    return {
        SOURCES[key]: eff.TableRead(
            SOURCES[key], window, rows_, frozenset(covered), read_at
        )
        for key, rows_ in by_source.items()
    }


def sum_for(tables_, ids, ranges):
    return eff.period_energy(tables_, ids, ranges)


class RatioTests(unittest.TestCase):
    def test_month_with_both_counters(self):
        self.assertEqual(eff.ratio(180.0, 50.0), 3.60)

    def test_too_little_electricity_is_unknown(self):
        self.assertIsNone(eff.ratio(1.0, 0.05))

    def test_exactly_the_threshold_is_known(self):
        self.assertEqual(eff.ratio(1.0, 0.1), 10.0)

    def test_missing_input_is_unknown(self):
        self.assertIsNone(eff.ratio(None, 5.0))
        self.assertIsNone(eff.ratio(5.0, None))

    def test_time_average_not_used(self):
        # A live COP sensor averaged 4.0; the ratio of changes is 3.12.
        self.assertEqual(eff.ratio(8.91, 2.86), 3.12)

    def test_input_contract_is_kwh(self):
        # Home Assistant converts 2500 Wh to 2.5 kWh before it reaches the module.
        self.assertEqual(eff.ratio(10.0, 2500 / 1000), 4.00)


class PeriodEnergyTests(unittest.TestCase):
    NOW = local(2026, 11, 17, 12, 0)

    def ranges(self):
        return eff.period_ranges(self.NOW, TZ)

    def test_several_outputs_summed(self):
        ts = tables(
            month={},
            day={},
            five={
                "out1": [row(local(2026, 11, 17, 1), 30.0)],
                "out2": [row(local(2026, 11, 17, 2), 2.0)],
                "el": [row(local(2026, 11, 17, 1), 8.0)],
            },
        )
        ranges = self.ranges()[eff.PERIOD_TODAY]
        out = sum_for(ts, ["out1", "out2"], ranges)
        el = sum_for(ts, ["el"], ranges)
        self.assertEqual(eff.ratio(out, el), 4.00)

    def test_month_to_date_includes_today(self):
        ts = tables(
            month={},
            day={
                "out": [day_row(2026, 11, 3, 60.0)],
                "el": [day_row(2026, 11, 3, 18.0)],
            },
            five={
                "out": [row(local(2026, 11, 17, 8), 2.0)],
                "el": [row(local(2026, 11, 17, 8), 0.5)],
            },
        )
        summary = eff.period_summary(
            ts, self.ranges()[eff.PERIOD_MONTH_TO_DATE], ["out"], ["el"]
        )
        self.assertEqual(summary["efficiency"], 3.35)
        self.assertEqual(summary["output_energy"], 62.0)
        self.assertEqual(summary["electrical_energy"], 18.5)

    def test_energies_kept_when_ratio_unknown(self):
        ts = tables(
            month={},
            day={},
            five={
                "out": [row(local(2026, 11, 17, 8), 0.2)],
                "el": [row(local(2026, 11, 17, 8), 0.05)],
            },
        )
        summary = eff.period_summary(
            ts, self.ranges()[eff.PERIOD_TODAY], ["out"], ["el"]
        )
        self.assertIsNone(summary["efficiency"])
        self.assertEqual(summary["output_energy"], 0.2)
        self.assertEqual(summary["electrical_energy"], 0.05)

    def test_statistic_without_data_is_unknown_not_zero(self):
        ts = tables(
            month={},
            day={},
            five={"out": [row(local(2026, 11, 17, 8), 2.0)]},
            covered={"out", "el"},
        )
        ranges = self.ranges()
        for period in eff.PERIODS:
            summary = eff.period_summary(ts, ranges[period], ["out"], ["el"])
            self.assertIsNone(summary["efficiency"])
            self.assertIsNone(summary["electrical_energy"])

    def test_month_read_failed(self):
        data = {
            "out": [day_row(2026, 11, 3, 60.0), row(local(2026, 11, 17, 8), 2.0)],
            "el": [day_row(2026, 11, 3, 18.0), row(local(2026, 11, 17, 8), 0.5)],
        }
        cut = local(2026, 11, 17).timestamp()
        ts = tables(
            month=None,
            day={k: [r for r in v if r["start"] < cut] for k, v in data.items()},
            five={k: [r for r in v if r["start"] >= cut] for k, v in data.items()},
        )
        ranges = self.ranges()
        figure = {
            p: eff.period_summary(ts, ranges[p], ["out"], ["el"]) for p in eff.PERIODS
        }
        self.assertIsNotNone(figure[eff.PERIOD_TODAY]["efficiency"])
        self.assertEqual(figure[eff.PERIOD_MONTH_TO_DATE]["efficiency"], 3.35)
        self.assertIsNone(figure[eff.PERIOD_YEAR_TO_DATE]["efficiency"])
        self.assertIsNone(figure[eff.PERIOD_ROLLING_12_MONTHS]["efficiency"])

    def test_month_table_never_read_is_unknown_not_partial(self):
        # The month table is absent (not needed when it was last read): year to
        # date must not fall back to the days it can see.
        ts = tables(
            day={
                i: [day_row(2026, 11, d, c) for d in range(13, 17)]
                for i, c in (("o", 9.0), ("e", 3.0))
            },
            five={"o": [], "e": []},
        )
        self.assertIsNone(
            eff.period_summary(
                ts, self.ranges()[eff.PERIOD_YEAR_TO_DATE], ["o"], ["e"]
            )["efficiency"]
        )

    def test_range_outside_the_read_window_is_unknown(self):
        day_window = eff.Window(
            local(2026, 11, 13).astimezone(UTC), local(2026, 11, 17).astimezone(UTC)
        )
        ts = {
            "day": eff.TableRead(
                "day", day_window, {"o": [day_row(2026, 11, 13, 9.0)]}, frozenset({"o"})
            ),
            "5minute": eff.TableRead("5minute", FAR, {"o": []}, frozenset({"o"})),
        }
        # Month to date starts 1 November, before the day window.
        self.assertIsNone(sum_for(ts, ["o"], self.ranges()[eff.PERIOD_MONTH_TO_DATE]))
        # Today needs only the 5-minute table.
        self.assertEqual(sum_for(ts, ["o"], self.ranges()[eff.PERIOD_TODAY]), 0.0)

    def test_uncovered_day_read_is_unknown(self):
        ts = tables(
            day={"o": [day_row(2026, 11, 3, 9.0)], "e": [day_row(2026, 11, 3, 3.0)]},
            five={
                "o": [row(local(2026, 11, 17, 8), 1.0)],
                "e": [row(local(2026, 11, 17, 8), 0.5)],
            },
            covered={"o"},
        )
        ranges = self.ranges()
        self.assertIsNone(sum_for(ts, ["e"], ranges[eff.PERIOD_MONTH_TO_DATE]))
        # The 5-minute table is read at every update; coverage does not apply.
        self.assertEqual(sum_for(ts, ["e"], ranges[eff.PERIOD_TODAY]), 0.5)

    def test_row_without_change_makes_period_unknown(self):
        ts = tables(month={}, day={}, five={"out": [row(local(2026, 11, 17, 8), None)]})
        self.assertIsNone(sum_for(ts, ["out"], self.ranges()[eff.PERIOD_TODAY]))

    def test_shortly_after_midnight_counts_nothing_twice(self):
        now = local(2026, 11, 17, 0, 5)
        ranges = eff.period_ranges(now, TZ)
        ts = tables(
            month={},
            day={
                "out": [day_row(2026, 11, 16, 10.0)],
                "el": [day_row(2026, 11, 16, 2.0)],
            },
            five={
                # 23:55 yesterday is read only for staleness and must not count.
                "out": [
                    row(local(2026, 11, 16, 23, 55), 0.7),
                    row(local(2026, 11, 17, 0, 0), 0.3),
                ],
                "el": [
                    row(local(2026, 11, 16, 23, 55), 0.1),
                    row(local(2026, 11, 17, 0, 0), 0.05),
                ],
            },
        )
        today = eff.period_summary(ts, ranges[eff.PERIOD_TODAY], ["out"], ["el"])
        self.assertEqual(today["output_energy"], 0.3)
        self.assertEqual(today["electrical_energy"], 0.05)
        mtd = eff.period_summary(ts, ranges[eff.PERIOD_MONTH_TO_DATE], ["out"], ["el"])
        self.assertEqual(mtd["output_energy"], 10.3)
        self.assertEqual(mtd["electrical_energy"], 2.05)


class RangeTests(unittest.TestCase):
    def assert_telescopes(self, ranges, start_local, now):
        self.assertEqual(ranges[0].start, start_local.astimezone(UTC))
        for a, b in pairwise(ranges):
            self.assertEqual(a.end, b.start, "gap or overlap")
        self.assertEqual(ranges[-1].end, now.astimezone(UTC))
        for r in ranges:
            self.assertLessEqual(r.start, r.end)

    def test_year_to_date_on_first_of_march(self):
        now = local(2027, 3, 1, 10)
        ranges = eff.period_ranges(now, TZ)
        ytd = ranges[eff.PERIOD_YEAR_TO_DATE]
        self.assert_telescopes(ytd, local(2027, 1, 1), now)
        self.assertEqual([r.source for r in ytd], ["month", "5minute"])
        self.assertEqual(ytd[0].end, local(2027, 3, 1).astimezone(UTC))
        mtd = ranges[eff.PERIOD_MONTH_TO_DATE]
        self.assert_telescopes(mtd, local(2027, 3, 1), now)
        self.assertEqual([r.source for r in mtd], ["5minute"])

    def test_first_of_january_has_no_completed_months_or_days(self):
        now = local(2027, 1, 1, 9)
        ranges = eff.period_ranges(now, TZ)
        self.assertEqual(
            [r.source for r in ranges[eff.PERIOD_YEAR_TO_DATE]], ["5minute"]
        )
        self.assertEqual(
            [r.source for r in ranges[eff.PERIOD_MONTH_TO_DATE]], ["5minute"]
        )
        self.assert_telescopes(
            ranges[eff.PERIOD_ROLLING_12_MONTHS], local(2026, 1, 1), now
        )

    def test_rolling_across_leap_day(self):
        now = local(2029, 3, 1, 10)
        rolling = eff.period_ranges(now, TZ)[eff.PERIOD_ROLLING_12_MONTHS]
        self.assert_telescopes(rolling, local(2028, 3, 1), now)

    def test_rolling_from_29_february(self):
        now = local(2028, 2, 29, 10)
        rolling = eff.period_ranges(now, TZ)[eff.PERIOD_ROLLING_12_MONTHS]
        self.assert_telescopes(rolling, local(2027, 2, 28), now)
        # Days to the month end, whole months, days of this month, today.
        self.assertEqual(
            [r.source for r in rolling], ["day", "month", "day", "5minute"]
        )

    def test_rolling_start_in_the_same_month_last_year(self):
        now = local(2026, 11, 17, 12)
        rolling = eff.period_ranges(now, TZ)[eff.PERIOD_ROLLING_12_MONTHS]
        self.assert_telescopes(rolling, local(2025, 11, 17), now)
        self.assertEqual(rolling[0].end, local(2025, 12, 1).astimezone(UTC))
        self.assertEqual(
            [r.source for r in rolling], ["day", "month", "day", "5minute"]
        )

    def test_daylight_saving_days_neither_overlap_nor_gap(self):
        for now in (
            local(2026, 3, 29, 15),  # clocks go forward (23 hour day)
            local(2026, 3, 30, 1),
            local(2026, 10, 25, 15),  # clocks go back (25 hour day)
            local(2026, 10, 26, 1),
        ):
            ranges = eff.period_ranges(now, TZ)
            today_start = datetime(now.year, now.month, now.day, tzinfo=TZ)
            for name, ranges_ in ranges.items():
                natural = {
                    eff.PERIOD_TODAY: today_start,
                    eff.PERIOD_MONTH_TO_DATE: datetime(
                        now.year, now.month, 1, tzinfo=TZ
                    ),
                    eff.PERIOD_YEAR_TO_DATE: datetime(now.year, 1, 1, tzinfo=TZ),
                    eff.PERIOD_ROLLING_12_MONTHS: datetime(
                        now.year - 1, now.month, now.day, tzinfo=TZ
                    ),
                }[name]
                self.assert_telescopes(ranges_, natural, now)
            self.assertEqual(
                ranges[eff.PERIOD_TODAY][0].start, today_start.astimezone(UTC)
            )

    def test_dst_day_lengths(self):
        spring = eff.period_ranges(local(2026, 3, 30, 1), TZ)[eff.PERIOD_MONTH_TO_DATE]
        self.assertEqual(spring[0].end - spring[0].start, timedelta(hours=24 * 28 + 23))
        autumn = eff.period_ranges(local(2026, 10, 26, 1), TZ)[eff.PERIOD_MONTH_TO_DATE]
        self.assertEqual(autumn[0].end - autumn[0].start, timedelta(hours=24 * 24 + 25))

    def test_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            eff.period_ranges(datetime(2026, 11, 17, 12), TZ)

    def test_naive_datetime_arguments_are_rejected(self):
        now = local(2026, 11, 17, 12)
        naive = datetime(2026, 11, 13)
        with self.assertRaises(ValueError):
            eff.period_ranges(now, TZ, naive)
        with self.assertRaises(ValueError):
            eff.period_starts(now, TZ, naive)
        with self.assertRaises(ValueError):
            eff.period_ranges(now, TZ, end=naive)
        with self.assertRaises(ValueError):
            eff.includes_estimated(naive, date(2026, 11, 13), TZ)
        with self.assertRaises(ValueError):
            eff.effective_start([naive], TZ)
        with self.assertRaises(ValueError):
            eff.history_windows(now, TZ, [naive])
        with self.assertRaises(ValueError):
            eff.cache_actions({}, naive, {}, [], now, TZ)
        with self.assertRaises(ValueError):
            eff.health(["x"], [], {"x": naive}, now)


class DayStartTests(unittest.TestCase):
    """The statistics day: the first whole UTC hour at or after local midnight."""

    def test_whole_hour_zone_starts_at_midnight(self):
        self.assertEqual(
            eff.day_start(date(2026, 11, 17), TZ), local(2026, 11, 17).astimezone(UTC)
        )

    def test_half_hour_zone_starts_at_half_past_midnight(self):
        start = eff.day_start(date(2026, 11, 17), KOLKATA)
        self.assertEqual(start, local(2026, 11, 17, 0, 30, KOLKATA))
        self.assertEqual(start, datetime(2026, 11, 16, 19, 0, tzinfo=UTC))

    def test_nonexistent_midnight_starts_at_first_existing_instant(self):
        # America/Santiago: on 6 September 2026 the clocks jump from 00:00 to 01:00.
        start = eff.day_start(date(2026, 9, 6), SANTIAGO)
        self.assertEqual(start, local(2026, 9, 6, 1, 0, SANTIAGO))
        self.assertEqual(start, datetime(2026, 9, 6, 4, 0, tzinfo=UTC))
        ranges = eff.period_ranges(local(2026, 9, 6, 12, 0, SANTIAGO), SANTIAGO)
        self.assertEqual(ranges[eff.PERIOD_TODAY][0].start, start)
        self.assertEqual(ranges[eff.PERIOD_MONTH_TO_DATE][-2].end, start)

    def test_effective_start_on_nonexistent_midnight(self):
        jump = datetime(
            2026, 9, 6, 4, 0, tzinfo=UTC
        )  # 01:00 local, the day's first instant
        self.assertEqual(
            eff.effective_start([jump], SANTIAGO), local(2026, 9, 6, 1, 0, SANTIAGO)
        )
        mid_day = local(2026, 9, 5, 14, 0, SANTIAGO)
        self.assertEqual(
            eff.effective_start([mid_day], SANTIAGO), local(2026, 9, 6, 1, 0, SANTIAGO)
        )

    def test_before_half_past_midnight_today_is_the_previous_day(self):
        now = local(2026, 11, 17, 0, 20, KOLKATA)
        self.assertEqual(eff.statistics_day(now, KOLKATA), date(2026, 11, 16))
        starts = eff.period_starts(now, KOLKATA)
        self.assertEqual(starts[eff.PERIOD_TODAY], local(2026, 11, 16, 0, 30, KOLKATA))
        later = local(2026, 11, 17, 0, 30, KOLKATA)
        self.assertEqual(eff.period_starts(later, KOLKATA)[eff.PERIOD_TODAY], later)

    def test_half_hour_zone_period_starts(self):
        now = local(2026, 11, 17, 12, 0, KOLKATA)
        starts = eff.period_starts(now, KOLKATA)
        self.assertEqual(starts[eff.PERIOD_TODAY], local(2026, 11, 17, 0, 30, KOLKATA))
        self.assertEqual(
            starts[eff.PERIOD_MONTH_TO_DATE], local(2026, 11, 1, 0, 30, KOLKATA)
        )
        self.assertEqual(
            starts[eff.PERIOD_YEAR_TO_DATE], local(2026, 1, 1, 0, 30, KOLKATA)
        )
        self.assertEqual(
            starts[eff.PERIOD_ROLLING_12_MONTHS], local(2025, 11, 17, 0, 30, KOLKATA)
        )

    def test_half_hour_zone_effective_start(self):
        # First hours are whole UTC hours: 18:00 UTC is 23:30 local on the 12th.
        self.assertEqual(
            eff.effective_start([datetime(2026, 11, 12, 18, 0, tzinfo=UTC)], KOLKATA),
            local(2026, 11, 13, 0, 30, KOLKATA),
        )
        self.assertEqual(
            eff.effective_start([datetime(2026, 11, 12, 19, 0, tzinfo=UTC)], KOLKATA),
            local(2026, 11, 13, 0, 30, KOLKATA),
        )


class FakeRecorder:
    """One energy counter as Home Assistant's recorder stores and returns it.

    The counter rises by a varying amount in each 5-minute period. 5-minute
    rows exist for periods compiled by ``compiled``; an hourly row's sum is
    that of its last 5-minute row (``_compile_hourly_statistics``) and starts
    on a whole UTC hour. ``read`` mimics ``_statistics_during_period_with_session``:
    it aligns a day read to local midnight and a month read to the local 1st,
    groups the hourly rows by the local date or month of their start with the
    row start at local midnight (``reduce_day_ts_factory``,
    ``reduce_month_ts_factory``, ``_reduce_statistic``) and sets ``change``
    against the last row before the aligned start in the same table
    (``_augment_result_with_change``).
    """

    BASE = datetime(2024, 6, 1, tzinfo=UTC).timestamp()

    def __init__(self, compiled: datetime):
        self.compiled = compiled.timestamp()
        slots = int((self.compiled - self.BASE) // 300)
        self.prefix = [0.0]
        for k in range(slots):  # multiples of 1/64 keep the float sums exact
            self.prefix.append(self.prefix[-1] + ((k * 7) % 13 + 1) / 64)

    def sum_at(self, ts: float) -> float:
        index = (ts - self.BASE) / 300
        assert index == int(index), "not on the 5-minute grid"
        return self.prefix[int(index)]

    def read(self, period: str, start: datetime, end: datetime, tz) -> list[dict]:
        if period in ("5minute", "hour"):
            step = 300 if period == "5minute" else 3600
            first = math.ceil(start.timestamp() / step) * step
            rows, t = [], first
            while t < end.timestamp() and t + step <= self.compiled:
                rows.append(
                    {
                        "start": t,
                        "end": t + step,
                        "change": self.sum_at(t + step) - self.sum_at(t),
                    }
                )
                t += step
            return rows
        start_local = start.astimezone(tz)
        end_local = end.astimezone(tz)
        if period == "day":
            aligned_start = start_local.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            aligned_end = end_local.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
        else:
            aligned_start = start_local.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            aligned_end = (end_local.replace(day=28) + timedelta(days=4)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
        a, b = aligned_start.timestamp(), aligned_end.timestamp()
        hours = []
        h = math.ceil(a / 3600) * 3600
        while h < b and h + 3600 <= self.compiled:
            hours.append(h)
            h += 3600
        rows: list[dict] = []
        key = None
        for h in hours:
            lt = datetime.fromtimestamp(h, tz)
            k = lt.date() if period == "day" else (lt.year, lt.month)
            if k != key:
                floor = lt.replace(hour=0, minute=0, second=0, microsecond=0)
                if period == "month":
                    floor = floor.replace(day=1)
                rows.append({"start": floor.timestamp(), "end": None, "sum": None})
                key = k
            rows[-1]["sum"] = self.sum_at(h + 3600)
        previous_hour = math.ceil(a / 3600) * 3600 - 3600
        prev = self.sum_at(previous_hour + 3600)
        for r in rows:
            r["change"] = r.pop("sum") - prev
            prev += r["change"]
        return rows


def simulate(now: datetime, tz, effective=None):
    """Read every needed table from a FakeRecorder the way the coordinator will."""
    compiled = datetime.fromtimestamp(now.timestamp() // 300 * 300, UTC)
    recorder = FakeRecorder(compiled)
    windows = eff.history_windows(now, tz, [effective])
    ts = {}
    five = recorder.read(
        "5minute", windows["5minute"].start, windows["5minute"].end, tz
    )
    ts["5minute"] = eff.TableRead(
        "5minute", windows["5minute"], {"x": five}, frozenset(), now
    )
    ends = eff.last_row_ends(["x"], [], ts)
    for source in ("day", "month"):
        if source in windows:
            w = windows[source]
            rows_ = recorder.read(source, w.start, w.end, tz)
            ts[source] = eff.TableRead(
                source, w, {"x": rows_}, eff.coverage(["x"], w, ends), now
            )
    return recorder, compiled, ts


class HalfHourTimeZoneTests(unittest.TestCase):
    """Periods checked against the rows Home Assistant builds from UTC-hour statistics."""

    CASES = (
        # zone, now, the expected local start of a day (independent of the module)
        (KOLKATA, local(2026, 11, 17, 12, 0, KOLKATA), (0, 30)),
        (KOLKATA, local(2026, 11, 17, 0, 20, KOLKATA), (0, 30)),  # still 16 November
        (KOLKATA, local(2026, 12, 1, 0, 35, KOLKATA), (0, 30)),  # just into December
        (
            ZoneInfo("Asia/Kathmandu"),
            local(2026, 11, 17, 12, 0, ZoneInfo("Asia/Kathmandu")),
            (0, 45),
        ),
        (TZ, local(2026, 11, 17, 12, 0), (0, 0)),
        (TZ, local(2026, 3, 29, 15, 0), (0, 0)),  # clocks go forward
    )

    def expected_start(self, day: date, tz, hm) -> float:
        return datetime(day.year, day.month, day.day, *hm, tzinfo=tz).timestamp()

    def test_periods_match_home_assistant_rows(self):
        for tz, now, hm in self.CASES:
            with self.subTest(zone=str(tz), now=now.isoformat()):
                recorder, compiled, ts = simulate(now, tz)
                local_now = now.astimezone(tz)
                today = local_now.date()
                if now.timestamp() < self.expected_start(today, tz, hm):
                    today -= timedelta(days=1)
                year_ago = min(today.day, 28 if today.month == 2 else today.day)
                natural = {
                    eff.PERIOD_TODAY: today,
                    eff.PERIOD_MONTH_TO_DATE: today.replace(day=1),
                    eff.PERIOD_YEAR_TO_DATE: date(today.year, 1, 1),
                    eff.PERIOD_ROLLING_12_MONTHS: date(
                        today.year - 1, today.month, year_ago
                    ),
                }
                ranges = eff.period_ranges(now, tz)
                for period, start_day in natural.items():
                    start = self.expected_start(start_day, tz, hm)
                    self.assertEqual(ranges[period][0].start.timestamp(), start, period)
                    truth = recorder.sum_at(compiled.timestamp()) - recorder.sum_at(
                        start
                    )
                    self.assertEqual(
                        eff.period_energy(ts, ["x"], ranges[period]), truth, period
                    )

    def test_daily_and_monthly_points_match_home_assistant_rows(self):
        now = local(2026, 11, 17, 12, 0, KOLKATA)
        recorder, _compiled, ts = simulate(now, KOLKATA)
        hm = (0, 30)
        for day, ranges in eff.daily_plan(now, KOLKATA, None)[:-1]:
            start = self.expected_start(day, KOLKATA, hm)
            end = self.expected_start(day + timedelta(days=1), KOLKATA, hm)
            self.assertEqual(
                eff.period_energy(ts, ["x"], ranges),
                recorder.sum_at(end) - recorder.sum_at(start),
            )
        for first, ranges in eff.monthly_plan(now, KOLKATA, None)[:-1]:
            start = self.expected_start(first, KOLKATA, hm)
            nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
            end = self.expected_start(nxt, KOLKATA, hm)
            self.assertEqual(
                eff.period_energy(ts, ["x"], ranges),
                recorder.sum_at(end) - recorder.sum_at(start),
            )

    def test_nonexistent_midnight_matches_home_assistant_rows(self):
        now = local(2026, 9, 6, 12, 0, SANTIAGO)
        recorder, compiled, ts = simulate(now, SANTIAGO)
        ranges = eff.period_ranges(now, SANTIAGO)
        starts = {
            eff.PERIOD_TODAY: local(
                2026, 9, 6, 1, 0, SANTIAGO
            ),  # midnight does not exist
            eff.PERIOD_MONTH_TO_DATE: local(2026, 9, 1, tz=SANTIAGO),
            eff.PERIOD_YEAR_TO_DATE: local(2026, 1, 1, tz=SANTIAGO),
            eff.PERIOD_ROLLING_12_MONTHS: local(2025, 9, 6, tz=SANTIAGO),
        }
        for period, start in starts.items():
            truth = recorder.sum_at(compiled.timestamp()) - recorder.sum_at(
                start.timestamp()
            )
            self.assertEqual(
                eff.period_energy(ts, ["x"], ranges[period]), truth, period
            )

    def test_first_update_of_the_day_waits_for_half_past_midnight(self):
        ids = ["x"]
        read_at = local(2026, 11, 16, 23, 55, KOLKATA)
        windows = eff.history_windows(read_at, KOLKATA)
        cached = {
            s: eff.TableRead(s, windows[s], {"x": []}, frozenset(ids), read_at)
            for s in ("day", "month")
        }
        at_0020 = local(2026, 11, 17, 0, 20, KOLKATA)
        actions = eff.cache_actions(
            cached,
            read_at,
            eff.history_windows(at_0020, KOLKATA),
            ids,
            at_0020,
            KOLKATA,
        )
        self.assertEqual(actions.tables, {"5minute"})
        self.assertFalse(actions.first_hours)
        at_0030 = local(2026, 11, 17, 0, 30, KOLKATA) + timedelta(seconds=30)
        actions = eff.cache_actions(
            cached,
            read_at,
            eff.history_windows(at_0030, KOLKATA),
            ids,
            at_0030,
            KOLKATA,
        )
        self.assertEqual(actions.tables, {"5minute", "day"})
        self.assertTrue(actions.first_hours)

    def test_new_month_waits_for_half_past_midnight_on_the_first(self):
        ids = ["x"]
        read_at = local(2026, 11, 30, 23, 0, KOLKATA)
        windows = eff.history_windows(read_at, KOLKATA)
        cached = {
            s: eff.TableRead(s, windows[s], {"x": []}, frozenset(ids), read_at)
            for s in ("day", "month")
        }
        at_0020 = local(2026, 12, 1, 0, 20, KOLKATA)
        actions = eff.cache_actions(
            cached,
            read_at,
            eff.history_windows(at_0020, KOLKATA),
            ids,
            at_0020,
            KOLKATA,
        )
        self.assertNotIn("month", actions.tables)
        at_0035 = local(2026, 12, 1, 0, 35, KOLKATA)
        actions = eff.cache_actions(
            cached,
            read_at,
            eff.history_windows(at_0035, KOLKATA),
            ids,
            at_0035,
            KOLKATA,
        )
        self.assertIn("month", actions.tables)

    def test_day_read_before_the_hour_is_compiled_is_retried(self):
        # A day read whose window ends at 00:30 local, made before the 5-minute
        # row ending at 00:30 exists, does not cover the statistic.
        now = local(2026, 11, 17, 0, 30, KOLKATA) + timedelta(seconds=5)
        window = eff.history_windows(now, KOLKATA)["day"]
        ends = {"x": local(2026, 11, 17, 0, 25, KOLKATA).timestamp()}
        self.assertEqual(eff.coverage(["x"], window, ends), frozenset())
        ends = {"x": local(2026, 11, 17, 0, 30, KOLKATA).timestamp()}
        self.assertEqual(eff.coverage(["x"], window, ends), {"x"})


class EffectiveStartTests(unittest.TestCase):
    def test_history_from_midnight(self):
        self.assertEqual(
            eff.effective_start([local(2026, 11, 13, 0)], TZ), local(2026, 11, 13)
        )

    def test_history_starting_mid_day(self):
        self.assertEqual(
            eff.effective_start([local(2026, 11, 13, 14)], TZ), local(2026, 11, 14)
        )

    def test_latest_first_hour_wins_and_epoch_input_works(self):
        hours = [local(2026, 1, 1, 0).timestamp(), local(2026, 11, 13, 0)]
        self.assertEqual(eff.effective_start(hours, TZ), local(2026, 11, 13))

    def test_no_hours(self):
        self.assertIsNone(eff.effective_start([], TZ))

    def test_first_hour_not_known_yet_counts_as_starting_now(self):
        # A statistic with rows but no hourly row yet: its service has not begun until tomorrow.
        now = local(2026, 11, 17, 9, 20)
        self.assertEqual(
            eff.effective_start([local(2025, 1, 1), None], TZ, now), local(2026, 11, 18)
        )
        ranges = eff.period_ranges(now, TZ, eff.effective_start([None], TZ, now))
        self.assertTrue(all(r is None for r in ranges.values()))
        with self.assertRaises(ValueError):
            eff.effective_start([None], TZ)

    def test_year_to_date_limited_by_electrical_history(self):
        now = local(2026, 11, 17, 12)
        effective = eff.effective_start([local(2026, 1, 1), local(2026, 11, 13)], TZ)
        ranges = eff.period_ranges(now, TZ, effective)
        ytd = ranges[eff.PERIOD_YEAR_TO_DATE]
        # 13 November is inside a completed month: served from the day table.
        self.assertEqual([r.source for r in ytd], ["day", "5minute"])
        self.assertEqual(ytd[0].start, local(2026, 11, 13).astimezone(UTC))
        self.assertEqual(
            eff.period_starts(now, TZ, effective)[eff.PERIOD_YEAR_TO_DATE],
            local(2026, 11, 13),
        )
        # Periods that start later are unaffected.
        self.assertEqual(
            eff.period_starts(now, TZ, effective)[eff.PERIOD_TODAY], local(2026, 11, 17)
        )

    def test_history_from_mid_day_starts_next_midnight(self):
        now = local(2026, 11, 17, 12)
        effective = eff.effective_start([local(2026, 11, 13, 14)], TZ)
        self.assertEqual(
            eff.period_starts(now, TZ, effective)[eff.PERIOD_YEAR_TO_DATE],
            local(2026, 11, 14),
        )

    def test_effective_start_mid_month_uses_whole_months_after_it(self):
        now = local(2026, 11, 17, 12)
        ranges = eff.period_ranges(now, TZ, local(2026, 3, 10))[eff.PERIOD_YEAR_TO_DATE]
        self.assertEqual([r.source for r in ranges], ["day", "month", "day", "5minute"])
        self.assertEqual(ranges[0].end, local(2026, 4, 1).astimezone(UTC))

    def test_limited_period_not_begun(self):
        now = local(2026, 11, 17, 12)
        effective = eff.effective_start([local(2026, 11, 17, 9)], TZ)  # tomorrow 00:00
        ranges = eff.period_ranges(now, TZ, effective)
        for period in eff.PERIODS:
            self.assertIsNone(ranges[period])
            summary = eff.period_summary(
                tables(month={}, day={}, five={}), ranges[period], ["o"], ["e"]
            )
            self.assertIsNone(summary["efficiency"])
        self.assertTrue(
            all(v is None for v in eff.period_starts(now, TZ, effective).values())
        )

    def test_history_starting_today_midnight_is_known(self):
        now = local(2026, 11, 17, 12)
        effective = eff.effective_start([local(2026, 11, 17, 0)], TZ)
        ranges = eff.period_ranges(now, TZ, effective)
        for period in eff.PERIODS:
            self.assertEqual([r.source for r in ranges[period]], ["5minute"])


class BackfillTests(unittest.TestCase):
    """History extended by a backfill: never a figure from the old start onwards."""

    IDS = ["o", "e"]

    def history(self):
        months, days = {"o": [], "e": []}, {"o": [], "e": []}
        for m in range(1, 11):
            months["o"].append(month_row(2026, m, 36.0))
            months["e"].append(month_row(2026, m, 10.0))
        for d in range(1, 18):
            days["o"].append(day_row(2026, 11, d, 9.0))
            days["e"].append(day_row(2026, 11, d, 3.0))
        return months, days

    def read(self, source, windows, rows_, now):
        return eff.TableRead(source, windows[source], rows_, frozenset(self.IDS), now)

    def test_year_to_date_unknown_until_months_are_read_again(self):
        months, days = self.history()
        setup = local(2026, 11, 17, 12)
        effective = local(2026, 11, 13)
        windows = eff.history_windows(setup, TZ, [effective])
        self.assertNotIn("month", windows)
        actions = eff.cache_actions({}, None, windows, self.IDS, setup, TZ)
        self.assertEqual(actions.tables, {"day", "5minute"})
        cache = {"day": self.read("day", windows, days, setup)}

        # Next day: the first-hours refresh finds the backfilled history.
        now = local(2026, 11, 18, 0, 0) + timedelta(seconds=30)
        first = eff.cache_actions(
            cache, setup, eff.history_windows(now, TZ, [effective]), self.IDS, now, TZ
        )
        self.assertTrue(first.first_hours)
        needed = eff.history_windows(now, TZ, [None])
        second = eff.cache_actions(cache, now, needed, self.IDS, now, TZ)
        self.assertFalse(second.first_hours)
        self.assertEqual(second.tables, {"month", "day", "5minute"})

        five = self.read(
            "5minute",
            needed,
            {
                "o": [row(local(2026, 11, 18), 0.9)],
                "e": [row(local(2026, 11, 18), 0.3)],
            },
            now,
        )
        ranges = eff.period_ranges(now, TZ)
        # The month read failed and the day read still holds the old window.
        stale = {
            "day": cache["day"],
            "month": eff.TableRead("month", needed["month"], None),
            "5minute": five,
        }
        self.assertIsNone(
            eff.period_summary(stale, ranges[eff.PERIOD_YEAR_TO_DATE], ["o"], ["e"])[
                "efficiency"
            ]
        )
        # Months not read at all: still unknown, not 13 November onwards.
        self.assertIsNone(
            eff.period_summary(
                {"day": cache["day"], "5minute": five},
                ranges[eff.PERIOD_YEAR_TO_DATE],
                ["o"],
                ["e"],
            )["efficiency"]
        )
        # After the re-read of both tables: from 1 January.
        fresh = {
            "month": self.read("month", needed, months, now),
            "day": self.read("day", needed, days, now),
            "5minute": five,
        }
        ytd = eff.period_summary(fresh, ranges[eff.PERIOD_YEAR_TO_DATE], ["o"], ["e"])
        self.assertEqual(ytd["output_energy"], 360.0 + 17 * 9.0 + 0.9)
        self.assertEqual(
            eff.period_starts(now, TZ)[eff.PERIOD_YEAR_TO_DATE], local(2026, 1, 1)
        )
        later = now + timedelta(minutes=5)
        self.assertEqual(
            eff.cache_actions(
                fresh, now, eff.history_windows(later, TZ, [None]), self.IDS, later, TZ
            ).tables,
            {"5minute"},
        )

    def test_moved_window_is_read_again_the_same_day(self):
        # A reload is not needed: a cached day table whose window no longer
        # contains the needed one is read again.
        now = local(2026, 11, 17, 12)
        old = eff.history_windows(now, TZ, [local(2026, 11, 13)])
        cache = {
            "day": eff.TableRead(
                "day", old["day"], {"o": [], "e": []}, frozenset(self.IDS), now
            )
        }
        later = now + timedelta(minutes=5)
        needed = eff.history_windows(later, TZ, [local(2026, 3, 10)])
        self.assertEqual(
            eff.cache_actions(cache, now, needed, self.IDS, later, TZ).tables,
            {"month", "day", "5minute"},
        )


class LaggingStatisticTests(unittest.TestCase):
    IDS = ["o", "e"]

    def test_unknown_and_retried_until_covered(self):
        now = local(2026, 11, 18, 0, 0) + timedelta(seconds=30)
        needed = eff.history_windows(now, TZ)
        five_rows = {
            "o": [row(local(2026, 11, 17, 23, 55), 0.5)],
            "e": [row(local(2026, 11, 17, 19, 55), 0.2)],  # nothing after 20:00 yet
        }
        five = eff.TableRead("5minute", needed["5minute"], five_rows, frozenset(), now)
        ends = eff.last_row_ends(self.IDS, [], {"5minute": five})
        day_rows = {
            "o": [day_row(2026, 11, d, 9.0) for d in range(1, 18)],
            "e": [day_row(2026, 11, d, 3.0) for d in range(1, 18)],
        }
        day = eff.TableRead(
            "day",
            needed["day"],
            day_rows,
            eff.coverage(self.IDS, needed["day"], ends),
            now,
        )
        self.assertEqual(day.covered, {"o"})
        month = eff.TableRead(
            "month",
            needed["month"],
            {"o": [], "e": []},
            eff.coverage(self.IDS, needed["month"], ends),
            now,
        )
        cache = {"day": day, "month": month, "5minute": five}
        ranges = eff.period_ranges(now, TZ)
        for period in (
            eff.PERIOD_MONTH_TO_DATE,
            eff.PERIOD_YEAR_TO_DATE,
            eff.PERIOD_ROLLING_12_MONTHS,
        ):
            self.assertIsNone(
                eff.period_summary(cache, ranges[period], ["o"], ["e"])["efficiency"],
                period,
            )
        self.assertEqual(eff.daily_series(cache, ["o"], ["e"], now, TZ), [])

        # Retried at each update while the statistic lags.
        for minutes in (5, 10, 15):
            later = now + timedelta(minutes=minutes)
            self.assertIn(
                "day",
                eff.cache_actions(
                    cache, now, eff.history_windows(later, TZ), self.IDS, later, TZ
                ).tables,
            )

        # Caught up: covered, known, and no further re-read.
        later = now + timedelta(minutes=20)
        ends = {"o": later.timestamp() - 30, "e": later.timestamp() - 30}
        cache["day"] = eff.TableRead(
            "day",
            needed["day"],
            day_rows,
            eff.coverage(self.IDS, needed["day"], ends),
            later,
        )
        self.assertEqual(
            eff.period_summary(cache, ranges[eff.PERIOD_MONTH_TO_DATE], ["o"], ["e"])[
                "efficiency"
            ],
            3.0,
        )
        after = later + timedelta(minutes=5)
        self.assertNotIn(
            "day",
            eff.cache_actions(
                cache, now, eff.history_windows(after, TZ), self.IDS, after, TZ
            ).tables,
        )


class ExternalStatisticTests(unittest.TestCase):
    """Overall electricity is an external statistic with hourly rows up to 14:00; it is 14:20."""

    NOW = local(2026, 11, 17, 14, 20)
    METADATA = [
        {
            "statistic_id": "heat_out",
            "source": "recorder",
            "has_sum": True,
            "unit_class": "energy",
        },
        {
            "statistic_id": "heat_el",
            "source": "recorder",
            "has_sum": True,
            "unit_class": "energy",
        },
        {
            "statistic_id": "ov_out",
            "source": "recorder",
            "has_sum": True,
            "unit_class": "energy",
        },
        {
            "statistic_id": "ov_el",
            "source": "tibber",
            "has_sum": True,
            "unit_class": "energy",
        },
    ]

    def reads(self):
        windows = eff.history_windows(self.NOW, TZ, [None], hourly=True)
        start = local(2026, 11, 17)
        five, hour = {}, {}
        for sid in (
            "heat_out",
            "heat_el",
            "ov_out",
        ):  # recorder: 5-minute rows to 14:15
            five[sid] = [
                row(start + timedelta(minutes=5 * k), 0.1) for k in range(14 * 12 + 3)
            ]
        for sid in ("heat_out", "heat_el", "ov_out", "ov_el"):  # hourly rows to 14:00
            hour[sid] = [
                row(start + timedelta(hours=k), 1.2, minutes=60) for k in range(14)
            ]
        return windows, {
            "5minute": eff.TableRead(
                "5minute", windows["5minute"], five, frozenset(), self.NOW
            ),
            "hour": eff.TableRead("hour", windows["hour"], hour, frozenset(), self.NOW),
            "day": eff.TableRead(
                "day", FAR, {s: [] for s in hour}, frozenset(hour), self.NOW
            ),
            "month": eff.TableRead(
                "month", FAR, {s: [] for s in hour}, frozenset(hour), self.NOW
            ),
        }

    def test_hour_window_only_when_needed(self):
        windows = eff.history_windows(self.NOW, TZ, [None], hourly=True)
        self.assertEqual(windows["hour"], windows["5minute"])
        self.assertNotIn("hour", eff.history_windows(self.NOW, TZ, [None]))
        self.assertEqual(eff.hourly_only(self.METADATA), {"ov_el"})

    def test_overall_ends_at_14_00_and_other_services_at_14_15(self):
        _windows, ts = self.reads()
        hourly = eff.hourly_only(self.METADATA)
        self.assertTrue(eff.reads_hourly(["ov_out", "ov_el"], hourly))
        self.assertFalse(eff.reads_hourly(["heat_out", "heat_el"], hourly))
        overall_end = eff.coverage_end(["ov_out", "ov_el"], hourly, ts, self.NOW)
        self.assertEqual(overall_end, local(2026, 11, 17, 14).astimezone(UTC))
        # A service without an hourly-only statistic ends at its last 5-minute rows.
        heating_end = eff.coverage_end(["heat_out", "heat_el"], hourly, ts, self.NOW)
        self.assertEqual(heating_end, local(2026, 11, 17, 14, 15).astimezone(UTC))

        overall = eff.period_ranges(self.NOW, TZ, end=overall_end, hourly=True)
        for period in eff.PERIODS:
            self.assertEqual(overall[period][-1].source, "hour")
            self.assertEqual(
                overall[period][-1].end, local(2026, 11, 17, 14).astimezone(UTC)
            )
        today = eff.period_summary(ts, overall[eff.PERIOD_TODAY], ["ov_out"], ["ov_el"])
        self.assertEqual(
            today["output_energy"], round(14 * 1.2, 3)
        )  # both counters to 14:00
        self.assertEqual(today["electrical_energy"], round(14 * 1.2, 3))

        heating = eff.period_ranges(self.NOW, TZ, end=heating_end)
        self.assertEqual(heating[eff.PERIOD_TODAY][-1].source, "5minute")
        self.assertEqual(heating[eff.PERIOD_TODAY][-1].end, heating_end)
        today = eff.period_summary(
            ts, heating[eff.PERIOD_TODAY], ["heat_out"], ["heat_el"]
        )
        self.assertEqual(today["output_energy"], round(171 * 0.1, 3))  # to 14:15

        series = eff.daily_series(
            ts, ["ov_out"], ["ov_el"], self.NOW, TZ, end=overall_end, hourly=True
        )
        self.assertEqual(series[-1]["start"], local(2026, 11, 17).isoformat())

    def test_last_row_ends_use_the_table_each_statistic_is_read_from(self):
        _, ts = self.reads()
        ends = eff.last_row_ends(["heat_out", "ov_el"], {"ov_el"}, ts)
        self.assertEqual(ends["heat_out"], local(2026, 11, 17, 14, 15).timestamp())
        self.assertEqual(ends["ov_el"], local(2026, 11, 17, 14, 0).timestamp())

    def test_missing_hourly_rows_make_every_period_unknown(self):
        _, ts = self.reads()
        ts["hour"].rows["ov_el"].clear()
        end = eff.coverage_end(["ov_out", "ov_el"], {"ov_el"}, ts, self.NOW)
        self.assertEqual(end, eff.NO_COVERAGE)
        self.assertTrue(
            all(
                r is None
                for r in eff.period_ranges(self.NOW, TZ, end=end, hourly=True).values()
            )
        )
        failed = {"hour": eff.TableRead("hour", ts["hour"].window, None)}
        self.assertEqual(
            eff.coverage_end(["ov_out", "ov_el"], {"ov_el"}, failed, self.NOW),
            eff.NO_COVERAGE,
        )
        self.assertEqual(
            eff.coverage_end(["ov_out", "ov_el"], {"ov_el"}, {}, self.NOW),
            eff.NO_COVERAGE,
        )

    def test_coverage_end_before_today_leaves_completed_days(self):
        midnight = local(2026, 11, 17)
        ranges = eff.period_ranges(
            local(2026, 11, 17, 0, 20), TZ, end=midnight, hourly=True
        )
        self.assertEqual(
            [r.source for r in ranges[eff.PERIOD_MONTH_TO_DATE]], ["day", "hour"]
        )
        self.assertEqual(
            ranges[eff.PERIOD_MONTH_TO_DATE][-1].start,
            ranges[eff.PERIOD_MONTH_TO_DATE][-1].end,
        )
        earlier = eff.period_ranges(
            local(2026, 11, 17, 0, 20),
            TZ,
            end=midnight - timedelta(hours=1),
            hourly=True,
        )
        self.assertTrue(all(r is None for r in earlier.values()))


class CoverageEndTests(unittest.TestCase):
    """Every service ends all its periods at its coverage end (design D2)."""

    NOW = local(2026, 11, 17, 10, 20)

    def reads(self, el_until=(8, 20)):
        """Heating output with 5-minute rows to 10:20, electricity only to ``el_until``."""
        windows = eff.history_windows(self.NOW, TZ)
        start = local(2026, 11, 17)
        el_end = local(2026, 11, 17, *el_until)
        five = {
            "out": [
                row(start + timedelta(minutes=5 * k), 0.4) for k in range(10 * 12 + 4)
            ],
            "el": [
                row(start + timedelta(minutes=5 * k), 0.1)
                for k in range(int((el_end - start).total_seconds()) // 300)
            ],
        }
        days = {
            "out": [day_row(2026, 11, d, 40.0) for d in range(1, 17)],
            "el": [day_row(2026, 11, d, 10.0) for d in range(1, 17)],
        }
        months = {"out": [], "el": []}
        return {
            "5minute": eff.TableRead(
                "5minute", windows["5minute"], five, frozenset(), self.NOW
            ),
            "day": eff.TableRead(
                "day", windows["day"], days, frozenset(five), self.NOW
            ),
            "month": eff.TableRead(
                "month", windows["month"], months, frozenset(five), self.NOW
            ),
        }

    def test_sensor_offline_cuts_both_counters(self):
        # Spec "Sensor offline": no electricity statistics since 08:20 and it is 10:20.
        ts = self.reads()
        end = eff.coverage_end(["out", "el"], [], ts, self.NOW)
        self.assertEqual(end, local(2026, 11, 17, 8, 20).astimezone(UTC))
        ranges = eff.period_ranges(self.NOW, TZ, end=end)
        for period in eff.PERIODS:
            self.assertEqual(ranges[period][-1].source, "5minute", period)
            self.assertEqual(ranges[period][-1].end, end, period)
        today = eff.period_summary(ts, ranges[eff.PERIOD_TODAY], ["out"], ["el"])
        # 100 five-minute periods to 08:20 for both counters: no output without electricity.
        self.assertEqual(today["output_energy"], round(100 * 0.4, 3))
        self.assertEqual(today["electrical_energy"], round(100 * 0.1, 3))
        self.assertEqual(today["efficiency"], 4.0)
        mtd = eff.period_summary(ts, ranges[eff.PERIOD_MONTH_TO_DATE], ["out"], ["el"])
        self.assertEqual(mtd["output_energy"], round(16 * 40.0 + 100 * 0.4, 3))
        self.assertEqual(mtd["efficiency"], 4.0)
        # Without the cut, today would count output to 10:20 against electricity to 08:20.
        uncut = eff.period_summary(
            ts, eff.period_ranges(self.NOW, TZ)[eff.PERIOD_TODAY], ["out"], ["el"]
        )
        self.assertEqual(uncut["output_energy"], round(124 * 0.4, 3))
        # The period starts are unchanged; today's daily point and November's point end at 08:20.
        self.assertEqual(
            eff.period_starts(self.NOW, TZ, end=end), eff.period_starts(self.NOW, TZ)
        )
        self.assertEqual(eff.daily_plan(self.NOW, TZ, None, end)[-1][1][-1].end, end)
        self.assertEqual(eff.monthly_plan(self.NOW, TZ, None, end)[-1][1][-1].end, end)
        daily = eff.daily_series(ts, ["out"], ["el"], self.NOW, TZ, end=end)
        self.assertEqual(
            daily[-1],
            {
                "start": local(2026, 11, 17).isoformat(),
                "efficiency": 4.0,
                "estimated": False,
            },
        )

    def test_healthy_service_ends_at_its_last_five_minute_row(self):
        ts = self.reads(el_until=(10, 20))
        self.assertEqual(
            eff.coverage_end(["out", "el"], [], ts, self.NOW),
            local(2026, 11, 17, 10, 20).astimezone(UTC),
        )
        # At most now, even when a row ends later.
        early = local(2026, 11, 17, 10, 0)
        self.assertEqual(
            eff.coverage_end(["out", "el"], [], ts, early), early.astimezone(UTC)
        )

    def test_statistic_without_a_row_in_the_today_window_makes_the_service_unknown(
        self,
    ):
        ts = self.reads()
        ts["5minute"].rows["el"].clear()
        end = eff.coverage_end(["out", "el"], [], ts, self.NOW)
        self.assertEqual(end, eff.NO_COVERAGE)
        ranges = eff.period_ranges(self.NOW, TZ, end=end)
        self.assertTrue(all(r is None for r in ranges.values()))
        self.assertTrue(
            all(s is None for s in eff.period_starts(self.NOW, TZ, end=end).values())
        )
        for period in eff.PERIODS:
            self.assertIsNone(
                eff.period_summary(ts, ranges[period], ["out"], ["el"])["efficiency"]
            )
        # No point for today or for the current month.
        daily = eff.daily_series(ts, ["out"], ["el"], self.NOW, TZ, end=end)
        self.assertNotIn(local(2026, 11, 17).isoformat(), [p["start"] for p in daily])
        monthly = eff.monthly_series(ts, ["out"], ["el"], self.NOW, TZ, end=end)
        self.assertNotIn(local(2026, 11, 1).isoformat(), [p["start"] for p in monthly])
        # A failed or missing 5-minute read: unknown too.
        self.assertEqual(
            eff.coverage_end(
                ["out", "el"],
                [],
                {"5minute": eff.TableRead("5minute", FAR, None)},
                self.NOW,
            ),
            eff.NO_COVERAGE,
        )
        self.assertEqual(
            eff.coverage_end(["out", "el"], [], {}, self.NOW), eff.NO_COVERAGE
        )

    def test_coverage_end_at_todays_start_keeps_the_completed_days(self):
        now = local(2026, 11, 17, 0, 20)
        ranges = eff.period_ranges(now, TZ, end=local(2026, 11, 17))
        self.assertEqual(
            [r.source for r in ranges[eff.PERIOD_MONTH_TO_DATE]], ["day", "5minute"]
        )
        self.assertEqual(
            ranges[eff.PERIOD_TODAY][0].start, ranges[eff.PERIOD_TODAY][0].end
        )
        earlier = eff.period_ranges(now, TZ, end=local(2026, 11, 16, 23, 55))
        self.assertTrue(all(r is None for r in earlier.values()))


class SeriesTests(unittest.TestCase):
    NOW = local(2026, 11, 17, 12)

    def monthly_rows(self, last=(2026, 10)):
        months, y, m = {"o": [], "e": []}, 2025, 11
        while (y, m) <= last:
            months["o"].append(month_row(y, m, 36.0))
            months["e"].append(month_row(y, m, 10.0))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return months

    def test_cooling_month_without_electricity_has_no_point(self):
        months = self.monthly_rows()
        months["e"][2] = month_row(2026, 1, 0.0)  # January: no electricity
        months["o"][2] = month_row(2026, 1, 0.0)
        ts = tables(
            month=months,
            day={"o": [day_row(2026, 11, 1, 36.0)], "e": [day_row(2026, 11, 1, 10.0)]},
            five={},
        )
        series = eff.monthly_series(ts, ["o"], ["e"], self.NOW, TZ)
        starts = [p["start"] for p in series]
        self.assertNotIn(local(2026, 1, 1).isoformat(), starts)
        self.assertIn(local(2026, 2, 1).isoformat(), starts)
        self.assertTrue(all(p["efficiency"] > 0 for p in series))

    def test_same_month_last_year_and_this_month_so_far(self):
        ts = tables(
            month=self.monthly_rows(),
            day={"o": [day_row(2026, 11, 1, 36.0)], "e": [day_row(2026, 11, 1, 10.0)]},
            five={
                "o": [row(local(2026, 11, 17, 8), 3.6)],
                "e": [row(local(2026, 11, 17, 8), 1.0)],
            },
        )
        series = eff.monthly_series(ts, ["o"], ["e"], self.NOW, TZ)
        starts = [p["start"] for p in series]
        self.assertIn(local(2025, 11, 1).isoformat(), starts)
        self.assertEqual(series[-1]["start"], local(2026, 11, 1).isoformat())
        self.assertEqual(series[-1]["efficiency"], 3.6)
        self.assertEqual(len(series), 13)
        self.assertEqual(set(series[0]), {"start", "efficiency", "estimated"})

    def test_estimated_marks_around_the_switch_over(self):
        now = local(2026, 12, 5, 12)
        months = self.monthly_rows(last=(2026, 11))
        ts = tables(
            month=months,
            day={"o": [day_row(2026, 12, 1, 36.0)], "e": [day_row(2026, 12, 1, 10.0)]},
            five={},
        )
        series = eff.monthly_series(
            ts, ["o"], ["e"], now, TZ, measured_since=date(2026, 11, 13)
        )
        marks = {p["start"]: p["estimated"] for p in series}
        self.assertTrue(marks[local(2026, 11, 1).isoformat()])
        self.assertTrue(marks[local(2026, 10, 1).isoformat()])
        self.assertTrue(marks[local(2025, 11, 1).isoformat()])
        self.assertFalse(marks[local(2026, 12, 1).isoformat()])

    def test_month_starting_at_the_measured_history(self):
        # Measured since 13 November and effective start 13 November: the
        # covered start of November and of year to date is not before it.
        effective = local(2026, 11, 13)
        since = date(2026, 11, 13)
        days = {
            "o": [day_row(2026, 11, d, 8.0) for d in range(13, 17)],
            "e": [day_row(2026, 11, d, 2.0) for d in range(13, 17)],
        }
        ts = tables(month={}, day=days, five={})
        monthly = eff.monthly_series(ts, ["o"], ["e"], self.NOW, TZ, effective, since)
        self.assertEqual(
            [(p["start"], p["estimated"]) for p in monthly],
            [(local(2026, 11, 1).isoformat(), False)],
        )
        starts = eff.period_starts(self.NOW, TZ, effective)
        self.assertFalse(
            eff.includes_estimated(starts[eff.PERIOD_YEAR_TO_DATE], since, TZ)
        )
        self.assertFalse(
            eff.includes_estimated(starts[eff.PERIOD_MONTH_TO_DATE], since, TZ)
        )
        # Without the effective start the same month starts on the 1st: estimated.
        self.assertTrue(
            eff.includes_estimated(
                eff.period_starts(self.NOW, TZ)[eff.PERIOD_YEAR_TO_DATE], since, TZ
            )
        )

    def test_daily_estimated_marks(self):
        days = {"o": [], "e": []}
        for d in range(1, 17):
            days["o"].append(day_row(2026, 11, d, 8.0))
            days["e"].append(day_row(2026, 11, d, 2.0))
        ts = tables(month={}, day=days, five={})
        series = eff.daily_series(
            ts, ["o"], ["e"], self.NOW, TZ, measured_since=date(2026, 11, 13)
        )
        marks = {p["start"]: p["estimated"] for p in series}
        self.assertTrue(marks[local(2026, 11, 12).isoformat()])
        self.assertFalse(marks[local(2026, 11, 13).isoformat()])
        self.assertFalse(marks[local(2026, 11, 16).isoformat()])

    def test_no_date_no_marks(self):
        ts = tables(
            month=self.monthly_rows(),
            day={"o": [day_row(2026, 11, 3, 36.0)], "e": [day_row(2026, 11, 3, 10.0)]},
            five={},
        )
        for series in (
            eff.monthly_series(ts, ["o"], ["e"], self.NOW, TZ),
            eff.daily_series(ts, ["o"], ["e"], self.NOW, TZ),
        ):
            self.assertTrue(series)
            self.assertFalse(any(p["estimated"] for p in series))
        self.assertFalse(eff.includes_estimated(local(2026, 1, 1), None, TZ))

    def test_includes_estimated_for_period_sensors(self):
        since = date(2026, 11, 13)
        self.assertTrue(eff.includes_estimated(local(2026, 1, 1), since, TZ))
        self.assertFalse(eff.includes_estimated(local(2026, 11, 13), since, TZ))
        self.assertFalse(eff.includes_estimated(None, since, TZ))

    def test_series_limited_by_effective_start(self):
        effective = local(2026, 11, 13)
        days = {"o": [], "e": []}
        for d in range(1, 17):
            days["o"].append(day_row(2026, 11, d, 8.0))
            days["e"].append(day_row(2026, 11, d, 2.0))
        ts = tables(month=self.monthly_rows(), day=days, five={})
        daily = eff.daily_series(ts, ["o"], ["e"], self.NOW, TZ, effective)
        self.assertEqual(daily[0]["start"], local(2026, 11, 13).isoformat())
        monthly = eff.monthly_series(ts, ["o"], ["e"], self.NOW, TZ, effective)
        self.assertEqual(
            [p["start"] for p in monthly], [local(2026, 11, 1).isoformat()]
        )
        self.assertEqual(monthly[0]["efficiency"], 4.0)  # only days 13..16 count

    def test_series_lengths(self):
        self.assertEqual(len(eff.daily_plan(self.NOW, TZ, None)), 31)
        self.assertEqual(len(eff.monthly_plan(self.NOW, TZ, None)), 24)

    def test_history_windows_cover_all_ranges(self):
        windows = eff.history_windows(self.NOW, TZ)
        self.assertEqual(windows["month"].start, local(2024, 12, 1).astimezone(UTC))
        self.assertEqual(windows["month"].end, local(2026, 11, 1).astimezone(UTC))
        self.assertEqual(windows["day"].start, local(2025, 11, 17).astimezone(UTC))
        self.assertEqual(windows["day"].end, local(2026, 11, 17).astimezone(UTC))
        self.assertEqual(
            windows["5minute"],
            eff.Window(local(2026, 11, 17).astimezone(UTC), self.NOW.astimezone(UTC)),
        )
        self.assertNotIn("hour", windows)

    def test_history_windows_today_reaches_back_three_hours_after_midnight(self):
        now = local(2026, 11, 17, 0, 5)
        windows = eff.history_windows(now, TZ)
        self.assertEqual(
            windows["5minute"].start, now.astimezone(UTC) - timedelta(hours=3)
        )

    def test_history_windows_with_a_recent_effective_start(self):
        windows = eff.history_windows(self.NOW, TZ, [local(2026, 11, 13)])
        self.assertNotIn("month", windows)
        self.assertEqual(
            windows["day"],
            eff.Window(
                local(2026, 11, 13).astimezone(UTC), local(2026, 11, 17).astimezone(UTC)
            ),
        )

    def test_history_windows_with_a_mid_month_effective_start_in_an_old_month(self):
        windows = eff.history_windows(self.NOW, TZ, [local(2025, 2, 10)])
        # February 2025 is cut by the effective start: its days come from the day table.
        self.assertEqual(windows["day"].start, local(2025, 2, 10).astimezone(UTC))
        self.assertEqual(windows["day"].end, local(2026, 11, 17).astimezone(UTC))
        self.assertEqual(windows["month"].start, local(2025, 3, 1).astimezone(UTC))
        self.assertEqual(windows["month"].end, local(2026, 11, 1).astimezone(UTC))

    def test_history_windows_union_over_services(self):
        windows = eff.history_windows(self.NOW, TZ, [local(2026, 11, 13), None])
        self.assertEqual(windows["month"].start, local(2024, 12, 1).astimezone(UTC))
        self.assertEqual(windows["day"].start, local(2025, 11, 17).astimezone(UTC))


class CacheTests(unittest.TestCase):
    IDS = ["o", "e"]

    def cache_at(self, read_at, covered=None, rows_=None, window_now=None):
        windows = eff.history_windows(window_now or read_at, TZ)
        covered = frozenset(self.IDS if covered is None else covered)
        rows_ = {"o": [], "e": []} if rows_ is None else rows_
        return {
            s: eff.TableRead(s, windows[s], rows_, covered, read_at)
            for s in ("day", "month")
        }

    def actions(self, cache, first_hours_read_at, now):
        return eff.cache_actions(
            cache, first_hours_read_at, eff.history_windows(now, TZ), self.IDS, now, TZ
        )

    def test_setup_reads_everything(self):
        a = self.actions({}, None, local(2026, 11, 17, 12))
        self.assertEqual(
            a, eff.CacheActions(frozenset({"month", "day", "5minute"}), True)
        )

    def test_ten_updates_in_a_day_read_history_once(self):
        cache, first_read, history_reads = {}, None, 0
        for i in range(10):
            now = local(2026, 11, 17, 1, 0) + timedelta(minutes=5 * i)
            actions = self.actions(cache, first_read, now)
            self.assertIn("5minute", actions.tables)
            if actions.first_hours:
                first_read = now
            if actions.tables & {"day", "month"}:
                history_reads += 1
                cache = self.cache_at(now)  # the coordinator's cache read succeeded
        self.assertEqual(history_reads, 1)

    def test_first_update_after_midnight_reads_the_completed_day(self):
        previous = local(2026, 11, 16, 23, 55)
        a = self.actions(self.cache_at(previous), previous, local(2026, 11, 17, 0, 5))
        self.assertEqual(a.tables, {"day", "5minute"})
        self.assertTrue(a.first_hours)

    def test_first_of_month_also_reads_the_completed_month(self):
        previous = local(2026, 11, 30, 23, 55)
        a = self.actions(self.cache_at(previous), previous, local(2026, 12, 1, 0, 5))
        self.assertEqual(a.tables, {"day", "month", "5minute"})

    def test_missed_updates_still_read_the_new_month(self):
        previous = local(2026, 11, 30, 12)
        a = self.actions(self.cache_at(previous), previous, local(2026, 12, 2, 9))
        self.assertEqual(a.tables, {"day", "month", "5minute"})

    def test_failed_cache_read_is_retried(self):
        now = local(2026, 11, 17, 0, 5)
        cache = self.cache_at(now)
        cache["day"] = eff.TableRead("day", cache["day"].window, None, frozenset(), now)
        for later in (now + timedelta(minutes=5), now + timedelta(minutes=10)):
            self.assertEqual(self.actions(cache, now, later).tables, {"day", "5minute"})

    def test_uncovered_read_is_retried(self):
        now = local(2026, 11, 17, 0, 5)
        cache = self.cache_at(now, covered={"o"})
        self.assertEqual(
            self.actions(cache, now, now + timedelta(minutes=5)).tables,
            {"day", "month", "5minute"},
        )

    def test_moved_window_is_read_again(self):
        now = local(2026, 11, 17, 12)
        cache = self.cache_at(now)
        later = now + timedelta(minutes=5)
        needed = eff.history_windows(
            later, TZ, [local(2022, 1, 1)]
        )  # no limit: same windows
        self.assertEqual(
            eff.cache_actions(cache, now, needed, self.IDS, later, TZ).tables,
            {"5minute"},
        )
        cache["month"] = eff.TableRead(
            "month",
            eff.Window(
                local(2025, 6, 1).astimezone(UTC), local(2026, 11, 1).astimezone(UTC)
            ),
            {"o": [], "e": []},
            frozenset(self.IDS),
            now,
        )
        self.assertEqual(
            eff.cache_actions(cache, now, needed, self.IDS, later, TZ).tables,
            {"month", "5minute"},
        )

    def test_new_mapped_statistic_is_read(self):
        now = local(2026, 11, 17, 12)
        cache = self.cache_at(now)
        later = now + timedelta(minutes=5)
        needed = eff.history_windows(later, TZ)
        actions = eff.cache_actions(cache, now, needed, [*self.IDS, "new"], later, TZ)
        self.assertEqual(actions.tables, {"day", "month", "5minute"})

    def test_hour_table_read_at_every_update_when_needed(self):
        now = local(2026, 11, 17, 12)
        needed = eff.history_windows(now, TZ, hourly=True)
        self.assertEqual(
            eff.cache_actions(
                self.cache_at(now), now, needed, self.IDS, now, TZ
            ).tables,
            {"5minute", "hour"},
        )

    def test_hour_table_follows_the_hourly_only_statistics_within_a_day(self):
        # The metadata is read at every update (design D4), so whether a service reads hourly can
        # change within a day: the hour table is asked for exactly when the needed windows hold it,
        # without a first-hours refresh or a history read.
        now = local(2026, 11, 17, 12)
        cache = self.cache_at(now)
        for minutes, hourly, expected in (
            (5, True, {"5minute", "hour"}),
            (10, False, {"5minute"}),
            (15, True, {"5minute", "hour"}),
        ):
            later = now + timedelta(minutes=minutes)
            needed = eff.history_windows(later, TZ, hourly=hourly)
            actions = eff.cache_actions(cache, now, needed, self.IDS, later, TZ)
            self.assertEqual(
                actions, eff.CacheActions(frozenset(expected), False), minutes
            )

    def test_local_midnight_decides_not_utc(self):
        # 23:30 UTC on 16 Nov is 00:30 local on 17 Nov in Amsterdam.
        previous = datetime(2026, 11, 16, 22, 30, tzinfo=UTC)  # 23:30 local, 16 Nov
        now = datetime(2026, 11, 16, 23, 30, tzinfo=UTC)
        self.assertIn(
            "day", self.actions(self.cache_at(previous), previous, now).tables
        )

    def test_crossing_utc_midnight_without_local_midnight_reads_no_day(self):
        previous = datetime(2026, 11, 16, 23, 30, tzinfo=UTC)  # 00:30 local, 17 Nov
        now = datetime(2026, 11, 17, 0, 30, tzinfo=UTC)  # 01:30 local, 17 Nov
        a = self.actions(self.cache_at(previous), previous, now)
        self.assertEqual(a.tables, {"5minute"})
        self.assertFalse(a.first_hours)


class HealthTests(unittest.TestCase):
    NOW = local(2026, 11, 17, 12)

    def meta(self, **kw):
        base = {
            "statistic_id": "sensor.x",
            "has_sum": True,
            "unit_class": "energy",
            "statistics_unit_of_measurement": "kWh",
            "source": "recorder",
        }
        base.update(kw)
        return base

    def check(self, metadata, last_end):
        return eff.health(["sensor.x"], metadata, {"sensor.x": last_end}, self.NOW)[
            "sensor.x"
        ]

    def test_ok(self):
        self.assertEqual(
            self.check([self.meta()], self.NOW - timedelta(minutes=10)), "ok"
        )

    def test_missing(self):
        self.assertEqual(self.check([], self.NOW - timedelta(minutes=10)), "missing")

    def test_no_sum(self):
        self.assertEqual(self.check([self.meta(has_sum=False)], self.NOW), "no_sum")

    def test_power_unit_is_not_energy(self):
        meta = self.meta(unit_class="power", statistics_unit_of_measurement="W")
        self.assertEqual(self.check([meta], self.NOW), "not_energy")

    def test_power_without_sum_is_not_energy(self):
        meta = self.meta(
            unit_class="power", statistics_unit_of_measurement="W", has_sum=False
        )
        self.assertEqual(self.check([meta], self.NOW), "not_energy")

    def test_stale_after_three_hours(self):
        self.assertEqual(
            self.check([self.meta()], self.NOW - timedelta(hours=3)), "stale"
        )

    def test_two_hours_after_the_row_ended_is_not_yet_stale(self):
        self.assertEqual(self.check([self.meta()], self.NOW - timedelta(hours=2)), "ok")
        self.assertEqual(
            self.check([self.meta()], self.NOW - timedelta(hours=2, seconds=1)), "stale"
        )

    def test_no_row_read_is_stale(self):
        self.assertEqual(self.check([self.meta()], None), "stale")

    def test_epoch_seconds_accepted(self):
        self.assertEqual(
            self.check([self.meta()], (self.NOW - timedelta(hours=3)).timestamp()),
            "stale",
        )

    def test_recovered(self):
        meta = [self.meta()]
        self.assertEqual(self.check(meta, self.NOW - timedelta(hours=3)), "stale")
        self.assertEqual(self.check(meta, self.NOW - timedelta(minutes=5)), "ok")

    def test_external_statistic_measured_from_its_last_hourly_row(self):
        meta = [self.meta(source="tibber")]
        hour_rows = {
            "sensor.x": [
                row(self.NOW - timedelta(hours=1, minutes=20), 1.0, minutes=60)
            ]
        }
        ts = {
            "hour": eff.TableRead("hour", FAR, hour_rows),
            "5minute": eff.TableRead("5minute", FAR, {}),
        }
        ends = eff.last_row_ends(["sensor.x"], eff.hourly_only(meta), ts)
        self.assertEqual(
            eff.health(["sensor.x"], meta, ends, self.NOW)["sensor.x"], "ok"
        )
        hour_rows["sensor.x"] = [
            row(self.NOW - timedelta(hours=3, minutes=20), 1.0, minutes=60)
        ]
        ends = eff.last_row_ends(
            ["sensor.x"],
            eff.hourly_only(meta),
            ts | {"hour": eff.TableRead("hour", FAR, hour_rows)},
        )
        self.assertEqual(
            eff.health(["sensor.x"], meta, ends, self.NOW)["sensor.x"], "stale"
        )


class CorrectedRatioTests(unittest.TestCase):
    def test_corrected_day(self):
        self.assertEqual(eff.corrected_ratio(36.8, 1.84, 9.2), 3.80)
        self.assertEqual(eff.ratio(36.8, 9.2), 4.00)  # uncorrected

    def test_corrected_month(self):
        self.assertEqual(eff.corrected_ratio(180.0, 5.0, 50.0), 3.50)

    def test_defrost_arriving_converted_from_watt_hours(self):
        # Home Assistant converts 2000 Wh to 2.0 kWh before it reaches the module.
        self.assertEqual(eff.corrected_ratio(10.0, 2000 / 1000, 2.0), 4.00)

    def test_overall_subtracts_both_sections(self):
        self.assertEqual(eff.corrected_ratio(50.0, 2.0 + 0.5, 12.5), 3.80)

    def test_defrost_exceeding_the_output_is_unknown(self):
        self.assertIsNone(eff.corrected_ratio(1.0, 1.2, 0.5))

    def test_corrected_output_of_exactly_zero_is_unknown(self):
        self.assertIsNone(eff.corrected_ratio(1.0, 1.0, 0.5))

    def test_small_corrected_output_is_a_figure(self):
        self.assertEqual(eff.corrected_ratio(1.0, 0.8, 0.5), 0.40)

    def test_too_little_electricity_is_unknown(self):
        self.assertIsNone(eff.corrected_ratio(2.0, 0.1, 0.05))

    def test_exactly_the_electrical_threshold_is_known(self):
        self.assertEqual(eff.corrected_ratio(1.5, 0.5, 0.1), 10.0)

    def test_missing_energy_is_unknown(self):
        self.assertIsNone(eff.corrected_ratio(None, 1.0, 5.0))
        self.assertIsNone(eff.corrected_ratio(5.0, None, 5.0))
        self.assertIsNone(eff.corrected_ratio(5.0, 1.0, None))

    def test_factor_applies_before_rounding(self):
        self.assertEqual(eff.corrected_ratio(2.0, 1.0, 3.0, 3.0), 1.0)

    def test_zero_defrost_equals_the_uncorrected_ratio(self):
        self.assertEqual(eff.corrected_ratio(36.8, 0.0, 9.2), eff.ratio(36.8, 9.2))


class DefrostStartTests(unittest.TestCase):
    NOW = local(2026, 11, 22, 12, 20)

    def test_the_end_of_the_latest_first_hour_not_moved_to_a_day_start(self):
        start = eff.defrost_start(
            [local(2026, 11, 18, 10), local(2026, 11, 2, 8)], self.NOW
        )
        self.assertEqual(start, local(2026, 11, 18, 11))

    def test_epoch_seconds_are_accepted(self):
        start = eff.defrost_start([local(2026, 11, 18, 10).timestamp()], self.NOW)
        self.assertEqual(start, local(2026, 11, 18, 11))

    def test_a_none_hour_counts_as_now_without_an_added_hour(self):
        self.assertEqual(eff.defrost_start([None], self.NOW), self.NOW)
        self.assertEqual(
            eff.defrost_start([local(2026, 11, 18, 10), None], self.NOW), self.NOW
        )
        # The end of a known hour later than now would win; a None hour never gets the extra hour.
        self.assertEqual(
            eff.defrost_start([None, local(2026, 11, 22, 11, 20)], self.NOW),
            local(2026, 11, 22, 12, 20),
        )

    def test_no_hours_is_none(self):
        self.assertIsNone(eff.defrost_start([], self.NOW))

    def test_defrost_partial_compares_the_covered_start(self):
        start = local(2026, 11, 18, 10)
        self.assertTrue(eff.defrost_partial(local(2026, 11, 18), start))
        self.assertFalse(eff.defrost_partial(local(2026, 11, 19), start))
        self.assertFalse(eff.defrost_partial(start, start))

    def test_defrost_partial_is_false_without_a_start(self):
        self.assertFalse(eff.defrost_partial(None, local(2026, 11, 18, 10)))
        self.assertFalse(eff.defrost_partial(local(2026, 11, 18), None))


class DefrostSummaryTests(unittest.TestCase):
    DAY = eff.Range("day", local(2026, 11, 16), local(2026, 11, 17))

    def day(self, **energies):
        """A day table with one row per given statistic (kwarg name = ID)."""
        return tables(
            month={}, day={k: [day_row(2026, 11, 16, v)] for k, v in energies.items()}
        )

    def test_corrected_period_with_its_inputs(self):
        summary = eff.period_summary(
            self.day(o=36.8, d=1.84, e=9.2), [self.DAY], ["o"], ["e"], defrost_ids=["d"]
        )
        self.assertEqual(summary["efficiency"], 3.80)
        self.assertEqual(summary["efficiency_uncorrected"], 4.00)
        self.assertEqual(summary["output_energy"], 36.8)
        self.assertEqual(summary["defrost_energy"], 1.84)
        self.assertEqual(summary["electrical_energy"], 9.2)

    def test_month_of_180_kwh(self):
        summary = eff.period_summary(
            self.day(o=180.0, d=5.0, e=50.0),
            [self.DAY],
            ["o"],
            ["e"],
            defrost_ids=["d"],
        )
        self.assertEqual(summary["efficiency"], 3.50)

    def test_defrost_energy_is_rounded_to_three_decimals(self):
        summary = eff.period_summary(
            self.day(o=36.8, d=1.84049, e=9.2),
            [self.DAY],
            ["o"],
            ["e"],
            defrost_ids=["d"],
        )
        self.assertEqual(summary["defrost_energy"], 1.84)

    def test_period_starting_before_the_defrost_rows_subtracts_only_the_later_rows(
        self,
    ):
        # 16 to 18 November; the defrost statistic has a row only for 18 November (0 kWh before it).
        ts = tables(
            month={},
            day={
                "o": [day_row(2026, 11, d, 10.0) for d in (16, 17, 18)],
                "e": [day_row(2026, 11, d, 2.5) for d in (16, 17, 18)],
                "d": [day_row(2026, 11, 18, 3.0)],
            },
        )
        rng = eff.Range("day", local(2026, 11, 16), local(2026, 11, 19))
        summary = eff.period_summary(ts, [rng], ["o"], ["e"], defrost_ids=["d"])
        self.assertEqual(summary["defrost_energy"], 3.0)
        self.assertEqual(summary["efficiency"], 3.60)  # (30 - 3) / 7.5
        self.assertEqual(summary["efficiency_uncorrected"], 4.00)

    def test_overall_subtracts_both_sections(self):
        ts = self.day(o=50.0, d1=2.0, d2=0.5, e=12.5)
        summary = eff.period_summary(
            ts, [self.DAY], ["o"], ["e"], defrost_ids=["d1", "d2"]
        )
        self.assertEqual(summary["efficiency"], 3.80)
        self.assertEqual(summary["defrost_energy"], 2.5)

    def test_defrost_exceeding_the_output_keeps_the_defrost_energy(self):
        summary = eff.period_summary(
            self.day(o=1.0, d=1.2, e=0.5), [self.DAY], ["o"], ["e"], defrost_ids=["d"]
        )
        self.assertIsNone(summary["efficiency"])
        self.assertEqual(summary["defrost_energy"], 1.2)
        self.assertEqual(summary["efficiency_uncorrected"], 2.0)
        self.assertEqual(summary["output_energy"], 1.0)
        self.assertEqual(summary["electrical_energy"], 0.5)

    def test_small_corrected_output(self):
        summary = eff.period_summary(
            self.day(o=1.0, d=0.8, e=0.5), [self.DAY], ["o"], ["e"], defrost_ids=["d"]
        )
        self.assertEqual(summary["efficiency"], 0.40)

    def test_too_little_electricity_keeps_the_energies(self):
        summary = eff.period_summary(
            self.day(o=2.0, d=0.1, e=0.05), [self.DAY], ["o"], ["e"], defrost_ids=["d"]
        )
        self.assertIsNone(summary["efficiency"])
        self.assertIsNone(summary["efficiency_uncorrected"])
        self.assertEqual(summary["defrost_energy"], 0.1)
        self.assertEqual(summary["electrical_energy"], 0.05)

    def test_defrost_statistic_without_data_is_unknown_not_uncorrected(self):
        ts = tables(
            month={},
            day={"o": [day_row(2026, 11, 16, 36.8)], "e": [day_row(2026, 11, 16, 9.2)]},
            covered={"o", "e", "d"},
        )
        summary = eff.period_summary(ts, [self.DAY], ["o"], ["e"], defrost_ids=["d"])
        self.assertIsNone(summary["efficiency"])
        self.assertIsNone(summary["defrost_energy"])
        self.assertEqual(summary["efficiency_uncorrected"], 4.00)

    def test_defrost_not_covered_by_the_read_is_unknown(self):
        ts = tables(
            month={},
            day={
                "o": [day_row(2026, 11, 16, 36.8)],
                "e": [day_row(2026, 11, 16, 9.2)],
                "d": [day_row(2026, 11, 16, 1.0)],
            },
            covered={"o", "e"},
        )
        summary = eff.period_summary(ts, [self.DAY], ["o"], ["e"], defrost_ids=["d"])
        self.assertIsNone(summary["efficiency"])
        self.assertIsNone(summary["defrost_energy"])

    def test_period_that_has_not_begun(self):
        summary = eff.period_summary({}, None, ["o"], ["e"], defrost_ids=["d"])
        self.assertEqual(
            summary,
            {
                "output_energy": None,
                "electrical_energy": None,
                "efficiency": None,
                "defrost_energy": None,
                "efficiency_uncorrected": None,
            },
        )

    def test_no_defrost_keys_without_defrost_ids(self):
        ts = self.day(o=36.8, e=9.2)
        for kwargs in ({}, {"defrost_ids": []}, {"defrost_ids": ()}):
            summary = eff.period_summary(ts, [self.DAY], ["o"], ["e"], **kwargs)
            self.assertEqual(
                set(summary), {"output_energy", "electrical_energy", "efficiency"}
            )
            self.assertEqual(summary["efficiency"], 4.00)
        self.assertEqual(
            set(eff.period_summary(ts, None, ["o"], ["e"])),
            {"output_energy", "electrical_energy", "efficiency"},
        )


class DefrostSeriesTests(unittest.TestCase):
    DEFROST_START = local(2026, 11, 18, 10)

    def test_daily_points_are_corrected_and_marked(self):
        now = local(2026, 11, 20, 12)
        # The defrost statistic starts on 18 November 10:00: it has no row for 17 November (0 kWh there).
        days = {"o": [], "e": [], "d": []}
        for d in (17, 18, 19):
            days["o"].append(day_row(2026, 11, d, 36.8))
            days["e"].append(day_row(2026, 11, d, 9.2))
            if d >= 18:
                days["d"].append(day_row(2026, 11, d, 1.84))
        ts = tables(month={}, day=days, five={})
        series = eff.daily_series(
            ts,
            ["o"],
            ["e"],
            now,
            TZ,
            defrost_ids=["d"],
            defrost_start=self.DEFROST_START,
        )
        marks = {p["start"]: p["defrost_partial"] for p in series}
        self.assertEqual(
            marks,
            {
                local(2026, 11, 17).isoformat(): True,
                local(2026, 11, 18).isoformat(): True,
                local(2026, 11, 19).isoformat(): False,
            },
        )
        self.assertEqual(
            {p["start"]: p["efficiency"] for p in series},
            {
                local(
                    2026, 11, 17
                ).isoformat(): 4.00,  # before the first row: uncorrected
                local(2026, 11, 18).isoformat(): 3.80,
                local(2026, 11, 19).isoformat(): 3.80,
            },
        )
        self.assertEqual(
            set(series[0]), {"start", "efficiency", "estimated", "defrost_partial"}
        )

    def test_no_daily_point_when_the_corrected_figure_is_unknown(self):
        now = local(2026, 11, 17, 12)
        days = {
            "o": [day_row(2026, 11, 15, 1.0), day_row(2026, 11, 16, 1.0)],
            "e": [day_row(2026, 11, 15, 0.5), day_row(2026, 11, 16, 0.5)],
            "d": [day_row(2026, 11, 15, 1.2), day_row(2026, 11, 16, 0.8)],
        }
        ts = tables(month={}, day=days, five={})
        series = eff.daily_series(
            ts,
            ["o"],
            ["e"],
            now,
            TZ,
            defrost_ids=["d"],
            defrost_start=self.DEFROST_START,
        )
        self.assertEqual(
            [(p["start"], p["efficiency"]) for p in series],
            [(local(2026, 11, 16).isoformat(), 0.40)],
        )

    def test_no_daily_point_when_the_defrost_statistic_has_no_data(self):
        now = local(2026, 11, 17, 12)
        ts = tables(
            month={},
            day={"o": [day_row(2026, 11, 16, 36.8)], "e": [day_row(2026, 11, 16, 9.2)]},
            five={},
            covered={"o", "e", "d"},
        )
        self.assertEqual(
            eff.daily_series(ts, ["o"], ["e"], now, TZ)[0]["efficiency"], 4.00
        )
        self.assertEqual(
            eff.daily_series(ts, ["o"], ["e"], now, TZ, defrost_ids=["d"]), []
        )

    def test_monthly_points_before_the_defrost_start_are_partial(self):
        now = local(2026, 12, 5, 12)
        ids = ("o", "e", "d")
        # The defrost statistic has no row before 18 November 2026: no October month row (0 kWh there).
        months = {
            "o": [month_row(2026, 10, 100.0), month_row(2026, 11, 100.0)],
            "e": [month_row(2026, 10, 25.0), month_row(2026, 11, 25.0)],
            "d": [month_row(2026, 11, 5.0)],
        }
        days = {
            i: [day_row(2026, 12, d, v) for d in range(1, 5)]
            for i, v in zip(ids, (10.0, 2.5, 0.0), strict=True)
        }
        ts = tables(month=months, day=days, five={})
        series = eff.monthly_series(
            ts,
            ["o"],
            ["e"],
            now,
            TZ,
            defrost_ids=["d"],
            defrost_start=self.DEFROST_START,
        )
        marks = {p["start"]: p["defrost_partial"] for p in series}
        self.assertEqual(
            marks,
            {
                local(2026, 10, 1).isoformat(): True,
                local(2026, 11, 1).isoformat(): True,
                local(2026, 12, 1).isoformat(): False,
            },
        )
        self.assertEqual(
            [p["efficiency"] for p in series], [4.00, 3.80, 4.00]
        )  # October: uncorrected

    def test_monthly_partial_uses_the_covered_start(self):
        # An effective start inside the defrost counter's history: the covered start is 19 November.
        now = local(2026, 11, 22, 12)
        days = {
            i: [day_row(2026, 11, d, v) for d in range(19, 22)]
            for i, v in (("o", 8.0), ("e", 2.0), ("d", 0.2))
        }
        ts = tables(month={}, day=days, five={})
        series = eff.monthly_series(
            ts,
            ["o"],
            ["e"],
            now,
            TZ,
            effective=local(2026, 11, 19),
            defrost_ids=["d"],
            defrost_start=self.DEFROST_START,
        )
        self.assertEqual([p["defrost_partial"] for p in series], [False])

    def test_without_defrost_ids_the_points_are_unchanged(self):
        now = local(2026, 11, 17, 12)
        ts = tables(
            month={},
            day={"o": [day_row(2026, 11, 16, 36.8)], "e": [day_row(2026, 11, 16, 9.2)]},
            five={},
        )
        for series in (
            eff.daily_series(ts, ["o"], ["e"], now, TZ),
            eff.daily_series(
                ts,
                ["o"],
                ["e"],
                now,
                TZ,
                defrost_ids=(),
                defrost_start=self.DEFROST_START,
            ),
            eff.monthly_series(
                ts, ["o"], ["e"], now, TZ, defrost_start=self.DEFROST_START
            ),
        ):
            self.assertTrue(series)
            for point in series:
                self.assertEqual(set(point), {"start", "efficiency", "estimated"})

    def test_an_unknown_defrost_start_marks_nothing(self):
        now = local(2026, 11, 17, 12)
        ts = tables(
            month={},
            day={
                i: [day_row(2026, 11, 16, v)]
                for i, v in (("o", 36.8), ("e", 9.2), ("d", 1.84))
            },
            five={},
        )
        (point,) = eff.daily_series(ts, ["o"], ["e"], now, TZ, defrost_ids=["d"])
        self.assertFalse(point["defrost_partial"])


class DefrostBaselineTests(unittest.TestCase):
    """A defrost statistic counts from the end of its first hour (design D12).

    Home Assistant computes the change of a statistic's first row in a table against a
    previous sum of 0, so the row holding the first hour carries the first sum (here an
    external counter that starts at 500.0 kWh).
    """

    FIRST = local(2026, 11, 18, 10)
    FIRSTS = {"d": (FIRST, 500.0)}

    def test_scenario_sum_that_does_not_start_at_zero(self):
        # The day row of 18 November holds the first hour: 502.0 kWh (the sum at the end of the
        # day against 0); the baseline 500.0 leaves the 2.0 kWh of that day after the first hour.
        ts = tables(
            month={},
            day={
                "o": [day_row(2026, 11, 18, 36.8)],
                "e": [day_row(2026, 11, 18, 9.2)],
                "d": [day_row(2026, 11, 18, 502.0)],
            },
        )
        rng = eff.Range("day", local(2026, 11, 18), local(2026, 11, 19))
        summary = eff.period_summary(
            ts, [rng], ["o"], ["e"], defrost_ids=["d"], defrost_firsts=self.FIRSTS
        )
        self.assertEqual(summary["defrost_energy"], 2.0)
        self.assertEqual(summary["efficiency"], 3.78)
        self.assertEqual(summary["efficiency_uncorrected"], 4.0)
        # Without the baseline the whole first sum would be subtracted: unknown, never 3.78.
        plain = eff.period_summary(ts, [rng], ["o"], ["e"], defrost_ids=["d"])
        self.assertEqual(plain["defrost_energy"], 502.0)
        self.assertIsNone(plain["efficiency"])

    def test_month_to_date_and_year_to_date_subtract_2_kwh(self):
        now = local(2026, 11, 22, 12)
        days = {"o": [], "e": [], "d": []}
        for day in range(1, 22):
            days["o"].append(day_row(2026, 11, day, 10.0))
            days["e"].append(day_row(2026, 11, day, 2.5))
        days["d"] = [day_row(2026, 11, 18, 502.0)] + [
            day_row(2026, 11, d, 0.0) for d in (19, 20, 21)
        ]
        months = {
            "o": [month_row(2026, m, 300.0) for m in range(1, 11)],
            "e": [month_row(2026, m, 75.0) for m in range(1, 11)],
        }
        ts = tables(
            month=months,
            day=days,
            five={"o": [], "e": [], "d": [row(local(2026, 11, 22, 1), 0.0)]},
        )
        ranges = eff.period_ranges(now, TZ)
        for period in ("month_to_date", "year_to_date"):
            self.assertEqual(
                eff.period_energy(ts, ["d"], ranges[period], self.FIRSTS), 2.0, period
            )
            self.assertEqual(
                eff.period_energy(ts, ["d"], ranges[period]), 502.0, period
            )

    def test_the_first_hour_row_of_the_hour_table_adds_0(self):
        # An hourly service: the first hour row carries the first sum (500.0), the next one its change.
        ts = tables(
            hour={
                "d": [
                    row(self.FIRST, 500.0, 60),
                    row(self.FIRST + timedelta(hours=1), 0.4, 60),
                ]
            }
        )
        rng = eff.Range("hour", local(2026, 11, 18), local(2026, 11, 18, 13))
        self.assertEqual(eff.period_energy(ts, ["d"], [rng], self.FIRSTS), 0.4)
        # A range that starts after the first hour has its own change as it is.
        later = eff.Range("hour", local(2026, 11, 18, 11), local(2026, 11, 18, 13))
        self.assertEqual(eff.period_energy(ts, ["d"], [later], self.FIRSTS), 0.4)

    def test_a_5_minute_row_inside_the_first_hour_counts_0(self):
        five = [
            row(self.FIRST, 0.1),
            row(self.FIRST + timedelta(minutes=55), 0.1),
            row(self.FIRST + timedelta(minutes=60), 0.2),
            row(self.FIRST + timedelta(minutes=65), 0.3),
        ]
        ts = tables(five={"d": five})
        rng = eff.Range("5minute", local(2026, 11, 18), local(2026, 11, 18, 12))
        self.assertAlmostEqual(eff.period_energy(ts, ["d"], [rng], self.FIRSTS), 0.5)
        self.assertAlmostEqual(eff.period_energy(ts, ["d"], [rng]), 0.7)

    def test_only_the_defrost_statistics_given_are_reduced(self):
        ts = tables(
            day={
                "o": [day_row(2026, 11, 18, 36.8)],
                "d": [day_row(2026, 11, 18, 502.0)],
            },
            month={},
        )
        rng = eff.Range("day", local(2026, 11, 18), local(2026, 11, 19))
        self.assertEqual(eff.period_energy(ts, ["o"], [rng], self.FIRSTS), 36.8)
        self.assertEqual(eff.period_energy(ts, ["o", "d"], [rng], self.FIRSTS), 38.8)

    def test_a_range_that_does_not_contain_the_first_hour_is_unchanged(self):
        ts = tables(day={"d": [day_row(2026, 11, 19, 1.5)]}, month={})
        rng = eff.Range("day", local(2026, 11, 19), local(2026, 11, 20))
        self.assertEqual(eff.period_energy(ts, ["d"], [rng], self.FIRSTS), 1.5)

    def test_the_month_row_holding_the_first_hour_is_reduced(self):
        ts = tables(month={"d": [month_row(2026, 11, 505.0)]}, day={})
        rng = eff.Range("month", local(2026, 11, 1), local(2026, 12, 1))
        self.assertEqual(eff.period_energy(ts, ["d"], [rng], self.FIRSTS), 5.0)

    def test_a_row_without_a_change_stays_unknown(self):
        ts = tables(day={"d": [day_row(2026, 11, 18, None)]}, month={})
        rng = eff.Range("day", local(2026, 11, 18), local(2026, 11, 19))
        self.assertIsNone(eff.period_energy(ts, ["d"], [rng], self.FIRSTS))

    def test_the_daily_point_of_the_first_day_is_corrected_from_the_baseline(self):
        now = local(2026, 11, 20, 12)
        days = {
            "o": [],
            "e": [],
            "d": [day_row(2026, 11, 18, 502.0), day_row(2026, 11, 19, 1.84)],
        }
        for d in (18, 19):
            days["o"].append(day_row(2026, 11, d, 36.8))
            days["e"].append(day_row(2026, 11, d, 9.2))
        ts = tables(month={}, day=days, five={})
        start = eff.defrost_start([self.FIRST], now)
        series = eff.daily_series(
            ts,
            ["o"],
            ["e"],
            now,
            TZ,
            defrost_ids=["d"],
            defrost_start=start,
            defrost_firsts=self.FIRSTS,
        )
        self.assertEqual(
            [(p["efficiency"], p["defrost_partial"]) for p in series],
            [(3.78, True), (3.80, False)],
        )
        monthly = eff.monthly_series(
            ts,
            ["o"],
            ["e"],
            now,
            TZ,
            defrost_ids=["d"],
            defrost_start=start,
            defrost_firsts=self.FIRSTS,
        )
        self.assertEqual(
            [p["efficiency"] for p in monthly], [3.79]
        )  # (73.6 - 3.84) / 18.4 with 2.0 + 1.84

    def test_without_defrost_ids_the_firsts_change_nothing(self):
        ts = tables(
            month={},
            day={"o": [day_row(2026, 11, 18, 36.8)], "e": [day_row(2026, 11, 18, 9.2)]},
            five={},
        )
        now = local(2026, 11, 19, 12)
        plain = eff.daily_series(ts, ["o"], ["e"], now, TZ)
        self.assertEqual(
            eff.daily_series(ts, ["o"], ["e"], now, TZ, defrost_firsts=self.FIRSTS),
            plain,
        )
        rng = eff.Range("day", local(2026, 11, 18), local(2026, 11, 19))
        self.assertEqual(
            eff.period_summary(ts, [rng], ["o"], ["e"], defrost_firsts=self.FIRSTS),
            eff.period_summary(ts, [rng], ["o"], ["e"]),
        )


class ImportTests(unittest.TestCase):
    def test_only_standard_library_is_imported(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "no relative imports")
                modules.add(node.module.split(".")[0])
        self.assertTrue(modules)
        self.assertNotIn("homeassistant", modules)
        self.assertLessEqual(modules, set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
