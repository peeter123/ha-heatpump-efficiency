"""The Heat Pump Efficiency integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_utc_time_change

from .const import PLATFORMS
from .coordinator import HeatPumpEfficiencyConfigEntry, HeatPumpEfficiencyCoordinator
from .seasons import default_seasons
from .validation import with_default_seasons, with_defrost_moved, without_planned

# 5-minute statistics are compiled at second 10 of every fifth minute (UTC)
# (recorder/core.py); reading at second 30 leaves time for the commit.
UPDATE_MINUTES = range(0, 60, 5)
UPDATE_SECOND = 30


async def async_migrate_entry(hass: HomeAssistant, entry: HeatPumpEfficiencyConfigEntry) -> bool:
    """Migrate an entry: minor 2 adds the season dates, minor 3 moves the planned defrost slot,
    minor 4 drops the planned section."""
    # config_entries.py ConfigEntry.async_migrate calls this when the entry's minor
    # version differs from ConfigFlow.MINOR_VERSION; it already refuses a higher major version.
    if entry.version == 1 and entry.minor_version < 4:
        options = dict(entry.options)
        if entry.minor_version < 2:
            # core_config.py Config.latitude (the season defaults)
            options = with_default_seasons(options, default_seasons(hass.config.latitude))
        if entry.minor_version < 3:
            options = with_defrost_moved(options)
        # After the defrost step: it reads the planned section's defrost slot first.
        options = without_planned(options)
        # config_entries.py ConfigEntries.async_update_entry(entry, options=..., minor_version=...)
        # stores the result once for all steps; no reload is triggered.
        hass.config_entries.async_update_entry(entry, options=options, minor_version=4)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HeatPumpEfficiencyConfigEntry) -> None:
    """Set up a heat pump from a config entry."""
    coordinator = HeatPumpEfficiencyCoordinator(hass, entry)
    # update_coordinator.py: raises ConfigEntryNotReady when the first refresh fails.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # helpers/event.py async_track_utc_time_change returns the cancel callback.
    entry.async_on_unload(
        async_track_utc_time_change(
            hass, coordinator.async_refresh_at, minute=UPDATE_MINUTES, second=UPDATE_SECOND
        )
    )
    # config_entries.py ConfigEntries.async_forward_entry_setups(entry, platforms)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: HeatPumpEfficiencyConfigEntry) -> None:
    """Unload a config entry."""
    # config_entries.py ConfigEntry.async_unload: a failure is an exception and the
    # result is only checked for None; async_unload_platforms_or_raise raises on failure.
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
