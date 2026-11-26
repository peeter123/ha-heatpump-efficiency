"""Tests for the pure season arithmetic (standard library only).

The package is registered as a bare module with the package path, so
``seasons.py`` can import its pure sibling ``efficiency.py`` without Home
Assistant. Time zone tests use zoneinfo (tzdata comes from the lint environment, scripts/lint.py).
"""

import ast
from datetime import UTC, date, datetime, timedelta
import importlib
from itertools import pairwise
from pathlib import Path
import random
import sys
import types
import unittest
from zoneinfo import ZoneInfo

PACKAGE = (
    Path(__file__).resolve().parents[1] / "custom_components" / "heatpump_efficiency"
)
_pkg = types.ModuleType("hpe_seasons_pkg")
_pkg.__path__ = [str(PACKAGE)]
sys.modules["hpe_seasons_pkg"] = _pkg
eff = importlib.import_module("hpe_seasons_pkg.efficiency")
seasons = importlib.import_module("hpe_seasons_pkg.seasons")

TZ = ZoneInfo("Europe/Amsterdam")
KOLKATA = ZoneInfo("Asia/Kolkata")
SANTIAGO = ZoneInfo("America/Santiago")

NORTH = seasons.default_seasons(52.0)
HEAT = (NORTH["heating_start"], NORTH["heating_end"])
COOL = (NORTH["cooling_start"], NORTH["cooling_end"])


def local(y, m, d, hh=0, mm=0, tz=TZ):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def effective_of(first_hour, tz=TZ):
    return eff.effective_start([first_hour], tz)


def since(md, first_hour, now, tz=TZ):
    return seasons.seasons_since(md[0], md[1], effective_of(first_hour, tz), now, tz)


def hourly_rows(first, hours, seed=1):
    """Hourly rows with a running ``sum``: [{'start', 'sum'}], increments from a seeded generator."""
    rng = random.Random(seed)
    total = 100.0
    rows = []
    for i in range(hours):
        start = first + timedelta(hours=i)
        total += round(rng.uniform(0.0, 3.0), 3)
        rows.append({"start": start.timestamp(), "sum": total})
    return rows


def reduce_rows(rows, tz, key):
    """Day or month rows from hourly rows as Home Assistant reduces them.

    ``key`` maps a local date to its group. Per group: ``start`` is local
    midnight of the group's first day, ``change`` the last ``sum`` in the group
    minus the last ``sum`` before it (0 when there is none).
    """
    groups: dict = {}
    for r in rows:
        day = datetime.fromtimestamp(r["start"], tz).date()
        groups.setdefault(key(day), []).append(r)
    out = []
    previous = 0.0
    for group_key in sorted(groups):
        group = sorted(groups[group_key], key=lambda r: r["start"])
        first_day = datetime.fromtimestamp(group[0]["start"], tz).date()
        first_day = key_start(group_key, first_day)
        out.append(
            {
                "start": datetime(
                    first_day.year, first_day.month, first_day.day, tzinfo=tz
                ).timestamp(),
                "change": group[-1]["sum"] - previous,
            }
        )
        previous = group[-1]["sum"]
    return out


def key_start(group_key, first_day):
    """The first day of a group: the day itself, or the 1st for a (year, month) key."""
    return (
        first_day
        if isinstance(group_key, date)
        else date(group_key[0], group_key[1], 1)
    )


class DefaultsTests(unittest.TestCase):
    def test_northern(self):
        self.assertEqual(
            seasons.default_seasons(52.0),
            {
                "heating_start": "10-01",
                "heating_end": "04-30",
                "cooling_start": "06-01",
                "cooling_end": "09-30",
            },
        )

    def test_unset_latitude_is_northern(self):
        self.assertEqual(seasons.default_seasons(0.0), seasons.default_seasons(52.0))

    def test_southern(self):
        self.assertEqual(
            seasons.default_seasons(-33.9),
            {
                "heating_start": "04-01",
                "heating_end": "10-31",
                "cooling_start": "12-01",
                "cooling_end": "02-28",
            },
        )


