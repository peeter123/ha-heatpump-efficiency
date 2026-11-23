"""Coordinator of the Heat Pump Efficiency integration.

Thin glue: the per-update orchestration (reads, cache, periods, series) lives in
``engine.py`` (pure, unit-tested with a fake reader).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.statistics import (
    async_list_statistic_ids,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import efficiency as eff
from .const import DOMAIN
from .engine import EngineResult, EngineState, async_update, error_changes
from .issues import async_update_issues
from .validation import normalize_mapping

_LOGGER = logging.getLogger(__name__)


class RecorderReader:
    """The engine's reader on top of the recorder."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def read(
        self,
        source: str,
        statistic_ids: frozenset[str],
        window: eff.Window,
        units: Mapping[str, str],
        types: frozenset[str],
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        """Read one table on the recorder's database executor.

        recorder/statistics.py statistics_during_period(hass, start_time, end_time,
        statistic_ids, period, units, types): rows with start >= start_time and
        start < end_time (_generate_statistics_during_period_stmt), so the half-open
        window needs no adjustment. recorder/core.py Recorder.async_add_executor_job
        runs it on the recorder's executor; get_instance is helpers/recorder.py.
        Home Assistant aligns the start and end of a day or month read to local day
        and month boundaries (_statistics_during_period_with_session), which is also
        why the half-open window needs no adjustment.
        """
        return await get_instance(self._hass).async_add_executor_job(
            statistics_during_period,
            self._hass,
            window.start,
            window.end,
            set(statistic_ids),
            source,  # the period argument: month, day, hour or 5minute
            dict(units),
            set(types),
        )

    async def metadata(self, statistic_ids: frozenset[str]) -> Sequence[Mapping[str, Any]]:
        """recorder/statistics.py async_list_statistic_ids (served from cache on the loop)."""
        return await async_list_statistic_ids(self._hass, set(statistic_ids))


class HeatPumpEfficiencyCoordinator(DataUpdateCoordinator[EngineResult]):
    """One coordinator per entry; no polling, refreshed by the 5-minute tracker.

    helpers/update_coordinator.py DataUpdateCoordinator with update_interval=None
    schedules nothing itself. A failed read never raises UpdateFailed (the engine
    turns it into unknown periods), so the sensors stay available.
    """

    config_entry: HeatPumpEfficiencyConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HeatPumpEfficiencyConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=None,
        )
        self.mapping = normalize_mapping(entry.options)
        self.engine_state = EngineState()
        self._reader = RecorderReader(hass)

    async def _async_update_data(self) -> EngineResult:
        # util/dt.py utcnow() and get_default_time_zone() (the configured time zone).
        tz = dt_util.get_default_time_zone()
        previous = dict(self.engine_state.errors)
        result = await async_update(
            self.engine_state, self.mapping, self._reader, dt_util.utcnow(), tz
        )
        # Log a read error once when it appears or changes, and when it clears.
        for key, old, new in error_changes(previous, self.engine_state.errors):
            if new is not None:
                _LOGGER.warning("Statistics read '%s' failed: %s", key, new)
            elif old is not None:
                _LOGGER.info("Statistics read '%s' works again", key)
        # Design D7: the health check runs after every update, on the event loop. It
        # logs its own failures and never raises, so it cannot fail the update.
        async_update_issues(
            self.hass, self.config_entry, self.mapping, result, self.engine_state, tz
        )
        return result

    async def async_refresh_at(self, _now: datetime) -> None:
        """Tracker callback (helpers/event.py async_track_utc_time_change passes the time)."""
        await self.async_refresh()


# Evaluated lazily (PEP 695), so the class above may refer to it.
type HeatPumpEfficiencyConfigEntry = ConfigEntry[HeatPumpEfficiencyCoordinator]
