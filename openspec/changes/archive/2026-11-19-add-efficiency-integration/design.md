# Design

## Context

See proposal.md - Why. Facts that shape the approach, all ha-core at tag 2026.11.2 unless marked:

- `recorder/statistics.py` `statistics_during_period(hass, start_time, end_time, statistic_ids: set, period,
  units, types: set) -> dict[str, list[StatisticsRow]]`: rows carry `start`/`end` as float epoch seconds and
  `change` (`float | None`). `change` is the row's sum minus the last sum before the aligned start, in the same
  table, else 0 (`_augment_result_with_change`). A statistic without rows is absent. `period="day"` aligns
  `end_time` to the next local midnight and `"month"` to the next month start (`_find_month_end_time`); both read
  only the hourly table, so a running day or month lacks its current hour. `units=None` converts to the entity's
  current state unit, so `units={"energy": "kWh"}` is always passed. Core calls it on the recorder's database
  executor: `get_instance(hass).async_add_executor_job(...)` (energy `websocket_api.py`, opower and tibber
  `coordinator.py`); the general executor logs a usage report in `recorder/pool.py`.
- 5-minute statistics are compiled at second 10 of every fifth minute (UTC) (`recorder/core.py`); the
  `EVENT_RECORDER_5MIN_STATISTICS_GENERATED` event fires before the commit (`statistics.py` `_compile_statistics`),
  so reading on that event can race the commit. Short-term statistics are purged with the recorder's
  `purge_keep_days`; hourly ones are kept.
- `async_list_statistic_ids(hass, statistic_ids, statistic_type)` (`recorder/statistics.py`) returns per ID
  `has_sum`, `source`, `statistics_unit_of_measurement`, `unit_class`, `mean_type`; served from cache on the loop.
- `helpers/selector.py` `StatisticSelector` (options `multiple`, `read_only` only; no unit filter) covers entity
  and external statistics.
- `config_entries.py`: `OptionsFlowWithReload` (reloads only when options changed; raises `ValueError` with
  update listeners); `OptionsFlow.config_entry` is a property; `async_create_entry(..., options=...)`;
  `async_setup_entry`/`async_unload_entry` return `None` (a boolean is reported for custom integrations).
- `helpers/update_coordinator.py` `DataUpdateCoordinator(hass, logger, *, config_entry, name, update_interval=None,
  ...)`: with `update_interval=None` there is no polling; `CoordinatorEntity.available` follows
  `last_update_success`, so per-period unknown values are returned as `None`, not as a failed update.
- `helpers/entity.py`: `_unrecorded_attributes` is merged in `__init_subclass__`, so it is a class attribute;
  `components/recorder/db_schema.py` `MAX_STATE_ATTRS_BYTES = 16384` applies after excluding them. A sensor with
  `state_class` must have a finite number or `None`. The logbook skips sensors with a unit or a state class
  (`is_sensor_continuous`).
- `helpers/entity_registry.py` `_async_generate_entity_id`: default entity ID from area, device and entity name;
  `has_entity_name` with `translation_key` names the entity from `translations/<lang>.json`.
- `helpers/issue_registry.py` `async_create_issue(..., config_entry_id=..., is_fixable=False, severity,
  translation_key, translation_placeholders)`; issues with `config_entry_id` are cleared with the entry; a
  non-fixable issue needs no repairs platform.
- `util/dt.py`: the time zone is a `zoneinfo.ZoneInfo` (`get_default_time_zone()`); wall-clock `replace` and
  `timedelta` on aware datetimes recompute the offset across DST; durations need UTC or timestamps.
- `script/hassfest/manifest.py` custom manifest: `domain`, `name`, `documentation`, `codeowners`, `version`,
  `iot_class`; HACS (hacs/documentation) also needs `issue_tracker` and `hacs.json`.
- Python: Home Assistant aliases `voluptuous` to `probatio` (`homeassistant/__init__.py`
  `install_as_voluptuous`); `import voluptuous as vol` remains valid for custom integrations.

## Goals / Non-Goals

**Goals:**