class SeasonRangeTests(unittest.TestCase):
    def test_heating_crosses_the_new_year(self):
        s = seasons.Season.starting("10-01", "04-30", 2026)
        self.assertEqual(s.start_day, date(2026, 10, 1))
        self.assertEqual(s.end_day, date(2027, 4, 30))
        self.assertEqual(s.start(TZ), local(2026, 10, 1))
        self.assertEqual(s.end(TZ), local(2027, 5, 1))

    def test_season_within_one_year(self):
        s = seasons.Season.starting("06-01", "09-30", 2026)
        self.assertEqual(s.start(TZ), local(2026, 6, 1))
        self.assertEqual(s.end(TZ), local(2026, 10, 1))

    def test_end_of_february_includes_the_leap_day(self):
        s = seasons.Season.starting("12-01", "02-28", 2027)
        self.assertEqual(s.end_day, date(2028, 2, 29))
        self.assertEqual(s.end(TZ), local(2028, 3, 1))
        other = seasons.Season.starting("12-01", "02-28", 2026)
        self.assertEqual(other.end_day, date(2027, 2, 28))
        self.assertEqual(other.end(TZ), local(2027, 3, 1))

    def test_half_hour_zone_boundaries(self):
        s = seasons.Season.starting("10-01", "04-30", 2026)
        self.assertEqual(s.start(KOLKATA), local(2026, 10, 1, 0, 30, KOLKATA))
        self.assertEqual(s.end(KOLKATA), local(2027, 5, 1, 0, 30, KOLKATA))
        # the boundary is a whole UTC hour
        self.assertEqual(s.start(KOLKATA).timestamp() % 3600, 0)

    def test_dst_days_as_boundaries(self):
        # the clocks go back on 25 October 2026 (25 h day) and forward on 29 March 2026 (23 h day)
        back = seasons.Season.starting("10-25", "04-30", 2026)
        self.assertEqual(back.start(TZ), local(2026, 10, 25))
        self.assertEqual(back.start(TZ), datetime(2026, 10, 24, 22, tzinfo=UTC))
        ends_on_change = seasons.Season.starting("10-01", "10-24", 2026)
        self.assertEqual(ends_on_change.end(TZ), datetime(2026, 10, 24, 22, tzinfo=UTC))
        spring = seasons.Season.starting("03-29", "09-30", 2026)
        self.assertEqual(spring.start(TZ), datetime(2026, 3, 28, 23, tzinfo=UTC))
        prev_end = seasons.Season.starting("10-01", "03-28", 2025)
        self.assertEqual(prev_end.end(TZ), spring.start(TZ))
        self.assertEqual(spring.start(TZ).astimezone(TZ).hour, 0)


class NonexistentMidnightTests(unittest.TestCase):
    def test_season_starts_at_the_first_existing_instant(self):
        # 6 September 2026 has no 00:00 in America/Santiago: the clocks jump to 01:00
        s = seasons.Season.starting("09-06", "04-30", 2026)
        start = s.start(SANTIAGO)
        self.assertEqual(start, eff.day_start(date(2026, 9, 6), SANTIAGO))
        self.assertEqual(start.astimezone(SANTIAGO).hour, 1)
        self.assertEqual(start.astimezone(SANTIAGO).date(), date(2026, 9, 6))
        previous = seasons.Season.starting("04-01", "09-05", 2026)
        self.assertEqual(previous.end(SANTIAGO), start)


