"""Tests of the config flow and the options flow, run in Home Assistant's test harness.

The statistics are synthetic: made-up statistic IDs written into the throwaway test recorder. The integration
itself only reads statistics. The real setup and unload of the integration run: an entry that a flow creates, or that
an options change reloads, is set up against the test recorder, and the ``hass`` fixture of the harness unloads it at
the end of the test. The tests of the setup itself are in ``test_init.py``.
"""

import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.recorder.common import async_wait_recording_done

from custom_components.heatpump_efficiency import sensor_model
from custom_components.heatpump_efficiency.const import DOMAIN
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from .helpers import add_statistic

NAME = "Test pump"

HEATING_OUTPUT = "sensor.test_heating_output"
HEATING_ELECTRICITY = "sensor.test_heating_electricity"
OVERALL_OUTPUT = "sensor.test_overall_output"
OVERALL_ELECTRICITY = "sensor.test_overall_electricity"
COOLING_OUTPUT = "sensor.test_cooling_output"
COOLING_ELECTRICITY = "sensor.test_cooling_electricity"
OTHER_OUTPUT = "sensor.test_other_output"
OTHER_ELECTRICITY = "sensor.test_other_electricity"
DEFROST_HEAT = "sensor.test_defrost_heat"
POWER = "sensor.test_power"  # a power statistic, not energy
MEAN_ONLY = "sensor.test_mean_only"  # energy without a running sum
MISSING = "sensor.test_missing"  # never written to the recorder

HEATING = {"output": [HEATING_OUTPUT], "electricity": [HEATING_ELECTRICITY]}
OVERALL = {"output": [OVERALL_OUTPUT], "electricity": [OVERALL_ELECTRICITY]}
COOLING = {"output": [COOLING_OUTPUT], "electricity": [COOLING_ELECTRICITY]}
COOLING_BTU = {**COOLING, "unit": "btu_per_wh"}
SEASON_FIELDS = {
    "heating_start_month": "10",
    "heating_start_day": 1,
    "heating_end_month": "4",
    "heating_end_day": 30,
    "cooling_start_month": "6",
    "cooling_start_day": 1,
    "cooling_end_month": "9",
    "cooling_end_day": 30,
}


@pytest.fixture(autouse=True)
async def recorder_and_hass(recorder_mock, hass):
    """Start the test recorder before ``hass``, and let the work of a test finish before the instance stops.

    ha-test-harness: pytest-homeassistant 2026.11.2, plugins.py ``recorder_db_url`` asserts that hass is not set up
    yet, so ``recorder_mock`` is requested first. The ``hass`` fixture unloads every LOADED entry after its
    ``yield`` (the entries that the real setup loaded). This fixture requests ``hass``, so pytest tears it down
    before ``hass``.
    """
    yield
    await hass.async_block_till_done()


@pytest.fixture
async def statistics(hass):
    """Write the synthetic statistics every flow test chooses from."""
    for statistic_id in (
        HEATING_OUTPUT,
        HEATING_ELECTRICITY,
        OVERALL_OUTPUT,
        OVERALL_ELECTRICITY,
        COOLING_OUTPUT,
        COOLING_ELECTRICITY,
        OTHER_OUTPUT,
        OTHER_ELECTRICITY,
        DEFROST_HEAT,
    ):
        add_statistic(hass, statistic_id)
    add_statistic(hass, POWER, unit="W", unit_class="power", has_sum=False)
    add_statistic(hass, MEAN_ONLY, has_sum=False)
    # ha-test-harness: pytest-homeassistant 2026.11.2, components/recorder/common.py async_wait_recording_done
    await async_wait_recording_done(hass)


def _add_entry(hass, options):
    """Add an existing entry with the given stored mapping (minor version 4, so no migration runs)."""
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, data={"name": NAME}, options=options, minor_version=4
    )
    entry.add_to_hass(hass)
    return entry


async def _start_user(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _submit_user(hass, user_input):
    result = await _start_user(hass)
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def _recover_user(hass, result):
    """Fix the cause: submit a valid form on the same flow and return the created entry's result.

    developers.home-assistant.io rules/config-flow-test-coverage.md (updated 2026-10-09): after each error the
    test fixes the cause and finishes the flow, to show the user can recover.
    """
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": NAME, "heating": HEATING}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {"name": NAME}
    assert result["options"] == {"heating": HEATING}
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert dict(entry.options) == {"heating": HEATING}


async def _recover_options(hass, entry, result):
    """Fix the cause: submit a valid mapping on the same options flow and check the saved options."""
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"heating": HEATING}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"heating": HEATING}
    assert dict(entry.options) == {"heating": HEATING}