- Exact period ratios for any installation that has energy counters with long-term statistics.
- Statistics reads proportional to what changed: today every 5 minutes, completed history once per day.
- All arithmetic in a Home Assistant-free module with standard-library tests.

**Non-Goals:**

- Writing, importing or repairing statistics; estimating missing history (installation tools do that).
- Computing cost or defrost figures (slots only).
- Fixable repair flows, a dashboard strategy or a custom card.

## Decisions

### D1. Domain, layout and manifest

Domain `heatpump_efficiency`, display name "Heat Pump Efficiency". `custom_components/heatpump_efficiency/`:
`manifest.json` (`config_flow: true`, `dependencies: ["recorder"]`, `integration_type: "service"`,
`iot_class: "calculated"`, `version`, `documentation`, `issue_tracker`, `codeowners`), `__init__.py`,
`config_flow.py`, `coordinator.py`, `sensor.py`, `diagnostics.py`,
`issues.py` (repair issue glue; not named `repairs.py`, which is a Home Assistant platform name), `const.py`,
`efficiency.py`, `validation.py`, `engine.py` (the per-update orchestration behind an injected
reader) and `sensor_model.py` (sensor specs, unique IDs, attributes) (pure, standard library only, tested like
`efficiency.py`), `translations/en.json`; `hacs.json` (`name`, `homeassistant: "2026.11.0"`) at
the repository root. `recorder` as a dependency guarantees the database is ready before entry setup. Alternative:
`integration_type: "helper"` (listed under Helpers, no device); rejected because each heat pump gets a device
that groups its sensors. Brand assets and the HACS default list are a publishing follow-up.

### D2. Pure module `efficiency.py`

Imports only the standard library; receives the time zone (`ZoneInfo`) and `now` as arguments; every datetime
argument must be timezone aware (a naive one raises `ValueError`). It owns:

- Statistics days. A day starts at the first whole UTC hour at or after local midnight; in whole-hour time zones
  that is local midnight, in Asia/Kolkata it is 00:30. Home Assistant groups hourly rows, which start on UTC
  hours, into day and month rows by the local day of their start (`recorder/statistics.py`
  `reduce_day_ts_factory`, `reduce_month_ts_factory`), so these are the only boundaries at which the tables
  telescope. Today is the day that contains now (in a half-hour zone, until 00:30 local still the previous
  day); a month and a year start at the day start of their 1st. A day whose local midnight does not exist starts
  at its first existing hour.
- `Range(source, start, end)`: a half-open UTC range read from one table: `month`, `day`, `hour` or `5minute`.
- `period_ranges(now, tz, effective=None, ...)`: the disjoint, adjacent ranges per period: days up to the next
  month start, whole completed months, completed days of this month, today. A start inside a completed month
  (an effective start, or a rolling start not on the 1st) reads the days of that month from the day table; a
  start on the 1st reads whole months. The rolling start is the same calendar day one year earlier, or the last
  day of that month when it does not exist. `None` for a period that has not begun. `period_starts` gives each
  period's covered start for the `period_start` attribute.
- `effective_start(first_hours, tz)`: the first day start at or after the latest first statistics hour. A
  statistic whose first hour is not known yet (no hourly row, only 5-minute rows) counts as starting now, so its
  service's periods have not begun until the next first-hours refresh.
- `history_windows(...)`: the read window per table, the union over all periods and both series for the given
  effective starts.
- `TableRead(source, window, rows, covered, read_at)`: one cached read of a table (rows `None` when it failed).
- `period_energy(tables, statistic_ids, ranges)`: the summed `change` over rows whose start lies in a range, or `None` when a needed read failed, a range is not inside the window its table was last read for,
  the read does not cover one of the IDs (see hourly-only below), a counted row has `change` `None`, or an ID has
  no rows in any read. A statistic with rows elsewhere but none in a covered range adds 0.
- `ratio(output_kwh, electrical_kwh)`: `round(output / electrical, 2)`, or `None` below 0.1 kWh electricity;
  `period_summary` returns both energies (3 decimals) and the ratio, keeping the energies when the ratio is
  unknown.
