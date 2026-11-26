"""Config flow and options flow of the Heat Pump Efficiency integration.

Thin glue: the rules live in ``validation.py`` (pure, unit-tested).
"""

from typing import Any

import probatio

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_list_statistic_ids,
    get_metadata,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er, selector

from . import sensor_model
from .const import DOMAIN
from .seasons import default_seasons
from .validation import (
    COOLING_UNITS,
    DEFROST_SERVICES,
    FIELD_DEFROST_HEAT,
    FIELD_ELECTRICITY,
    FIELD_MEASURED_SINCE,
    FIELD_NAME,
    FIELD_OUTPUT,
    FIELD_UNIT,
    SEASON_DATES,
    SEASON_DAY_SUFFIX,
    SEASON_MONTH_SUFFIX,
    SECTION_SEASONS,
    SERVICE_COOLING,
    SERVICES,
    Validation,
    cooling_unit,
    expanded_sections,
    normalize_mapping,
    shared_outputs,
    statistic_ids,
    suggested_values,
    unit_change_needs_warning,
    validate,
)

# data_entry_flow.py section(schema, {"collapsed": bool}); a submitted section is a nested dict.
# selector.py StatisticSelector(multiple=True) returns list[str], single returns str;
# DateSelector returns the submitted "YYYY-MM-DD" string; EntitySelector a str.
_STATISTICS = selector.StatisticSelector(
    selector.StatisticSelectorConfig(multiple=True)
)


# selector.py SelectSelector(SelectSelectorConfig(options, mode, translation_key)) returns a
# str; NumberSelector(NumberSelectorConfig(min, max, step, mode)) returns a float (converted
# to int in validation.py). Month names and unit names come from translations
# (selector.month.options, selector.cooling_unit.options).
_MONTH = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[str(month) for month in range(1, 13)],
        mode=selector.SelectSelectorMode.DROPDOWN,
        translation_key="month",
    )
)
_DAY = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1, max=31, step=1, mode=selector.NumberSelectorMode.BOX
    )
)
_COOLING_UNIT = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=list(COOLING_UNITS),
        mode=selector.SelectSelectorMode.DROPDOWN,
        translation_key="cooling_unit",
    )
)


def _service_schema(service: str) -> probatio.Schema:
    schema: dict[Any, Any] = {
        probatio.Optional(FIELD_OUTPUT): _STATISTICS,
        probatio.Optional(FIELD_ELECTRICITY): _STATISTICS,
        probatio.Optional(FIELD_MEASURED_SINCE): selector.DateSelector(),
    }
    if service == SERVICE_COOLING:
        schema[probatio.Optional(FIELD_UNIT)] = _COOLING_UNIT
    if service in DEFROST_SERVICES:
        # The same multiple StatisticSelector as output and electricity (list[str]).
        schema[probatio.Optional(FIELD_DEFROST_HEAT)] = _STATISTICS
    return probatio.Schema(schema)


def _seasons_schema() -> probatio.Schema:
    schema: dict[Any, Any] = {}
    for date_key in SEASON_DATES:
        schema[probatio.Optional(date_key + SEASON_MONTH_SUFFIX)] = _MONTH
        schema[probatio.Optional(date_key + SEASON_DAY_SUFFIX)] = _DAY
    return probatio.Schema(schema)


def _form_schema(with_name: bool, expanded: set[str]) -> probatio.Schema:
    """The sectioned form; ``with_name`` adds the name (setup only)."""
    schema: dict[Any, Any] = {}
    if with_name:
        schema[probatio.Required(FIELD_NAME)] = selector.TextSelector()
    for service in SERVICES:
        schema[probatio.Optional(service)] = section(
            _service_schema(service), {"collapsed": service not in expanded}
        )
    schema[probatio.Optional(SECTION_SEASONS)] = section(
        _seasons_schema(), {"collapsed": SECTION_SEASONS not in expanded}
    )
    return probatio.Schema(schema)


async def _async_validate(
    hass: HomeAssistant, mapping: dict[str, Any], name: str | None
) -> Validation:
    """List the chosen statistics' metadata and apply the pure rules."""
    ids = statistic_ids(mapping)
    # recorder/statistics.py async_list_statistic_ids(hass, statistic_ids, statistic_type):
    # dicts with statistic_id, has_sum, unit_class, source; absent when it does not exist.
    metadata = await async_list_statistic_ids(hass, ids) if ids else []
    return validate(mapping, metadata, name)


class HeatPumpEfficiencyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a heat pump. No unique ID: several heat pumps may be added."""

    VERSION = 1
    # config_entries.py ConfigFlow.MINOR_VERSION: a lower entry minor version calls
    # async_migrate_entry (version 2 adds the season dates, version 3 moves the planned
    # defrost slot into the Heating section, version 4 drops the planned section).
    MINOR_VERSION = 4

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HeatPumpEfficiencyOptionsFlow:
        """Return the options flow."""
        return HeatPumpEfficiencyOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the name and the mapping."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        defaults = default_seasons(
            self.hass.config.latitude
        )  # core_config.py Config.latitude
        schema = _form_schema(True, expanded_sections(None))
        schema = self.add_suggested_values_to_schema(
            schema, suggested_values(None, defaults)
        )
        if user_input is not None:
            mapping = normalize_mapping(user_input)
            name = str(user_input.get(FIELD_NAME, "")).strip()
            result = await _async_validate(self.hass, mapping, name)
            if not result.errors:
                # config_entries.py ConfigFlow._async_current_entries() returns this domain's
                # entries (the user source filters out ignored ones); an entry's mapping is its options.
                shared = shared_outputs(
                    mapping, [entry.options for entry in self._async_current_entries()]
                )
                if shared:
                    # data_entry_flow.py FlowHandler.async_abort(*, reason, description_placeholders)
                    return self.async_abort(
                        reason="already_configured",
                        description_placeholders={"statistics": ", ".join(shared)},
                    )
                # config_entries.py ConfigFlow.async_create_entry(title, data, options)
                return self.async_create_entry(
                    title=name, data={FIELD_NAME: name}, options=mapping
                )
            errors, placeholders = result.errors, result.placeholders
            schema = _form_schema(True, expanded_sections(mapping, errors))
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )


class HeatPumpEfficiencyOptionsFlow(OptionsFlowWithReload):
    """Change the mapping, dates and the Cooling unit; reloads the entry when options change.

    config_entries.py OptionsFlowWithReload reloads only when options changed and
    raises ValueError when the entry has update listeners, so none is added.
    """

    _pending: dict[str, Any]
    _sensors: str

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form with the current values and store the new mapping."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        mapping = self.config_entry.options
        if user_input is not None:
            mapping = normalize_mapping(user_input)
            result = await _async_validate(self.hass, mapping, None)
            if not result.errors:
                # Query the statistics only when the Cooling unit really changes.
                if cooling_unit(self.config_entry.options) != cooling_unit(mapping):
                    with_statistics = (
                        await self._async_cooling_entities_with_statistics()
                    )
                    if unit_change_needs_warning(
                        self.config_entry.options, mapping, bool(with_statistics)
                    ):
                        self._pending = mapping
                        self._sensors = ", ".join(with_statistics)
                        return await self.async_step_unit_change()
                return self.async_create_entry(data=mapping)
            errors, placeholders = result.errors, result.placeholders
        # Sections with stored values or errors start expanded.
        schema = _form_schema(False, expanded_sections(mapping, errors))
        # data_entry_flow.py add_suggested_values_to_schema handles nested sections.
        # Stored season dates become form fields; the defaults fill in when none are stored.
        defaults = default_seasons(
            self.hass.config.latitude
        )  # core_config.py Config.latitude
        suggested = (
            user_input
            if user_input is not None
            else suggested_values(self.config_entry.options, defaults)
        )
        schema = self.add_suggested_values_to_schema(schema, suggested)
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_unit_change(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Warn that the Cooling sensors' statistics cannot be converted; store on submit.

        Closing the dialog stores nothing (data_entry_flow.py: an unfinished flow is
        simply aborted by the frontend).
        """
        if user_input is not None:
            return self.async_create_entry(data=self._pending)
        return self.async_show_form(
            step_id="unit_change",
            data_schema=probatio.Schema({}),
            description_placeholders={"sensors": self._sensors},
        )

    async def _async_cooling_entities_with_statistics(self) -> list[str]:
        """The entity IDs of this entry's Cooling sensors that have stored statistics."""
        # helpers/entity_registry.py async_get(hass) and
        # EntityRegistry.async_get_entity_id(domain, platform, unique_id) -> entity_id | None.
        registry = er.async_get(self.hass)
        entity_ids = {
            entity_id
            for unique_id in sensor_model.service_unique_ids(
                self.config_entry.entry_id, SERVICE_COOLING
            )
            if (
                entity_id := registry.async_get_entity_id(
                    "sensor",
                    DOMAIN,
                    unique_id,
                )
            )
        }
        if not entity_ids:
            return []
        # recorder/statistics.py get_metadata(hass, *, statistic_ids): metadata of the
        # statistics stored in the recorder (async_list_statistic_ids would also list live
        # sensors that have no stored statistics yet); it reads the database, so it runs on
        # the recorder's executor (recorder/__init__.py get_instance).
        metadata = await get_instance(self.hass).async_add_executor_job(
            lambda: get_metadata(self.hass, statistic_ids=entity_ids)
        )
        return sorted(metadata)
