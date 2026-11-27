"""Tests of the sensors: their state, unit and attributes, the season sensor and the removal of stale sensors.

The statistics are synthetic (see ``helpers.py``): every service has counters that grow by the same amount every hour,
so every period of a service shows the same efficiency, and its energies follow from the hours the period counts.
"""

import pytest

from custom_components.heatpump_efficiency import efficiency as eff
from custom_components.heatpump_efficiency.const import DOMAIN
from custom_components.heatpump_efficiency.engine import EngineResult
from custom_components.heatpump_efficiency.sensor import (
    EfficiencySensor,
    MonthToDateEfficiencySensor,
    SeasonEfficiencySensor,
    TodayEfficiencySensor,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers import entity_registry as er

from .helpers import (
    COOLING,
    HEATING,
    HOT_WATER,
    NOW,
    SEASONS,
    add_entry,
    add_history,
    entity_id_of,
    setup_entry,
    state_of,
)

# The counters start on 1 October 00:00 and the last complete hour at NOW is 11:00 on 15 November: today has 12 hours,
# month to date 14 days and 12 hours, and year to date and the rolling 12 months 1092 hours, of which the first counts 0
# (helpers.py add_statistic): the energies below are in hours of one kWh per hour of electricity.
HOURS = {
    "today": 12,
    "month_to_date": 14 * 24 + 12,
    "year_to_date": 31 * 24 + 14 * 24 + 12 - 1,
    "rolling_12_months": 31 * 24 + 14 * 24 + 12 - 1,
}


async def test_the_period_sensors_show_the_efficiency_and_the_energies(frozen_hass):
    """Each period sensor shows its efficiency, with the energies and the start of its period as attributes."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})

    await setup_entry(hass, entry)

    starts = {
        "today": "2026-11-15",
        "month_to_date": "2026-11-01",
        "year_to_date": "2026-10-01",  # cut by the first statistics hour
        "rolling_12_months": "2026-10-01",
    }
    for period, hours in HOURS.items():
        state = state_of(hass, entry, "heating", period)
        assert float(state.state) == pytest.approx(3.0), period
        assert state.attributes["state_class"] == "measurement"
        assert ATTR_UNIT_OF_MEASUREMENT not in state.attributes
        assert state.attributes["output_energy"] == pytest.approx(3.0 * hours), period
        assert state.attributes["electrical_energy"] == pytest.approx(1.0 * hours)
        assert state.attributes["period_start"].startswith(starts[period]), period
        assert state.attributes["includes_estimated"] is False
        # No defrost statistics: no correction attributes.
        assert "defrost_energy" not in state.attributes


async def test_today_and_month_to_date_carry_their_series(frozen_hass):
    """Today carries the daily series and month to date the monthly series, as points with an efficiency."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})

    await setup_entry(hass, entry)

    today = state_of(hass, entry, "heating", "today").attributes
    month = state_of(hass, entry, "heating", "month_to_date").attributes
    assert "monthly" not in today
    assert "daily" not in month
    daily, monthly = today["daily"], month["monthly"]
    assert daily[-1]["start"].startswith("2026-11-15")
    assert monthly[-1]["start"].startswith("2026-11-01")
    assert [p["efficiency"] for p in daily + monthly] == pytest.approx(
        [3.0] * (len(daily) + len(monthly))
    )
    for period in ("year_to_date", "rolling_12_months"):
        attributes = state_of(hass, entry, "heating", period).attributes
        assert "daily" not in attributes
        assert "monthly" not in attributes


def test_the_series_and_season_attributes_are_not_recorded():
    """The series attributes are in the unrecorded attributes, so they do not count against the recorder's limit.

    ha-core 2026.11.2 helpers/entity.py Entity.__init_subclass__ combines ``_unrecorded_attributes`` of a class with
    the component's into ``__combined_unrecorded_attributes``, which Entity.__async_calculate_state passes to the
    state machine as ``unrecorded_attributes``.
    """
    combined = "_Entity__combined_unrecorded_attributes"
    assert "daily" in getattr(TodayEfficiencySensor, combined)
    assert "monthly" in getattr(MonthToDateEfficiencySensor, combined)
    assert "seasons" in getattr(SeasonEfficiencySensor, combined)
    # The series of one sensor is not hidden on the others.
    assert "daily" not in getattr(MonthToDateEfficiencySensor, combined)
    assert "monthly" not in getattr(TodayEfficiencySensor, combined)
    for name in ("daily", "monthly", "seasons"):
        assert name not in getattr(EfficiencySensor, combined)


@pytest.mark.parametrize(
    ("section", "unit", "figure"),
    [
        pytest.param({**COOLING}, None, 3.0, id="w_per_w"),
        pytest.param(
            {**COOLING, "unit": "btu_per_wh"}, "BTU/Wh", 10.24, id="btu_per_wh"
        ),
    ],
)
async def test_cooling_has_the_unit_and_the_factor_of_its_setting(
    frozen_hass, section, unit, figure
):
    """Cooling shows W/W as a plain figure and BTU/Wh with its unit and the factor 3.412142 (2 decimals)."""
    hass = frozen_hass
    await add_history(hass, COOLING)
    entry = add_entry(hass, {"cooling": section})

    await setup_entry(hass, entry)

    for period in eff.PERIODS:
        state = state_of(hass, entry, "cooling", period)
        assert float(state.state) == pytest.approx(figure), period
        assert state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == unit, period


async def test_the_season_sensor_shows_the_running_season(frozen_hass):
    """The season sensor shows the running season with its dates, its flags and its points."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING, "seasons": SEASONS})

    await setup_entry(hass, entry)

    state = state_of(hass, entry, "heating", "heating_season")
    attributes = state.attributes
    assert float(state.state) == pytest.approx(3.0)
    assert attributes["period_start"].startswith("2026-10-01")
    assert attributes["season_end"].startswith("2027-05-01")  # the day after 30 April
    assert attributes["complete"] is True  # the counters start with the season
    assert attributes["ended"] is False
    assert attributes["output_energy"] == pytest.approx(3.0 * HOURS["year_to_date"])
    assert attributes["electrical_energy"] == pytest.approx(HOURS["year_to_date"])
    (point,) = attributes["seasons"]
    assert point["efficiency"] == pytest.approx(3.0)
    assert point["start"].startswith("2026-10-01")


async def test_a_season_that_has_not_begun_is_unknown_without_attributes(frozen_hass):
    """A season sensor without a season in the history is unknown and carries no attributes."""
    hass = frozen_hass
    await add_history(hass, COOLING)
    entry = add_entry(hass, {"cooling": COOLING, "seasons": SEASONS})

    await setup_entry(hass, entry)

    # The cooling season ended on 30 September, before the first statistics hour of the counters.
    state = state_of(hass, entry, "cooling", "cooling_season")
    assert state.state == STATE_UNKNOWN
    assert "seasons" not in state.attributes
    assert "period_start" not in state.attributes


async def test_a_sensor_without_a_result_is_available_and_unknown(frozen_hass):
    """Without a result for its service, a sensor keeps the coordinator's availability and shows unknown.

    Design D5 of reach-silver-quality-scale: a missing result leaves ``super().available``, which is the coordinator's
    ``last_update_success`` (ha-core 2026.11.2 helpers/update_coordinator.py CoordinatorEntity.available).
    """
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING, "seasons": SEASONS})
    await setup_entry(hass, entry)
    assert float(state_of(hass, entry, "heating", "today").state) == pytest.approx(3.0)

    empty = EngineResult({}, NOW, eff.CacheActions(frozenset()), {}, frozenset(), ())
    entry.runtime_data.async_set_updated_data(empty)
    await hass.async_block_till_done()

    for period in (*eff.PERIODS, "heating_season"):
        state = state_of(hass, entry, "heating", period)
        assert state.state == STATE_UNKNOWN, period
        assert "output_energy" not in state.attributes, period
    assert "daily" not in state_of(hass, entry, "heating", "today").attributes


async def test_a_failed_coordinator_makes_every_sensor_unavailable(frozen_hass):
    """A coordinator that failed to update makes its sensors unavailable, as ``super().available`` says."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})
    await setup_entry(hass, entry)

    coordinator = entry.runtime_data
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    for period in eff.PERIODS:
        assert state_of(hass, entry, "heating", period).state == STATE_UNAVAILABLE


async def test_the_sensors_of_a_service_that_is_no_longer_mapped_are_removed(
    frozen_hass,
):
    """After an options change that unmaps a service, its sensors leave the entity registry; the others stay."""
    hass = frozen_hass
    await add_history(hass, HEATING, HOT_WATER)
    entry = add_entry(hass, {"heating": HEATING, "hot_water": HOT_WATER})
    await setup_entry(hass, entry)
    hot_water_entity = entity_id_of(hass, entry, "hot_water", "today")
    assert hot_water_entity is not None

    hass.config_entries.async_update_entry(entry, options={"heating": HEATING})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    for period in eff.PERIODS:
        assert entity_id_of(hass, entry, "hot_water", period) is None
        assert entity_id_of(hass, entry, "heating", period) is not None
    assert registry.async_get(hot_water_entity) is None
    remaining = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {e.platform for e in remaining} == {DOMAIN}
    assert len(remaining) == 5  # Heating: four periods and its season
