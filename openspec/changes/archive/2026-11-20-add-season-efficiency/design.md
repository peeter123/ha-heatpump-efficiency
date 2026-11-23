# Design

## Context

See proposal.md - Why. The integration (archived change `2026-11-19-add-efficiency-integration`, its design D1 to
D8) computes every period from cached table reads: `efficiency.py` `period_ranges` builds disjoint ranges (days of
a partial first month, whole months, completed days, today) and `period_summary` sums the rows' `change`. The
engine (`engine.py`) reads through an injected `Reader` whose `read(source, ids, window, units, types)` wraps
`statistics_during_period`. Facts that shape this change, all ha-core at tag 2026.11.2:

- `recorder/statistics.py` `statistics_during_period(hass, start_time, end_time, statistic_ids, period, units,
  types)` accepts `types` `{"change", "last_reset", "max", "mean", "min", "state", "sum"}`; with `period="hour"`
  it returns the hourly rows with `start` in `[start_time, end_time)`, each with its running `sum` converted by
  `units`. Hourly statistics are kept; only the short-term table is purged (archived design, Context).
- `recorder/statistics.py` `statistic_during_period(hass, start_time, end_time, statistic_id, types, units)`
  computes `change` as a newest minus an oldest `sum` (`_get_newest_sum_statistic`, `_get_oldest_sum_statistic`).
  When a statistic's hourly and 5-minute histories start within an hour of each other it takes a head from the
  short-term table up to the end of that first hour, not up to `end_time`, and a missing row at the start is
  replaced by the next row after it. Both differ from the telescoping of the day and month `change`, so it is not
  used (D3).
- `sensor/recorder.py` `_update_issues`: a recorded sensor whose state unit no longer matches its statistics
  metadata unit, without a unit converter for either, gets the issue `units_changed` (`is_fixable=False`, severity
  warning, domain `sensor`); `_normalize_states` logs that long-term statistics are suppressed while the unit is
  unstable and links to the statistics developer tools (`LINK_DEV_STATISTICS`).
- `sensor/entity.py` validates `native_unit_of_measurement` only against `DEVICE_CLASS_UNITS` of a device class;
  a sensor without a device class may use any unit, such as `BTU/Wh`.
- `config_entries.py` `ConfigEntry.async_migrate`: an entry whose `minor_version` differs from the handler's
  `MINOR_VERSION` at the same `VERSION` calls the integration's `async_migrate_entry(hass, entry)`;
  `ConfigEntries.async_update_entry(entry, *, options=..., minor_version=...)` stores the result.
- `core_config.py` `Config.latitude` (float, 0 when not set).
- `helpers/selector.py` `SelectSelector` (`options`, `mode` dropdown, `translation_key`) and `NumberSelector`
  (`min`, `max`, `step`, `mode` box).

## Goals / Non-Goals

**Goals:**

- Season figures that equal the sum of their days exactly, by the same day boundaries as every other period.
- A season history of any length that costs a few small reads once, not a long day read at every refresh.
- All season and unit arithmetic in Home Assistant-free modules with standard-library tests.

**Non-Goals:**

- Rated SCOP or SEER (reference climate, bin method), a Hot water season or a cooling-season Overall.
- Converting, relabelling or deleting statistics, including the Cooling sensors' own.

## Decisions

### D1. Season dates: storage, defaults and validation