class SeasonsSinceTests(unittest.TestCase):
    def test_running_season_is_complete_and_not_ended(self):
        infos = since(HEAT, local(2026, 1, 5, 12), local(2027, 1, 15, 12))
        last = infos[-1]
        self.assertEqual(last.season.start_day, date(2026, 10, 1))
        self.assertTrue(last.complete)
        self.assertFalse(last.ended)
        self.assertEqual(last.covered_start, local(2026, 10, 1))
        self.assertEqual(last.natural_end, local(2027, 5, 1))

    def test_between_seasons_the_last_season_has_ended(self):
        infos = since(HEAT, local(2026, 1, 5, 12), local(2027, 7, 15, 12))
        last = infos[-1]
        self.assertEqual(last.season.start_day, date(2026, 10, 1))
        self.assertEqual(last.season.end_day, date(2027, 4, 30))
        self.assertTrue(last.ended)
        self.assertTrue(last.complete)

    def test_cut_first_season_is_not_complete(self):
        first_hour = local(2026, 11, 13, 14)
        infos = since(HEAT, first_hour, local(2027, 1, 15, 12))
        self.assertEqual(len(infos), 1)
        info = infos[0]
        self.assertEqual(info.covered_start, local(2026, 11, 14))
        self.assertEqual(info.natural_start, local(2026, 10, 1))
        self.assertFalse(info.complete)

    def test_no_season_has_begun(self):
        self.assertEqual(
            since(COOL, local(2026, 11, 13, 14), local(2027, 3, 15, 12)), []
        )
        self.assertEqual(
            seasons.seasons_since("06-01", "09-30", None, local(2027, 3, 15), TZ), []
        )
        # the season starts the day after "now": not begun
        self.assertEqual(
            since(COOL, local(2026, 11, 13, 14), local(2027, 5, 31, 23, 59)), []
        )
        begun = since(COOL, local(2026, 11, 13, 14), local(2027, 6, 1, 0, 1))
        self.assertEqual(len(begun), 1)
        self.assertFalse(begun[0].ended)

    def test_effective_start_between_seasons_takes_the_next_season(self):
        infos = since(HEAT, local(2026, 6, 1, 12), local(2027, 1, 15))
        self.assertEqual([i.season.start_day for i in infos], [date(2026, 10, 1)])
        self.assertTrue(infos[0].complete)

    def test_effective_start_inside_a_crossing_season(self):
        infos = since(HEAT, local(2027, 2, 10, 12), local(2027, 7, 15))
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].season.start_day, date(2026, 10, 1))
        self.assertEqual(infos[0].covered_start, local(2027, 2, 11))
        self.assertFalse(infos[0].complete)
        self.assertTrue(infos[0].ended)

    def test_several_years_of_history(self):
        infos = since(HEAT, local(2023, 9, 1), local(2027, 1, 15))
        self.assertEqual(
            [i.season.start_day for i in infos],
            [
                date(2023, 10, 1),
                date(2024, 10, 1),
                date(2025, 10, 1),
                date(2026, 10, 1),
            ],
        )
        self.assertEqual([i.ended for i in infos], [True, True, True, False])
        self.assertTrue(all(i.complete for i in infos))

    def test_history_starting_inside_a_season_keeps_that_season(self):
        infos = since(HEAT, local(2024, 1, 10, 3), local(2025, 1, 15))
        self.assertEqual(
            [i.season.start_day for i in infos], [date(2023, 10, 1), date(2024, 10, 1)]
        )
        self.assertFalse(infos[0].complete)
        self.assertEqual(infos[0].covered_start, local(2024, 1, 11))

    def test_end_day_today_is_not_ended_and_next_day_is(self):
        first = local(2025, 1, 1)
        on_last_day = since(HEAT, first, local(2027, 4, 30, 12))
        self.assertFalse(on_last_day[-1].ended)
        after = since(HEAT, first, local(2027, 5, 1, 0, 30))
        self.assertTrue(after[-1].ended)

    def test_half_hour_zone(self):
        first = local(2026, 9, 1, 12, tz=KOLKATA)
        # 00:20 on 1 May is still the previous statistics day, so the season has not ended
        before = since(HEAT, first, local(2027, 5, 1, 0, 20, KOLKATA), KOLKATA)
        self.assertFalse(before[-1].ended)
        after = since(HEAT, first, local(2027, 5, 1, 0, 30, KOLKATA), KOLKATA)
        self.assertTrue(after[-1].ended)
        self.assertEqual(after[-1].natural_end, local(2027, 5, 1, 0, 30, KOLKATA))

    def test_southern_cooling_across_a_leap_february(self):
        south = seasons.default_seasons(-33.9)
        infos = seasons.seasons_since(
            south["cooling_start"],
            south["cooling_end"],
            effective_of(local(2027, 11, 1)),
            local(2028, 3, 15),
            TZ,
        )
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].season.end_day, date(2028, 2, 29))
        self.assertTrue(infos[0].ended)

    def test_naive_datetimes_are_rejected(self):
        with self.assertRaises(ValueError):
            seasons.seasons_since(
                "10-01", "04-30", local(2026, 1, 1), datetime(2027, 1, 1), TZ
            )
        with self.assertRaises(ValueError):
            seasons.seasons_since(
                "10-01", "04-30", datetime(2026, 1, 1), local(2027, 1, 1), TZ
            )


class RunningRangesTests(unittest.TestCase):
    def test_ranges_telescope_from_the_covered_start_to_now(self):
        now = local(2027, 1, 15, 12)
        info = since(HEAT, local(2026, 1, 5, 12), now)[-1]
        ranges = seasons.running_ranges(info, now, TZ)
        self.assertEqual(ranges[0].start, local(2026, 10, 1))
        self.assertEqual(ranges[-1].end, now)
        self.assertEqual(ranges[-1].source, "5minute")
        for a, b in pairwise(ranges):
            self.assertEqual(a.end, b.start)
        self.assertIn("month", [r.source for r in ranges])

    def test_cut_running_season_reads_days_then_months(self):
        now = local(2027, 1, 15, 12)
        info = since(HEAT, local(2026, 11, 13, 14), now)[0]
        self.assertEqual(info.covered_start, local(2026, 11, 14))
        ranges = seasons.running_ranges(info, now, TZ)
        self.assertEqual([r.source for r in ranges], ["day", "month", "day", "5minute"])
        self.assertEqual(ranges[0].start, local(2026, 11, 14))
        self.assertEqual(ranges[0].end, local(2026, 12, 1))
        self.assertEqual(ranges[1].end, local(2027, 1, 1))

    def test_equals_period_ranges_for_a_year_start(self):
        now = local(2027, 3, 10, 9)
        effective = local(2026, 12, 3, 14)
        info = seasons.SeasonInfo(
            seasons.Season(date(2027, 1, 1), date(2027, 6, 30)),
            local(2027, 1, 1),
            local(2027, 7, 1),
            local(2027, 1, 1),
            True,
            False,
        )
        self.assertEqual(
            seasons.running_ranges(info, now, TZ),
            eff.period_ranges(now, TZ, effective)["year_to_date"],
        )

    def test_hourly_and_coverage_end(self):
        now = local(2027, 1, 15, 12)
        info = since(HEAT, local(2026, 1, 5, 12), now)[-1]
        end = local(2027, 1, 15, 9)
        ranges = seasons.running_ranges(info, now, TZ, end, hourly=True)
        self.assertEqual(ranges[-1].source, "hour")
        self.assertEqual(ranges[-1].end, end)
        # coverage end before today's start: unknown
        self.assertIsNone(
            seasons.running_ranges(info, now, TZ, local(2027, 1, 14, 20), hourly=False)
        )

    def test_ended_season_has_no_running_ranges(self):
        now = local(2027, 7, 15, 12)
        info = since(HEAT, local(2026, 1, 5, 12), now)[-1]
        self.assertIsNone(seasons.running_ranges(info, now, TZ))


