"""Fixtures for the Home Assistant tests."""

from unittest.mock import patch

import pytest

from custom_components.heatpump_efficiency import coordinator as coordinator_module
from homeassistant.components.recorder import statistics as recorder_statistics
from homeassistant.core import HomeAssistant

from .helpers import NOW, ReadFaults

# The test hass uses the configuration folder <ha_test_root>/testing_config, with ha_test_root defaulting to tests
# (pytest-homeassistant 2026.11.2 _paths.py configure, common.py get_test_config_dir); this repository does not have
# it. The loader mounts it with loader.async_setup -> async_mount_config_dir, then lists custom
# integrations by importing custom_components (ha-core 2026.11.2 homeassistant/loader.py _get_custom_components).
# Importing ours first, during collection, puts the repository's namespace package into sys.modules, so that
# import finds our custom_components/ whether or not the configuration folder exists. The ``hass`` fixture of
# pytest-homeassistant 2026.11.2 (plugins.py, with ``custom_integrations_enabled`` true by default) pops
# loader.DATA_CUSTOM_COMPONENTS, so the integration is found without a wrapper fixture. The import of the coordinator
# module above is that early import: it imports the package first.


@pytest.fixture
async def utc_hass(recorder_mock, hass: HomeAssistant) -> HomeAssistant:
    """A test instance with the test recorder, set to UTC, so that the periods of the tests follow UTC days.

    ha-test-harness: pytest-homeassistant 2026.11.2 plugins.py ``recorder_db_url`` asserts that the ``hass`` fixture is
    not set up yet, so ``recorder_mock`` must be requested before ``hass``; this fixture does that, and a test that
    uses it never requests ``hass`` or ``recorder_mock`` itself, or at least lists this fixture first. The time zone
    is set as common.py async_test_home_assistant does (``hass.config.async_set_time_zone``) and restored by it.
    """
    await hass.config.async_set_time_zone("UTC")
    return hass


@pytest.fixture
async def frozen_hass(utc_hass: HomeAssistant, freezer) -> HomeAssistant:
    """``utc_hass`` with the clock frozen at ``NOW``; the test moves it with ``freezer`` (list this fixture first).

    The ``freezer`` fixture is pytest-freezer's (a requirement of pytest-homeassistant), which freezes after the
    instance exists, as Home Assistant's own tests do.
    """
    freezer.move_to(NOW)
    return utc_hass


@pytest.fixture
def faults():
    """Let a test make the coordinator's statistics reads fail, and the reads work again.

    The coordinator module imports ``statistics_during_period`` and ``async_list_statistic_ids`` by name
    (coordinator.py), so patching its names changes only the coordinator's reads; the others (the config flow, the
    test's own) are untouched. The patched functions call the real ones unless a switch of ``ReadFaults`` is on.
    """
    switches = ReadFaults()
    real_read = recorder_statistics.statistics_during_period
    real_list = recorder_statistics.async_list_statistic_ids

    def read(hass, start_time, end_time, statistic_ids, period, units, types):
        # Runs on the recorder's executor (coordinator.py RecorderReader.read).
        if switches.fails(period, end_time):
            raise RuntimeError(f"{period} read failed")
        return real_read(
            hass, start_time, end_time, statistic_ids, period, units, types
        )

    async def list_ids(hass, statistic_ids=None, statistic_type=None):
        if switches.metadata:
            raise RuntimeError("metadata read failed")
        return await real_list(hass, statistic_ids, statistic_type)

    with (
        patch.object(coordinator_module, "statistics_during_period", read),
        patch.object(coordinator_module, "async_list_statistic_ids", list_ids),
    ):
        yield switches