Stored in the entry options as a section `seasons` with four `MM-DD` strings: `heating_start`, `heating_end`,
`cooling_start`, `cooling_end`. The form section `seasons` (collapsed) has per date a month `SelectSelector`
(dropdown, options `1` to `12`, `translation_key` `month`) and a day `NumberSelector` (1 to 31, step 1, box);
`validation.py` converts between the form fields and the stored strings and validates: a day that does not exist
in its month, a non-integer day, or 29 February, is `season_invalid_day`; a date with an empty month or day is
`season_missing` (all four dates are always stored; group 2 review, 2026-11-20); a start equal to its end is
`season_same_day`; all are
keyed on the `seasons` section like the existing per-section errors (archived D6). Defaults, a pure function
`default_seasons(latitude)` in `seasons.py`: latitude >= 0 (0 is also Home Assistant's unset value) gives heating
`10-01` to `04-30` and cooling `06-01` to `09-30`; below 0 heating `04-01` to `10-31` and cooling `12-01` to
`02-28`. The config flow and the options flow use the stored dates as suggested values, or the defaults for
`hass.config.latitude` when none are stored. Alternative: a `DateSelector`; rejected because it asks for a year.
Alternative: computing the defaults at every load; rejected because a change of the home location would move the
seasons silently.

### D2. Migration of existing entries

`ConfigFlow.MINOR_VERSION = 2` (`VERSION` stays 1, so an older integration version still loads the entry and
ignores the `seasons` key). `__init__.py` `async_migrate_entry`: for `minor_version < 2` it adds
`default_seasons(hass.config.latitude)` to the options when no `seasons` are stored (stored dates are kept), keeps
every other key, and calls
`async_update_entry(entry, options=..., minor_version=2)`. The options flow is not involved, so no reload is
triggered by the migration itself.

### D3. Season arithmetic, a new pure module `seasons.py`

Standard library only, imports `efficiency.py` (pure) for `day_start`, `statistics_day`, `Range`, the ratio and
the estimated rule; `efficiency._cover` becomes the public `cover`. Inputs are the four `MM-DD` dates, `now`, the
time zone, the service's effective start and measured-since date.

- `Season(start_day, end_day)`: dates; the UTC range is `[day_start(start_day), day_start(end_day + 1 day))`, so
  it telescopes with days and months. Crossing the new year when the start's `(month, day)` is after the end's.
  An end on 28 February includes 29 February in a leap year (the next day is 1 March).
- `seasons_since(dates, effective, now, tz)`: every season from the one containing the effective start's day (or
  the first one that starts after it) up to the one that contains today or ended last; oldest first; empty when
  none has begun. The covered start is the later of the natural start and the effective start (archived D2
  `effective_start`), `complete` is covered start == natural start, `ended` is natural end <= today's start.
  Unlike `period_ranges`, where an effective start of None means no limit, `seasons_since` returns no season for
  None: the engine gives None only when no statistic of the service has rows, so the service is unknown either way,
  and a season list needs a known history start. Decided at the group 1 review (2026-11-20).
- The running season (not ended) is a period like year to date: `efficiency.period_ranges`-style ranges from its
  covered start to the service's coverage end (archived D2), summed by `period_summary` from the cached month,
  day and today tables. `history_windows` includes the running season's start, so the month and day windows
  cover it (at most about 12 months back, already inside the rolling 12 months and the 24-month series).
- A finished season is computed from boundary readings (D4): per statistic `reading(end) - reading(start)`,
  summed per side, then `ratio`. `reading(b)` is the `sum` of the newest hourly row that starts before `b`, or 0
  when the statistic's first statistics hour is at or after `b`. This equals the sum of the hourly `change`
  over `[start, end)`, because each hourly `change` is the row's `sum` minus the previous row's (0 without one,
  `_augment_result_with_change`), and day and month rows are reductions of the hourly rows; so a finished season
  equals its days, and a statistic without rows in the season adds 0, as for any other period.
- `season_points(...)`: per season `start` (covered start, ISO in the time zone), `end` (natural end, ISO),
  `efficiency` (None when unknown), `output_energy`, `electrical_energy` (kWh, 3 decimals), `estimated`
  (`includes_estimated` of the covered start), `complete`, `ended`. The sensor state is the last point.

Tests in `tests/test_seasons.py`: both hemispheres, crossing the new year, a leap year end of February, a
half-hour time zone, a DST day as a boundary, a cut first season, a history with no season begun, the readings
against a day-by-day sum of the same synthetic rows, and the 0.1 kWh rule.

### D4. Boundary readings: read, cache and refresh

One read per boundary instant for all statistics of the services that use it: `Reader.read("hour", ids,
Window(b - 31 days, b), {"energy": "kWh"}, {"sum"})`, the newest row per statistic is its reading. A boundary is a
finished season's covered start or natural end. Cached in `EngineState.boundaries` as `{b: BoundaryRead}` (its
fields as settled below). A reading counts for a statistic only when it is covered: the statistic's
last row (`last_row_ends`, archived D2) ended at or after `b` at read time, and it has a row in the 31-day window
or its first statistics hour is at or after `b`. A failed or uncovered reading makes the seasons that need it
unknown; when it is read again is settled below. `boundary_actions` decides the
reads: a boundary not in the cache; a failed or pending one (below); one whose `read_at` lies before `b` + 1 day, read
again at the first update of the next day (the first update after midnight runs 20 s after the hourly row for 23:00
is compiled, the archived risk for completed days); and all of them when the first statistics hours change or
the entry reloads (the cache is lost on reload by design). Alternative: the existing month and day tables over
the whole history; rejected because each table is one contiguous window, so a history of N years streams about
N x 8760 hourly rows per statistic per refresh. Alternative: `statistic_during_period`; rejected (Context).

