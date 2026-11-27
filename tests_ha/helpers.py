"""Helpers shared by the Home Assistant tests.

The data is synthetic: the statistic IDs are made up and the counters are hourly rows written into the throwaway
test recorder. A counter that grows by the same amount every hour makes every period of a service show the same
efficiency (the output rate over the electricity rate), whichever hours the period counts, so the tests can check
a figure without repeating the period arithmetic of ``tests/``.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.components.recorder.common import async_wait_recording_done

from custom_components.heatpump_efficiency import sensor_model
from custom_components.heatpump_efficiency.const import DOMAIN
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_import_statistics,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

NAME = "Test pump"

# The clock of the tests that freeze it: 20 minutes past noon (UTC, the time zone they set) on a Sunday in the middle
# of a month. Hourly rows exist from FIRST_HOUR to LAST_HOUR, the last complete hour before NOW, so every period of a
# service has data: today (12 hours), month to date, year to date and the rolling 12 months (from 1 October, the
# effective start, so the completed October is one range of the month table). The first hour counts 0 (see
# add_statistic), so a period that holds it counts one hour less than it has.
NOW = datetime(2026, 11, 15, 12, 20, tzinfo=UTC)
FIRST_HOUR = datetime(2026, 10, 1, tzinfo=UTC)
LAST_HOUR = datetime(2026, 11, 15, 11, tzinfo=UTC)

# External statistics ("test" is their source) have hourly rows only, so a service that maps them reads the hour
# table. The statistics of a recorder source (an entity ID) also have 5-minute rows in a real installation, which the
# test recorder does not compile: a service that maps only those is unknown until it has them.
HEATING = {
    "output": ["test:heating_output"],
    "electricity": ["test:heating_electricity"],
}
COOLING = {
    "output": ["test:cooling_output"],
    "electricity": ["test:cooling_electricity"],
}
HOT_WATER = {
    "output": ["sensor.test_hot_water_output"],
    "electricity": ["sensor.test_hot_water_electricity"],
}
SEASONS = {
    "heating_start": "10-01",
    "heating_end": "04-30",
    "cooling_start": "06-01",
    "cooling_end": "09-30",
}


def add_statistic(
    hass: HomeAssistant,
    statistic_id: str,
    *,
    unit: str = "kWh",
    unit_class: str | None = "energy",
    has_sum: bool = True,
    first: datetime | None = None,
    last: datetime | None = None,
    per_hour: float = 1.0,
) -> None:
    """Queue a synthetic statistic in the test recorder; wait for it with ``async_wait_recording_done``.

    Without ``first`` it is one hourly point, the hour before now, with a sum of ``per_hour``. With ``first`` and
    ``last`` (whole UTC hours) it is one row per hour from ``first`` to ``last`` whose running sum starts at 0 and grows
    by ``per_hour`` every hour, so the ``change`` of every row after the first is ``per_hour`` and the first hour counts
    0. A sum that starts at 0 gives the same energies whichever previous sum Home Assistant takes for the first row of
    a table (the engine's design D12 documents 0).

    An entity ID is a statistic of the source ``recorder`` and an ID with a colon (``domain:name``) an external
    statistic of the source ``domain``: recorder/statistics.py async_import_statistics and
    async_add_external_statistics (ha-core 2026.11.2) require exactly these combinations.
    """
    source = (
        statistic_id.split(":", maxsplit=1)[0] if ":" in statistic_id else "recorder"
    )
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE if has_sum else StatisticMeanType.ARITHMETIC,
        has_sum=has_sum,
        name=None,
        source=source,
        statistic_id=statistic_id,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )
    if first is None:
        starts = [
            dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
            - timedelta(hours=1)
        ]
    else:
        assert last is not None
        starts = [
            first + timedelta(hours=hour)
            for hour in range(int((last - first) / timedelta(hours=1)) + 1)
        ]
    if has_sum:
        first_sum = per_hour if first is None else 0.0
        points = [
            StatisticData(
                start=start,
                state=first_sum + per_hour * n,
                sum=first_sum + per_hour * n,
            )
            for n, start in enumerate(starts)
        ]
    else:
        points = [
            StatisticData(start=start, mean=1.0, min=1.0, max=1.0) for start in starts
        ]
    if ":" in statistic_id:
        async_add_external_statistics(hass, metadata, points)
    else:
        async_import_statistics(hass, metadata, points)


async def add_history(
    hass: HomeAssistant,
    *sections: dict[str, list[str]],
    output: float = 3.0,
    electricity: float = 1.0,
    first: datetime = FIRST_HOUR,
    last: datetime = LAST_HOUR,
) -> None:
    """Write hourly counters for the statistics of the given service sections and wait for the recorder.

    Every output statistic grows by ``output`` kWh per hour and every electricity statistic by ``electricity`` kWh, so
    a service shows an efficiency of ``output / electricity``.
    """
    for section in sections:
        for statistic_id in section["output"]:
            add_statistic(hass, statistic_id, first=first, last=last, per_hour=output)
        for statistic_id in section["electricity"]:
            add_statistic(
                hass, statistic_id, first=first, last=last, per_hour=electricity
            )
    # ha-test-harness: pytest_homeassistant components/recorder/common.py async_wait_recording_done
    await async_wait_recording_done(hass)


def add_entry(
    hass: HomeAssistant,
    options: dict[str, Any],
    *,
    version: int = 1,
    minor_version: int = 4,
) -> MockConfigEntry:
    """Add an entry with the stored mapping ``options`` (minor version 4, so no migration runs unless asked)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={"name": NAME},
        options=options,
        version=version,
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    return entry


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up an entry that was added with ``add_entry`` and check that it loaded."""
    # config_entries.py ConfigEntries.async_setup sets up the integration and the entry (ha-core 2026.11.2).
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def entity_id_of(
    hass: HomeAssistant, entry: MockConfigEntry, service: str, period: str
) -> str | None:
    """The entity ID of the sensor of a service and period (or season), found by its unique ID."""
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, sensor_model.unique_id(entry.entry_id, service, period)
    )


def state_of(
    hass: HomeAssistant, entry: MockConfigEntry, service: str, period: str
) -> State:
    """The state of the sensor of a service and period (or season); fails when the sensor does not exist."""
    entity_id = entity_id_of(hass, entry, service, period)
    assert entity_id is not None, (service, period)
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


async def fire_tracker(hass: HomeAssistant, freezer: Any, moment: datetime) -> None:
    """Move the frozen clock to ``moment``, fire the timers that are due, and wait for the refresh they start.

    ha-test-harness: pytest_homeassistant common.py async_fire_time_changed runs every timer that is due at the frozen
    time plus half a second. ha-core 2026.11.2 helpers/event.py _TrackUTCTimeChange._pattern_time_change_listener
    runs the action as a background job, so the wait includes the background tasks
    (core.py HomeAssistant.async_block_till_done).
    """
    freezer.move_to(moment)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


class ReadFaults:
    """Switches that make the coordinator's statistics reads fail (see the ``faults`` fixture)."""

    def __init__(self) -> None:
        """Start with every read working."""
        self.months = False
        self.recent = False
        self.metadata = False

    def fails(self, period: str, end: datetime | None) -> bool:
        """Whether a ``statistics_during_period`` read of ``period`` ending at ``end`` fails.

        ``months``: the read of completed months, which ends at the start of a month (local midnight, UTC here); the
        first-hours read of the month table ends at now (engine.py first_hours_window) and is left alone, as the
        engine tests do. ``recent``: every read of the 5-minute table.
        """
        if period == "5minute":
            return self.recent
        if period == "month" and end is not None:
            return self.months and (end.hour, end.minute, end.second) == (0, 0, 0)
        return False