class BoundaryReadingTests(unittest.TestCase):
    B = local(2026, 10, 1)

    def rows(self):
        return [
            {"start": (self.B - timedelta(hours=3)).timestamp(), "sum": 10.0},
            {"start": (self.B - timedelta(hours=1)).timestamp(), "sum": 12.5},
            {"start": (self.B - timedelta(hours=2)).timestamp(), "sum": 11.0},
        ]

    def test_newest_row_before_the_boundary(self):
        last_end = (self.B + timedelta(hours=5)).timestamp()
        first = (self.B - timedelta(days=100)).timestamp()
        self.assertEqual(
            seasons.boundary_reading(self.rows(), first, last_end, self.B), 12.5
        )

    def test_row_starting_at_the_boundary_is_not_before_it(self):
        rows = [*self.rows(), {"start": self.B.timestamp(), "sum": 99.0}]
        last_end = (self.B + timedelta(hours=5)).timestamp()
        self.assertEqual(
            seasons.boundary_reading(
                rows, self.B - timedelta(days=9), last_end, self.B
            ),
            12.5,
        )

    def test_zero_when_the_first_hour_is_at_or_after_the_boundary(self):
        last_end = (self.B + timedelta(hours=5)).timestamp()
        self.assertEqual(seasons.boundary_reading([], self.B, last_end, self.B), 0.0)
        self.assertEqual(
            seasons.boundary_reading(
                None, self.B + timedelta(days=3), last_end, self.B
            ),
            0.0,
        )

    def test_baseline_when_the_first_hour_is_at_or_after_the_boundary(self):
        last_end = (self.B + timedelta(hours=5)).timestamp()
        self.assertEqual(
            seasons.boundary_reading([], self.B, last_end, self.B, 500.0), 500.0
        )
        self.assertEqual(
            seasons.boundary_reading(
                None, self.B + timedelta(days=3), last_end, self.B, 500.0
            ),
            500.0,
        )
        self.assertEqual(
            seasons.boundary_reading(
                None, self.B + timedelta(days=3), last_end, self.B, None
            ),
            0.0,
        )

    def test_baseline_is_ignored_when_the_first_hour_is_before_the_boundary(self):
        last_end = (self.B + timedelta(hours=5)).timestamp()
        first = (self.B - timedelta(days=100)).timestamp()
        self.assertEqual(
            seasons.boundary_reading(self.rows(), first, last_end, self.B, 500.0), 12.5
        )
        # Not covered stays unknown whatever the baseline.
        self.assertIsNone(
            seasons.boundary_reading(self.rows(), first, None, self.B, 500.0)
        )

    def test_none_when_not_covered(self):
        first = self.B - timedelta(days=100)
        before = (self.B - timedelta(minutes=5)).timestamp()
        self.assertIsNone(seasons.boundary_reading(self.rows(), first, before, self.B))
        self.assertIsNone(seasons.boundary_reading(self.rows(), first, None, self.B))
        at = self.B.timestamp()
        self.assertEqual(seasons.boundary_reading(self.rows(), first, at, self.B), 12.5)

    def test_none_without_a_row_before_when_the_first_hour_is_before(self):
        last_end = (self.B + timedelta(hours=5)).timestamp()
        first = self.B - timedelta(days=100)
        self.assertIsNone(seasons.boundary_reading([], first, last_end, self.B))
        self.assertIsNone(seasons.boundary_reading(None, first, last_end, self.B))
        after_only = [{"start": (self.B + timedelta(hours=1)).timestamp(), "sum": 5.0}]
        self.assertIsNone(seasons.boundary_reading(after_only, first, last_end, self.B))

    def test_naive_boundary_is_rejected(self):
        with self.assertRaises(ValueError):
            seasons.boundary_reading([], None, 1.0, datetime(2026, 10, 1))