async def _submit_options(hass, entry, user_input):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )


# Section inputs that each end in one error key; shared by the user step and the options flow.
ERROR_CASES = [
    pytest.param({}, {"base": "nothing_mapped"}, id="nothing_mapped"),
    pytest.param(
        {"heating": {"output": [MISSING], "electricity": [HEATING_ELECTRICITY]}},
        {"heating": "statistic_missing"},
        id="statistic_missing",
    ),
    pytest.param(
        {"heating": {"output": [POWER], "electricity": [HEATING_ELECTRICITY]}},
        {"heating": "statistic_not_energy"},
        id="statistic_not_energy",
    ),
    pytest.param(
        {"heating": {"output": [MEAN_ONLY], "electricity": [HEATING_ELECTRICITY]}},
        {"heating": "statistic_no_sum"},
        id="statistic_no_sum",
    ),
    pytest.param(
        {"heating": {"output": [HEATING_OUTPUT]}},
        {"heating": "electricity_missing"},
        id="electricity_missing",
    ),
    pytest.param(
        {"heating": {"electricity": [HEATING_ELECTRICITY]}},
        {"heating": "output_missing"},
        id="output_missing",
    ),
    pytest.param(
        {"heating": {**HEATING, "defrost_heat": [HEATING_OUTPUT]}},
        {"heating": "defrost_duplicate"},
        id="defrost_duplicate",
    ),
    pytest.param(
        {"heating": HEATING, "hot_water": {"defrost_heat": [DEFROST_HEAT]}},
        {"hot_water": "defrost_unused"},
        id="defrost_unused",
    ),
    pytest.param(
        {
            "heating": HEATING,
            "seasons": {"heating_start_month": "10", "heating_start_day": 1},
        },
        {"seasons": "season_missing"},
        id="season_missing",
    ),
    pytest.param(
        {
            "heating": HEATING,
            "seasons": {
                **SEASON_FIELDS,
                "heating_end_month": "4",
                "heating_end_day": 31,
            },
        },
        {"seasons": "season_invalid_day"},
        id="season_invalid_day",
    ),
    pytest.param(
        {
            "heating": HEATING,
            "seasons": {
                **SEASON_FIELDS,
                "heating_end_month": "10",
                "heating_end_day": 1,
            },
        },
        {"seasons": "season_same_day"},
        id="season_same_day",
    ),
]


# --- user step ---------------------------------------------------------------------------------------------


