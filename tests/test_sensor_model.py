"""Tests of the sensors' pure model and of sensor.py's class attributes (pytest, without Home Assistant)."""

import ast
import importlib
import json
from pathlib import Path
import sys
import types

PACKAGE = (
    Path(__file__).resolve().parents[1] / "custom_components" / "heatpump_efficiency"
)
_pkg = types.ModuleType("hpe_sensor_pkg")
_pkg.__path__ = [str(PACKAGE)]
sys.modules["hpe_sensor_pkg"] = _pkg
eff = importlib.import_module("hpe_sensor_pkg.efficiency")
model = importlib.import_module("hpe_sensor_pkg.sensor_model")
engine = importlib.import_module("hpe_sensor_pkg.engine")

ENTRY = "01ENTRYID"
MAPPING = {
    "heating": {"output": ["sensor.a"], "electricity": ["sensor.b"]},
    "hot_water": {"output": ["sensor.c"], "electricity": []},  # half mapped: no sensors
    "overall": {"output": ["sensor.d"], "electricity": ["sensor.e"]},
}


class TestSensorSpecs:
    def test_four_sensors_per_configured_service_and_none_for_others(self):
        specs = model.sensor_specs(ENTRY, MAPPING)
        periods = [s for s in specs if not s.is_season]
        assert len(periods) == 8
        assert {s.service for s in specs} == {"heating", "overall"}
        for service in ("hot_water", "cooling"):
            assert not [s for s in specs if s.service == service]
        assert {s.period for s in periods} == set(eff.PERIODS)

    def test_season_sensors_for_heating_overall_and_cooling_but_not_hot_water(self):
        full = {
            **MAPPING,
            "hot_water": {"output": ["sensor.c"], "electricity": ["sensor.f"]},
            "cooling": {"output": ["sensor.g"], "electricity": ["sensor.h"]},
        }
        seasons = {s.service: s for s in model.sensor_specs(ENTRY, full) if s.is_season}
        assert set(seasons) == {"heating", "overall", "cooling"}
        assert seasons["heating"].unique_id == f"{ENTRY}_heating_heating_season"
        assert seasons["overall"].unique_id == f"{ENTRY}_overall_heating_season"
        assert seasons["cooling"].unique_id == f"{ENTRY}_cooling_cooling_season"
        assert seasons["cooling"].translation_key == "cooling_cooling_season"
        assert len(model.sensor_specs(ENTRY, full)) == 16 + 3

    def test_no_cooling_season_sensor_when_cooling_is_not_configured(self):
        specs = model.sensor_specs(ENTRY, MAPPING)
        assert sorted(s.service for s in specs if s.is_season) == ["heating", "overall"]
        assert not [s for s in specs if s.unique_id.endswith("cooling_season")]
        only = model.sensor_specs(ENTRY, {"heating": MAPPING["heating"]})
        assert [s.unique_id for s in only if s.is_season] == [
            f"{ENTRY}_heating_heating_season"
        ]

    def test_cooling_sensors_carry_the_unit_only_in_btu_per_wh(self):
        cooling = {"output": ["sensor.g"], "electricity": ["sensor.h"]}
        for unit, expected in (
            ("btu_per_wh", "BTU/Wh"),
            ("w_per_w", None),
            (None, None),
        ):
            mapping = {
                **MAPPING,
                "cooling": {**cooling, **({} if unit is None else {"unit": unit})},
            }
            units = {s.service: s.unit for s in model.sensor_specs(ENTRY, mapping)}
            assert units["cooling"] == expected, unit
            assert units["heating"] is None
            assert units["overall"] is None
            assert {
                s.unit
                for s in model.sensor_specs(ENTRY, mapping)
                if s.service == "cooling"
            } == {expected}

    def test_service_unique_ids_for_the_unit_change_lookup(self):
        ids = model.service_unique_ids(ENTRY, "cooling")
        assert len(ids) == 5
        assert f"{ENTRY}_cooling_cooling_season" in ids
        assert len(model.service_unique_ids(ENTRY, "hot_water")) == 4

    def test_unique_ids_and_translation_keys(self):
        specs = {
            (s.service, s.period): s
            for s in model.sensor_specs(ENTRY, MAPPING)
            if not s.is_season
        }
        spec = specs[("heating", "month_to_date")]
        assert spec.unique_id == f"{ENTRY}_heating_month_to_date"
        assert spec.translation_key == "heating_month_to_date"
        assert len({s.unique_id for s in specs.values()}) == 8

    def test_every_translation_key_has_a_name(self):
        translations = json.loads(
            (PACKAGE / "translations" / "en.json").read_text(encoding="utf-8")
        )
        names = translations["entity"]["sensor"]
        every = {
            model.translation_key(service, period)
            for service in ("heating", "hot_water", "cooling", "overall")
            for period in eff.PERIODS
        } | {
            model.translation_key(service, season)
            for service, season in model.SEASONS.items()
        }
        assert set(names) == every
        assert len(every) == 19
        for key, text in names.items():
            assert text["name"], key
            assert text["name"].isascii(), key

    def test_nothing_mapped_gives_no_sensors(self):
        assert model.sensor_specs(ENTRY, {}) == []


