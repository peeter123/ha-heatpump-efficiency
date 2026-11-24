"""Pure setup-form rules for the Heat Pump Efficiency integration.

Standard library only (no Home Assistant import), so the rules are unit-tested
offline. The config flow and the options flow are thin glue around these
functions: ``normalize_mapping`` turns the submitted form into the stored
mapping, ``validate`` checks it against the statistics metadata that
``async_list_statistic_ids`` returns.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# Sections of the form and keys of the stored mapping.
SERVICE_HEATING = "heating"
SERVICE_HOT_WATER = "hot_water"
SERVICE_COOLING = "cooling"
SERVICE_OVERALL = "overall"
SERVICES = (SERVICE_HEATING, SERVICE_HOT_WATER, SERVICE_COOLING, SERVICE_OVERALL)
# The legacy stored key of the former planned section (the price source and, before minor
# version 3, the defrost slot); no form has it now and only the migration helpers read it.
SECTION_PLANNED = "planned"
SECTION_SEASONS = "seasons"
# Sections that start expanded in the form; the others are collapsed.
EXPANDED_SECTIONS = (SERVICE_HEATING, SERVICE_OVERALL)

FIELD_OUTPUT = "output"
FIELD_ELECTRICITY = "electricity"
FIELD_MEASURED_SINCE = "measured_since"
FIELD_DEFROST_HEAT = "defrost_heat"
FIELD_UNIT = "unit"  # Cooling section only
SERVICE_FIELDS = (FIELD_OUTPUT, FIELD_ELECTRICITY, FIELD_MEASURED_SINCE)
COOLING_FIELDS = (*SERVICE_FIELDS, FIELD_UNIT)
DEFROST_SERVICES = (SERVICE_HEATING, SERVICE_HOT_WATER)  # the sections with a defrost heat field

# Cooling efficiency unit: W/W is the default and is not stored.
UNIT_W_PER_W = "w_per_w"
UNIT_BTU_PER_WH = "btu_per_wh"
COOLING_UNITS = (UNIT_W_PER_W, UNIT_BTU_PER_WH)

# Season dates: stored as ``MM-DD`` strings under the ``seasons`` key (same names
# as ``seasons.DATE_KEYS``); the form has a month and a day field per date.
SEASON_DATES = ("heating_start", "heating_end", "cooling_start", "cooling_end")
SEASON_PAIRS = (("heating_start", "heating_end"), ("cooling_start", "cooling_end"))
SEASON_MONTH_SUFFIX = "_month"
SEASON_DAY_SUFFIX = "_day"
SEASON_FIELDS = tuple(
    f"{date_key}{suffix}"
    for date_key in SEASON_DATES
    for suffix in (SEASON_MONTH_SUFFIX, SEASON_DAY_SUFFIX)
)

FIELD_NAME = "name"
BASE = "base"

# Error keys (translations ``<flow>.error.<key>``).
ERROR_NAME_REQUIRED = "name_required"
ERROR_NOTHING_MAPPED = "nothing_mapped"
ERROR_ELECTRICITY_MISSING = "electricity_missing"  # output without electricity
ERROR_OUTPUT_MISSING = "output_missing"  # electricity without output
ERROR_STATISTIC_MISSING = "statistic_missing"
ERROR_STATISTIC_NOT_ENERGY = "statistic_not_energy"
ERROR_STATISTIC_NO_SUM = "statistic_no_sum"
ERROR_SEASON_INVALID_DAY = "season_invalid_day"  # a day not in its month, or 29 February
ERROR_SEASON_SAME_DAY = "season_same_day"  # a season's start equals its end
ERROR_SEASON_MISSING = "season_missing"  # a season date with an empty month or day
ERROR_DEFROST_DUPLICATE = "defrost_duplicate"  # a defrost statistic mapped twice or also as output or electricity
ERROR_DEFROST_UNUSED = "defrost_unused"  # a defrost statistic that corrects nothing
ERRORS = (
    ERROR_NAME_REQUIRED,
    ERROR_NOTHING_MAPPED,
    ERROR_ELECTRICITY_MISSING,
    ERROR_OUTPUT_MISSING,
    ERROR_STATISTIC_MISSING,
    ERROR_STATISTIC_NOT_ENERGY,
    ERROR_STATISTIC_NO_SUM,
    ERROR_SEASON_INVALID_DAY,
    ERROR_SEASON_SAME_DAY,
    ERROR_SEASON_MISSING,
    ERROR_DEFROST_DUPLICATE,
    ERROR_DEFROST_UNUSED,
)
# Statistic errors name the failing choices through these placeholders.
PLACEHOLDERS = {
    ERROR_STATISTIC_MISSING: "missing",
    ERROR_STATISTIC_NOT_ENERGY: "not_energy",
    ERROR_STATISTIC_NO_SUM: "no_sum",
    ERROR_DEFROST_DUPLICATE: "duplicate",
}
# Per section only the first applicable error is shown, in this order.
_ERROR_PRIORITY = (
    ERROR_STATISTIC_MISSING,
    ERROR_STATISTIC_NOT_ENERGY,
    ERROR_STATISTIC_NO_SUM,
    ERROR_ELECTRICITY_MISSING,
    ERROR_OUTPUT_MISSING,
    ERROR_DEFROST_DUPLICATE,
    ERROR_DEFROST_UNUSED,
)

ENERGY_UNIT_CLASS = "energy"  # recorder metadata unit_class of kWh, Wh, MWh, ...


@dataclass(frozen=True)
class Validation:
    """Result of ``validate``: field errors keyed by section (or ``base``)."""

    errors: dict[str, str] = field(default_factory=dict)
    placeholders: dict[str, str] = field(default_factory=dict)


def _ids(value: Any) -> list[str]:
    """Return the non-empty, de-duplicated statistic IDs of a multiple selector."""
    if not value:
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and item))


def _int(value: Any) -> int | None:
    """An int from a form value (a NumberSelector gives a float, a SelectSelector a str)."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number == int(number) else None


