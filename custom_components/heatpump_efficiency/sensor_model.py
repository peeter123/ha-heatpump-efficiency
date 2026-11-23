"""Pure description of the sensors of one entry (standard library only).

``sensor.py`` is thin glue around these functions: which sensors exist for a
mapping (four period sensors and a season sensor per service with a season), their
unique IDs, translation keys and units (the Cooling unit), the attributes of a period
and of a season sensor, and which of this entry's registry entries are stale.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from . import efficiency as eff
from . import validation as val

# The series attribute each period sensor carries (design D5); both are unrecorded.
SERIES_ATTRIBUTES: Mapping[str, str] = {
    eff.PERIOD_TODAY: "daily",
    eff.PERIOD_MONTH_TO_DATE: "monthly",
}
ATTR_OUTPUT_ENERGY = "output_energy"
ATTR_ELECTRICAL_ENERGY = "electrical_energy"
ATTR_PERIOD_START = "period_start"
ATTR_INCLUDES_ESTIMATED = "includes_estimated"
ATTR_SEASON_END = "season_end"
ATTR_COMPLETE = "complete"
ATTR_ENDED = "ended"
ATTR_DEFROST_ENERGY = "defrost_energy"  # only when the result is corrected (design D7)
ATTR_EFFICIENCY_UNCORRECTED = "efficiency_uncorrected"
ATTR_DEFROST_SINCE = "defrost_since"  # only when set: the covered start is before the defrost start
ATTR_SEASONS = "seasons"  # the season points; unrecorded (design D7)

# The season sensor of each service (design D7); Hot water has none. The name is
# the translation key part and the last segment of the unique ID.
SEASON_HEATING = "heating_season"
SEASON_COOLING = "cooling_season"
SEASONS: Mapping[str, str] = {
    val.SERVICE_HEATING: SEASON_HEATING,
    val.SERVICE_OVERALL: SEASON_HEATING,
    val.SERVICE_COOLING: SEASON_COOLING,
}
BTU_PER_WH_UNIT = "BTU/Wh"  # unit of the Cooling sensors in BTU/Wh (design D5)


@dataclass(frozen=True)
class SensorSpec:
    """One sensor: a configured service (or Overall) and a period or a season.

    ``period`` holds the period name or, for a season sensor, the season name
    (``is_season``). ``unit`` is the native unit, None for no unit.
    """

    service: str
    period: str
    unique_id: str
    translation_key: str
    is_season: bool = False
    unit: str | None = None


def translation_key(service: str, period: str) -> str:
    """The translation key, for example ``hot_water_month_to_date``."""
    return f"{service}_{period}"


def unique_id(entry_id: str, service: str, period: str) -> str:
    """The unique ID ``<entry_id>_<service>_<period>``."""
    return f"{entry_id}_{service}_{period}"


def cooling_unit_of_measurement(mapping: Mapping[str, Any]) -> str | None:
    """``BTU/Wh`` when the stored Cooling unit is ``btu_per_wh``, else None (W/W: no unit)."""
    return BTU_PER_WH_UNIT if val.cooling_unit(mapping) == val.UNIT_BTU_PER_WH else None


def sensor_specs(entry_id: str, mapping: Mapping[str, Any]) -> list[SensorSpec]:
    """The sensors of a mapping.

    Per configured service four period sensors, and one season sensor when the
    service has a season (``SEASONS``); none for services that are not configured.
    The Cooling sensors carry the Cooling unit.
    """
    specs = []
    for service in val.configured_services(mapping):
        unit = cooling_unit_of_measurement(mapping) if service == val.SERVICE_COOLING else None
        for period in eff.PERIODS:
            specs.append(
                SensorSpec(
                    service, period, unique_id(entry_id, service, period),
                    translation_key(service, period), False, unit,
                )
            )
        season = SEASONS.get(service)
        if season is not None:
            specs.append(
                SensorSpec(
                    service, season, unique_id(entry_id, service, season),
                    translation_key(service, season), True, unit,
                )
            )
    return specs


def service_unique_ids(entry_id: str, service: str) -> list[str]:
    """Every unique ID a service can have: its periods and its season sensor, if any."""
    names = [*eff.PERIODS, *([SEASONS[service]] if service in SEASONS else [])]
    return [unique_id(entry_id, service, name) for name in names]


def stale_unique_ids(
    entry_id: str, mapping: Mapping[str, Any], existing: Iterable[str | None]
) -> list[str]:
    """The unique IDs among ``existing`` (this entry's sensor registry entries) to remove.

    Those of this entry (prefix ``<entry_id>_``) that the mapping no longer
    expects, because their service is no longer configured.
    """
    expected = {spec.unique_id for spec in sensor_specs(entry_id, mapping)}
    prefix = f"{entry_id}_"
    return [
        uid for uid in existing if uid is not None and uid.startswith(prefix) and uid not in expected
    ]


def period_attributes(period: Any) -> dict[str, Any]:
    """The attributes of a period sensor from an ``engine.PeriodResult``.

    A corrected result (a service with defrost statistics) adds the defrost energy and
    the uncorrected efficiency, and ``defrost_since`` when it is set (design D7).
    """
    return {
        ATTR_OUTPUT_ENERGY: period.output_energy,
        ATTR_ELECTRICAL_ENERGY: period.electrical_energy,
        ATTR_PERIOD_START: period.period_start,
        ATTR_INCLUDES_ESTIMATED: period.includes_estimated,
        **_defrost_attributes(period),
    }


def _defrost_attributes(result: Any) -> dict[str, Any]:
    """The defrost attributes of a period or season result; none when it is not corrected."""
    if not result.corrected:
        return {}
    attributes = {
        ATTR_DEFROST_ENERGY: result.defrost_energy,
        ATTR_EFFICIENCY_UNCORRECTED: result.efficiency_uncorrected,
    }
    if result.defrost_since is not None:
        attributes[ATTR_DEFROST_SINCE] = result.defrost_since
    return attributes


def season_attributes(season: Any) -> dict[str, Any] | None:
    """The attributes of a season sensor from an ``engine.SeasonResult``.

    None (no attributes) when there is no result or no season has begun, so an
    unknown season sensor carries no misleading flags. A corrected season adds the
    defrost attributes as a period does.
    """
    if season is None or season.period_start is None:
        return None
    return {
        ATTR_OUTPUT_ENERGY: season.output_energy,
        ATTR_ELECTRICAL_ENERGY: season.electrical_energy,
        ATTR_PERIOD_START: season.period_start,
        ATTR_INCLUDES_ESTIMATED: season.includes_estimated,
        ATTR_SEASON_END: season.season_end,
        ATTR_COMPLETE: season.complete,
        ATTR_ENDED: season.ended,
        **_defrost_attributes(season),
        ATTR_SEASONS: season.points,
    }
