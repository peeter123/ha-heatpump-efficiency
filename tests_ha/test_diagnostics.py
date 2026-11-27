"""Tests of the diagnostics of a loaded entry.

The statistics are synthetic (see ``helpers.py``).
"""

from datetime import timedelta

import pytest
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry

from custom_components.heatpump_efficiency import efficiency as eff
from custom_components.heatpump_efficiency.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.util import dt as dt_util

from .helpers import HEATING, SEASONS, add_entry, add_history, setup_entry

SECTIONS = {
    "metadata",
    "first_hours",
    "first_hours_read_at",
    "first_hours_failed",
    "updated_at",
    "windows",
    "tables",
    "energies",
    "defrost",
    "boundaries",
    "seasons",
    "errors",
}


async def test_the_diagnostics_hold_the_options_the_seasons_and_the_cached_data(
    frozen_hass,
):
    """The diagnostics of a loaded entry hold its options, its season dates, the errors and the cached data."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING, "seasons": SEASONS})
    await setup_entry(hass, entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["options"] == {"heating": HEATING, "seasons": SEASONS}
    assert diagnostics["season_dates"] == {
        "heating": ["10-01", "04-30"],
        "cooling": ["06-01", "09-30"],
    }
    assert diagnostics["season_dates_valid"] is True
    assert set(diagnostics) >= SECTIONS
    # Every read worked: an error is None.
    assert diagnostics["errors"]
    assert all(error is None for error in diagnostics["errors"].values())
    assert diagnostics["first_hours_failed"] == []
    assert set(diagnostics["first_hours"]) == set(
        HEATING["output"] + HEATING["electricity"]
    )
    assert diagnostics["tables"]["hour"]["ok"] is True
    assert diagnostics["updated_at"].startswith("2026-11-15T12:20:00")
    assert set(diagnostics["energies"]) == {"heating"}
    assert set(diagnostics["energies"]["heating"]) == set(eff.PERIODS)
    assert diagnostics["energies"]["heating"]["today"]["efficiency"] == pytest.approx(
        3.0
    )
    assert diagnostics["seasons"]["heating"]["efficiency"] == pytest.approx(3.0)
    assert diagnostics["seasons"]["heating"]["ended"] is False


async def test_the_diagnostics_without_season_dates_say_so(utc_hass, hass_client):
    """An entry without season dates has no season dates in its diagnostics, which the diagnostics platform serves.

    ha-test-harness: pytest_homeassistant components/diagnostics get_diagnostics_for_config_entry sets up the
    diagnostics component and downloads the entry's diagnostics with an authenticated client; the data is the
    return value of the integration's ``async_get_config_entry_diagnostics``.
    """
    hass = utc_hass
    # The clock is the real one here: the figures are not checked, only the shape of the data.
    last = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=1
    )
    await add_history(hass, HEATING, first=last - timedelta(days=3), last=last)
    entry = add_entry(hass, {"heating": HEATING})
    await setup_entry(hass, entry)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["options"] == {"heating": HEATING}
    assert diagnostics["season_dates"] is None
    assert diagnostics["season_dates_valid"] is False
    assert set(diagnostics) >= SECTIONS
    assert diagnostics["seasons"] == {}
    assert all(error is None for error in diagnostics["errors"].values())