def _month_day(value: Any) -> tuple[int, int] | None:
    """A stored ``MM-DD`` string as (month, day); None when it is not shaped so."""
    if not isinstance(value, str):
        return None
    month, sep, day = value.partition("-")
    if not sep or not month.isdigit() or not day.isdigit():
        return None
    return int(month), int(day)


def _empty(value: Any) -> bool:
    """Whether a submitted form value is empty (cleared)."""
    return value is None or value == ""


def _seasons_from_input(data: Mapping[str, Any]) -> dict[str, str]:
    """The stored season dates of a submitted section (form fields or stored strings).

    All four dates are returned. A date with an empty month or day is ``""``
    (``season_missing``); a month or day that is not a whole number is kept as
    unparsable text (``season_invalid_day``). Ranges are checked by ``validate``.
    """
    seasons: dict[str, str] = {}
    for date_key in SEASON_DATES:
        month_raw = data.get(date_key + SEASON_MONTH_SUFFIX)
        day_raw = data.get(date_key + SEASON_DAY_SUFFIX)
        if date_key + SEASON_MONTH_SUFFIX not in data and date_key + SEASON_DAY_SUFFIX not in data:
            # An already stored ``MM-DD`` string (normalizing is idempotent).
            stored = data.get(date_key)
            parsed = _month_day(stored)
            if parsed is not None:
                seasons[date_key] = f"{parsed[0]:02d}-{parsed[1]:02d}"
            else:
                seasons[date_key] = "" if _empty(stored) else str(stored)
        elif _empty(month_raw) or _empty(day_raw):
            seasons[date_key] = ""
        else:
            month, day = _int(month_raw), _int(day_raw)
            if month is not None and day is not None:
                seasons[date_key] = f"{month:02d}-{day:02d}"
            else:
                seasons[date_key] = f"{month_raw}-{day_raw}"
    return seasons


def season_form_values(seasons: Mapping[str, str]) -> dict[str, Any]:
    """The form fields (month as ``"10"``, day as ``1``) of stored ``MM-DD`` dates."""
    values: dict[str, Any] = {}
    for date_key in SEASON_DATES:
        if (parsed := _month_day(seasons.get(date_key))) is not None:
            values[date_key + SEASON_MONTH_SUFFIX] = str(parsed[0])
            values[date_key + SEASON_DAY_SUFFIX] = parsed[1]
    return values


def suggested_values(
    mapping: Mapping[str, Any] | None, defaults: Mapping[str, str]
) -> dict[str, Any]:
    """The suggested form values: the mapping with its seasons as form fields.

    The stored dates are used, or ``defaults`` (``seasons.default_seasons``) when
    none are stored.
    """
    values = dict(mapping or {})
    stored = values.get(SECTION_SEASONS) or defaults
    values[SECTION_SEASONS] = season_form_values(stored)
    if values.get(SERVICE_COOLING):  # show the default unit explicitly
        values[SERVICE_COOLING] = {
            **values[SERVICE_COOLING],
            FIELD_UNIT: cooling_unit(values),
        }
    return values