class TestStaleUniqueIds:
    def test_unique_ids_of_unmapped_services_are_removed(self):
        existing = [
            s.unique_id
            for s in model.sensor_specs(
                ENTRY, {**MAPPING, "cooling": MAPPING["heating"]}
            )
        ]
        # Cooling is removed from the mapping; heating and overall stay.
        stale = model.stale_unique_ids(ENTRY, MAPPING, existing)
        assert sorted(stale) == sorted(model.service_unique_ids(ENTRY, "cooling"))

    def test_current_sensors_and_other_entries_are_kept(self):
        current = [s.unique_id for s in model.sensor_specs(ENTRY, MAPPING)]
        other = ["02OTHER_heating_today", None, "unrelated"]
        assert model.stale_unique_ids(ENTRY, MAPPING, current + other) == []

    def test_everything_goes_when_the_mapping_is_empty(self):
        current = [s.unique_id for s in model.sensor_specs(ENTRY, MAPPING)]
        assert sorted(model.stale_unique_ids(ENTRY, {}, current)) == sorted(current)


class TestAttributes:
    def test_period_attributes(self):
        period = engine.PeriodResult(
            62.0, 18.5, 3.35, "2026-11-01T00:00:00+01:00", True
        )
        assert model.period_attributes(period) == {
            "output_energy": 62.0,
            "electrical_energy": 18.5,
            "period_start": "2026-11-01T00:00:00+01:00",
            "includes_estimated": True,
        }

    def test_season_attributes(self):
        points = [{"start": "2026-10-01T00:00:00+02:00", "efficiency": 3.6}]
        season = engine.SeasonResult(
            3.6,
            9000.0,
            2500.0,
            "2026-10-01T00:00:00+02:00",
            "2027-05-01T00:00:00+02:00",
            False,
            True,
            False,
            points,
        )
        assert model.season_attributes(season) == {
            "output_energy": 9000.0,
            "electrical_energy": 2500.0,
            "period_start": "2026-10-01T00:00:00+02:00",
            "includes_estimated": False,
            "season_end": "2027-05-01T00:00:00+02:00",
            "complete": True,
            "ended": False,
            "seasons": points,
        }

    def test_corrected_period_has_the_defrost_attributes(self):
        period = engine.PeriodResult(
            62.0,
            18.5,
            3.1,
            "2026-11-01T00:00:00+01:00",
            False,
            4.6,
            3.35,
            "2026-11-18T10:00:00+01:00",
            True,
        )
        attributes = model.period_attributes(period)
        assert attributes["output_energy"] == 62.0
        assert attributes["defrost_energy"] == 4.6
        assert attributes["efficiency_uncorrected"] == 3.35
        assert attributes["defrost_since"] == "2026-11-18T10:00:00+01:00"

    def test_corrected_period_without_defrost_since_omits_it(self):
        period = engine.PeriodResult(
            62.0, 18.5, 3.1, "2026-11-19T00:00:00+01:00", False, 4.6, 3.35, None, True
        )
        attributes = model.period_attributes(period)
        assert attributes["defrost_energy"] == 4.6
        assert "defrost_since" not in attributes
        unknown = engine.PeriodResult(
            None, None, None, "2026-11-19T00:00:00+01:00", False, None, None, None, True
        )
        attributes = model.period_attributes(
            unknown
        )  # corrected but unknown: the keys stay, None
        assert attributes["defrost_energy"] is None
        assert "efficiency_uncorrected" in attributes

    def test_corrected_season_has_the_defrost_attributes(self):
        season = engine.SeasonResult(
            3.1,
            9000.0,
            2500.0,
            "2026-10-01T00:00:00+02:00",
            "2027-05-01T00:00:00+02:00",
            False,
            True,
            False,
            [],
            defrost_energy=40.0,
            efficiency_uncorrected=3.6,
            defrost_since="2026-11-18T10:00:00+01:00",
            corrected=True,
        )
        attributes = model.season_attributes(season)
        assert attributes["defrost_energy"] == 40.0
        assert attributes["efficiency_uncorrected"] == 3.6
        assert attributes["defrost_since"] == "2026-11-18T10:00:00+01:00"
        assert "seasons" in attributes

    def test_uncorrected_results_have_no_defrost_attributes(self):
        period = engine.PeriodResult(
            62.0, 18.5, 3.35, "2026-11-01T00:00:00+01:00", False
        )
        season = engine.SeasonResult(
            3.6,
            9000.0,
            2500.0,
            "2026-10-01T00:00:00+02:00",
            "2027-05-01T00:00:00+02:00",
            False,
            True,
            False,
            [],
        )
        for attributes in (
            model.period_attributes(period),
            model.season_attributes(season),
        ):
            for name in ("defrost_energy", "efficiency_uncorrected", "defrost_since"):
                assert name not in attributes

    def test_unknown_season_has_no_attributes(self):
        assert model.season_attributes(None) is None  # no valid dates
        nothing = engine.SeasonResult(
            None, None, None, None, None, False, False, False, []
        )
        assert model.season_attributes(nothing) is None  # no season has begun

    def test_series_attributes_are_on_today_and_month_to_date(self):
        assert dict(model.SERIES_ATTRIBUTES) == {
            "today": "daily",
            "month_to_date": "monthly",
        }