Settled at the group 3 review (2026-11-20):

- `BoundaryRead` holds the readings computed at read time (`seasons.boundary_reading` with that update's
  `last_row_ends` and first hours), per statistic a `sum`, or a reason when there is none: `pending` (the
  statistic's last row ended before `b`, or it has no 5-minute rows), or `no_row` (its last row ended at or after
  `b` and it has no row in the 31-day window while its first hour is before `b`). A failed read (exception) has no
  readings. Retries: a failed read at the next update; a `pending` reading only at an update where that statistic's
  last row ends at or after `b`; a `no_row` reading is final, like a good one, until the first hours change or the
  entry reloads. Either way the seasons that need it stay unknown. So a statistic with a gap of more than 31 days
  before a boundary, or a dead mapped statistic, causes no read at every update. This is the spec's "incomplete
  read": `pending` is read again, `no_row` cannot improve by reading again.
- The next-day re-read runs when `read_at < b + 1 day <= now`. When a re-read fails, the earlier good readings
  are kept and the rule that asked for it asks again at the next update; after a change of first hours they are
  not.
- The first hours need the whole history once a service has a season: with the archived window of about 25
  months, a longer history gives a false first hour and drops the oldest seasons. The first successful read
  after a load reads `month` over `[2000-01-01 UTC, now)`; later daily refreshes read `month` only from
  2000-01-01 UTC to the end of the month of the latest known first hour, which still sees a backfill that moves
  a first hour earlier. A statistic with no row in that bounded window, such as one whose earliest rows were
  removed, gets the full read again. Without a season the archived window is unchanged.

### D5. Cooling efficiency unit

Stored in the Cooling section as `unit`: `w_per_w` (default, also when absent) or `btu_per_wh`, a
`SelectSelector` with `translation_key` `cooling_unit`; `normalize_mapping` keeps it only when Cooling is
configured and drops the default. `efficiency.ratio(output, electrical, factor=1.0)` multiplies before rounding
to 2 decimals; the 0.1 kWh rule is checked on the electrical energy first. `BTU_PER_WH = 3.412142` (derived:
1 W = 3.412142 BTU/h, International Table BTU). The engine passes the factor for the Cooling service to its
periods, daily and monthly series and season points; Overall and the other services use 1.0. The Cooling sensors
get `native_unit_of_measurement = "BTU/Wh"` in BTU/Wh and `None` in W/W, so W/W entities are unchanged.

### D6. Warning step before a cooling unit change

In the options flow, after validation, when Cooling stays configured and the submitted Cooling unit differs from
the stored one (removing Cooling removes its sensors, so no warning): the flow looks up the entity IDs of this
entry's Cooling sensors in the entity registry by unique ID (`helpers/entity_registry.py`
`EntityRegistry.async_get_entity_id(domain, platform, unique_id)`) and reads their stored statistics metadata with
`recorder/statistics.py` `get_metadata(hass, statistic_ids=...)` on the recorder executor
(`get_instance(hass).async_add_executor_job`); when any has stored metadata it shows step `unit_change` (a form
without fields, description from translations naming the affected sensors through a placeholder); submitting
stores the options, closing the dialog stores nothing. No statistics: store at once. Not
`async_list_statistic_ids`: besides stored metadata it lists every live sensor with a state class whose statistics
will be compiled in the next period (`list_statistic_ids` via the recorder platforms, `sensor/recorder.py`
`list_statistic_ids`), so it would warn before any statistics exist; `units_changed` is raised from the stored
metadata (`sensor/recorder.py` `_update_issues`). Corrected at the group 2 review (2026-11-20). The pure decision
(Cooling configured, unit changed and statistics exist) lives in `validation.py`. The text says Home Assistant
cannot convert the statistics, reports the change as a repair issue, and offers its fix in the statistics
developer tools; the integration changes no statistics.

### D7. Entities

