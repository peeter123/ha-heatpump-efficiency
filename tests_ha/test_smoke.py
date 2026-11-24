"""Smoke test: the harness loads the integration and its config flow starts."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.heatpump_efficiency.const import DOMAIN


async def test_user_step_shows_the_form(recorder_mock, hass):
    """The user step returns the setup form."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
