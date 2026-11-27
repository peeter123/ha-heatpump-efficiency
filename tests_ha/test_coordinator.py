"""Tests of the coordinator and its recorder reader, and of the sensors' availability while a read fails.

The statistics are synthetic (see ``helpers.py``). A failed read is injected with the ``faults`` fixture, which makes
the coordinator's own calls of ``statistics_during_period`` or ``async_list_statistic_ids`` raise; the engine's
handling of every kind of failed read is checked in ``tests/test_engine.py``, and these tests check the glue: the log
and the state of the sensors in Home Assistant.
"""

from datetime import UTC, datetime, timedelta
import logging

import pytest
from pytest_homeassistant.components.recorder.common import async_wait_recording_done

from custom_components.heatpump_efficiency import efficiency as eff, sensor_model
from custom_components.heatpump_efficiency.coordinator import RecorderReader
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .helpers import (
    FIRST_HOUR,
    HEATING,
    HOT_WATER,
    LAST_HOUR,
    NOW,
    SEASONS,
    add_entry,
    add_history,
    add_statistic,
    fire_tracker,
    setup_entry,
    state_of,
)

LOGGER = "custom_components.heatpump_efficiency.coordinator"

# The first mark of the 5-minute tracker after the setup at NOW (12:20:00) is 12:20:30, then every five minutes.
FIRST_MARK = NOW + timedelta(seconds=30)
FIGURE = 3.0  # the efficiency of every period: 3 kWh of output per kWh of electricity (helpers.add_history)


def mark(number):
    """The ``number``-th mark of the tracker after the setup (0: 12:20:30, 1: 12:25:30, ...)."""
    return FIRST_MARK + timedelta(minutes=5 * number)


def read_lines(caplog):
    """The info lines about a statistics read that the coordinator logged, in order."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER
        and record.levelno == logging.INFO
        and record.getMessage().startswith("Statistics read")
    ]


def states(hass, entry, service):
    """The states of the four period sensors of a service, by period."""
    return {p: state_of(hass, entry, service, p).state for p in eff.PERIODS}


def assert_figures(hass, entry, service, periods=eff.PERIODS):
    """Check that the given period sensors of a service show the figure."""
    shown = states(hass, entry, service)
    for period in periods:
        assert float(shown[period]) == pytest.approx(FIGURE), (period, shown)


async def test_the_reader_reads_the_window_in_kwh_and_the_requested_types(utc_hass):
    """The reader passes the half-open window, the unit and the types to ``statistics_during_period``."""
    hass = utc_hass
    statistic_id = "test:meter_wh"
    # A counter in Wh that grows by 1000 Wh every hour: 1 kWh per row in the unit of the read.
    add_statistic(
        hass, statistic_id, unit="Wh", first=FIRST_HOUR, last=LAST_HOUR, per_hour=1000.0
    )
    await async_wait_recording_done(hass)
    reader = RecorderReader(hass)
    window = eff.Window(
        datetime(2026, 11, 15, 8, tzinfo=UTC), datetime(2026, 11, 15, 11, tzinfo=UTC)
    )

    changes = await reader.read(
        "hour",
        frozenset({statistic_id}),
        window,
        {"energy": "kWh"},
        frozenset({"change"}),
    )
    sums = await reader.read(
        "hour",
        frozenset({statistic_id}),
        window,
        {"energy": "kWh"},
        frozenset({"sum"}),
    )

    # recorder/statistics.py statistics_during_period (ha-core 2026.11.2): the rows with start >= start_time and
    # start < end_time, with epoch seconds, so the rows at 08:00, 09:00 and 10:00 and not the one at 11:00.
    rows = changes[statistic_id]
    starts = [row["start"] for row in rows]
    assert starts == [
        datetime(2026, 11, 15, hour, tzinfo=UTC).timestamp() for hour in (8, 9, 10)
    ]
    assert [row["end"] for row in rows] == [start + 3600 for start in starts]
    assert [row["change"] for row in rows] == pytest.approx([1.0, 1.0, 1.0])
    assert all("sum" not in row for row in rows)
    rows = sums[statistic_id]
    assert all("change" not in row for row in rows)
    assert rows[1]["sum"] - rows[0]["sum"] == pytest.approx(1.0)  # kWh, not Wh


async def test_the_reader_lists_the_metadata_of_the_statistics_that_exist(utc_hass):
    """The metadata of the asked statistics names their source, and a statistic that does not exist is absent."""
    hass = utc_hass
    add_statistic(hass, "test:meter", first=FIRST_HOUR, last=LAST_HOUR)
    await async_wait_recording_done(hass)

    metadata = await RecorderReader(hass).metadata(
        frozenset({"test:meter", "test:never_written"})
    )

    assert [m["statistic_id"] for m in metadata] == ["test:meter"]
    assert metadata[0]["source"] == "test"
    assert metadata[0]["has_sum"] is True
    assert metadata[0]["unit_class"] == "energy"


async def test_month_read_fails_for_one_update(frozen_hass, freezer, faults):
    """Scenario "Month read fails for one update": year to date and rolling 12 months are unavailable, then show.

    The read of completed months fails at the setup and works at the next update. Today and month to date, which
    do not use the month table, stay available throughout.
    """
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})
    faults.months = True

    await setup_entry(hass, entry)

    shown = states(hass, entry, "heating")
    assert shown["year_to_date"] == STATE_UNAVAILABLE
    assert shown["rolling_12_months"] == STATE_UNAVAILABLE
    assert_figures(hass, entry, "heating", ("today", "month_to_date"))

    faults.months = False
    await fire_tracker(hass, freezer, mark(0))

    assert_figures(hass, entry, "heating")


async def test_recent_read_fails(frozen_hass, freezer, faults, caplog):
    """Scenario "Recent read fails": the services that read 5-minute statistics are unavailable, the others are not.

    Heating maps external statistics, which have hourly rows only (its service reads the hour table); Hot water maps
    statistics of the recorder, which a real installation also has as 5-minute statistics. The test recorder has no
    5-minute rows, so Hot water is unknown while every read works.
    """
    hass = frozen_hass
    await add_history(hass, HEATING, HOT_WATER)
    entry = add_entry(hass, {"heating": HEATING, "hot_water": HOT_WATER})
    await setup_entry(hass, entry)
    assert_figures(hass, entry, "heating")
    assert set(states(hass, entry, "hot_water").values()) == {STATE_UNKNOWN}

    faults.recent = True
    await fire_tracker(hass, freezer, mark(0))

    assert set(states(hass, entry, "hot_water").values()) == {STATE_UNAVAILABLE}
    assert_figures(
        hass, entry, "heating"
    )  # its cached completed days and months cover its statistics

    faults.recent = False
    await fire_tracker(hass, freezer, mark(1))

    assert set(states(hass, entry, "hot_water").values()) == {STATE_UNKNOWN}
    assert_figures(hass, entry, "heating")
    assert read_lines(caplog) == [
        "Statistics read '5minute' failed: RuntimeError: 5minute read failed",
        "Statistics read '5minute' works again",
    ]
    assert not [
        r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING
    ]


async def test_a_failed_read_is_logged_once_at_info_level(
    frozen_hass, freezer, faults, caplog
):
    """Scenario "Logged once": three failed updates in a row give one info line, and the recovery one more."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})
    faults.months = True

    await setup_entry(hass, entry)  # the first failed update
    await fire_tracker(hass, freezer, mark(0))  # the second
    await fire_tracker(hass, freezer, mark(1))  # the third
    assert read_lines(caplog) == [
        "Statistics read 'month' failed: RuntimeError: month read failed"
    ]

    faults.months = False
    await fire_tracker(hass, freezer, mark(2))

    assert read_lines(caplog) == [
        "Statistics read 'month' failed: RuntimeError: month read failed",
        "Statistics read 'month' works again",
    ]
    # The failure is not a warning: the sensors say it (unavailable), and the info line is for the log.
    assert not [
        r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING
    ]