- `daily_series` / `monthly_series`: per day (31) and month (24) points, limited by the effective start. A point
  and a period sensor are estimated when their covered start (the period start, or the effective start where it
  cuts the period) lies before the start of the measured-since day (`includes_estimated`).
- Hourly-only statistics. A statistic whose metadata `source` is not `recorder` (an external statistic) has no
  5-minute rows. A service or Overall with such a statistic reads today from the `hour` table. Every service and
  Overall ends all its periods at its coverage end: the earliest end of the last row among its statistics
  (hourly for a service with an hourly-only statistic, 5-minute otherwise), at most now, so a recorder statistic
  whose sensor is offline also cuts the other counters of its service at the same instant; a statistic with no
  row in the today window makes every period of its service unknown.
  A day or month read covers a statistic only when, at the time of that read, the statistic's last row (hourly
  for hourly-only statistics, 5-minute otherwise) ended at or after the end of the read window; periods that need
  an uncovered read are unknown and the read is retried (D4). The hour and 5-minute reads need no coverage: their
  ranges end at the service's coverage end. When an hourly-only service's coverage end lies before today's start,
  every period of that service is unknown; when it equals today's start, today is empty (unknown by the 0.1 kWh
  rule) and the other periods use the completed days.
- `cache_actions(...)`: which reads an update needs (D4).
- `health(statistic_ids, metadata, last_row_end, now)`: per statistic one of ok, missing, not_energy, no_sum,
  stale, checked in that order (a power statistic without a sum is not_energy).

Tests in `tests/test_efficiency.py` cover every spec scenario that does not need Home Assistant, including the
DST days, a half-hour time zone, 1 January, the 1st of a month, leap days, the mid-day history start, an
effective start that moves after a backfill, and a lagging hourly-only statistic.

### D3. Reads: four tables, units fixed

Per heat pump all mapped IDs are read together, one call per range kind, with `types={"change"}` and
`units={"energy": "kWh"}`, on the recorder executor:

- months: `period="month"`, from the earliest needed month start (24 months back for the series) to the current
  month start;
- days: `period="day"`, from the earliest needed day (31 days back, the rolling start, the current month start,
  or the days of an older month cut by an effective start, up to 24 months back) to today's start;
- today: `period="5minute"`, from `min(today's start, now - 3 h)` to now; rows before today's start serve only
  the staleness check and the coverage;
- hours: `period="hour"`, only when a service has an hourly-only statistic, over the same window as today.

The windows come from `history_windows` (D2) and are half-open; an end that is not reduced by 1 s only adds a
running day or month row that no range counts. Each period sums the rows of its disjoint ranges (D2), which
telescope exactly because each table's `change` is taken against the previous row of the same table
(`_augment_result_with_change`). 5-minute rows cover only today because the short-term table is purged. First statistics hours come from one `period="month"` read for all IDs from one month before the start of
the month window that `history_windows` gives without an effective start (a first hour before it cannot change any
period or series; the extra month keeps a missing hourly row at that start from cutting the oldest month), then a `period="day"` and an `"hour"` read per ID inside its first month and day; they are refreshed with
the completed history. A failed first-hours read is retried at every update; until the first successful read it
makes the services of the affected IDs unknown, and after that the last good first hours are kept (a backfill that
moves a first hour shows once a refresh succeeds). Decided at the final whole-change review (2026-11-19).
Until metadata has been read successfully once, every service is unknown, because whether a statistic is
hourly-only is not known.

### D4. Coordinator with a fixed schedule and a cache

One `DataUpdateCoordinator` per entry with `update_interval=None`, driven by
`async_track_utc_time_change(minute=range(0, 60, 5), second=30)` (20 s after the compile and its commit), at
setup, and on reload. `entry.runtime_data` holds it; the tracker is removed via `entry.async_on_unload`.

