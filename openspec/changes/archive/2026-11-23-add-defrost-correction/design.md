# Design

## Context

See proposal.md - Why. The integration (archived changes `2026-11-19-add-efficiency-integration` and
`2026-11-20-add-season-efficiency`, their designs) computes every figure from cached table reads through
`engine.py`: per configured service an `engine.Service` with `output_ids` and `electrical_ids`, whose `ids`
(both together) feed everything: the effective start (`engine._effective`, the latest first statistics hour of
`ids`, moved to the next day start), the read windows (`needed_windows`), the coverage end
(`efficiency.coverage_end`), the hourly reading of external statistics (`efficiency.reads_hourly`), the boundary
reads of finished seasons (`boundaries_needed`) and the health check (`issues.py`). Simply adding a defrost
statistic to `ids` would therefore cut every period of a service to the defrost statistic's first hour, which the
user ruled out. The planned slot `validation.FIELD_DEFROST_HEAT` (in `PLANNED_FIELDS`) is a single statistic,
stored only and never read (`validation.statistic_ids` excludes it). Config entries are at `VERSION` 1,
`MINOR_VERSION` 2 (`config_flow.py`), migrated by `__init__.async_migrate_entry`.

Facts that shape the change, all ha-core at tag 2026.11.2 (cited as in the archived designs, no new API):

- `recorder/statistics.py` `statistics_during_period(hass, start_time, end_time, statistic_ids, period, units,
  types)`: every read already passes `units={"energy": "kWh"}`, so a defrost statistic in Wh or MWh arrives in
  kWh like the output and electrical ones. Each row's `change` is its `sum` minus the last `sum` before the
  aligned start in the same table, else 0 (`_augment_result_with_change`); a statistic has no rows before its
  first statistics hour.
- `recorder/statistics.py` `async_list_statistic_ids(hass, statistic_ids, statistic_type)`: per ID `has_sum`,
  `source`, `unit_class`; what `validation.classify` and `efficiency.health` already use.
- `config_entries.py` `ConfigEntry.async_migrate`: an entry whose `minor_version` differs from the handler's
  `MINOR_VERSION` at the same `VERSION` calls `async_migrate_entry(hass, entry)`, also when the entry's minor
  version is higher (an older integration version then keeps the entry); `ConfigEntries.async_update_entry(entry,
  *, options=..., minor_version=...)` stores the result.
- `helpers/selector.py` `StatisticSelector(StatisticSelectorConfig(multiple=True))` returns `list[str]`;
  `data_entry_flow.py` `section` nests a section's fields.
- `helpers/entity.py` `Entity._unrecorded_attributes` (combined in `__init_subclass__`) and
  `recorder/db_schema.py` `MAX_STATE_ATTRS_BYTES`: the reason `daily`, `monthly` and `seasons` are unrecorded.

## Goals / Non-Goals

**Goals:**

- A correction that changes no figure, read, window or cache decision for an owner who maps no defrost statistic.
- No new statistics read: the defrost statistics join the existing reads, and finished seasons keep their caching
  semantics (design D4 of `2026-11-20-add-season-efficiency`).
- All defrost arithmetic in Home Assistant-free modules with standard-library tests.

**Non-Goals:**

- Detecting whether a heat meter already subtracts defrost heat (the README warns instead).
- Estimating defrost heat before the defrost statistic's first hour, or correcting hourly.

## Decisions

### D1. User decisions (2026-11-22, settled in explore)

Recorded as given; the specs follow them:

- Corrected efficiency = (output - defrost heat) / electricity, the gross defrost heat subtracted, valid per day
  or longer, not per hour.
- (A) Correct in place: with a defrost statistic mapped, the Heating, Hot water and Overall figures (periods,
  daily and monthly series, seasons) are corrected; nothing changes without one. Attributes `defrost_energy`,
  `efficiency_uncorrected`, `defrost_since`; points get `defrost_partial`.
- (Y) A defrost field in the Heating and the Hot water section replaces the planned slot; Overall subtracts the
  sum of both; the same statistic in both sections is rejected; a migration to minor version 3 moves the planned
  value into Heating; the price source stays in the planned section, stored only. Where to map it (README): a
  unit that always takes defrost heat from one circuit by a setting maps it under that service; a reverse-cycle
  unit takes it from the active circuit, so split counters map one per service, and a single counter maps under
  the dominant service (Overall exact, the per-service split approximate); a water-side meter that already counts
  both directions needs no defrost statistic.
