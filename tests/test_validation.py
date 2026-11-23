"""Tests for the pure setup-form rules (standard library only).

Covers the efficiency-setup scenarios that do not need Home Assistant. The module
is loaded by file path; the package __init__.py (which imports Home Assistant) is
never imported.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "heatpump_efficiency"
_spec = importlib.util.spec_from_file_location("validation_under_test", PACKAGE / "validation.py")
val = importlib.util.module_from_spec(_spec)
sys.modules["validation_under_test"] = val
_spec.loader.exec_module(val)


def meta(statistic_id, unit_class="energy", has_sum=True, source="recorder"):
    return {
        "statistic_id": statistic_id,
        "unit_class": unit_class,
        "has_sum": has_sum,
        "source": source,
    }


OUT, ELEC = "sensor.heat_pump_heat_energy", "sensor.heat_pump_electric_energy"
GOOD = [meta(OUT), meta(ELEC)]


def form(**sections):
    return val.normalize_mapping(sections)


class ModuleHygieneTest(unittest.TestCase):
    def test_imports_only_standard_library(self):
        tree = ast.parse((PACKAGE / "validation.py").read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                roots.add((node.module or "").split(".")[0])
        self.assertTrue(roots <= set(sys.stdlib_module_names), roots)


class HeatPumpAddedTest(unittest.TestCase):
    def test_heating_only(self):
        mapping = form(
            heating={"output": [OUT], "electricity": [ELEC]},
            hot_water={},
            cooling={"measured_since": "2026-11-13"},
            overall={"output": [], "electricity": None},
        )
        self.assertEqual(val.configured_services(mapping), ["heating"])
        self.assertEqual(set(mapping), {"heating"})
        self.assertFalse(val.validate(mapping, GOOD, "Pump").errors)

    def test_nothing_mapped(self):
        for submitted in ({}, {"heating": {}, "planned": {"price": "sensor.price"}}):
            result = val.validate(val.normalize_mapping(submitted), [], "Pump")
            self.assertEqual(result.errors, {"base": "nothing_mapped"})

    def test_output_without_electricity(self):
        mapping = form(cooling={"output": [OUT]})
        result = val.validate(mapping, GOOD, "Pump")
        self.assertEqual(result.errors, {"cooling": "electricity_missing"})
        self.assertEqual(val.configured_services(mapping), [])

    def test_electricity_without_output(self):
        result = val.validate(form(overall={"electricity": [ELEC]}), GOOD, "Pump")
        self.assertEqual(result.errors, {"overall": "output_missing"})

    def test_error_only_on_failing_section(self):
        mapping = form(
            heating={"output": [OUT], "electricity": [ELEC]}, cooling={"output": [OUT]}
        )
        self.assertEqual(set(val.validate(mapping, GOOD, "Pump").errors), {"cooling"})

    def test_empty_name(self):
        mapping = form(heating={"output": [OUT], "electricity": [ELEC]})
        self.assertEqual(val.validate(mapping, GOOD, "  ").errors, {"name": "name_required"})
        self.assertFalse(val.validate(mapping, GOOD, None).errors)  # options flow: no name

    def test_two_heat_pumps_are_independent(self):
        first = form(heating={"output": [OUT], "electricity": [ELEC]})
        second = form(overall={"output": ["sensor.b_heat"], "electricity": ["sensor.b_elec"]})
        self.assertEqual(val.configured_services(first), ["heating"])
        self.assertEqual(val.configured_services(second), ["overall"])
        self.assertEqual(val.statistic_ids(first) & val.statistic_ids(second), set())

    def test_config_flow_sets_no_unique_id(self):
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        self.assertNotIn("async_set_unique_id", source)
        self.assertNotIn("_abort_if_unique_id", source)
        self.assertNotIn("async_add_update_listener", source)


class StatisticsValidatedTest(unittest.TestCase):
    def check(self, metadata, **sections):
        return val.validate(form(**sections), metadata, "Pump")

    def test_external_statistic_accepted(self):
        meta_ext = meta("utility:total_import", source="utility")
        result = self.check(
            [meta_ext, meta(OUT)],
            overall={"output": [OUT], "electricity": ["utility:total_import"]},
        )
        self.assertFalse(result.errors)

    def test_power_instead_of_energy(self):
        result = self.check(
            [meta(OUT), meta(ELEC, unit_class="power", has_sum=False)],
            heating={"output": [OUT], "electricity": [ELEC]},
        )
        self.assertEqual(result.errors, {"heating": "statistic_not_energy"})
        self.assertEqual(result.placeholders["not_energy"], "heating: " + ELEC)
        self.assertEqual(result.placeholders["no_sum"], "")

    def test_mean_only_statistic(self):
        result = self.check(
            [meta(OUT), meta(ELEC, has_sum=False)],
            heating={"output": [OUT], "electricity": [ELEC]},
        )
        self.assertEqual(result.errors, {"heating": "statistic_no_sum"})
        self.assertEqual(result.placeholders["no_sum"], "heating: " + ELEC)

    def test_statistic_does_not_exist(self):
        result = self.check([meta(OUT)], heating={"output": [OUT], "electricity": [ELEC]})
        self.assertEqual(result.errors, {"heating": "statistic_missing"})
        self.assertEqual(result.placeholders["missing"], "heating: " + ELEC)

    def test_all_failing_choices_are_named(self):
        result = self.check(
            [meta("sensor.a", unit_class=None, has_sum=False), meta("sensor.b", has_sum=False)],
            heating={"output": ["sensor.a", "sensor.b", "sensor.c"], "electricity": [ELEC]},
        )
        self.assertEqual(result.placeholders["not_energy"], "heating: sensor.a")
        self.assertEqual(result.placeholders["no_sum"], "heating: sensor.b")
        self.assertEqual(result.placeholders["missing"], "heating: sensor.c, " + ELEC)

    def test_two_sections_list_their_own_statistics(self):
        result = self.check(
            [meta(OUT), meta(ELEC)],
            heating={"output": [OUT], "electricity": ["sensor.a"]},
            cooling={"output": ["sensor.b"], "electricity": [ELEC]},
        )
        self.assertEqual(
            result.errors, {"heating": "statistic_missing", "cooling": "statistic_missing"}
        )
        self.assertEqual(result.placeholders["missing"], "heating: sensor.a; cooling: sensor.b")

    def test_one_failing_section_names_only_itself(self):
        result = self.check(
            [meta(OUT), meta(ELEC)],
            heating={"output": [OUT], "electricity": [ELEC]},
            cooling={"output": ["sensor.b"], "electricity": [ELEC]},
        )
        self.assertEqual(result.errors, {"cooling": "statistic_missing"})
        self.assertEqual(result.placeholders["missing"], "cooling: sensor.b")

    def test_submitted_planned_key_is_ignored(self):
        mapping = form(
            heating={"output": [OUT], "electricity": [ELEC]},
            planned={"price": "sensor.unknown_price"},
        )
        self.assertNotIn("planned", mapping)
        self.assertFalse(val.validate(mapping, GOOD, "Pump").errors)
        self.assertEqual(val.statistic_ids(mapping), {OUT, ELEC})
        self.assertFalse(hasattr(val, "FIELD_PRICE"))
        self.assertFalse(hasattr(val, "PLANNED_FIELDS"))


DEF_H, DEF_W = "sensor.heat_pump_defrost_heat", "sensor.heat_pump_hot_water_defrost_heat"
HEATING = {"output": [OUT], "electricity": [ELEC]}
HOT_WATER = {"output": ["sensor.hw_heat"], "electricity": ["sensor.hw_elec"]}
HW_META = [meta("sensor.hw_heat"), meta("sensor.hw_elec")]


class DefrostFieldsTest(unittest.TestCase):
    """The efficiency-setup defrost scenarios that need no Home Assistant (design D2)."""

    def check(self, metadata, **sections):
        return val.validate(form(**sections), metadata, "Pump")

    def test_defrost_statistic_stored_and_shown_again(self):
        mapping = form(heating={**HEATING, "defrost_heat": [DEF_H]})
        self.assertEqual(mapping["heating"]["defrost_heat"], [DEF_H])
        self.assertEqual(val.defrost_ids(mapping, "heating"), [DEF_H])
        self.assertEqual(val.normalize_mapping(mapping), mapping)  # idempotent
        self.assertEqual(val.suggested_values(mapping, {})["heating"]["defrost_heat"], [DEF_H])
        self.assertEqual(val.statistic_ids(mapping), {OUT, ELEC, DEF_H})
        self.assertFalse(val.validate(mapping, [*GOOD, meta(DEF_H)], "Pump").errors)

    def test_several_defrost_statistics_are_kept_in_order_without_duplicates(self):
        mapping = form(heating={**HEATING, "defrost_heat": [DEF_H, DEF_W, DEF_H]})
        self.assertEqual(mapping["heating"]["defrost_heat"], [DEF_H, DEF_W])

    def test_defrost_in_w_is_rejected_on_its_section(self):
        result = self.check(
            [*GOOD, *HW_META, meta(DEF_W, unit_class="power", has_sum=False)],
            heating=HEATING,
            hot_water={**HOT_WATER, "defrost_heat": [DEF_W]},
        )
        self.assertEqual(result.errors, {"hot_water": "statistic_not_energy"})
        self.assertEqual(result.placeholders["not_energy"], f"hot_water: {DEF_W}")

    def test_missing_and_sumless_defrost_statistics(self):
        result = self.check(GOOD, heating={**HEATING, "defrost_heat": [DEF_H]})
        self.assertEqual(result.errors, {"heating": "statistic_missing"})
        result = self.check(
            [*GOOD, meta(DEF_H, has_sum=False)], heating={**HEATING, "defrost_heat": [DEF_H]}
        )
        self.assertEqual(result.errors, {"heating": "statistic_no_sum"})

    def test_defrost_alone_does_not_configure_a_service(self):
        mapping = form(
            heating={"defrost_heat": [DEF_H], "measured_since": "2026-11-13"},
            overall={"output": [OUT], "electricity": [ELEC]},
        )
        self.assertEqual(val.configured_services(mapping), ["overall"])
        self.assertEqual(mapping["heating"], {"defrost_heat": [DEF_H]})  # no measured_since
        # Neither electricity_missing nor output_missing for the defrost-only section.
        self.assertFalse(val.validate(mapping, [*GOOD, meta(DEF_H)], "Pump").errors)

    def test_only_a_defrost_statistic_maps_nothing(self):
        mapping = form(heating={"defrost_heat": [DEF_H]})
        result = val.validate(mapping, [meta(DEF_H)], "Pump")
        self.assertEqual(result.errors["base"], "nothing_mapped")  # and nothing is created
        self.assertEqual(result.errors.get("heating"), "defrost_unused")  # it corrects nothing

    def test_defrost_alone_does_not_keep_a_cooling_unit(self):
        mapping = form(cooling={"defrost_heat": [DEF_H], "unit": "btu_per_wh"}, heating=HEATING)
        self.assertNotIn("cooling", mapping)

    def test_defrost_in_both_sections(self):
        mapping = form(
            heating={**HEATING, "defrost_heat": [DEF_H]},
            hot_water={**HOT_WATER, "defrost_heat": [DEF_W]},
        )
        self.assertEqual(val.defrost_ids(mapping, "hot_water"), [DEF_W])
        metadata = [*GOOD, *HW_META, meta(DEF_H), meta(DEF_W)]
        self.assertFalse(val.validate(mapping, metadata, "Pump").errors)

    def test_defrost_dropped_for_cooling_and_overall_and_a_planned_key_is_ignored(self):
        mapping = form(
            heating=HEATING,
            cooling={**HEATING, "defrost_heat": [DEF_H]},
            overall={**HEATING, "defrost_heat": [DEF_H]},
            planned={"price": "sensor.price", "defrost_heat": [DEF_H]},
        )
        self.assertNotIn("defrost_heat", mapping["cooling"])
        self.assertNotIn("defrost_heat", mapping["overall"])
        self.assertNotIn("planned", mapping)
        self.assertEqual(val.defrost_ids(mapping, "cooling"), [])
        self.assertEqual(val.defrost_ids(mapping, "overall"), [])

    def test_same_statistic_in_both_sections_is_rejected(self):
        result = self.check(
            [*GOOD, *HW_META, meta(DEF_H)],
            heating={**HEATING, "defrost_heat": [DEF_H]},
            hot_water={**HOT_WATER, "defrost_heat": [DEF_H]},
        )
        self.assertEqual(
            result.errors, {"heating": "defrost_duplicate", "hot_water": "defrost_duplicate"}
        )
        self.assertEqual(result.placeholders["duplicate"], f"heating: {DEF_H}; hot_water: {DEF_H}")

    def test_defrost_used_as_output_is_rejected_on_the_defrost_section(self):
        result = self.check(GOOD, heating={**HEATING, "defrost_heat": [OUT]})
        self.assertEqual(result.errors, {"heating": "defrost_duplicate"})
        self.assertEqual(result.placeholders["duplicate"], f"heating: {OUT}")
        # Also as another section's electrical statistic.
        result = self.check(
            [*GOOD, *HW_META],
            heating={**HEATING, "defrost_heat": ["sensor.hw_elec"]},
            hot_water=HOT_WATER,
        )
        self.assertEqual(result.errors, {"heating": "defrost_duplicate"})

    def test_duplicate_has_lower_priority_than_statistic_errors(self):
        result = self.check([meta(ELEC)], heating={**HEATING, "defrost_heat": [OUT]})
        self.assertEqual(result.errors, {"heating": "statistic_missing"})

    def test_defrost_that_corrects_nothing_is_rejected(self):
        result = self.check(
            [*HW_META, meta(DEF_H)], hot_water=HOT_WATER, heating={"defrost_heat": [DEF_H]}
        )
        self.assertEqual(result.errors, {"heating": "defrost_unused"})

    def test_defrost_of_an_unconfigured_service_corrects_overall(self):
        result = self.check(
            [*GOOD, meta(DEF_H)], heating={"defrost_heat": [DEF_H]}, overall=HEATING
        )
        self.assertEqual(result.errors, {})

    def test_error_codes_and_priority(self):
        self.assertIn("defrost_duplicate", val.ERRORS)
        self.assertIn("defrost_unused", val.ERRORS)
        self.assertEqual(val.PLACEHOLDERS["defrost_duplicate"], "duplicate")
        self.assertEqual(val._ERROR_PRIORITY[-2:], ("defrost_duplicate", "defrost_unused"))


class DefrostMigrationTest(unittest.TestCase):
    """The minor version 3 step (design D3)."""

    def test_slot_moves_to_heating_and_the_price_source_stays(self):
        stored = {
            "heating": {"output": [OUT], "electricity": [ELEC], "measured_since": "2026-11-13"},
            "overall": {"output": [OUT], "electricity": [ELEC]},
            "seasons": {"heating_start": "10-01"},
            "planned": {"price": "sensor.price", "defrost_heat": DEF_H},
        }
        moved = val.with_defrost_moved(stored)
        self.assertEqual(moved["heating"], {**stored["heating"], "defrost_heat": [DEF_H]})
        self.assertEqual(moved["planned"], {"price": "sensor.price"})
        self.assertEqual(moved["overall"], stored["overall"])
        self.assertEqual(moved["seasons"], stored["seasons"])
        self.assertEqual(set(moved), set(stored))
        self.assertEqual(stored["planned"]["defrost_heat"], DEF_H)  # input not modified
        self.assertNotIn("defrost_heat", stored["heating"])

    def test_slot_creates_the_heating_section_and_drops_an_empty_planned(self):
        stored = {"overall": {"output": [OUT]}, "planned": {"defrost_heat": DEF_H}}
        moved = val.with_defrost_moved(stored)
        self.assertEqual(moved["heating"], {"defrost_heat": [DEF_H]})
        self.assertNotIn("planned", moved)

    def test_slot_is_added_to_a_list_without_duplicates(self):
        stored = {"heating": {"defrost_heat": [DEF_W, DEF_H]}, "planned": {"defrost_heat": [DEF_H]}}
        self.assertEqual(val.with_defrost_moved(stored)["heating"]["defrost_heat"], [DEF_W, DEF_H])

    def test_slot_holding_an_output_statistic(self):
        # The slot value is also the Heating output: it is dropped, not moved.
        stored = {
            "heating": {"output": [OUT], "electricity": [ELEC]},
            "planned": {"price": "sensor.price", "defrost_heat": OUT},
        }
        moved = val.with_defrost_moved(stored)
        self.assertEqual(moved["heating"], {"output": [OUT], "electricity": [ELEC]})
        self.assertNotIn("defrost_heat", moved["heating"])
        self.assertEqual(moved["planned"], {"price": "sensor.price"})
        self.assertEqual(stored["planned"]["defrost_heat"], OUT)  # input not modified

    def test_slot_holding_an_electrical_statistic_or_an_output_of_another_section(self):
        stored = {
            "heating": {"output": [OUT], "electricity": [ELEC]},
            "overall": {"output": [DEF_W], "electricity": [DEF_H]},
            "planned": {"defrost_heat": ELEC},
        }
        moved = val.with_defrost_moved(stored)
        self.assertNotIn("defrost_heat", moved["heating"])
        self.assertNotIn("planned", moved)  # nothing left in it
        # A list: only the values that are not mapped move.
        stored = {**stored, "planned": {"defrost_heat": [DEF_H, "sensor.free"]}}
        self.assertEqual(val.with_defrost_moved(stored)["heating"]["defrost_heat"], ["sensor.free"])

    def test_slot_dropped_without_creating_a_heating_section(self):
        stored = {"overall": {"output": [OUT], "electricity": [ELEC]}, "planned": {"defrost_heat": [OUT]}}
        moved = val.with_defrost_moved(stored)
        self.assertNotIn("heating", moved)
        self.assertNotIn("planned", moved)
        self.assertEqual(moved["overall"], stored["overall"])

    def test_mapping_without_a_slot_is_unchanged(self):
        for stored in (
            {"heating": {"output": [OUT]}, "planned": {"price": "sensor.price"}},
            {"heating": {"output": [OUT]}},
            {},
        ):
            self.assertEqual(val.with_defrost_moved(stored), stored)

    def test_migration_is_idempotent(self):
        once = val.with_defrost_moved({"planned": {"defrost_heat": DEF_H, "price": "sensor.p"}})
        self.assertEqual(val.with_defrost_moved(once), once)


def migrate(options, minor_version):
    """The steps of ``__init__.async_migrate_entry`` in its order (the pure helpers only)."""
    if minor_version < 2:
        options = val.with_default_seasons(options, default_seasons(52.0))
    if minor_version < 3:
        options = val.with_defrost_moved(options)
    return val.without_planned(options)


class PlannedMigrationTest(unittest.TestCase):
    """The minor version 4 step (design D2): the planned section is dropped."""

    def test_price_source_dropped(self):
        # Scenario "Price source dropped".
        stored = {
            "heating": {"output": [OUT], "electricity": [ELEC]},
            "overall": {"output": [OUT], "electricity": [ELEC]},
            "seasons": {"heating_start": "10-01", "heating_end": "04-30"},
            "planned": {"price": "sensor.price"},
        }
        migrated = val.without_planned(stored)
        self.assertNotIn("planned", migrated)
        self.assertEqual(migrated, {key: stored[key] for key in stored if key != "planned"})
        self.assertEqual(stored["planned"], {"price": "sensor.price"})  # input not modified

    def test_entry_without_a_planned_section_is_unchanged(self):
        # Scenario "Entry without a planned section".
        stored = {"heating": {"output": [OUT], "electricity": [ELEC]}, "seasons": {"heating_start": "10-01"}}
        migrated = val.without_planned(stored)
        self.assertEqual(migrated, stored)
        self.assertIsNot(migrated, stored)
        self.assertEqual(val.without_planned({}), {})

    def test_step_is_idempotent(self):
        once = val.without_planned({"heating": {"output": [OUT]}, "planned": {"price": "sensor.p"}})
        self.assertEqual(val.without_planned(once), once)

    def test_minor_2_chain_moves_the_slot_and_drops_the_section(self):
        # Scenario "Slot moved to Heating": the defrost step still sees the planned slot.
        stored = {
            "heating": {"output": [OUT], "electricity": [ELEC]},
            "overall": {"output": [OUT], "electricity": [ELEC]},
            "seasons": {"heating_start": "10-01"},
            "planned": {"price": "sensor.price", "defrost_heat": DEF_H},
        }
        migrated = migrate(stored, 2)
        self.assertEqual(migrated["heating"], {**stored["heating"], "defrost_heat": [DEF_H]})
        self.assertNotIn("planned", migrated)
        self.assertEqual(migrated["overall"], stored["overall"])
        self.assertEqual(migrated["seasons"], stored["seasons"])
        self.assertEqual(stored["planned"]["defrost_heat"], DEF_H)  # input not modified

    def test_minor_1_chain_ends_in_the_current_shape(self):
        stored = {"heating": {"output": [OUT], "electricity": [ELEC]}, "planned": {"price": "sensor.p"}}
        migrated = migrate(stored, 1)
        self.assertEqual(set(migrated), {"heating", "seasons"})
        self.assertEqual(migrated["seasons"], default_seasons(52.0))

    def test_minor_3_entry_only_loses_the_planned_section(self):
        stored = {"heating": {"output": [OUT], "defrost_heat": [DEF_H]}, "planned": {"price": "sensor.p"}}
        self.assertEqual(migrate(stored, 3), {"heating": stored["heating"]})

    def test_slot_holding_an_output_statistic_ends_without_a_planned_section(self):
        # Scenario "Slot holding an output statistic".
        stored = {
            "heating": {"output": [OUT], "electricity": [ELEC]},
            "planned": {"price": "sensor.price", "defrost_heat": OUT},
        }
        migrated = migrate(stored, 2)
        self.assertEqual(migrated, {"heating": {"output": [OUT], "electricity": [ELEC]}})

    def test_one_update_call_for_the_whole_migration(self):
        source = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("hass.config_entries.async_update_entry("), 1)
        self.assertEqual(source.count("minor_version=4)"), 1)
        self.assertNotIn("minor_version=3)", source)
        self.assertLess(source.index("options = with_defrost_moved("), source.index("options = without_planned("))
        flow = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("MINOR_VERSION = 4", flow)


class MappingChangedTest(unittest.TestCase):
    def test_meter_replaced_keeps_service_keys(self):
        before = form(overall={"output": [OUT], "electricity": [ELEC]})
        after = form(overall={"output": [OUT], "electricity": ["sensor.new_meter_energy"]})
        self.assertEqual(val.configured_services(before), val.configured_services(after))
        self.assertEqual(after["overall"]["electricity"], ["sensor.new_meter_energy"])

    def test_removed_service_is_no_longer_configured(self):
        mapping = form(heating={"output": [OUT], "electricity": [ELEC]}, cooling={})
        self.assertNotIn("cooling", val.configured_services(mapping))

    def test_normalize_is_idempotent(self):
        mapping = form(
            heating={"output": [OUT, OUT], "electricity": [ELEC], "measured_since": "2026-11-13"},
        )
        self.assertEqual(val.normalize_mapping(mapping), mapping)
        self.assertEqual(mapping["heating"]["output"], [OUT])


class StoredSettingsTest(unittest.TestCase):
    def test_date_stored(self):
        mapping = form(
            hot_water={"output": [OUT], "electricity": [ELEC], "measured_since": "2026-11-13"}
        )
        self.assertEqual(mapping["hot_water"]["measured_since"], "2026-11-13")
        again = val.normalize_mapping(mapping)
        self.assertEqual(again["hot_water"]["measured_since"], "2026-11-13")

    def test_no_date_means_no_key(self):
        mapping = form(heating={"output": [OUT], "electricity": [ELEC], "measured_since": None})
        self.assertNotIn("measured_since", mapping["heating"])

    def test_planned_section_is_not_stored(self):
        mapping = form(
            heating={"output": [OUT], "electricity": [ELEC]},
            planned={"price": "sensor.electricity_price", "defrost_heat": "sensor.defrost_heat"},
        )
        self.assertEqual(set(mapping), {"heating"})
        self.assertEqual(val.configured_services(mapping), ["heating"])
        self.assertEqual(val.statistic_ids(mapping), {OUT, ELEC})


class ExpandedSectionsTest(unittest.TestCase):
    def test_defaults_to_heating_and_overall(self):
        self.assertEqual(val.expanded_sections(None), {"heating", "overall"})

    def test_stored_sections_expand(self):
        stored = form(
            cooling={"output": [OUT], "electricity": [ELEC]},
        )
        self.assertEqual(val.expanded_sections(stored), {"heating", "overall", "cooling"})

    def test_planned_never_expands(self):
        # Neither a stored legacy planned section nor an error code of that name expands it.
        stored = {"heating": {"output": [OUT]}, "planned": {"price": "sensor.price"}}
        self.assertNotIn("planned", val.expanded_sections(stored))
        self.assertNotIn("planned", val.expanded_sections(stored, ["planned"]))

    def test_error_sections_expand_and_base_is_ignored(self):
        shown = val.expanded_sections({}, ["hot_water", "base", "name"])
        self.assertEqual(shown, {"heating", "overall", "hot_water"})

    def test_const_does_not_reexport_validation_keys(self):
        self.assertNotIn("validation", (PACKAGE / "const.py").read_text(encoding="utf-8"))


_pkg = types.ModuleType("hpe_validation_pkg")  # seasons.py imports efficiency.py relatively
_pkg.__path__ = [str(PACKAGE)]
sys.modules["hpe_validation_pkg"] = _pkg
default_seasons = importlib.import_module("hpe_validation_pkg.seasons").default_seasons


def seasons_form(**values):
    """A submitted seasons section: heating_start=(10, 1) gives month "10" and day 1.0."""
    data = {}
    for key, (month, day) in values.items():
        data[key + "_month"] = str(month)
        data[key + "_day"] = float(day)  # a NumberSelector submits floats
    return data


def with_seasons(**values):
    return val.normalize_mapping(
        {"heating": {"output": [OUT], "electricity": [ELEC]}, "seasons": seasons_form(**values)}
    )


GOOD_SEASONS = {
    "heating_start": (10, 1),
    "heating_end": (4, 30),
    "cooling_start": (6, 1),
    "cooling_end": (9, 30),
}


class SeasonDatesTest(unittest.TestCase):
    def test_northern_defaults_are_the_suggested_values(self):
        values = val.suggested_values(None, default_seasons(52.0))["seasons"]
        self.assertEqual((values["heating_start_month"], values["heating_start_day"]), ("10", 1))
        self.assertEqual((values["heating_end_month"], values["heating_end_day"]), ("4", 30))
        self.assertEqual((values["cooling_start_month"], values["cooling_start_day"]), ("6", 1))
        self.assertEqual((values["cooling_end_month"], values["cooling_end_day"]), ("9", 30))

    def test_southern_defaults_are_the_suggested_values(self):
        values = val.suggested_values(None, default_seasons(-33.9))["seasons"]
        self.assertEqual((values["heating_start_month"], values["heating_start_day"]), ("4", 1))
        self.assertEqual((values["heating_end_month"], values["heating_end_day"]), ("10", 31))
        self.assertEqual((values["cooling_start_month"], values["cooling_start_day"]), ("12", 1))
        self.assertEqual((values["cooling_end_month"], values["cooling_end_day"]), ("2", 28))

    def test_stored_dates_win_over_defaults(self):
        stored = {"seasons": {"heating_start": "09-15", "heating_end": "05-15"}}
        values = val.suggested_values(stored, default_seasons(52.0))["seasons"]
        self.assertEqual((values["heating_start_month"], values["heating_start_day"]), ("9", 15))
        self.assertNotIn("cooling_start_month", values)

    def test_same_start_and_end_rejected(self):
        mapping = with_seasons(**{**GOOD_SEASONS, "cooling_start": (6, 1), "cooling_end": (6, 1)})
        self.assertEqual(val.validate(mapping, GOOD).errors, {"seasons": "season_same_day"})

    def test_day_not_in_month_rejected(self):
        mapping = with_seasons(**{**GOOD_SEASONS, "heating_end": (4, 31)})
        self.assertEqual(mapping["seasons"]["heating_end"], "04-31")
        self.assertEqual(val.validate(mapping, GOOD).errors, {"seasons": "season_invalid_day"})

    def test_29_february_rejected(self):
        mapping = with_seasons(**{**GOOD_SEASONS, "cooling_end": (2, 29)})
        self.assertEqual(val.validate(mapping, GOOD).errors, {"seasons": "season_invalid_day"})

    def test_28_february_valid_and_out_of_range_values_rejected(self):
        ok = with_seasons(**{**GOOD_SEASONS, "cooling_end": (2, 28)})
        self.assertFalse(val.validate(ok, GOOD).errors)
        for month, day in ((13, 1), (0, 5), (5, 0), (5, 32)):
            mapping = with_seasons(**{**GOOD_SEASONS, "heating_end": (month, day)})
            self.assertEqual(
                val.validate(mapping, GOOD).errors, {"seasons": "season_invalid_day"}, (month, day)
            )

    def test_cleared_day_is_missing(self):
        data = seasons_form(**GOOD_SEASONS)
        data["heating_end_day"] = None
        mapping = val.normalize_mapping(
            {"heating": {"output": [OUT], "electricity": [ELEC]}, "seasons": data}
        )
        self.assertEqual(val.validate(mapping, GOOD).errors, {"seasons": "season_missing"})
        data["heating_end_day"] = ""
        data.pop("cooling_start_month")
        mapping = val.normalize_mapping({"heating": mapping["heating"], "seasons": data})
        self.assertEqual(val.validate(mapping, GOOD).errors, {"seasons": "season_missing"})

    def test_cleared_section_is_missing(self):
        mapping = val.normalize_mapping(
            {"heating": {"output": [OUT], "electricity": [ELEC]}, "seasons": {}}
        )
        self.assertEqual(set(mapping["seasons"]), set(val.SEASON_DATES))
        self.assertEqual(val.validate(mapping, GOOD).errors, {"seasons": "season_missing"})

    def test_non_integer_day_is_invalid(self):
        data = seasons_form(**GOOD_SEASONS)
        data["heating_end_day"] = 15.5
        mapping = val.normalize_mapping(
            {"heating": {"output": [OUT], "electricity": [ELEC]}, "seasons": data}
        )
        self.assertEqual(val.validate(mapping, GOOD).errors, {"seasons": "season_invalid_day"})

    def test_good_dates_are_valid_including_a_season_crossing_the_new_year(self):
        self.assertFalse(val.validate(with_seasons(**GOOD_SEASONS), GOOD).errors)

    def test_15_september_to_15_may_round_trip(self):
        mapping = with_seasons(**{**GOOD_SEASONS, "heating_start": (9, 15), "heating_end": (5, 15)})
        self.assertEqual(mapping["seasons"]["heating_start"], "09-15")
        self.assertEqual(mapping["seasons"]["heating_end"], "05-15")
        self.assertFalse(val.validate(mapping, GOOD).errors)
        shown = val.suggested_values(mapping, default_seasons(52.0))["seasons"]
        self.assertEqual((shown["heating_start_month"], shown["heating_start_day"]), ("9", 15))
        self.assertEqual((shown["heating_end_month"], shown["heating_end_day"]), ("5", 15))
        again = val.normalize_mapping({**mapping, "seasons": shown})
        self.assertEqual(again, mapping)
        self.assertEqual(val.normalize_mapping(mapping), mapping)  # idempotent on stored strings

    def test_seasons_do_not_configure_a_service(self):
        mapping = val.normalize_mapping({"seasons": seasons_form(**GOOD_SEASONS)})
        self.assertEqual(val.configured_services(mapping), [])
        self.assertEqual(val.statistic_ids(mapping), set())
        self.assertEqual(val.validate(mapping, []).errors, {"base": "nothing_mapped"})

    def test_seasons_section_is_collapsed_unless_it_has_an_error(self):
        stored = with_seasons(**GOOD_SEASONS)
        self.assertNotIn("seasons", val.expanded_sections(stored))
        self.assertNotIn("seasons", val.expanded_sections(None))
        self.assertIn("seasons", val.expanded_sections(stored, ["seasons"]))

    def test_migration_keeps_every_key_and_adds_the_four_dates(self):
        version_1 = form(
            heating={"output": [OUT], "electricity": [ELEC], "measured_since": "2026-11-13"},
            cooling={"output": [OUT], "electricity": [ELEC], "unit": "btu_per_wh"},
        )
        merged = val.with_default_seasons(version_1, default_seasons(52.0))
        self.assertEqual({k: v for k, v in merged.items() if k != "seasons"}, version_1)
        self.assertEqual(merged["seasons"], default_seasons(52.0))
        self.assertEqual(set(merged["seasons"]), set(val.SEASON_DATES))
        self.assertNotIn("seasons", version_1)  # the input is not modified

    def test_migration_never_overwrites_stored_dates(self):
        stored = with_seasons(**{**GOOD_SEASONS, "heating_start": (9, 15)})
        merged = val.with_default_seasons(stored, default_seasons(-33.9))
        self.assertEqual(merged["seasons"]["heating_start"], "09-15")


class CoolingUnitTest(unittest.TestCase):
    COOLING = {"output": [OUT], "electricity": [ELEC]}

    def test_default_unit_is_w_per_w_and_not_stored(self):
        mapping = form(cooling=dict(self.COOLING))
        self.assertEqual(val.cooling_unit(mapping), "w_per_w")
        self.assertNotIn("unit", mapping["cooling"])
        explicit = form(cooling={**self.COOLING, "unit": "w_per_w"})
        self.assertNotIn("unit", explicit["cooling"])
        self.assertEqual(val.cooling_unit({}), "w_per_w")
        self.assertEqual(val.cooling_unit(None), "w_per_w")

    def test_btu_per_wh_is_stored_and_shown_again(self):
        mapping = form(cooling={**self.COOLING, "unit": "btu_per_wh"})
        self.assertEqual(mapping["cooling"]["unit"], "btu_per_wh")
        self.assertEqual(val.cooling_unit(mapping), "btu_per_wh")
        self.assertEqual(val.normalize_mapping(mapping), mapping)
        shown = val.suggested_values(mapping, default_seasons(52.0))
        self.assertEqual(shown["cooling"]["unit"], "btu_per_wh")
        self.assertFalse(val.validate(mapping, GOOD).errors)

    def test_unit_is_dropped_when_cooling_is_not_configured(self):
        mapping = form(
            heating={"output": [OUT], "electricity": [ELEC]}, cooling={"unit": "btu_per_wh"}
        )
        self.assertNotIn("cooling", mapping)
        self.assertEqual(val.cooling_unit(mapping), "w_per_w")

    def test_unit_is_only_a_cooling_field(self):
        mapping = form(heating={**self.COOLING, "unit": "btu_per_wh"})
        self.assertNotIn("unit", mapping["heating"])

    def test_warning_decision(self):
        stored = form(cooling=dict(self.COOLING))
        btu = form(cooling={**self.COOLING, "unit": "btu_per_wh"})
        self.assertTrue(val.unit_change_needs_warning(stored, btu, True))
        self.assertTrue(val.unit_change_needs_warning(btu, stored, True))  # and back
        self.assertFalse(val.unit_change_needs_warning(stored, btu, False))  # no statistics yet
        self.assertFalse(val.unit_change_needs_warning(stored, stored, True))  # unit unchanged
        self.assertFalse(val.unit_change_needs_warning(btu, btu, True))

    def test_removing_cooling_never_warns(self):
        btu = form(cooling={**self.COOLING, "unit": "btu_per_wh"})
        removed = form(heating=dict(self.COOLING))
        self.assertFalse(val.unit_change_needs_warning(btu, removed, True))

    def test_default_unit_is_suggested_when_cooling_is_configured(self):
        shown = val.suggested_values(form(cooling=dict(self.COOLING)), default_seasons(52.0))
        self.assertEqual(shown["cooling"]["unit"], "w_per_w")


if __name__ == "__main__":
    unittest.main()
