"""Diagnostics of the Heat Pump Efficiency integration (design D8)."""

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import HeatPumpEfficiencyConfigEntry
from .engine import diagnostics_data
from .seasons import COOLING, HEATING
from .validation import SECTION_SEASONS, season_dates_valid


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HeatPumpEfficiencyConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of a config entry.

    The data: options, season dates, metadata, last query windows, cached energies,
    boundary reads, season points and last errors.

    The defrost data (design D8): the options hold the defrost fields, ``defrost`` lists
    each service's defrost statistics and their start, and the energies and season of a
    corrected service carry ``defrost_energy``, ``efficiency_uncorrected`` and
    ``defrost_since``.

    Nothing is redacted: the data holds statistic IDs and energies, no secrets.
    components/diagnostics DiagnosticsProtocol.async_get_config_entry_diagnostics.
    """
    coordinator = entry.runtime_data
    return {
        "options": dict(entry.options),
        "season_dates": _season_dates(entry.options),
        "season_dates_valid": season_dates_valid(entry.options),
        **diagnostics_data(coordinator.engine_state, coordinator.data),
    }


def _season_dates(options: Mapping[str, Any]) -> dict[str, list[str]] | None:
    """The stored ``MM-DD`` start and end of each season kind, or None when there are none."""
    section = options.get(SECTION_SEASONS)
    if not section:
        return None
    return {
        kind: [section.get(f"{kind}_start"), section.get(f"{kind}_end")]
        for kind in (HEATING, COOLING)
    }