`sensor_model.py`: `SEASONS = {heating: heating_season, overall: heating_season, cooling: cooling_season}`; per
configured service in it one season sensor, unique ID `<entry_id>_<service>_<season>` (for example
`<entry_id>_overall_heating_season`), translation key `<service>_<season>`, `state_class` measurement, 2 decimals,
unit per D5. Attributes: `output_energy`, `electrical_energy`, `period_start` (covered start), `includes_estimated`,
`season_end`, `complete`, `ended`, and `seasons` (the points, in `_unrecorded_attributes`). `stale_unique_ids`
includes the season sensors among the expected IDs. `sensor.py` adds the season entity class; the period sensors
and series of Cooling get the unit and factor of D5. `diagnostics.py` adds the season dates, the boundary reads and
the season points.

### D8. Documentation

README: the season dates and their defaults, the season sensors, state between seasons, history, the `complete`,
`ended` and `estimated` flags, measured versus rated SCOP and SEER, the cooling unit and the warning with Home
Assistant's statistics developer tools, a markdown-card table of `seasons` (one row per season and service, with
efficiency, energies and notes for partial, running and estimated seasons; no statistics `mean`), and the
definitions of a season boundary. Changed at the live check (2026-11-20, user's choice): an apexcharts-card
column chart of `seasons` was replaced, because its shared tooltip groups points by index, so series with
different season counts do not group, and a few seasons read better as numbers with their flags.

## Risks / Trade-offs

- [A season boundary at a time a statistic had no row for more than 31 days] -> The reading is not covered, so
  that season is unknown (never a partial figure); the window is a constant in the pure module.
- [A backfill that rewrites sums without moving a statistic's first hour leaves cached boundary readings stale]
  -> The README already says to reload the entry after a backfill; the reload drops the cache.
- [A dead statistic still mapped (no current rows) makes its running season unknown, and every finished season
  not read before it stopped (`pending` readings) unknown with null figures; finished seasons read while it was
  alive keep their figures until the entry is reloaded] -> Those figures are correct past data, so they are kept
  (final review, 2026-11-20); the period sensors are unknown and its repair issue tells the owner. A service
  that is unknown as a whole (its metadata not read yet, or a mapped statistic's first hour not known) gives its
  season sensor an unknown state and no attributes, so no `seasons` history either; a begun season with an
  unknown efficiency keeps its point (group 4 review, 2026-11-20).
- [The first read after a reload reads every boundary, 2 per season per season kind] -> Each read is at most 744
  hourly rows per statistic; 10 years of history is about 40 reads once.
- [The first-hours read after a load streams the whole hourly history of every mapped statistic, because Home
  Assistant reduces month rows from hourly rows (about 87,600 rows per statistic for 10 years)] -> Once per
  load; the daily refresh reads only up to the month of the latest first hour of all mapped statistics, so
  statistics that started earlier still stream their history up to that month (D4, group 3 review,
  2026-11-20). Grouping the reads by first month would bound it further; not done.
- [Changing the cooling unit raises Home Assistant's `units_changed` issue and stops the compilation of the
  sensors' long-term statistics (`sensor/recorder.py` `compile_statistics`) until the owner fixes them in the
  statistics developer tools or the unit changes back] -> The warning step and the README say so (final
  review, 2026-11-20); those statistics are a time average the integration does not use; the series and season
  points follow the new unit at the reload.
- [An API client that omits the collapsed `seasons` section stores no dates, or drops the stored ones on an
  options change (the season sensors are unknown)] -> Accepted (final review, 2026-11-20): the frontend always submits the section, because it
  carries suggested values.
- [Cooling removed and later added again with BTU/Wh can reuse the old entity IDs, whose unitless statistics still
  exist, while no sensor is registered at the time of the check, so no warning is shown] -> Accepted (group 2
  review, 2026-11-20): Home Assistant still raises its own `units_changed` issue.
- [Changing the season dates changes the `seasons` history at once] -> Intended; the history is recomputed at
  the reload (spec "Mapping changed later").

## Migration Plan

Code: minor version 2 with `async_migrate_entry` (D2); downgrading keeps working because the major version is
unchanged. Live installation in the final task group (copy, restart with a backup offered, check the migrated
options, verify seasons against a direct statistics read, the warning step without saving, optionally a dashboard
card). Rollback: restore the previous integration folder and restart; the `seasons` key is ignored by it.