def with_default_seasons(
    options: Mapping[str, Any], defaults: Mapping[str, str]
) -> dict[str, Any]:
    """Return the options with ``defaults`` added under ``seasons`` when absent.

    Used by the migration of an entry from before season dates: every other key
    is kept unchanged.
    """
    merged = dict(options)
    if not merged.get(SECTION_SEASONS):
        merged[SECTION_SEASONS] = dict(defaults)
    return merged


def with_defrost_moved(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return the options with a planned defrost slot moved into the Heating section.

    Used by the migration to minor version 3 (design D3): the slot's value (one ID
    or a list) is added to the Heating ``defrost_heat`` list, creating the section
    when absent and keeping the IDs already there first, without duplicates. It is
    removed from the planned section, which is dropped when it is then empty. A slot
    value that is also an output or electrical ID of any section is dropped instead of
    moved, since it would be a ``defrost_duplicate`` that makes Heating subtract its own
    output with no repair issue to explain it. Every other key is kept unchanged; the
    input is not modified. Options without a slot are returned as an equal copy.
    """
    merged = dict(options)
    planned = dict(merged.get(SECTION_PLANNED) or {})
    slot = planned.pop(FIELD_DEFROST_HEAT, None)
    slot_ids = _ids([slot] if isinstance(slot, str) else slot)
    if not slot_ids:
        return dict(options)
    mapped = {
        statistic_id
        for service in SERVICES
        for field in (FIELD_OUTPUT, FIELD_ELECTRICITY)
        for statistic_id in _ids((merged.get(service) or {}).get(field))
    }
    moved = [statistic_id for statistic_id in slot_ids if statistic_id not in mapped]
    if moved:
        heating = dict(merged.get(SERVICE_HEATING) or {})
        heating[FIELD_DEFROST_HEAT] = _ids([*_ids(heating.get(FIELD_DEFROST_HEAT)), *moved])
        merged[SERVICE_HEATING] = heating
    if planned:
        merged[SECTION_PLANNED] = planned
    else:
        merged.pop(SECTION_PLANNED, None)
    return merged


def without_planned(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return the options without the legacy planned section.

    Used by the migration to minor version 4 (design D2): drops the ``planned`` key,
    which only ever held an unused price source once the defrost slot had moved. Every
    other key is kept unchanged; the input is not modified. Options without the key are
    returned as an equal copy, so the step is idempotent.
    """
    return {key: value for key, value in options.items() if key != SECTION_PLANNED}


def cooling_unit(mapping: Mapping[str, Any] | None) -> str:
    """The cooling efficiency unit of a mapping (``w_per_w`` when absent)."""
    unit = ((mapping or {}).get(SERVICE_COOLING) or {}).get(FIELD_UNIT)
    return unit if unit in COOLING_UNITS else UNIT_W_PER_W


def unit_change_needs_warning(
    stored: Mapping[str, Any] | None,
    new: Mapping[str, Any] | None,
    cooling_has_statistics: bool,
) -> bool:
    """Whether an options change must show the unit warning step.

    True when Cooling is configured in the new mapping, its unit differs from
    the stored one and at least one Cooling sensor already has long-term
    statistics. Removing Cooling never warns.
    """
    return (
        SERVICE_COOLING in configured_services(new or {})
        and cooling_unit(stored) != cooling_unit(new)
        and cooling_has_statistics
    )


def season_error(seasons: Mapping[str, Any]) -> str | None:
    """The first season error of stored ``MM-DD`` dates, or None.

    All four dates are required: ``season_missing`` when one is empty.
    ``season_invalid_day``: not a whole month and day, a month outside 1 to 12 or
    a day not in its month; 29 February is never valid (the dates recur every
    year). ``season_same_day``: a season's start equals its end.
    """
    if any(not seasons.get(date_key) for date_key in SEASON_DATES):
        return ERROR_SEASON_MISSING
    for date_key in SEASON_DATES:
        parsed = _month_day(seasons[date_key])
        if parsed is None:
            return ERROR_SEASON_INVALID_DAY
        month, day = parsed
        if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(2001, month)[1]:
            return ERROR_SEASON_INVALID_DAY
    for start, end in SEASON_PAIRS:
        if seasons[start] == seasons[end]:
            return ERROR_SEASON_SAME_DAY
    return None


def season_dates_valid(mapping: Mapping[str, Any]) -> bool:
    """Whether the stored season dates are present and valid (what the engine requires)."""
    seasons = mapping.get(SECTION_SEASONS) or {}
    return bool(seasons) and season_error(seasons) is None