- The defrost statistic never moves a service's effective start; before its first hour it counts as 0 kWh, and
  periods and points that start earlier are flagged.
- The repair checks cover the defrost statistics; a broken defrost mapping is visible, never a silent fallback to
  uncorrected figures (D6).
- A corrected output of 0 or less is unknown, with `defrost_energy` still shown. Cooling is never corrected.

### D2. Storage and validation (`validation.py`)

`FIELD_DEFROST_HEAT = "defrost_heat"` moves from `PLANNED_FIELDS` (now `(FIELD_PRICE,)`) into the Heating and Hot
water sections (`DEFROST_SERVICES = (SERVICE_HEATING, SERVICE_HOT_WATER)`), stored as a list of statistic IDs
like `output` and `electricity` (`_ids`), so two defrost counters can be summed. Alternative: a single statistic
as in the slot; rejected because every other energy field takes several and sums them, and a cascade of two units
would need two. `normalize_mapping` keeps a service section when it has an output, electrical or (Heating and Hot
water only) defrost statistic; `measured_since` and the Cooling `unit` are kept only with an output or electrical
statistic, since a defrost field alone does not configure a service (`configured_services` is unchanged). A
`defrost_heat` submitted for Cooling, Overall or the planned section is dropped. `statistic_ids` now includes the
defrost IDs, so the form validates their metadata with `classify` (missing, not energy, no sum, named per section
in the existing placeholders); `nothing_mapped` is based on the output and electrical IDs only, so a form with only
a defrost statistic still gets it. New pure helper `defrost_ids(mapping, service)`: the stored IDs of
that section, empty for Cooling and Overall.

New errors, keyed on the section of the defrost field, after the existing ones in `_ERROR_PRIORITY`:

- `defrost_duplicate` (placeholder `duplicate`, the failing IDs per section as in `validate`): a defrost ID in
  both sections, or one that is also an output or electrical ID of any section.
- `defrost_unused`: a defrost ID in the section of a service that is not configured while Overall is not
  configured either, so it corrects nothing. Alternative: requiring the section's own service; rejected because
  an owner with one heat meter and one electricity meter (Overall only) could then not correct at all.

`electricity_missing` and `output_missing` apply only to a section with an output or electrical statistic, so a
defrost-only section gets neither (for existing mappings nothing changes: such sections were dropped before).

### D3. Migration to minor version 3