async def test_metadata_never_read_makes_every_sensor_unavailable(
    frozen_hass, freezer, faults, caplog
):
    """Scenario "Metadata never read": every sensor of the entry is unavailable until the metadata is read."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    # With season dates, so that the Heating season sensor has a season to be unavailable for.
    entry = add_entry(
        hass, {"heating": HEATING, "hot_water": HOT_WATER, "seasons": SEASONS}
    )
    faults.metadata = True

    await setup_entry(hass, entry)

    specs = sensor_model.sensor_specs(entry.entry_id, entry.options)
    assert (
        len(specs) == 9
    )  # Heating: four periods and a season; Hot water: four periods
    for spec in specs:
        shown = state_of(hass, entry, spec.service, spec.period).state
        assert shown == STATE_UNAVAILABLE, spec

    faults.metadata = False
    await fire_tracker(hass, freezer, mark(0))

    assert_figures(hass, entry, "heating")
    assert set(states(hass, entry, "hot_water").values()) == {STATE_UNKNOWN}
    assert read_lines(caplog) == [
        "Statistics read 'metadata' failed: RuntimeError: metadata read failed",
        "Statistics read 'metadata' works again",
    ]


async def test_a_later_metadata_failure_keeps_the_sensors_available(
    frozen_hass, freezer, faults, caplog
):
    """Scenario "Later metadata failure": after one good read the sensors use the last metadata and stay available."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING})
    await setup_entry(hass, entry)
    assert_figures(hass, entry, "heating")

    faults.metadata = True
    await fire_tracker(hass, freezer, mark(0))

    assert_figures(hass, entry, "heating")
    assert read_lines(caplog) == [
        "Statistics read 'metadata' failed: RuntimeError: metadata read failed"
    ]

    faults.metadata = False
    await fire_tracker(hass, freezer, mark(1))

    assert_figures(hass, entry, "heating")
    assert read_lines(caplog)[-1] == "Statistics read 'metadata' works again"


async def test_unknown_is_not_unavailable(frozen_hass):
    """Scenario "Unknown is not unavailable": with every read working, a period without a figure is unknown.

    Heating maps statistics that do not exist, and Hot water statistics of the recorder that have no 5-minute rows.
    """
    hass = frozen_hass
    await add_history(hass, HOT_WATER)
    entry = add_entry(hass, {"heating": HEATING, "hot_water": HOT_WATER})

    await setup_entry(hass, entry)

    for spec in sensor_model.sensor_specs(entry.entry_id, entry.options):
        shown = state_of(hass, entry, spec.service, spec.period).state
        assert shown == STATE_UNKNOWN, spec