class TestSensorSource:
    """sensor.py imports Home Assistant, so its classes are read with ast."""

    def setup_method(self):
        tree = ast.parse((PACKAGE / "sensor.py").read_text(encoding="utf-8"))
        self.classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    def class_value(self, name, attribute):
        """The literal value of a class-level assignment, or None when the class has none."""
        for node in self.classes[name].body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == attribute for t in node.targets
            ):
                call = node.value
                if isinstance(call, ast.Call) and ast.unparse(call.func) == "frozenset":
                    return frozenset(ast.literal_eval(call.args[0]))
                return ast.literal_eval(call)
        return None

    def test_series_attributes_are_unrecorded_class_attributes(self):
        assert self.class_value("TodayEfficiencySensor", "_unrecorded_attributes") == {
            "daily"
        }
        assert self.class_value(
            "MonthToDateEfficiencySensor", "_unrecorded_attributes"
        ) == {"monthly"}
        # No other class (the base one) hides or records series: the base has none.
        assert self.class_value("EfficiencySensor", "_unrecorded_attributes") is None
        for name, attribute in (
            ("TodayEfficiencySensor", "daily"),
            ("MonthToDateEfficiencySensor", "monthly"),
        ):
            source = ast.unparse(self.classes[name])
            assert f"'{attribute}': service.{attribute}" in source
            assert (
                model.SERIES_ATTRIBUTES[
                    {"daily": "today", "monthly": "month_to_date"}[attribute]
                ]
                == attribute
            )

    def test_sensor_class_attributes(self):
        assert self.class_value("EfficiencySensor", "_attr_has_entity_name") is True
        assert (
            self.class_value("EfficiencySensor", "_attr_suggested_display_precision")
            == 2
        )
        source = (PACKAGE / "sensor.py").read_text(encoding="utf-8")
        assert "_attr_state_class = SensorStateClass.MEASUREMENT" in source
        assert "device_class" not in source
        assert (
            "_attr_native_unit_of_measurement = spec.unit" in source
        )  # None unless BTU/Wh

    def test_season_sensor_hides_its_points_from_the_recorder(self):
        assert self.class_value("SeasonEfficiencySensor", "_unrecorded_attributes") == {
            "seasons"
        }
        assert model.ATTR_SEASONS == "seasons"
        # The defrost attributes are scalars: recorded, in no unrecorded set (design D7).
        for name in (
            "TodayEfficiencySensor",
            "MonthToDateEfficiencySensor",
            "SeasonEfficiencySensor",
        ):
            assert not {
                model.ATTR_DEFROST_ENERGY,
                model.ATTR_EFFICIENCY_UNCORRECTED,
                model.ATTR_DEFROST_SINCE,
            } & self.class_value(name, "_unrecorded_attributes")