class SeasonEnergyTests(unittest.TestCase):
    def test_sum_of_differences(self):
        start = {"a": 10.0, "b": 5.0}
        end = {"a": 14.0, "b": 8.5}
        self.assertAlmostEqual(seasons.season_energy(start, end, ["a", "b"]), 7.5)

    def test_none_when_a_reading_is_missing(self):
        self.assertIsNone(
            seasons.season_energy(
                {"a": 1.0, "b": None}, {"a": 2.0, "b": 3.0}, ["a", "b"]
            )
        )
        self.assertIsNone(seasons.season_energy({"a": 1.0}, {"a": 2.0}, ["a", "b"]))
        self.assertIsNone(seasons.season_energy({}, {}, []))

    def test_finished_season_equals_the_day_by_day_sum(self):
        first = local(2026, 9, 15)
        rows = hourly_rows(first, 24 * 260)
        # day by day: hourly change = sum - previous sum (0 baseline for the first row), grouped by statistics day
        changes_by_day: dict[date, float] = {}
        previous = 0.0
        for r in rows:
            day = eff.statistics_day(r["start"], TZ)
            changes_by_day[day] = changes_by_day.get(day, 0.0) + (r["sum"] - previous)
            previous = r["sum"]
        info = since(HEAT, first, local(2027, 6, 20))[-1]
        self.assertTrue(info.ended)
        day = info.season.start_day
        expected = 0.0
        while day <= info.season.end_day:
            expected += changes_by_day.get(day, 0.0)
            day += timedelta(days=1)
        last_end = rows[-1]["start"] + 3600
        first_hour = rows[0]["start"]
        start_b, end_b = seasons.boundary_instants(info)
        start_r = {"x": seasons.boundary_reading(rows, first_hour, last_end, start_b)}
        end_r = {"x": seasons.boundary_reading(rows, first_hour, last_end, end_b)}
        self.assertAlmostEqual(
            seasons.season_energy(start_r, end_r, ["x"]), expected, places=6
        )

    def check_equals_period_energy(self, tz, first_hour, gap):
        """Boundary-reading season energy equals ``period_energy`` of the day and month rows."""
        rows = hourly_rows(first_hour, 24 * 270, seed=7)
        rows = [r for i, r in enumerate(rows) if not (gap[0] <= i < gap[1])]
        info = since(HEAT, first_hour, first_hour + timedelta(days=270), tz)[0]
        self.assertTrue(info.ended)
        window = eff.Window(
            datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
        )
        ids = frozenset({"x"})
        tables = {
            "day": eff.TableRead(
                "day", window, {"x": reduce_rows(rows, tz, lambda d: d)}, ids
            ),
            "month": eff.TableRead(
                "month",
                window,
                {"x": reduce_rows(rows, tz, lambda d: (d.year, d.month))},
                ids,
            ),
        }
        ranges = eff.cover(
            info.season.start_day, info.season.end_day + timedelta(days=1), tz
        )
        self.assertIn("month", [r.source for r in ranges])
        expected = eff.period_energy(tables, ["x"], ranges)
        last_end = rows[-1]["start"] + 3600
        start_b, end_b = seasons.boundary_instants(info)
        start_r = {
            "x": seasons.boundary_reading(rows, rows[0]["start"], last_end, start_b)
        }
        end_r = {"x": seasons.boundary_reading(rows, rows[0]["start"], last_end, end_b)}
        return start_r, end_r, expected, info

    def test_first_hour_at_the_covered_start_and_a_gap_inside_the_season(self):
        for tz, first_hour in (
            (TZ, local(2026, 10, 1)),
            (KOLKATA, local(2026, 10, 1, 0, 30, KOLKATA)),
        ):
            with self.subTest(tz=str(tz)):
                # a gap of 30 hours in January (hours 2700 to 2730 of the history)
                start_r, end_r, expected, info = self.check_equals_period_energy(
                    tz, first_hour, (2700, 2730)
                )
                self.assertEqual(info.covered_start, first_hour.astimezone(UTC))
                self.assertEqual(start_r["x"], 0.0)
                self.assertAlmostEqual(
                    seasons.season_energy(start_r, end_r, ["x"]), expected, places=6
                )

    def test_first_hour_before_the_season_with_a_gap(self):
        for tz, first_hour in (
            (TZ, local(2026, 9, 20, 5)),
            (KOLKATA, local(2026, 9, 20, 5, 30, KOLKATA)),
        ):
            with self.subTest(tz=str(tz)):
                start_r, end_r, expected, _ = self.check_equals_period_energy(
                    tz, first_hour, (1500, 1507)
                )
                self.assertGreater(start_r["x"], 0.0)
                self.assertAlmostEqual(
                    seasons.season_energy(start_r, end_r, ["x"]), expected, places=6
                )

    def test_season_starting_after_the_first_hour_reads_the_sum_before_the_covered_start(
        self,
    ):
        first = local(2026, 11, 13, 14)
        rows = hourly_rows(first, 24 * 200)
        info = since(HEAT, first, local(2027, 6, 20))[0]
        self.assertEqual(info.covered_start, local(2026, 11, 14))
        last_end = rows[-1]["start"] + 3600
        start_b, end_b = seasons.boundary_instants(info)
        start_r = seasons.boundary_reading(rows, rows[0]["start"], last_end, start_b)
        end_r = seasons.boundary_reading(rows, rows[0]["start"], last_end, end_b)
        total = 0.0
        previous = 0.0
        for r in rows:
            if start_b.timestamp() <= r["start"] < end_b.timestamp():
                total += r["sum"] - previous
            previous = r["sum"]
        # the first 10 hours of 13 November are before the covered start: the reading there is a sum, not 0
        self.assertGreater(start_r, 0.0)
        self.assertAlmostEqual(end_r - start_r, total, places=6)