async def test_user_step_shows_the_form(hass):
    """Starting the flow shows the user form."""
    result = await _start_user(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_step_creates_the_entry_with_the_normalized_mapping(
    hass, statistics
):
    """A valid form creates the entry: the name as data, the mapping as options."""
    result = await _submit_user(
        hass,
        {
            "name": f"  {NAME}  ",
            "heating": {
                **HEATING,
                "measured_since": "2026-01-01",
                "defrost_heat": [DEFROST_HEAT],
            },
            "cooling": COOLING_BTU,
            "overall": OVERALL,
            "seasons": SEASON_FIELDS,
        },
    )
    await hass.async_block_till_done()

    expected = {
        "heating": {
            **HEATING,
            "measured_since": "2026-01-01",
            "defrost_heat": [DEFROST_HEAT],
        },
        "cooling": COOLING_BTU,
        "overall": OVERALL,
        "seasons": {
            "heating_start": "10-01",
            "heating_end": "04-30",
            "cooling_start": "06-01",
            "cooling_end": "09-30",
        },
    }
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {"name": NAME}
    assert result["options"] == expected
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert dict(entry.options) == expected
    assert entry.state is ConfigEntryState.LOADED  # the real setup ran


@pytest.mark.parametrize(("sections", "errors"), ERROR_CASES)
async def test_user_step_shows_each_validation_error(
    hass, statistics, sections, errors
):
    """Each rule of the pure validation ends in the form again, with its error key."""
    result = await _submit_user(hass, {"name": NAME, **sections})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == errors
    assert hass.config_entries.async_entries(DOMAIN) == []

    await _recover_user(hass, result)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.LOADED


async def test_user_step_requires_a_name(hass, statistics):
    """A blank name is an error on the name field."""
    result = await _submit_user(hass, {"name": "   ", "heating": HEATING})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_required"}

    await _recover_user(hass, result)


async def test_user_step_names_the_missing_statistic(hass, statistics):
    """The error text gets the failing statistic, labelled with its section."""
    result = await _submit_user(
        hass,
        {
            "name": NAME,
            "heating": {"output": [MISSING], "electricity": [HEATING_ELECTRICITY]},
        },
    )

    assert result["errors"] == {"heating": "statistic_missing"}
    assert result["description_placeholders"]["missing"] == f"heating: {MISSING}"

    await _recover_user(hass, result)


async def test_user_step_adds_a_second_heat_pump_with_its_own_outputs(hass, statistics):
    """Different output statistics, even sharing an electrical statistic, create a second entry."""
    _add_entry(hass, {"heating": HEATING})

    result = await _submit_user(
        hass,
        {
            "name": "Second pump",
            "heating": {"output": [OTHER_OUTPUT], "electricity": [HEATING_ELECTRICITY]},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


async def test_user_step_accepts_overall_reusing_its_own_heating_output(
    hass, statistics
):
    """An output shared between sections of the same new entry is not a duplicate."""
    result = await _submit_user(
        hass,
        {
            "name": NAME,
            "heating": HEATING,
            "overall": {
                "output": [HEATING_OUTPUT],
                "electricity": [OVERALL_ELECTRICITY],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step_aborts_when_another_entry_uses_an_output(hass, statistics):
    """An output statistic of another entry ends the setup as already configured, naming it."""
    existing = _add_entry(hass, {"heating": HEATING})

    result = await _submit_user(
        hass,
        {
            "name": "Second pump",
            "overall": {
                "output": [OTHER_OUTPUT, HEATING_OUTPUT],
                "electricity": [OTHER_ELECTRICITY],
            },
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert result["description_placeholders"] == {"statistics": HEATING_OUTPUT}
    assert hass.config_entries.async_entries(DOMAIN) == [existing]
    assert existing.state is ConfigEntryState.NOT_LOADED  # nothing was set up


async def test_user_step_abort_names_every_shared_statistic_sorted(hass, statistics):
    """Several shared outputs are listed together, sorted, separated by commas."""
    _add_entry(hass, {"heating": HEATING})
    _add_entry(hass, {"cooling": COOLING})

    result = await _submit_user(
        hass,
        {
            "name": "Second pump",
            "heating": {"output": [HEATING_OUTPUT], "electricity": [OTHER_ELECTRICITY]},
            "cooling": {"output": [COOLING_OUTPUT], "electricity": [OTHER_ELECTRICITY]},
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert result["description_placeholders"] == {
        "statistics": f"{COOLING_OUTPUT}, {HEATING_OUTPUT}"
    }


# --- options flow ------------------------------------------------------------------------------------------


async def test_options_flow_shows_the_form_with_the_stored_values(hass):
    """The form opens on the init step with no errors, and the stored output is the suggested value."""
    entry = _add_entry(hass, {"heating": HEATING})

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {}
    # homeassistant/data_entry_flow.py add_suggested_values_to_schema (2026.11.2) puts the stored value in the
    # marker's description["suggested_value"], inside the section's own schema.
    sections = {str(key): value for key, value in result["data_schema"].schema.items()}
    fields = {str(key): key for key in sections["heating"].schema.schema}
    assert fields["output"].description == {"suggested_value": [HEATING_OUTPUT]}


async def test_options_flow_saves_the_new_mapping(hass, statistics):
    """A valid change is stored as the entry's options, and the entry reloads."""
    entry = _add_entry(hass, {"heating": HEATING})

    result = await _submit_options(
        hass,
        entry,
        {"heating": HEATING, "overall": {**OVERALL, "measured_since": "2026-02-01"}},
    )
    await hass.async_block_till_done()

    expected = {
        "heating": HEATING,
        "overall": {**OVERALL, "measured_since": "2026-02-01"},
    }
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == expected
    assert dict(entry.options) == expected


@pytest.mark.parametrize(("sections", "errors"), ERROR_CASES)
async def test_options_flow_shows_each_validation_error(
    hass, statistics, sections, errors
):
    """Each rule of the pure validation ends in the form again, and the stored options stay."""
    entry = _add_entry(hass, {"heating": HEATING})

    result = await _submit_options(hass, entry, sections)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == errors
    assert dict(entry.options) == {"heating": HEATING}

    await _recover_options(hass, entry, result)


async def test_options_flow_names_the_missing_statistic(hass, statistics):
    """The error text gets the failing statistic, labelled with its section."""
    entry = _add_entry(hass, {"heating": HEATING})

    result = await _submit_options(
        hass,
        entry,
        {"heating": {"output": [MISSING], "electricity": [HEATING_ELECTRICITY]}},
    )

    assert result["description_placeholders"]["missing"] == f"heating: {MISSING}"

    await _recover_options(hass, entry, result)


async def test_options_flow_does_not_check_for_duplicates(hass, statistics):
    """Only the setup refuses a shared output; the options flow keeps accepting it (design D3)."""
    entry = _add_entry(hass, {"heating": HEATING})
    _add_entry(
        hass,
        {"overall": {"output": [OTHER_OUTPUT], "electricity": [OTHER_ELECTRICITY]}},
    )

    result = await _submit_options(
        hass, entry, {"heating": {**HEATING, "output": [OTHER_OUTPUT]}}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_flow_saves_a_cooling_change_without_warning_when_the_unit_is_unchanged(
    hass, statistics
):
    """Changing something other than the Cooling unit never queries or warns."""
    entry = _add_entry(hass, {"cooling": COOLING_BTU})

    result = await _submit_options(
        hass, entry, {"cooling": {**COOLING_BTU, "measured_since": "2026-03-01"}}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "cooling": {**COOLING_BTU, "measured_since": "2026-03-01"}
    }


def _register_cooling_sensors(hass, entry, count):
    """Register the first ``count`` Cooling sensors of the entry; return their entity IDs."""
    registry = er.async_get(hass)
    unique_ids = sensor_model.service_unique_ids(entry.entry_id, "cooling")
    return [
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            unique_id,
            config_entry=entry,
            suggested_object_id=f"test_cooling_{index}",
        ).entity_id
        for index, unique_id in enumerate(unique_ids[:count])
    ]


async def test_options_flow_unit_change_without_registered_sensors_saves_directly(
    hass, statistics
):
    """No Cooling sensor in the entity registry: nothing to warn about."""
    entry = _add_entry(hass, {"cooling": COOLING})

    result = await _submit_options(hass, entry, {"cooling": COOLING_BTU})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"cooling": COOLING_BTU}


async def test_options_flow_unit_change_without_stored_statistics_saves_directly(
    hass, statistics
):
    """Registered Cooling sensors that have no long-term statistics yet do not warn."""
    entry = _add_entry(hass, {"cooling": COOLING})
    _register_cooling_sensors(hass, entry, 2)

    result = await _submit_options(hass, entry, {"cooling": COOLING_BTU})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"cooling": COOLING_BTU}


async def test_options_flow_unit_change_with_statistics_warns_then_saves_on_confirmation(
    hass, statistics
):
    """Stored Cooling statistics make the unit change ask first; submitting the step stores it."""
    entry = _add_entry(hass, {"cooling": COOLING})
    with_statistics, _ = _register_cooling_sensors(hass, entry, 2)
    add_statistic(hass, with_statistics, unit="W/W", unit_class=None, has_sum=False)
    await async_wait_recording_done(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"cooling": COOLING_BTU}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "unit_change"
    assert result["description_placeholders"] == {"sensors": with_statistics}
    assert dict(entry.options) == {
        "cooling": COOLING
    }  # nothing stored before the confirmation

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"cooling": COOLING_BTU}
    assert dict(entry.options) == {"cooling": COOLING_BTU}


async def test_options_flow_unit_change_names_every_sensor_with_statistics(
    hass, statistics
):
    """The warning lists all affected Cooling sensors, sorted, separated by commas."""
    entry = _add_entry(hass, {"cooling": COOLING_BTU})
    sensors = _register_cooling_sensors(hass, entry, 2)
    for sensor in sensors:
        add_statistic(hass, sensor, unit="BTU/Wh", unit_class=None, has_sum=False)
    await async_wait_recording_done(hass)

    result = await _submit_options(hass, entry, {"cooling": COOLING})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "unit_change"
    assert result["description_placeholders"] == {"sensors": ", ".join(sorted(sensors))}
