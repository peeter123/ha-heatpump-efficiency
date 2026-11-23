"""Tests of the statistics health repair issues (standard library only).

The pure plan (``repairs_model.py``) and the real glue (``issues.py``) run against
the fake reader of ``test_engine.py`` and a fake issue registry: a small in-memory
class with the create and delete semantics of Home Assistant's
``helpers/issue_registry.py`` (``async_create_issue`` replaces by
``(domain, issue_id)``, ``async_delete_issue`` ignores a missing issue,
``async_clear_config_entry`` deletes by ``config_entry_id``). ``issues.py`` is
loaded with a stub of ``homeassistant.helpers.issue_registry`` and
``homeassistant.const`` that exist only while it is imported.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace

# This folder on sys.path, so the module also runs as ``tests.test_repairs`` from the repository root.
_TESTS = str(Path(__file__).resolve().parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
import test_engine as te  # noqa: E402 - registers the bare package and loads engine and efficiency by path

PKG = "hpe_engine_pkg"


class FakeIssueRegistry:
    """In-memory ``IssueRegistry``: issues by (domain, issue_id)."""

    def __init__(self):
        self.issues: dict[tuple[str, str], SimpleNamespace] = {}
        self.known_entries: set[str] = set()

    def clear_config_entry(self, config_entry_id: str) -> None:
        # helpers/issue_registry.py IssueRegistry.async_clear_config_entry, called by
        # config_entries.py ConfigEntries._async_clean_up when an entry is removed.
        for key in [k for k, i in self.issues.items() if i.config_entry_id == config_entry_id]:
            del self.issues[key]


class Severity(StrEnum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"


def _load_glue(registry: FakeIssueRegistry):
    """Import issues.py against a stub issue registry; restore sys.modules afterwards."""
    ir = types.ModuleType("homeassistant.helpers.issue_registry")
    ir.IssueSeverity = Severity
    ir.async_get = lambda hass: registry

    def async_create_issue(
        hass, domain, issue_id, *, config_entry_id=None, is_fixable, severity,
        translation_key, translation_placeholders=None, **kwargs,
    ):
        if config_entry_id is not None and config_entry_id not in registry.known_entries:
            raise RuntimeError("Can't link issue to unknown config entry")
        registry.issues[(domain, issue_id)] = SimpleNamespace(
            issue_id=issue_id,
            domain=domain,
            config_entry_id=config_entry_id,
            is_fixable=is_fixable,
            severity=severity,
            translation_key=translation_key,
            translation_placeholders=translation_placeholders,
        )

    def async_delete_issue(hass, domain, issue_id, **kwargs):
        registry.issues.pop((domain, issue_id), None)

    ir.async_create_issue = async_create_issue
    ir.async_delete_issue = async_delete_issue
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.issue_registry = ir
    const = types.ModuleType("homeassistant.const")
    const.Platform = SimpleNamespace(SENSOR="sensor")
    root = types.ModuleType("homeassistant")
    stubs = {
        "homeassistant": root,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.issue_registry": ir,
        "homeassistant.const": const,
    }
    saved = {k: sys.modules.get(k) for k in stubs}
    for name in (f"{PKG}.issues", f"{PKG}.const"):
        sys.modules.pop(name, None)
    sys.modules.update(stubs)
    try:
        return importlib.import_module(f"{PKG}.issues")
    finally:
        for name, module in saved.items():
            if module is None:
                del sys.modules[name]
            else:
                sys.modules[name] = module


model = importlib.import_module(f"{PKG}.repairs_model")
eff, engine = te.eff, te.engine
ENTRY_ID = "entry1"
OTHER_ENTRY_ID = "entry2"
TITLE = "Heat pump"
NOW = te.utc(2026, 11, 17, 10, 20, 30)


class Stats(te.FakeStats):
    """The fake reader with statistics that can be renamed (missing) or changed in metadata."""

    def __init__(self):
        super().__init__()
        self.missing: set[str] = set()
        self.meta: dict[str, dict] = {}

    async def read(self, source, statistic_ids, window, units, types):
        return await super().read(source, set(statistic_ids) - self.missing, window, units, types)

    async def metadata(self, statistic_ids):
        rows = await super().metadata(set(statistic_ids) - self.missing)
        return [{**row, **self.meta.get(row["statistic_id"], {})} for row in rows]


class Rig:
    """One entry: the real engine, the real glue and the fake registry."""

    def __init__(self, mapping=None, stats=None, entry_id=ENTRY_ID, registry=None):
        self.registry = registry or FakeIssueRegistry()
        self.registry.known_entries.add(entry_id)
        self.glue = _load_glue(self.registry)
        self.stats = stats or te.make_stats()
        if not isinstance(self.stats, Stats):
            raise TypeError
        self.mapping = mapping or {"heating": te.MAPPING["heating"]}
        self.entry = SimpleNamespace(entry_id=entry_id, title=TITLE)
        self.state = engine.EngineState()

    def update(self, now: datetime = NOW):
        self.stats.now = now
        result = te.asyncio.run(engine.async_update(self.state, self.mapping, self.stats, now, te.TZ))
        self.glue.async_update_issues(object(), self.entry, self.mapping, result, self.state, te.TZ)
        return result

    def issues(self) -> dict[str, tuple[str, dict]]:
        return {
            issue_id: (i.translation_key, i.translation_placeholders)
            for (domain, issue_id), i in self.registry.issues.items()
            if domain == "heatpump_efficiency" and i.config_entry_id == self.entry.entry_id
        }


def make_rig(**kwargs) -> Rig:
    stats = Stats()
    for sid, rate in ((te.OUT_H, 2.0), (te.EL_H, 0.5), (te.OUT_W, 1.0), (te.EL_W, 0.25), (te.OUT_A, 3.0)):
        stats.series[sid] = te.Series(te.FIRST, rate)
    stats.series[te.EL_A] = te.Series(te.FIRST, 0.75, source="external")
    return Rig(stats=stats, **kwargs)


def iid(statistic_id: str, entry_id: str = ENTRY_ID) -> str:
    return f"{entry_id}_{statistic_id}"


class ScenarioTest(unittest.TestCase):
    """The scenarios of the statistics-health spec, through the engine, the plan and the glue."""

    def test_healthy_entry_has_no_issue(self):
        rig = make_rig()
        rig.update()
        self.assertEqual(rig.issues(), {})

    def test_statistic_renamed(self):
        rig = make_rig()
        rig.stats.missing.add(te.EL_H)
        rig.update()
        key, placeholders = rig.issues()[iid(te.EL_H)]
        self.assertEqual(key, "statistic_missing")
        self.assertEqual(placeholders["heat_pump"], TITLE)
        self.assertEqual(placeholders["statistic_id"], te.EL_H)
        self.assertEqual(list(rig.issues()), [iid(te.EL_H)])

    def test_issue_is_a_non_fixable_warning_with_the_config_entry(self):
        rig = make_rig()
        rig.stats.missing.add(te.EL_H)
        rig.update()
        issue = rig.registry.issues[("heatpump_efficiency", iid(te.EL_H))]
        self.assertIs(issue.is_fixable, False)
        self.assertEqual(issue.severity, Severity.WARNING)
        self.assertEqual(issue.config_entry_id, ENTRY_ID)

    def test_unit_changed_to_watt(self):
        rig = make_rig()
        rig.stats.meta[te.OUT_H] = {"unit_class": "power", "has_sum": False}
        rig.update()
        self.assertEqual(rig.issues()[iid(te.OUT_H)][0], "statistic_not_energy")

    def test_no_sum(self):
        rig = make_rig()
        rig.stats.meta[te.OUT_H] = {"has_sum": False}
        rig.update()
        self.assertEqual(rig.issues()[iid(te.OUT_H)][0], "statistic_no_sum")

    def test_sensor_stopped_for_three_hours(self):
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 3 * te.H
        rig.update()
        key, placeholders = rig.issues()[iid(te.EL_H)]
        self.assertEqual(key, "statistic_stale")
        # The last 5-minute row ended at 07:20 UTC (now 10:20:30 minus 3 h), 08:20 local.
        self.assertEqual(placeholders["last_statistics"], "2026-11-17 08:20")

    def test_two_hours_behind_is_not_stale(self):
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 110 * 60
        rig.update()
        self.assertEqual(rig.issues(), {})

    def test_sensor_stopped_has_exactly_the_placeholders_of_its_text(self):
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 3 * te.H
        rig.update()
        _, placeholders = rig.issues()[iid(te.EL_H)]
        self.assertEqual(set(placeholders), {"heat_pump", "statistic_id", "last_statistics"})

    def test_stale_without_any_row_in_the_window(self):
        # Design D7: no row today or in the last 3 hours has its own key, without a last time.
        rig = make_rig()
        rig.stats.series[te.EL_H] = te.Series(te.utc(2099, 1, 1), 0.5)  # no row yet
        rig.update()
        key, placeholders = rig.issues()[iid(te.EL_H)]
        self.assertEqual(key, "statistic_stale_no_rows")
        self.assertEqual(placeholders, {"heat_pump": TITLE, "statistic_id": te.EL_H})

    def test_stale_key_depends_on_the_staleness_window(self):
        # The window is today or the last 3 hours, whichever is longer. At 11:20 local it is today:
        # a last row 5 hours ago is in it, so its time is shown.
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 5 * te.H
        rig.update()
        key, placeholders = rig.issues()[iid(te.EL_H)]
        self.assertEqual((key, placeholders["last_statistics"]), ("statistic_stale", "2026-11-17 06:20"))
        # Shortly after midnight the window is the last 3 hours: a row 5 hours old is outside it.
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 5 * te.H
        rig.update(te.utc(2026, 11, 17, 23, 5, 30))
        self.assertEqual(rig.issues()[iid(te.EL_H)][0], "statistic_stale_no_rows")

    def test_switches_between_the_stale_keys(self):
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 150 * 60
        rig.update(te.utc(2026, 11, 17, 23, 5, 30))  # 00:05 local: window is the last 3 hours
        self.assertEqual(rig.issues()[iid(te.EL_H)][0], "statistic_stale")
        rig.stats.series[te.EL_H].lag = 4 * te.H
        rig.update(te.utc(2026, 11, 17, 23, 10, 30))
        key, placeholders = rig.issues()[iid(te.EL_H)]
        self.assertEqual(key, "statistic_stale_no_rows")
        self.assertNotIn("last_statistics", placeholders)

    def test_problem_resolved_when_the_statistic_updates_again(self):
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 3 * te.H
        rig.update()
        self.assertIn(iid(te.EL_H), rig.issues())
        rig.stats.series[te.EL_H].lag = 0
        rig.update(NOW + timedelta(minutes=5))
        self.assertEqual(rig.issues(), {})

    def test_problem_resolved_when_the_statistic_exists_again(self):
        rig = make_rig()
        rig.stats.missing.add(te.EL_H)
        rig.update()
        self.assertIn(iid(te.EL_H), rig.issues())
        rig.stats.missing.clear()
        # The metadata is read at every update (design D4): the issue goes at the next check.
        result = rig.update(NOW + timedelta(minutes=5))
        self.assertEqual(rig.issues(), {})
        # Its first hour was read while it was missing and is read again only at the next
        # first-hours refresh, so its service has not begun until then (conservative).
        self.assertIsNone(rig.state.first_hours[te.EL_H])
        self.assertIsNone(result.services["heating"].periods["year_to_date"].efficiency)
        result = rig.update(NOW + timedelta(days=1))
        self.assertEqual(rig.issues(), {})
        self.assertEqual(result.services["heating"].periods["year_to_date"].efficiency, 4.0)

    def test_problem_resolved_when_the_mapping_changes_to_a_valid_statistic(self):
        rig = make_rig()
        rig.stats.missing.add(te.EL_H)
        rig.update()
        self.assertIn(iid(te.EL_H), rig.issues())
        # Options changed: a reload gives a new coordinator with a fresh engine state.
        rig.mapping = {"heating": {"output": [te.OUT_H], "electricity": [te.EL_W]}}
        rig.state = engine.EngineState()
        rig.update(NOW + timedelta(minutes=5))
        self.assertEqual(rig.issues(), {})

    def test_statistic_renamed_after_setup(self):
        # Healthy at setup, renamed afterwards: missing at the next check, not stopped.
        rig = make_rig()
        rig.update()
        self.assertEqual(rig.issues(), {})
        rig.stats.missing.add(te.EL_H)
        rig.update(NOW + timedelta(minutes=5))
        self.assertEqual({k: v[0] for k, v in rig.issues().items()}, {iid(te.EL_H): "statistic_missing"})

    def test_unit_changed_to_watt_after_setup(self):
        rig = make_rig()
        rig.update()
        rig.stats.meta[te.OUT_H] = {"unit_class": "power", "has_sum": False}
        rig.update(NOW + timedelta(minutes=5))
        self.assertEqual({k: v[0] for k, v in rig.issues().items()}, {iid(te.OUT_H): "statistic_not_energy"})
        rig.stats.meta.clear()  # the energy unit restored
        rig.update(NOW + timedelta(minutes=10))
        self.assertEqual(rig.issues(), {})

    def test_one_issue_per_statistic_and_update_replaces(self):
        rig = make_rig(mapping=te.MAPPING)
        rig.stats.missing.update({te.EL_H, te.EL_W})
        rig.update()
        rig.update(NOW + timedelta(minutes=5))
        self.assertEqual(set(rig.issues()), {iid(te.EL_H), iid(te.EL_W)})
        self.assertEqual(len(rig.registry.issues), 2)

    def test_integration_removed(self):
        registry = FakeIssueRegistry()
        mine = make_rig(registry=registry)
        other = make_rig(registry=registry, entry_id=OTHER_ENTRY_ID)
        for rig in (mine, other):
            rig.stats.missing.add(te.EL_H)
            rig.update()
        self.assertEqual(len(registry.issues), 2)
        registry.clear_config_entry(ENTRY_ID)  # Home Assistant does this on entry removal
        self.assertEqual(mine.issues(), {})
        self.assertEqual(set(other.issues()), {iid(te.EL_H, OTHER_ENTRY_ID)})

    def test_glue_only_touches_its_own_entry(self):
        registry = FakeIssueRegistry()
        other = make_rig(registry=registry, entry_id=OTHER_ENTRY_ID)
        other.stats.missing.add(te.EL_H)
        other.update()
        mine = make_rig(registry=registry)
        mine.update()  # healthy: deletes nothing of the other entry
        self.assertEqual(set(other.issues()), {iid(te.EL_H, OTHER_ENTRY_ID)})

    def test_external_statistic_stale_from_the_hourly_table(self):
        mapping = {"overall": te.MAPPING_OVERALL["overall"]}
        rig = make_rig(mapping=mapping)
        rig.stats.series[te.EL_A].lag = 3 * te.H + 30 * 60
        rig.update()
        issues = rig.issues()
        self.assertEqual(set(issues), {iid(te.EL_A)})
        key, placeholders = issues[iid(te.EL_A)]
        self.assertEqual(key, "statistic_stale")
        # Hourly rows: the last one ended at 06:00 UTC, 07:00 local.
        self.assertEqual(placeholders["last_statistics"], "2026-11-17 07:00")
        # The recorder statistic of Overall, with 5-minute rows, is healthy.
        self.assertNotIn(iid(te.OUT_A), issues)

    def test_external_statistic_two_hours_behind_is_healthy(self):
        rig = make_rig(mapping={"overall": te.MAPPING_OVERALL["overall"]})
        rig.stats.series[te.EL_A].lag = 30 * 60
        rig.update()
        self.assertEqual(rig.issues(), {})


class ConservativeTest(unittest.TestCase):
    def test_failed_metadata_read_raises_no_false_missing_issue(self):
        rig = make_rig()

        async def boom(ids):
            raise RuntimeError("boom")

        rig.stats.metadata = boom
        rig.update()
        self.assertFalse(rig.state.metadata_ok)
        self.assertEqual(rig.issues(), {})

    def test_existing_issues_stay_until_the_metadata_is_known(self):
        rig = make_rig()
        rig.stats.missing.add(te.EL_H)
        rig.update()
        rig.state = engine.EngineState()  # a reload: metadata unknown again

        async def boom(ids):
            raise RuntimeError("boom")

        real = rig.stats.metadata
        rig.stats.metadata = boom
        rig.update(NOW + timedelta(minutes=5))
        self.assertIn(iid(te.EL_H), rig.issues())
        rig.stats.metadata = real
        rig.stats.missing.clear()
        rig.update(NOW + timedelta(minutes=10))
        self.assertEqual(rig.issues(), {})

    def test_failed_metadata_read_mid_day_keeps_the_issues_of_the_last_metadata(self):
        rig = make_rig()
        rig.stats.missing.add(te.EL_H)
        rig.update()
        real = rig.stats.metadata

        async def boom(ids):
            raise RuntimeError("boom")

        rig.stats.metadata = boom
        rig.stats.missing.clear()  # exists again, but the metadata read fails
        rig.update(NOW + timedelta(minutes=5))
        self.assertTrue(rig.state.metadata_ok)
        self.assertEqual(rig.issues()[iid(te.EL_H)][0], "statistic_missing")
        rig.stats.metadata = real
        rig.update(NOW + timedelta(minutes=10))
        self.assertEqual(rig.issues(), {})

    def test_repairs_failure_never_fails_the_update(self):
        # The entry was removed while the update waited on a read: Home Assistant's
        # async_create_issue raises for the unknown config entry. The glue logs it.
        rig = make_rig()
        rig.registry.known_entries.discard(ENTRY_ID)
        rig.stats.missing.add(te.EL_H)
        with self.assertLogs(f"{PKG}.issues", "ERROR"):
            rig.update()
        self.assertEqual(rig.issues(), {})

    def test_failed_5minute_read_is_not_reported_as_stopped(self):
        rig = make_rig()
        rig.update()
        rig.stats.fail.add("5minute")
        rig.update(NOW + timedelta(minutes=5))
        self.assertEqual(rig.issues(), {})

    def test_failed_read_keeps_an_existing_stale_issue(self):
        rig = make_rig()
        rig.stats.series[te.EL_H].lag = 3 * te.H
        rig.update()
        rig.stats.fail.add("5minute")
        rig.update(NOW + timedelta(minutes=5))
        self.assertIn(iid(te.EL_H), rig.issues())


class DefrostIssueTest(unittest.TestCase):
    """The defrost statistics get the issues of any mapped statistic (design D9)."""

    def rig(self, mapping):
        rig = make_rig(mapping=mapping)
        rig.stats.series[te.DEF_H] = te.Series(te.FIRST, 0.1)
        return rig

    def test_mapped_defrost_statistic_is_missing(self):
        rig = self.rig(te.MAPPING_DEFROST)
        rig.stats.missing.add(te.DEF_H)
        rig.update()
        self.assertEqual(rig.issues()[iid(te.DEF_H)][0], "statistic_missing")
        self.assertEqual(rig.issues()[iid(te.DEF_H)][1]["statistic_id"], te.DEF_H)

    def test_mapped_defrost_statistic_is_stale(self):
        rig = self.rig(te.MAPPING_DEFROST)
        rig.stats.series[te.DEF_H].lag = 3 * te.H
        rig.update()
        self.assertEqual(rig.issues()[iid(te.DEF_H)][0], "statistic_stale")

    def test_defrost_in_an_unconfigured_section_is_checked_through_overall(self):
        mapping = {"heating": {"defrost_heat": [te.DEF_H]}, "overall": te.MAPPING_OVERALL["overall"]}
        rig = self.rig(mapping)
        rig.stats.missing.add(te.DEF_H)
        rig.update()
        self.assertEqual(rig.issues()[iid(te.DEF_H)][0], "statistic_missing")

    def test_defrost_in_an_unconfigured_section_is_stale_through_overall(self):
        mapping = {"heating": {"defrost_heat": [te.DEF_H]}, "overall": te.MAPPING_OVERALL["overall"]}
        rig = self.rig(mapping)
        rig.stats.series[te.DEF_H].lag = 3 * te.H
        rig.update()
        self.assertEqual(rig.issues()[iid(te.DEF_H)][0], "statistic_stale")

    def test_defrost_that_corrects_nothing_is_not_checked(self):
        rig = self.rig({"heating": {"defrost_heat": [te.DEF_H]}, "hot_water": te.MAPPING["hot_water"]})
        rig.stats.missing.add(te.DEF_H)
        rig.update()
        self.assertEqual(rig.issues(), {})


class PlanTest(unittest.TestCase):
    """The pure function on its own."""

    TZ = te.TZ

    def plan(self, health, existing=(), metadata_ok=True, mapped=("a", "b"), skip=(), last=None):
        return model.plan_issues(
            "e", "Pump", mapped, health, last or {}, existing, metadata_ok, self.TZ, skip
        )

    def test_create_and_delete(self):
        plan = self.plan({"a": "ok", "b": "missing"}, existing=["e_a"])
        self.assertEqual([s.issue_id for s in plan.create], ["e_b"])
        self.assertEqual(plan.create[0].translation_key, "statistic_missing")
        self.assertEqual(plan.delete, ("e_a",))

    def test_every_health_maps_to_a_key_with_its_placeholders(self):
        ts = datetime(2026, 11, 17, 7, 20, tzinfo=te.UTC).timestamp()
        for health, key in model.ISSUE_KEYS.items():
            for last in (ts, None):
                spec = self.plan({"a": health, "b": "ok"}, last={"a": last}).create[0]
                stale = health == "stale"
                self.assertEqual(
                    spec.translation_key, model.STALE_NO_ROWS_KEY if stale and last is None else key
                )
                expected = set(model.PLACEHOLDERS) | ({model.LAST_STATISTICS} if stale and last else set())
                self.assertEqual(set(spec.placeholders), expected, (health, last))

    def test_issue_key(self):
        self.assertEqual(model.issue_key("stale", 1.0), "statistic_stale")
        self.assertEqual(model.issue_key("stale", None), "statistic_stale_no_rows")
        self.assertEqual(model.issue_key("missing", None), "statistic_missing")
        self.assertIsNone(model.issue_key("ok", None))
        self.assertEqual(len(set(model.TRANSLATION_KEYS)), 5)

    def test_unmapped_issue_is_deleted_even_before_the_metadata_is_known(self):
        plan = self.plan({}, existing=["e_gone", "e_a"], metadata_ok=False)
        self.assertEqual((plan.create, plan.delete), ((), ("e_gone",)))

    def test_skipped_statistic_keeps_its_issue(self):
        plan = self.plan({"a": "stale", "b": "ok"}, existing=["e_a"], skip=["a"])
        self.assertEqual((plan.create, plan.delete), ((), ()))

    def test_statistic_without_health_keeps_its_issue(self):
        plan = self.plan({}, existing=["e_a"])
        self.assertEqual((plan.create, plan.delete), ((), ()))

    def test_unchecked_only_for_stale_with_a_failed_table(self):
        health = {"x": "stale", "y": "stale", "z": "missing"}
        errors = {"5minute": "boom", "hour": None}
        self.assertEqual(model.unchecked(health, {"y"}, errors), {"x"})
        self.assertEqual(model.unchecked(health, {"y"}, {"hour": "boom"}), {"y"})

    def test_last_statistics_time_is_local(self):
        ts = datetime(2026, 11, 17, 7, 20, tzinfo=te.UTC).timestamp()
        spec = self.plan({"a": "stale", "b": "ok"}, last={"a": ts}).create[0]
        self.assertEqual(spec.placeholders["last_statistics"], "2026-11-17 08:20")


if __name__ == "__main__":
    unittest.main()