`ConfigFlow.MINOR_VERSION = 3` (`VERSION` stays 1). Pure `with_defrost_moved(options)` in `validation.py`: when
the planned section holds `defrost_heat` (the slot's single ID, or a list), it is added to the Heating section's
`defrost_heat` list (creating the section when absent, de-duplicated), removed from the planned section, and the
planned section is dropped when it is then empty; every other key is kept unchanged. A moved ID that is also an
output or electrical ID of any section is dropped instead of moved, since it would be a `defrost_duplicate` that
makes Heating subtract its own output with no repair issue to explain it (decided 2026-11-23 in the final review).
`async_migrate_entry` runs
the steps in order: `minor_version < 2` adds the season dates (unchanged), `minor_version < 3` moves the slot,
then one `async_update_entry(entry, options=..., minor_version=3)`. An entry whose Heating and Overall are both
unconfigured gets the defrost value in a Heating section that corrects nothing; it is ignored by the engine and
the health check (no service uses it), and the options form shows `defrost_unused` when the owner next saves.
Downgrading keeps working: an older version calls its own `async_migrate_entry`, which does nothing for minor 3,
and its `normalize_mapping` ignores the unknown `defrost_heat` key.

### D4. A correction, not an input (`engine.py`)

`Service` gets `defrost_ids: tuple[str, ...] = ()` and the property `all_ids` (`ids` plus `defrost_ids`); `ids`
stays output plus electrical. `services_of`: Heating gets `defrost_ids(mapping, heating)`, Hot water its own,
Overall the union of both in form order, Cooling none. Which set each rule uses:

| Rule | Set | Why |
| --- | --- | --- |
| Effective start and read windows (`_effective`, `needed_windows`) | `ids` | a defrost statistic never moves or widens them |
| Whether every first hour is known (`_effective`'s `known`) | `all_ids` | flags need the defrost start |
| Metadata, first hours, `5minute`, `hour`, `day`, `month` reads, coverage of history reads | `all_ids` | complete reads (D6) |
| `coverage_end`, `reads_hourly`, `_read_ids` | `all_ids` | the end at the last common statistics, external statistics hourly |
| `boundaries_needed` (finished seasons) | `all_ids` | the defrost readings join the same boundary read |
| Health check (`issues.py`) | `all_ids` of every service | D9 |

Zero before the first hour: `efficiency.period_energy` adds 0 for a statistic without rows in a range (it has no
rows before its first hour), and the defrost statistic's first hour itself counts from its baseline (D12). The
defrost start of a service, `efficiency.defrost_start` (D5), takes the first
hours of its defrost statistics as `_effective` does: a known hour as is; a statistic with rows in this update's
5-minute or hour read but no hourly row yet counts as starting now (so every period and point is
`defrost_partial` until the next first-hours refresh, while today's defrost heat is subtracted); one without rows
is left out (its service is unknown through `coverage_end`). The boundary reads of finished seasons treat such a
statistic the same way: its first hour counts as now, so every past boundary reads 0.0, while `BoundaryRead`
keeps the raw first hour so the next first-hours refresh re-reads the boundaries. A service that reads hourly (an
external statistic among its `all_ids`, for example Overall with an external output statistic) has no hourly row
of a newly mapped defrost statistic until the recorder compiles its first hour, so its figures are unknown for at
most about an hour, as for a newly mapped output or electrical statistic (decided 2026-11-23 in the group 2
review).

Reads and caches. No new read and no new cache entry: the defrost IDs are more statistics in the existing reads,
`EngineState.tables`, `cache_actions` and `EngineState.boundaries` work as before, and a `BoundaryRead` carries
the defrost readings, reasons (`pending`, `no_row`) and first hours like the others, so a finished season is
still read once and re-read by the same rules. One adjustment keeps the bounded first-hours refresh bounded:
`first_hours_window` ends at the month of the latest known first hour, and a recent defrost statistic would make
that the current month, so the daily refresh would stream the whole hourly history of every output and electrical
statistic. `_refresh_first_hours` therefore calls `read_first_hours` per group, the output and electrical IDs and
the defrost IDs, each with the known first hours of its own group; `first_hours_read_at` moves only when both
succeed. Without seasons both groups read the same fixed window (one extra small read per day). A defrost first
hour older than that window is reported as its start, which flags no period or point inside the windows.

`PeriodResult` and `SeasonResult` get `defrost_energy`, `efficiency_uncorrected`, `defrost_since` (ISO in the time
zone, set only when the covered start lies before the defrost start) and `corrected` (the service has defrost
IDs), all defaulting to no correction; `ServiceResult` gets `defrost_ids` and `defrost_start` (ISO) for the
diagnostics.

### D5. Arithmetic (pure, `efficiency.py` and `seasons.py`)

- `efficiency.corrected_ratio(output_kwh, defrost_kwh, electrical_kwh, factor=1.0)`: None when an energy is None,
  the electrical energy is below 0.1 kWh (checked first, the rule of `ratio`), or the unrounded output minus
  defrost is 0 or less; else `round((output - defrost) / electrical * factor, 2)`. The 0.1 kWh rule stays on
  electricity only: it guards against a tiny divisor, while a small positive corrected output is a real, low
  figure (spec "Small corrected output"). Inputs: the three energies in kWh and the unit factor.
- `efficiency.defrost_start(first_hours, now)`: the latest end of the defrost statistics' first hours (a first
  hour plus one hour, since a statistic counts from the end of its first hour, D12), not moved to a day start, so
  `defrost_since` is the point from which the counter is counted. Inputs: aware datetimes or epoch seconds, and
  None for a statistic with rows but no hourly row, which counts as `now` (not plus one hour). None for no hours.
- `efficiency.defrost_partial(covered_start, defrost_start)`: covered start before the defrost start; False when
  either is None.
- `period_summary(..., defrost_ids=())`: with defrost IDs it also returns `defrost_energy` (`period_energy` of
  the defrost IDs, 3 decimals) and `efficiency_uncorrected` (`ratio`), and `efficiency` from `corrected_ratio`;
  without them its result is unchanged.
- `_points`, `daily_series` and `monthly_series` get `defrost_ids=()` and `defrost_start=None`: with defrost IDs
  a point's efficiency is `corrected_ratio` (no point when unknown, never 0) and it carries `defrost_partial` of
  its covered start (`ranges[0].start`, the same start as `estimated`).
- `seasons.season_points(..., defrost=None, defrost_start=None)`: `defrost` is one defrost energy per season or
  None (no defrost statistic, points unchanged); with it each point gets `defrost_energy` (3 decimals),
  `defrost_partial` of its covered start, and `efficiency` from `corrected_ratio`. The engine passes
  `seasons.season_energy` of the defrost IDs for a finished season and `period_energy` for the running one.

Tests: `tests/test_efficiency.py` and `tests/test_seasons.py` for the `defrost-correction` and `period-efficiency`
scenarios that need no Home Assistant; `tests/test_engine.py` with the fake reader for the engine rules (D4, D6).

### D6. Behind or missing: unknown, never a fallback

A defrost statistic is treated like the output and electrical statistics of its service, except for the start.
Behind: the service's periods end at its last statistics (`coverage_end`), today is unknown when that lies before
today's start, and after 2 hours a repair issue names it. Missing, without rows, not an energy statistic or
without a sum: `coverage_end` or `period_energy` gives None, so the corrected figures are unknown, and the repair
issue says why. A history read that did not cover it is read again, as for any mapped statistic. Alternative:
falling back to the uncorrected figure; rejected (user, 2026-11-22) because it would shift every figure by the
defrost share without notice and hide the broken mapping. `efficiency_uncorrected` stays available as an
attribute wherever the output and electrical energies are known.

### D7. Entities and attributes (`sensor_model.py`, `sensor.py`)

No new entity, unique ID, unit, state class or precision. `period_attributes` and `season_attributes` add, when
`corrected`, `defrost_energy` and `efficiency_uncorrected`, and `defrost_since` when it is set
(`ATTR_DEFROST_ENERGY`, `ATTR_EFFICIENCY_UNCORRECTED`, `ATTR_DEFROST_SINCE`). `output_energy` stays the measured
output, so the state equals (`output_energy` - `defrost_energy`) / `electrical_energy` up to rounding. The new
attributes are scalars and are recorded like `output_energy`; `daily`, `monthly` and `seasons`, whose points grow
by `defrost_partial` (and `defrost_energy` for seasons), stay in `_unrecorded_attributes`.

### D8. Diagnostics

`engine.diagnostics_data` adds per service `defrost` (`ids`, `since`) and, for corrected services, the
`defrost_energy`, `efficiency_uncorrected` and `defrost_since` of each period and season; the boundary reads
already list every statistic's reading. `diagnostics.py` is unchanged apart from its docstring; the options it
shows include the defrost fields.

### D9. Repairs

`issues.py` checks `all_ids` of every service from `engine.services_of` (moved into a pure helper
`engine.mapped_ids(mapping)` so a test covers it), so a defrost statistic gets the same issues as any mapped
statistic. The issue texts already say "the sensors that use it"; only the README's "Only the output and
electrical statistics are checked" changes. A defrost value that corrects nothing (D3) is not checked.

### D10. Form and translations

`config_flow.py`: `_service_schema` adds `vol.Optional(FIELD_DEFROST_HEAT): _STATISTICS` for Heating and Hot
water; `_planned_schema` keeps only the price source. Strings in `translations/en.json` (the integration ships no
`strings.json`, as in the archived changes), in both `config.step.user` and `options.step.init`: the
`defrost_heat` label and description in the Heating and Hot water sections (it subtracts the heat a defrost takes
from that circuit; a field alone does not configure the service but corrects Overall; leave it empty when the heat
meter already counts both directions), the Heating and Hot water section descriptions, the planned section
description with one slot, the options step description, and the errors `defrost_duplicate` (with
`{duplicate}`) and `defrost_unused`. `tests/test_integration_files.py` checks them like the other keys.

### D11. Documentation

README: the defrost field in the setup list, where to map it (D1), the double-counting warning, the firmware's
`Total Defrost Energy` as a labelled firmware-entity example under the existing example mapping (Heating,
counting since 18 November 2026, no backfill, so earlier periods are `defrost_partial`), the correction under
Definitions with its limits (per day or longer; before the first hour 0), the attributes and flags, the repairs
and the diagnostics, the migration of the planned slot, and a `defrost_partial` note in the example season table.

### D12. Baseline of a defrost statistic (decided 2026-11-23 in the final review)

Home Assistant computes the `change` of a statistic's first row in a table against a previous sum of 0
(`_augment_result_with_change`, Facts), so the row that holds a statistic's first hour carries its whole first
`sum`. A recorder-compiled statistic starts its sum at about 0, but an external or imported one can start at any
value (for example 500 kWh), and every period, point and season spanning its first hour would then subtract that
value. The output and electrical statistics never meet this, because their effective start lies after their first
hour; a defrost statistic is exempt from that start (D4), so it gets a baseline instead.

- Baseline: the `change` of the statistic's first hourly row in the first-hours read (`engine._first_hour`
  already reads that day's hourly rows with `change`), which equals that row's `sum` because no row precedes it.
  No new read and no new read type. `read_first_hours` returns it next to each first hour; `EngineState` keeps it
  with `first_hours` (refreshed with them), and a statistic with a None first hour has none.
- The statistic counts from the end of its first hour: in `efficiency.period_energy`, given the defrost
  statistics' first hours and baselines, the change of the hour, day or month row that holds the first hour is
  reduced by the baseline (so the first hour row itself adds 0), and a 5-minute row that starts inside the first
  hour adds 0. `seasons.boundary_reading` returns the baseline instead of 0.0 when the first hour is at or after
  the boundary. The same functions serve the periods, the daily and monthly points and the running and finished
  seasons, so every figure agrees.
- `defrost_start` is the end of the first hour (D5), so `defrost_since` and `defrost_partial` name the point from
  which defrost heat is counted.
- Without seasons, a first hour older than `first_hours_window` is reported at the window start (D4); its
  "baseline" is then that hour's ordinary change, but no read range or boundary reaches back to it, so it changes
  nothing. With seasons the window reaches the real first hour.
- A statistic with rows but no hourly row yet (first hour None) has no baseline: its 5-minute changes count from 0
  as before. That case occurs only for a recorder statistic, whose sum starts near 0; when its first hourly row
  appears, the energy of that first hour stops being counted.
- Accepted as is (group 6 review, 2026-11-23): a first hourly row without a `change` gives no baseline, so the
  statistic is not reduced (only possible for a row without a sum, which `has_sum` statistics do not have); and
  without seasons, a defrost statistic older than `first_hours_window` with a gap of more than about a month at
  the window start gets a reported first hour inside the read ranges, which drops one ordinary hour and sets the
  flags from there, as the same gap already moves the effective start of an output or electrical statistic.
- Inputs: the first hour, the baseline, the table rows and ranges or the boundary rows; pure functions in
  `efficiency.py` and `seasons.py`, unit-tested. Diagnostics show each defrost statistic's baseline next to its
  first hour.

Alternative: documenting the limitation; rejected by the user (2026-11-23), since an imported or external defrost
counter would otherwise make every period that spans its first hour far too low.

## Risks / Trade-offs

- [The defrost heat inside a defrost statistic's first hour is not counted (D12)] -> At most one hour of a new
  counter; `defrost_since` names the end of that hour.
- [A backfill that changes a defrost statistic's first sum without moving its first hour] -> The baseline is read
  again at the next daily first-hours refresh; finished seasons keep their cached readings until the first hour
  moves or the entry is reloaded, as for any statistic.

- [A water-side heat meter that already subtracts the reverse flow, with a defrost statistic also mapped, is
  corrected twice] -> The README and the field description warn; the integration cannot tell.
- [A single defrost counter on a reverse-cycle unit mapped under the dominant service makes the per-service split
  approximate] -> Documented; Overall, which subtracts the sum, is exact.
- [Short periods: a defrost's heat is counted at once while the reheating after it is counted over the next hours,
  so today can dip right after a defrost] -> Accepted (user: valid per day or longer); no hourly figure exists.
- [Periods and seasons before the defrost statistic's first hour are uncorrected (0 subtracted) and look better
  than later ones] -> Flagged by `defrost_since` and `defrost_partial`; no estimate is made.
- [A defrost counter that restarts at 0 after a gap] -> As for any statistic (README "A statistic restarts at 0").
- [Removing the defrost statistic from the mapping returns the figures to uncorrected] -> Intended; the entry
  reloads and the attributes disappear.
- [Two first-hours reads per refresh instead of one] -> Small; it keeps the daily refresh bounded (D4).
- [The health check and the reads gain one or two statistics per service] -> The same reads, a few more rows.

## Migration Plan

Code: minor version 3 with the slot move (D3); downgrading keeps working because the major version is unchanged.
Live installation in the final task group (copy, restart with a backup offered, check the migrated entry, map the
defrost statistic under Heating, verify the corrected figures against a direct statistics read, optionally the
season table note). Rollback: restore the previous integration folder and restart; it ignores the `defrost_heat`
key in the service sections, so its figures are uncorrected again.
