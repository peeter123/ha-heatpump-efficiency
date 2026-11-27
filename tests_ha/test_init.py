"""Tests of the setup, the 5-minute refresh, the unload, the reload and the migration of an entry.

The statistics are synthetic (see ``helpers.py``): made-up statistic IDs written into the throwaway test recorder.
"""

from datetime import timedelta

import pytest

from custom_components.heatpump_efficiency import async_migrate_entry, sensor_model
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from .helpers import (
    COOLING,
    HEATING,
    NOW,
    SEASONS,
    add_entry,
    add_history,
    entity_id_of,
    fire_tracker,
    setup_entry,
    state_of,
)

DEFROST = "sensor.test_defrost_heat"


async def test_setup_creates_the_sensors_of_each_mapped_service(frozen_hass):
    """Setup loads the entry with four period sensors and a season sensor per mapped service, and no others."""
    hass = frozen_hass
    await add_history(hass, HEATING, COOLING)
    entry = add_entry(
        hass, {"heating": HEATING, "cooling": COOLING, "seasons": SEASONS}
    )

    await setup_entry(hass, entry)

    specs = sensor_model.sensor_specs(entry.entry_id, entry.options)
    assert len(specs) == 10  # Heating and Cooling: four periods and a season each
    registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {e.unique_id for e in registered} == {s.unique_id for s in specs}
    for spec in specs:
        assert state_of(hass, entry, spec.service, spec.period) is not None
    assert entity_id_of(hass, entry, "hot_water", "today") is None
    assert entity_id_of(hass, entry, "overall", "today") is None


async def test_the_tracker_refreshes_every_five_minutes(frozen_hass, freezer):
    """The coordinator refreshes at second 30 of every fifth minute, and at no other time."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})
    await setup_entry(hass, entry)
    coordinator = entry.runtime_data
    assert coordinator.engine_state.updated_at == NOW  # the first refresh of the setup

    first = NOW + timedelta(seconds=30)  # 12:20:30
    await fire_tracker(hass, freezer, first)
    assert coordinator.engine_state.updated_at == first

    # Between two marks nothing is due.
    await fire_tracker(hass, freezer, NOW + timedelta(minutes=2))
    assert coordinator.engine_state.updated_at == first

    second = NOW + timedelta(minutes=5, seconds=30)  # 12:25:30
    await fire_tracker(hass, freezer, second)
    assert coordinator.engine_state.updated_at == second


async def test_unload_removes_the_entry_and_stops_the_refreshes(frozen_hass, freezer):
    """Unloading the entry cancels the tracker, so the coordinator is not refreshed any more."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})
    await setup_entry(hass, entry)
    coordinator = entry.runtime_data

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    await fire_tracker(hass, freezer, NOW + timedelta(minutes=5, seconds=30))
    assert coordinator.engine_state.updated_at == NOW


async def test_an_options_change_reloads_the_entry(frozen_hass):
    """Saving new options in the options flow reloads the entry, which then has the sensors of the new mapping."""
    hass = frozen_hass
    await add_history(hass, HEATING, COOLING)
    entry = add_entry(hass, {"heating": HEATING})
    await setup_entry(hass, entry)
    before = entry.runtime_data
    assert entity_id_of(hass, entry, "cooling", "today") is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"heating": HEATING, "cooling": COOLING}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"heating": HEATING, "cooling": COOLING}
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not before
    assert entity_id_of(hass, entry, "cooling", "today") is not None
    assert state_of(hass, entry, "heating", "today") is not None


@pytest.mark.parametrize(
    ("minor_version", "stored", "migrated"),
    [
        pytest.param(
            1,
            {"heating": HEATING, "planned": {"defrost_heat": DEFROST}},
            {"heating": {**HEATING, "defrost_heat": [DEFROST]}, "seasons": SEASONS},
            id="minor_1",
        ),
        pytest.param(
            2,
            {
                "heating": HEATING,
                "seasons": SEASONS,
                "planned": {"defrost_heat": DEFROST},
            },
            {"heating": {**HEATING, "defrost_heat": [DEFROST]}, "seasons": SEASONS},
            id="minor_2",
        ),
        pytest.param(
            3,
            {
                "heating": HEATING,
                "seasons": SEASONS,
                "planned": {"price_source": "sensor.test_price"},
            },
            {"heating": HEATING, "seasons": SEASONS},
            id="minor_3",
        ),
    ],
)
async def test_an_entry_of_an_earlier_minor_version_is_migrated_on_setup(
    utc_hass, minor_version, stored, migrated
):
    """Setup migrates an entry of minor version 1, 2 or 3 to 4 and loads it with the migrated options."""
    hass = utc_hass
    # pytest-homeassistant 2026.11.2 common.py async_test_home_assistant sets the latitude to 32.87336, north of the
    # equator, so a missing season section gets the northern defaults, which are SEASONS (seasons.py default_seasons).
    assert hass.config.latitude > 0
    entry = add_entry(hass, stored, minor_version=minor_version)

    await setup_entry(hass, entry)

    assert entry.version == 1
    assert entry.minor_version == 4
    assert dict(entry.options) == migrated


@pytest.mark.parametrize(
    ("version", "minor_version"),
    [pytest.param(2, 1, id="other_major_version"), pytest.param(1, 4, id="current")],
)
async def test_the_migration_leaves_other_entries_alone(
    utc_hass, version, minor_version
):
    """An entry that is not of major version 1 with a lower minor version keeps its options and versions."""
    hass = utc_hass
    stored = {"heating": HEATING, "planned": {"defrost_heat": DEFROST}}
    entry = add_entry(hass, stored, version=version, minor_version=minor_version)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == version
    assert entry.minor_version == minor_version
    assert dict(entry.options) == stored