def normalize_mapping(user_input: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the stored mapping for a submitted form (idempotent).

    The form submits one dict per section. A service section is kept when it
    has an output, electrical or (Heating and Hot water) defrost statistic; a
    measured-since date or a Cooling unit is kept only with an output or electrical
    statistic. ``defrost_heat`` is dropped for Cooling and Overall. Empty values are
    dropped. A submitted ``planned`` key is ignored.
    ``seasons`` is converted from the form's month and day fields to ``MM-DD``
    strings (already converted strings are kept); the dates are not checked here.
    A submitted ``seasons`` section always yields four dates, ``""`` for a missing one.
    """
    mapping: dict[str, dict[str, Any]] = {}
    for service in SERVICES:
        data = user_input.get(service) or {}
        entry: dict[str, Any] = {}
        for key in (FIELD_OUTPUT, FIELD_ELECTRICITY):
            if ids := _ids(data.get(key)):
                entry[key] = ids
        defrost = _ids(data.get(FIELD_DEFROST_HEAT)) if service in DEFROST_SERVICES else []
        if not entry and not defrost:
            continue
        # A defrost statistic alone keeps the section but does not configure the service.
        # Like measured_since, a unit alone does not configure Cooling; W/W is the default.
        if entry:
            if since := data.get(FIELD_MEASURED_SINCE):
                entry[FIELD_MEASURED_SINCE] = str(since)
            if service == SERVICE_COOLING and data.get(FIELD_UNIT) == UNIT_BTU_PER_WH:
                entry[FIELD_UNIT] = UNIT_BTU_PER_WH
        if defrost:
            entry[FIELD_DEFROST_HEAT] = defrost
        mapping[service] = entry
    if SECTION_SEASONS in user_input:  # a submitted (even emptied) section is checked
        mapping[SECTION_SEASONS] = _seasons_from_input(user_input[SECTION_SEASONS] or {})
    return mapping


def expanded_sections(
    stored: Mapping[str, Any] | None, errors: Iterable[str] = ()
) -> set[str]:
    """Return the form sections to show expanded.

    Heating and Overall always; any section with stored values; any section
    that has an error. Collapsed sections would otherwise hide both. The
    ``seasons`` section always has stored values, so it expands only on an error.
    """
    sections = set(EXPANDED_SECTIONS)
    sections.update(
        key for key, value in (stored or {}).items() if value and key != SECTION_SEASONS
    )
    sections.update(errors)
    return sections & {*SERVICES, SECTION_SEASONS}


def configured_services(mapping: Mapping[str, Any]) -> list[str]:
    """Return the services that get sensors: both output and electricity mapped."""
    return [
        service
        for service in SERVICES
        if (entry := mapping.get(service))
        and entry.get(FIELD_OUTPUT)
        and entry.get(FIELD_ELECTRICITY)
    ]


def defrost_ids(mapping: Mapping[str, Any], service: str) -> list[str]:
    """The stored defrost heat statistic IDs of one service section (design D2).

    Only Heating and Hot water have the field; Cooling and Overall give an empty list.
    """
    if service not in DEFROST_SERVICES:
        return []
    return _ids((mapping.get(service) or {}).get(FIELD_DEFROST_HEAT))


def _measured_ids(mapping: Mapping[str, Any]) -> set[str]:
    """Every output and electricity statistic ID of the mapping."""
    return {
        statistic_id
        for service in SERVICES
        for key in (FIELD_OUTPUT, FIELD_ELECTRICITY)
        for statistic_id in (mapping.get(service) or {}).get(key, [])
    }


def _output_ids(mapping: Mapping[str, Any]) -> set[str]:
    """Every output statistic ID of the mapping (all sections and Overall)."""
    return {
        statistic_id
        for service in SERVICES
        for statistic_id in _ids((mapping.get(service) or {}).get(FIELD_OUTPUT))
    }


def shared_outputs(
    mapping: Mapping[str, Any], other_mappings: Iterable[Mapping[str, Any]]
) -> list[str]:
    """The sorted output statistic IDs of ``mapping`` that another mapping also uses as output.

    Used by the setup to refuse a heat pump that an existing entry already measures
    (design D3). Electrical and defrost heat statistics never count, and an output
    shared between sections of the same mapping does not either: only the other
    mappings (the stored options of the other entries) are compared.
    """
    others: set[str] = set()
    for other in other_mappings:
        others |= _output_ids(other)
    return sorted(_output_ids(mapping) & others)


def statistic_ids(mapping: Mapping[str, Any]) -> set[str]:
    """Return every output, electricity and defrost heat statistic ID of the mapping."""
    return _measured_ids(mapping) | {
        statistic_id for service in DEFROST_SERVICES for statistic_id in defrost_ids(mapping, service)
    }


def classify(statistic_id: str, metadata: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Return the error for one statistic, or None when it is usable.

    ``metadata`` maps statistic ID to a dict from ``async_list_statistic_ids``.
    A statistic is usable when it exists, has an energy unit class and has a
    running sum, whatever its source (external statistics are accepted). Same
    order as ``efficiency.health``: a power statistic is not energy even when
    it also lacks a sum.
    """
    meta = metadata.get(statistic_id)
    if meta is None:
        return ERROR_STATISTIC_MISSING
    if meta.get("unit_class") != ENERGY_UNIT_CLASS:
        return ERROR_STATISTIC_NOT_ENERGY
    if not meta.get("has_sum"):
        return ERROR_STATISTIC_NO_SUM
    return None


def validate(
    mapping: Mapping[str, Any],
    metadata: Iterable[Mapping[str, Any]],
    name: str | None = None,
) -> Validation:
    """Validate a normalized mapping (and the name, when given).

    Errors are keyed by the section of the failing choice (a section, not the
    field inside it, because Home Assistant shows errors per top-level form
    key); an empty mapping and an empty name are the exceptions, keyed by
    ``base`` and ``name``. ``placeholders`` lists the failing statistic IDs per
    reason for the error texts, grouped by section and labelled with the section
    key (``heating: sensor.a; cooling: sensor.b``), because placeholders apply to
    the whole form while each section shows its own error. The key is used, not a
    display name, so that no English text lives in this module.
    """
    by_id = {meta["statistic_id"]: meta for meta in metadata}
    errors: dict[str, str] = {}
    failing: dict[str, dict[str, list[str]]] = {code: {} for code in PLACEHOLDERS}
    if name is not None and not name.strip():
        errors[FIELD_NAME] = ERROR_NAME_REQUIRED
    measured = _measured_ids(mapping)
    if not measured:  # a defrost statistic alone maps nothing
        errors[BASE] = ERROR_NOTHING_MAPPED
    for service in SERVICES:
        entry = mapping.get(service)
        if not entry:
            continue
        found: set[str] = set()
        defrost = defrost_ids(mapping, service)
        for statistic_id in (
            *entry.get(FIELD_OUTPUT, []),
            *entry.get(FIELD_ELECTRICITY, []),
            *defrost,
        ):
            if (code := classify(statistic_id, by_id)) is not None:
                found.add(code)
                section_ids = failing[code].setdefault(service, [])
                if statistic_id not in section_ids:
                    section_ids.append(statistic_id)
        # A defrost-only section gets neither error: it configures no service.
        if entry.get(FIELD_OUTPUT) or entry.get(FIELD_ELECTRICITY):
            if not entry.get(FIELD_ELECTRICITY):
                found.add(ERROR_ELECTRICITY_MISSING)
            if not entry.get(FIELD_OUTPUT):
                found.add(ERROR_OUTPUT_MISSING)
        # A defrost ID in the other defrost section or also an output or electrical ID.
        other = {
            statistic_id
            for other_service in DEFROST_SERVICES
            if other_service != service
            for statistic_id in defrost_ids(mapping, other_service)
        }
        for statistic_id in defrost:
            if statistic_id in measured or statistic_id in other:
                found.add(ERROR_DEFROST_DUPLICATE)
                section_ids = failing[ERROR_DEFROST_DUPLICATE].setdefault(service, [])
                if statistic_id not in section_ids:
                    section_ids.append(statistic_id)
        # Nothing to correct: the service is not configured and Overall is not either.
        if defrost and not {service, SERVICE_OVERALL} & set(configured_services(mapping)):
            found.add(ERROR_DEFROST_UNUSED)
        for code in _ERROR_PRIORITY:
            if code in found:
                errors[service] = code
                break
    if SECTION_SEASONS in mapping and (
        season_code := season_error(mapping[SECTION_SEASONS] or {})
    ):
        errors[SECTION_SEASONS] = season_code
    placeholders = {
        PLACEHOLDERS[code]: "; ".join(
            f"{service}: {', '.join(ids)}" for service, ids in by_section.items()
        )
        for code, by_section in failing.items()
    }
    return Validation(errors, placeholders)
