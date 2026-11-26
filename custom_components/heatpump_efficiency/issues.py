"""Repair issues for unhealthy mapped statistics (design D7).

Thin glue over ``repairs_model.plan_issues``. The issues are non-fixable, so there
is no repairs platform: components/repairs/issue_handler.py
``RepairsFlowManager.async_create_flow`` refuses an issue whose ``is_fixable`` is
false and loads the integration's ``repairs`` platform (``async_create_fix_flow``)
only for fixable ones. This module is not such a platform.
"""

from collections.abc import Mapping
from datetime import tzinfo
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import issue_registry as ir

from . import efficiency as eff, engine, repairs_model
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def async_update_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
    mapping: Mapping[str, Any],
    result: engine.EngineResult,
    state: engine.EngineState,
    tz: tzinfo,
) -> None:
    """Create, update and delete this entry's issues after an update (on the event loop).

    helpers/issue_registry.py: ``IssueRegistry.issues`` is a dict keyed by
    ``(domain, issue_id)`` of ``IssueEntry`` with ``config_entry_id``;
    ``async_create_issue`` creates or replaces (an unchanged replacement fires
    nothing) and raises ``HomeAssistantError`` for an unknown ``config_entry_id``;
    ``async_delete_issue`` ignores an issue that does not exist. Home Assistant
    removes every issue with the entry's ``config_entry_id`` when the entry is
    removed (config_entries.py ``ConfigEntries._async_clean_up`` calls
    ``IssueRegistry.async_clear_config_entry``).

    Never raises (design D7: the health check never fails the update). For
    example, when the entry is removed while an update waits on a read,
    ``async_create_issue`` raises ``HomeAssistantError`` for the unknown
    ``config_entry_id`` (``IssueRegistry.async_get_or_create``); that is logged.
    """
    try:
        _async_apply(hass, entry, mapping, result, state, tz)
    except Exception:  # a repairs failure must not fail the update
        _LOGGER.exception("Updating the repair issues of %s failed", entry.title)


def _async_apply(
    hass: HomeAssistant,
    entry: ConfigEntry,
    mapping: Mapping[str, Any],
    result: engine.EngineResult,
    state: engine.EngineState,
    tz: tzinfo,
) -> None:
    """Apply ``repairs_model.plan_issues`` to this entry's issues (may raise)."""
    mapped = engine.mapped_ids(mapping)
    health = eff.health(mapped, result.metadata, result.last_row_ends, result.now)
    existing = [
        issue.issue_id
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.config_entry_id == entry.entry_id
    ]
    plan = repairs_model.plan_issues(
        entry.entry_id,
        entry.title,
        mapped,
        health,
        result.last_row_ends,
        existing,
        state.metadata_ok,
        tz,
        repairs_model.unchecked(health, result.hourly_only, state.errors),
    )
    for spec in plan.create:
        ir.async_create_issue(
            hass,
            DOMAIN,
            spec.issue_id,
            config_entry_id=entry.entry_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=spec.translation_key,
            translation_placeholders=dict(spec.placeholders),
        )
    for issue_id in plan.delete:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