class SeasonPointTests(unittest.TestCase):
    def test_ratio_of_a_finished_season(self):
        infos = since(HEAT, local(2025, 9, 1), local(2027, 7, 15))
        points = seasons.season_points(infos, [(9000.0, 2500.0)] * len(infos), None, TZ)
        self.assertEqual(points[-1]["efficiency"], 3.60)
        self.assertEqual(points[-1]["output_energy"], 9000.0)
        self.assertEqual(points[-1]["electrical_energy"], 2500.0)

    def test_point_fields(self):
        infos = since(HEAT, local(2026, 11, 13, 14), local(2027, 1, 15))
        (point,) = seasons.season_points(infos, [(1000.1234, 250.0)], None, TZ)
        self.assertEqual(point["start"], local(2026, 11, 14).isoformat())
        self.assertEqual(point["end"], local(2027, 5, 1).isoformat())
        self.assertEqual(point["output_energy"], 1000.123)
        self.assertEqual(point["efficiency"], 4.0)
        self.assertFalse(point["complete"])
        self.assertFalse(point["ended"])
        self.assertFalse(point["estimated"])
        self.assertEqual(
            set(point),
            {
                "start",
                "end",
                "efficiency",
                "output_energy",
                "electrical_energy",
                "estimated",
                "complete",
                "ended",
            },
        )

    def test_unknown_season_keeps_its_point(self):
        infos = since(HEAT, local(2025, 9, 1), local(2027, 7, 15))
        energies = [(None, None)] * (len(infos) - 1) + [(0.2, 0.05)]
        points = seasons.season_points(infos, energies, None, TZ)
        self.assertEqual(len(points), len(infos))
        self.assertIsNone(points[-1]["efficiency"])
        self.assertEqual(points[-1]["output_energy"], 0.2)
        self.assertEqual(points[-1]["electrical_energy"], 0.05)
        self.assertIsNone(points[0]["efficiency"])
        self.assertIsNone(points[0]["output_energy"])

    def test_estimated_before_measured_since(self):
        infos = since(HEAT, local(2024, 9, 1), local(2027, 1, 15))
        points = seasons.season_points(
            infos, [(1.0, 1.0)] * len(infos), date(2026, 11, 13), TZ
        )
        self.assertEqual(
            [p["start"][:10] for p in points],
            ["2024-10-01", "2025-10-01", "2026-10-01"],
        )
        self.assertEqual([p["estimated"] for p in points], [True, True, True])
        later = seasons.season_points(
            infos, [(1.0, 1.0)] * len(infos), date(2026, 10, 1), TZ
        )
        self.assertEqual([p["estimated"] for p in later], [True, True, False])

    def test_cooling_unit_factor(self):
        infos = since(COOL, local(2025, 1, 1), local(2027, 1, 15))
        (point, *_) = seasons.season_points(
            infos, [(470.0, 100.0)] * len(infos), None, TZ, eff.BTU_PER_WH
        )
        self.assertEqual(point["efficiency"], 16.04)
        self.assertEqual(point["output_energy"], 470.0)

    def test_length_mismatch_is_an_error(self):
        infos = since(HEAT, local(2025, 9, 1), local(2027, 7, 15))
        with self.assertRaises(ValueError):
            seasons.season_points(infos, [], None, TZ)

    def test_defrost_length_mismatch_is_an_error(self):
        infos = since(HEAT, local(2025, 9, 1), local(2027, 7, 15))
        with self.assertRaises(ValueError):
            seasons.season_points(
                infos, [(1.0, 1.0)] * len(infos), None, TZ, defrost=[]
            )

    def test_points_unchanged_without_defrost(self):
        infos = since(HEAT, local(2025, 9, 1), local(2026, 12, 5))
        energies = [(9000.0, 2500.0)] * len(infos)
        plain = seasons.season_points(infos, energies, None, TZ)
        self.assertEqual(
            seasons.season_points(infos, energies, None, TZ, defrost=None), plain
        )
        self.assertEqual(
            seasons.season_points(
                infos, energies, None, TZ, defrost_start=local(2026, 11, 18, 10)
            ),
            plain,
        )
        for point in plain:
            self.assertNotIn("defrost_energy", point)
            self.assertNotIn("defrost_partial", point)

    def test_seasons_around_the_defrost_counter_start(self):
        # Seasons from 1 October 2025 and 1 October 2026; the defrost statistic starts on 18 November 2026.
        infos = since(HEAT, local(2025, 9, 1), local(2026, 12, 5))
        self.assertEqual(
            [i.season.start_day for i in infos], [date(2025, 10, 1), date(2026, 10, 1)]
        )
        # Finished season: the readings at its boundaries are 0.0 because the counter's first hour is
        # at or after both; running season: the defrost heat since 18 November 2026.
        first_hour = local(2026, 11, 18, 10)
        last_end = local(2026, 12, 5).timestamp()
        start_b, end_b = seasons.boundary_instants(infos[0])
        readings = {
            "start": {
                "d": seasons.boundary_reading(None, first_hour, last_end, start_b)
            },
            "end": {"d": seasons.boundary_reading(None, first_hour, last_end, end_b)},
        }
        self.assertEqual(readings, {"start": {"d": 0.0}, "end": {"d": 0.0}})
        finished = seasons.season_energy(readings["start"], readings["end"], ["d"])
        energies = [(9000.0, 2500.0), (3000.0, 750.0)]
        points = seasons.season_points(
            infos,
            energies,
            None,
            TZ,
            defrost=[finished, 100.0],
            defrost_start=local(2026, 11, 18, 10),
        )
        first, second = points
        self.assertTrue(first["defrost_partial"])
        self.assertTrue(second["defrost_partial"])
        self.assertEqual(first["defrost_energy"], 0.0)
        self.assertEqual(second["defrost_energy"], 100.0)
        # 0.0 kWh of defrost heat: the corrected efficiency equals the uncorrected one.
        self.assertEqual(first["efficiency"], 3.60)
        self.assertEqual(first["efficiency"], eff.ratio(9000.0, 2500.0))
        self.assertEqual(second["efficiency"], 3.87)  # (3000 - 100) / 750
        self.assertEqual(second["output_energy"], 3000.0)

    def test_finished_season_spanning_the_defrost_counters_start(self):
        # The first statistics hour is 15 November 2025 10:00 with a sum of 500.0 kWh; the sum is
        # 520.0 kWh at the season's end: the season's defrost energy is 20.0 kWh, not 520.0.
        infos = since(HEAT, local(2025, 9, 1), local(2026, 12, 5))
        info = infos[0]
        first_hour = local(2025, 11, 15, 10)
        start_b, end_b = seasons.boundary_instants(info)
        last_end = local(2026, 12, 5).timestamp()
        rows = [
            {"start": first_hour.timestamp(), "sum": 500.0},
            {"start": (end_b - timedelta(hours=1)).timestamp(), "sum": 520.0},
        ]
        start_r = {
            "d": seasons.boundary_reading(rows, first_hour, last_end, start_b, 500.0)
        }
        end_r = {
            "d": seasons.boundary_reading(rows, first_hour, last_end, end_b, 500.0)
        }
        self.assertEqual((start_r, end_r), ({"d": 500.0}, {"d": 520.0}))
        defrost = seasons.season_energy(start_r, end_r, ["d"])
        self.assertEqual(defrost, 20.0)
        (point, *_) = seasons.season_points(
            infos,
            [(900.0, 250.0)] * len(infos),
            None,
            TZ,
            defrost=[defrost] * len(infos),
            defrost_start=first_hour + timedelta(hours=1),
        )
        self.assertEqual(point["defrost_energy"], 20.0)
        self.assertTrue(point["defrost_partial"])
        self.assertEqual(point["efficiency"], 3.52)  # (900 - 20) / 250

    def test_season_after_the_defrost_start_is_not_partial(self):
        infos = since(HEAT, local(2026, 12, 1), local(2026, 12, 5))
        (point,) = seasons.season_points(
            infos,
            [(100.0, 25.0)],
            None,
            TZ,
            defrost=[5.0],
            defrost_start=local(2026, 11, 18, 10),
        )
        self.assertFalse(point["defrost_partial"])
        self.assertEqual(point["efficiency"], 3.80)

    def test_defrost_energy_is_rounded_to_three_decimals(self):
        infos = since(HEAT, local(2026, 12, 1), local(2026, 12, 5))
        (point,) = seasons.season_points(
            infos, [(100.0, 25.0)], None, TZ, defrost=[1.23456], defrost_start=None
        )
        self.assertEqual(point["defrost_energy"], 1.235)
        self.assertFalse(point["defrost_partial"])
        self.assertEqual(
            set(point),
            {
                "start",
                "end",
                "efficiency",
                "output_energy",
                "electrical_energy",
                "estimated",
                "complete",
                "ended",
                "defrost_energy",
                "defrost_partial",
            },
        )

    def test_unknown_defrost_energy_makes_the_point_unknown_but_keeps_it(self):
        infos = since(HEAT, local(2026, 12, 1), local(2026, 12, 5))
        (point,) = seasons.season_points(
            infos, [(100.0, 25.0)], None, TZ, defrost=[None]
        )
        self.assertIsNone(point["efficiency"])
        self.assertIsNone(point["defrost_energy"])
        self.assertEqual(point["output_energy"], 100.0)

    def test_defrost_exceeding_the_output_is_unknown_with_its_energy(self):
        infos = since(HEAT, local(2026, 12, 1), local(2026, 12, 5))
        (point,) = seasons.season_points(infos, [(10.0, 5.0)], None, TZ, defrost=[12.0])
        self.assertIsNone(point["efficiency"])
        self.assertEqual(point["defrost_energy"], 12.0)

    def test_unit_factor_with_defrost(self):
        infos = since(HEAT, local(2025, 9, 1), local(2027, 7, 15))
        (point, *_) = seasons.season_points(
            infos,
            [(470.0, 100.0)] * len(infos),
            None,
            TZ,
            eff.BTU_PER_WH,
            defrost=[70.0] * len(infos),
        )
        self.assertEqual(point["efficiency"], 13.65)  # (470 - 70) / 100 * 3.412142