Cache: per table the window it was read for, the rows, and which statistics the read covers (D2). Metadata is read
at every update (`async_list_statistic_ids` is served from the recorder's metadata cache on the loop when every ID
is cached); a failed metadata read keeps the last good metadata, and `first_hours_read_at` depends on the first
hours alone. Months, days and first hours are read at setup and when the entry reloads; days and first hours
again at the first update of a new day (today's start, D2), and months at the first update of a new month (the calendar
month changed, which also covers a missed update). A cached table is also read again when the window now needed
is not inside the cached window (the effective start moved after the daily first-hours refresh, for example after
a backfill), when its last read failed, or when its last read did not cover every mapped statistic (a half-hour
time zone before the first hourly row of the day is compiled, or a lagging external statistic); such a retry
happens at every update until it succeeds. `cache_actions` decides this from the cache state, the needed windows
and the day and month of `now`. On a new day the coordinator calls it twice: the first call asks for first hours,
and the second, with the windows recomputed from the new first hours, returns the tables to read. Every update reads today's 5-minute rows, and hourly rows when a service has an
hourly-only statistic. A failed or uncovered read marks only the periods that need it as `None` (spec "Never a
partial figure"); the coordinator does not raise `UpdateFailed`, so sensors stay available and show unknown. A
backfill is picked up by the daily first-hours refresh, and at once by reloading the entry.

### D5. Entities

One device per entry (`DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=<entry title>,
entry_type=DeviceEntryType.SERVICE)`). Per configured service and Overall four sensors (`today`,
`month_to_date`, `year_to_date`, `rolling_12_months`), `has_entity_name` with translation keys such as
`hot_water_month_to_date`, `state_class=MEASUREMENT`, no unit, `suggested_display_precision=2`, value a float or
`None`. Attributes: `output_energy`, `electrical_energy` (kWh, 3 decimals), `period_start` (ISO, effective),
`includes_estimated`. The today sensor carries `daily` and the month-to-date sensor `monthly`
(`[{"start": ISO, "efficiency": float, "estimated": bool}, ...]`), both in `_unrecorded_attributes` as a class
attribute. Unique IDs `<entry_id>_<service>_<period>`, so entity IDs survive mapping changes. At setup the
sensor platform removes this entry's own entity registry entries whose unique ID is no longer expected
(`helpers/entity_registry.py` `async_entries_for_config_entry`, `EntityRegistry.async_remove`), so a service
removed from the mapping loses its sensors instead of leaving unavailable entities.

### D6. Config flow and options flow

Config flow step `user`: name, then one section per service and Overall (`data_entry_flow.section`, collapsed
except Heating and Overall) with `output` and `electricity` (`StatisticSelector(multiple=True)`) and
`measured_since` (date selector, optional); a collapsed section `planned` with `price` (entity selector, optional)
and `defrost_heat` (statistic selector, optional). Validation via `async_list_statistic_ids`: exists, `has_sum`,
`unit_class == "energy"`, checked in that order with `health` (D2); the rules live in the pure module
`validation.py` (standard library only, tested like `efficiency.py`). Errors are keyed by the section, because
Home Assistant shows errors per top-level form key and the frontend's expandable section does not pass errors to
its fields (core `mqtt/config_flow.py` does the same); each names the failing statistics or the missing field,
one per section in the order missing, not energy, no sum, electricity missing, output missing. An empty mapping
is an error on `base`, and a name of only spaces is `name_required`. A statistic with an energy unit but
`unit_class` `None` is rejected as not energy (rare: migration and imports fill `unit_class` from the unit).
External statistics (`source` not `recorder`) are accepted and read hourly (D2). The name goes to `data`, the
mapping to `options`, nested per section like the form, with empty values and unconfigured services dropped; a
measured-since date alone does not configure a service and is not kept. Options flow `OptionsFlowWithReload` with the same
schema and suggested values; no update listener. Strings in `translations/en.json` only (`strings.json` is
core-only). Alternative: an `EntitySelector` filtered by energy device class; rejected because it hides external
statistics and filters on entity state, not statistics.

### D7. Health and repairs

At every cache refresh and every update, each mapped statistic's health (D2) is evaluated from the metadata and
the end of its last row in the table it is read from (5-minute, or hourly for an hourly-only statistic); stale is
a last row that ended more than 2 hours ago, or no row in the staleness window. One non-fixable issue per entry and statistic,
`issue_id = f"{entry_id}_{statistic_id}"`, severity warning, `config_entry_id` set, translation keys
`statistic_missing`, `statistic_no_sum`, `statistic_not_energy`, `statistic_stale` (with the last statistics
time) and `statistic_stale_no_rows` (no statistics today or in the last 3 hours), with placeholders for the heat
pump name and statistic ID; deleted when healthy, at the next check because metadata is read at every update
(D4). The decisions live in the pure `repairs_model.py`; `issues.py` applies them to this entry's own issues and
never fails the update. Until metadata has been read once nothing is classified and only issues of statistics
no longer mapped are deleted; a statistic whose own 5-minute or hourly read failed is not judged stale. The cost
and defrost slots are not checked (not used yet).

### D8. Diagnostics and documentation

`diagnostics.py` returns the options, the metadata of the mapped statistics, the last query windows, the cached
energies per period and the last error per read; nothing is redacted because the data holds no secrets. The
README covers install (HACS custom repository or manual copy), setup, definitions, the period and history rules,
the attributes, example cards (entities, an apexcharts-card chart reading `daily` and `monthly` with
`data_generator` returning attribute points, no statistics `mean`), troubleshooting with repairs and diagnostics,
and the Ecoforest ecoGEO mapping as a labelled example.

## Risks / Trade-offs

- [`statistics_during_period` is not a documented public API and may change] -> `hacs.json` pins the minimum
  version; the design cites the 2026.11.2 signature; diagnostics show read errors.
- [The first update after midnight runs before yesterday's last hourly row is committed] -> The completed-day
  read happens at 00:00:30 after the 00:00:10 compile, which also writes the hourly row for 23:00; the live group
  checks yesterday's total against a direct statistics read, and a missing day row falls back to unknown, not to
  a partial figure.
- [The today read lacks the current 5-minute period] -> Accepted; the figure is at most one 5-minute period old.
- [A mapped statistic restarts at 0 with a gap (no previous row in the short-term table after a long outage)] ->
  Its first 5-minute `change` equals its whole sum; rare, documented in the README troubleshooting.
- [Rolling 12 months and the series read up to 24 months of month rows once per day] -> Bounded and cached.
- [A mapped statistic that has stopped, or has no rows, is never covered, so the day and month reads are
  retried at every update while it lasts] -> Accepted: the reads are bounded (at most 24 month rows and about
  730 day rows per statistic, the latter when an effective start cuts a month 24 months back; Home Assistant
  builds them by reducing the hourly rows of the window, so about 27 000 hourly rows per statistic are streamed
  per retry); per-statistic coverage or a backoff is a possible follow-up, and the stale or missing repair issue (D7) tells the owner.
- [An external statistic that is routinely more than 2 hours behind (for example a utility import a day late)
  leaves every period and series point of its service or Overall unknown and its stale issue raised] ->
  Accepted for this change; the README troubleshooting states that an external statistic must be at most 2 hours
  behind. Ending such a service's periods at its coverage end before today is a possible follow-up change.
- [A backfill or meter junction can give a negative period energy, and a period starting at an imported
  statistic's first hour counts that row's whole sum when the import is not 0-based (`_augment_result_with_change`
  uses 0 without an earlier row)] -> No guard in this change; the live group compares the oldest monthly point and
  any junction day with a direct statistics read, and a follow-up treats a negative period energy as unknown if it
  occurs.
- [Default entity IDs depend on the device name, area and Home Assistant language at first registration] ->
  Unique IDs keep them stable afterwards; the README names the default pattern.

## Migration Plan

Install on the live installation in the final task group (copy, restart with a backup offered, add the entry,
verify, then the dashboard). Rollback: remove the config entry and the folder, restart, restore the saved
dashboard config.

## Open Questions

- The GitHub repository URL and code owner handle for `documentation`, `issue_tracker` and `codeowners` in the
  manifest and `hacs.json`; placeholders until the user supplies them before publishing.
