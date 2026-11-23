"""Statistics health repair issues: which issues to create and delete (design D7).

Pure: standard library and pure siblings only. ``issues.py`` applies the plan to
the Home Assistant issue registry.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo

from . import efficiency as eff

# Health (efficiency.health) to issue translation key (translations/en.json "issues").
# A stale statistic without any row in the staleness window gets STALE_NO_ROWS_KEY instead.
ISSUE_KEYS: dict[str, str] = {
    eff.HEALTH_MISSING: "statistic_missing",
    eff.HEALTH_NOT_ENERGY: "statistic_not_energy",
    eff.HEALTH_NO_SUM: "statistic_no_sum",
    eff.HEALTH_STALE: "statistic_stale",
}
STALE_NO_ROWS_KEY = "statistic_stale_no_rows"

# Every issue translation key (design D7).
TRANSLATION_KEYS: tuple[str, ...] = (*ISSUE_KEYS.values(), STALE_NO_ROWS_KEY)

# The placeholders every issue carries, and the one only ``statistic_stale`` carries.
PLACEHOLDERS: tuple[str, ...] = ("heat_pump", "statistic_id")
LAST_STATISTICS = "last_statistics"
TIME_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class IssueSpec:
    """One issue to create (or replace): Home Assistant ignores an unchanged replacement."""

    issue_id: str
    translation_key: str
    placeholders: Mapping[str, str]


@dataclass(frozen=True)
class IssuePlan:
    """The issues to create or update and the issue IDs to delete."""

    create: tuple[IssueSpec, ...]
    delete: tuple[str, ...]


def issue_id(entry_id: str, statistic_id: str) -> str:
    """One issue per entry and statistic."""
    return f"{entry_id}_{statistic_id}"


def unchecked(
    health: Mapping[str, str],
    hourly_only_ids: Iterable[str],
    errors: Mapping[str, str | None],
) -> frozenset[str]:
    """The statistics whose staleness cannot be judged: stale, but the table read failed.

    Inputs: ``efficiency.health``, the hourly-only IDs, and the engine's last
    error per read (``EngineState.errors``, keyed by table). A failed read leaves
    no rows, which would otherwise look like a stopped statistic.
    """
    hourly = set(hourly_only_ids)
    return frozenset(
        statistic_id
        for statistic_id, value in health.items()
        if value == eff.HEALTH_STALE
        and errors.get(eff.SOURCE_HOUR if statistic_id in hourly else eff.SOURCE_5MINUTE)
    )


def issue_key(health: str, last_row_end: float | None) -> str | None:
    """The translation key of one statistic's issue; None when it is healthy.

    Inputs: its health (``efficiency.health``) and the end of its last row
    (``last_row_ends``). Stale with a last row: ``statistic_stale`` (with its
    time); stale without any row in the staleness window: ``statistic_stale_no_rows``.
    """
    if health == eff.HEALTH_STALE and last_row_end is None:
        return STALE_NO_ROWS_KEY
    return ISSUE_KEYS.get(health)


def _placeholders(
    key: str, heat_pump: str, statistic_id: str, last_row_end: float | None, tz: tzinfo
) -> dict[str, str]:
    placeholders = {"heat_pump": heat_pump, "statistic_id": statistic_id}
    if key == ISSUE_KEYS[eff.HEALTH_STALE] and last_row_end is not None:
        placeholders[LAST_STATISTICS] = datetime.fromtimestamp(last_row_end, tz).strftime(TIME_FORMAT)
    return placeholders


def plan_issues(
    entry_id: str,
    heat_pump: str,
    mapped_ids: Iterable[str],
    health: Mapping[str, str],
    last_row_end: Mapping[str, float | None],
    existing: Iterable[str],
    metadata_ok: bool,
    tz: tzinfo,
    skip: Iterable[str] = (),
) -> IssuePlan:
    """Decide the issues of one entry after an update.

    Inputs: the entry ID, the heat pump name, the mapped statistic IDs, the health
    per ID (``efficiency.health``), the end of each last row (epoch seconds), the
    issue IDs that exist for this entry, whether the metadata has been read
    successfully (``EngineState.metadata_ok``), the time zone for the last
    statistics time, and the IDs whose health cannot be judged (``unchecked``).

    An unhealthy statistic gets its issue (``issue_key``): every issue carries the
    heat pump name and the statistic ID, and ``statistic_stale`` also the local
    time its last row ended. An issue is deleted when its statistic
    is healthy again or no longer mapped (an options change). Conservative cases:
    before the metadata is known nothing is classified, so no issue is created and
    only the issues of unmapped statistics are deleted; the issues of skipped
    statistics, or of ones without a health value, stay as they are.
    """
    by_issue = {issue_id(entry_id, s): s for s in mapped_ids}
    skipped = set(skip)
    create: list[IssueSpec] = []
    if metadata_ok:
        for iid, statistic_id in sorted(by_issue.items()):
            last = last_row_end.get(statistic_id)
            key = issue_key(health.get(statistic_id, eff.HEALTH_OK), last)
            if key is None or statistic_id in skipped:
                continue
            create.append(IssueSpec(iid, key, _placeholders(key, heat_pump, statistic_id, last, tz)))
    wanted = {spec.issue_id for spec in create}
    delete: list[str] = []
    for iid in sorted(set(existing)):
        statistic_id = by_issue.get(iid)
        if statistic_id is None:
            delete.append(iid)  # no longer mapped
        elif iid in wanted or not metadata_ok or statistic_id in skipped:
            continue
        elif health.get(statistic_id) == eff.HEALTH_OK:
            delete.append(iid)
    return IssuePlan(tuple(create), tuple(delete))