class UnitTests(unittest.TestCase):
    def test_btu_per_wh(self):
        self.assertEqual(eff.BTU_PER_WH, 3.412142)
        self.assertEqual(eff.ratio(470.0, 100.0, eff.BTU_PER_WH), 16.04)

    def test_below_the_electrical_threshold_is_unknown_in_any_unit(self):
        self.assertIsNone(eff.ratio(1.0, 0.05, eff.BTU_PER_WH))
        self.assertIsNone(eff.ratio(1.0, 0.05))

    def test_factor_applies_before_rounding(self):
        # 1/3 = 0.333.. -> 0.33, but 3 * (1/3) = 1.0: the factor acts on the unrounded ratio
        self.assertEqual(eff.ratio(1.0, 3.0, 3.0), 1.0)
        self.assertEqual(eff.ratio(1.0, 3.0), 0.33)
        self.assertEqual(eff.ratio(9000.0, 2500.0), 3.6)
        self.assertEqual(eff.ratio(9000.0, 2500.0, 1.0), 3.6)

    def test_period_summary_with_factor(self):
        window = eff.Window(local(2026, 1, 1), local(2027, 1, 1))
        rng = eff.Range("day", local(2026, 12, 1), local(2026, 12, 2))
        day = {
            "start": local(2026, 12, 1).timestamp(),
            "end": local(2026, 12, 2).timestamp(),
        }
        tbl = {
            "day": eff.TableRead(
                "day",
                window,
                {"o": [dict(day, change=470.0)], "e": [dict(day, change=100.0)]},
                frozenset({"o", "e"}),
            )
        }
        plain = eff.period_summary(tbl, [rng], ["o"], ["e"])
        converted = eff.period_summary(tbl, [rng], ["o"], ["e"], eff.BTU_PER_WH)
        self.assertEqual(plain["efficiency"], 4.7)
        self.assertEqual(converted["efficiency"], 16.04)
        self.assertEqual(converted["output_energy"], 470.0)


class ImportTests(unittest.TestCase):
    def test_nothing_from_home_assistant_is_imported(self):
        tree = ast.parse((PACKAGE / "seasons.py").read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    self.assertEqual(node.level, 1)
                    self.assertEqual(node.module, None)
                    self.assertEqual([a.name for a in node.names], ["efficiency"])
                else:
                    modules.add(node.module.split(".")[0])
        self.assertTrue(modules)
        self.assertNotIn("homeassistant", modules)
        self.assertLessEqual(modules, set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
