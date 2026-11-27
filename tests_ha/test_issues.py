"""Tests of the repair issues of unhealthy statistics, through Home Assistant's issue registry.

The statistics are synthetic (see ``helpers.py``). The rules (which statistic gets which issue) are checked in
``tests/test_repairs.py``; these tests check the glue: the issues that reach the registry, with their fields, their
deletion, and a registry failure that must not fail the update.
"""

from datetime import timedelta
import logging
from unittest.mock import patch

from custom_components.heatpump_efficiency.const import DOMAIN
from custom_components.heatpump_efficiency.repairs_model import issue_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .helpers import (
    HEATING,
    HOT_WATER,
    LAST_HOUR,
    NAME,
    NOW,
    add_entry,
    add_history,
    fire_tracker,
    setup_entry,
)

MISSING = "test:missing_electricity"
HEATING_MISSING = {"output": HEATING["output"], "electricity": [MISSING]}
ISSUES_LOGGER = "custom_components.heatpump_efficiency.issues"


def issues_of(hass, entry):
    """The issues of the entry in the issue registry, by statistic ID."""
    prefix = f"{entry.entry_id}_"
    return {
        issue.issue_id.removeprefix(prefix): issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.config_entry_id == entry.entry_id
    }


async def test_a_missing_statistic_gets_a_repair_issue(frozen_hass):
    """A mapped statistic that does not exist gets an issue with its fields, and a healthy one gets none."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING_MISSING})

    await setup_entry(hass, entry)

    found = issues_of(hass, entry)
    assert set(found) == {MISSING}
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, issue_id(entry.entry_id, MISSING)
    )
    assert issue is found[MISSING]
    assert issue.translation_key == "statistic_missing"
    assert issue.translation_placeholders == {
        "heat_pump": NAME,
        "statistic_id": MISSING,
    }
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.config_entry_id == entry.entry_id


async def test_a_statistic_without_recent_rows_gets_a_stale_issue(frozen_hass):
    """Statistics of the recorder without 5-minute rows are stale without rows; the issue has no last time."""
    hass = frozen_hass
    await add_history(hass, HOT_WATER)
    entry = add_entry(hass, {"hot_water": HOT_WATER})

    await setup_entry(hass, entry)

    found = issues_of(hass, entry)
    assert set(found) == set(HOT_WATER["output"] + HOT_WATER["electricity"])
    for statistic_id, issue in found.items():
        assert issue.translation_key == "statistic_stale_no_rows"
        assert issue.translation_placeholders == {
            "heat_pump": NAME,
            "statistic_id": statistic_id,
        }


async def test_a_stale_statistic_names_the_time_of_its_last_statistics(frozen_hass):
    """A statistic whose last row ended more than two hours ago gets a stale issue with the local time of that row."""
    hass = frozen_hass
    # Rows up to the hour that starts at 07:00, so the last row ends at 08:00, 4 hours 20 minutes before NOW.
    await add_history(hass, HEATING, last=LAST_HOUR.replace(hour=7))
    entry = add_entry(hass, {"heating": HEATING})

    await setup_entry(hass, entry)

    found = issues_of(hass, entry)
    assert set(found) == set(HEATING["output"] + HEATING["electricity"])
    for statistic_id, issue in found.items():
        assert issue.translation_key == "statistic_stale"
        assert issue.translation_placeholders == {
            "heat_pump": NAME,
            "statistic_id": statistic_id,
            "last_statistics": "2026-11-15 08:00",  # UTC, the time zone of the tests
        }


async def test_an_issue_is_deleted_when_its_statistic_is_healthy_again(
    frozen_hass, freezer
):
    """The issue of a missing statistic is deleted at the first update after the statistic has data."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING_MISSING})
    await setup_entry(hass, entry)
    assert set(issues_of(hass, entry)) == {MISSING}

    await add_history(hass, {"output": [], "electricity": [MISSING]})
    await fire_tracker(hass, freezer, NOW + timedelta(seconds=30))

    assert issues_of(hass, entry) == {}


async def test_the_issue_of_a_statistic_that_is_no_longer_mapped_is_deleted(
    frozen_hass,
):
    """After an options change that drops the statistic, the reloaded entry deletes its issue."""
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING_MISSING})
    await setup_entry(hass, entry)
    assert set(issues_of(hass, entry)) == {MISSING}

    hass.config_entries.async_update_entry(entry, options={"heating": HEATING})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert issues_of(hass, entry) == {}


async def test_a_failing_issue_registry_does_not_fail_the_update(frozen_hass, caplog):
    """A failure of the issue registry is logged and the update still succeeds, with its sensors working.

    helpers/issue_registry.py async_create_issue raises HomeAssistantError, for example for an unknown config entry
    (ha-core 2026.11.2); issues.py logs it instead of failing the update (design D7). The mock stands for the module:
    its ``async_get(hass).issues.items()`` is an empty iteration and ``async_create_issue`` raises.
    """
    hass = frozen_hass
    await add_history(hass, HEATING)
    entry = add_entry(hass, {"heating": HEATING_MISSING})

    # Only the issue registry module as issues.py sees it is replaced, so nothing else of Home Assistant is affected.
    with patch("custom_components.heatpump_efficiency.issues.ir") as registry:
        registry.async_create_issue.side_effect = HomeAssistantError("no registry")
        await setup_entry(hass, entry)

    assert entry.runtime_data.last_update_success is True
    assert issues_of(hass, entry) == {}
    errors = [
        record
        for record in caplog.records
        if record.name == ISSUES_LOGGER and record.levelno == logging.ERROR
    ]
    assert [record.getMessage() for record in errors] == [
        f"Updating the repair issues of {NAME} failed"
    ]
    assert errors[0].exc_info is not None
