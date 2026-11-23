# Proposal

## Why

During a defrost many heat pumps take heat back out of the water circuit to melt the ice on the outdoor coil. Many
heat meters and firmware counters do not subtract that heat: they stop counting while the flow is reversed, and
count the heat again when the heat pump delivers it a second time after the defrost. So the mapped output
statistics overstate the useful heat, and every Heating, Hot water and Overall figure is too high by the defrost
share. The real efficiency over a day or longer is (output - defrost heat) / electricity.

The setup form already has a single defrost heat slot in the planned section, stored only (requirement "Cost and
defrost slots"). Now that the live example firmware counts the defrost heat, the slot can be used. Live example
(firmware-entity): the esphome-ecoforest-ecogeo firmware's `Total Defrost Energy` (kWh, total increasing) counts
from 0 since its first firmware with the counter on 18 November 2026, with no backfill; the first real defrost, on
22 November 2026, took 16 minutes and 1.84 kWh, about 5 % of that day's heat.

## What Changes

- **Defrost heat per heating service.** The Heating and Hot water sections get an optional defrost heat field (one
  or more energy statistics, summed), validated like the output and electricity fields. It replaces the single
  `defrost_heat` slot of the planned section. The same statistic may not be mapped twice (in both sections, or
  also as an output or electricity statistic). A defrost statistic in a section whose service is not configured
  corrects Overall only, and is rejected when Overall is not configured either. Cooling has no defrost field.
- **Corrected in place.** When a defrost statistic is mapped, the Heating, Hot water and Overall figures (the four
  periods, the daily and monthly series and the seasons) use output minus defrost heat over the same range.
  Heating subtracts the Heating section's defrost statistics, Hot water the Hot water section's, Overall the sum
  of both. Owners who map no defrost statistic see no change. Cooling is never corrected.
- **A correction, not an input.** The defrost statistic never moves a service's effective start: before its first
  statistics hour it counts as 0 kWh. Otherwise it counts like a mapped statistic of its service: its reads must
  be complete, the service's periods end at its last statistics, an external defrost statistic is read hourly,
  and a defrost statistic without statistics makes the corrected figures unknown, never silently uncorrected.
- A corrected figure whose output minus defrost heat is 0 or less is unknown. The 0.1 kWh rule stays on the
  electrical energy.
- **New attributes** on the corrected period and season sensors: `defrost_energy` (kWh subtracted),
  `efficiency_uncorrected`, and `defrost_since` (the defrost statistic's first statistics hour, only on a period
  that starts before it). `output_energy` stays the measured output. Daily, monthly and season points get a
  `defrost_partial` flag; season points also get `defrost_energy`. The large attributes stay out of the
  recorder as before.
- **Repairs.** The statistics health check covers the mapped defrost statistics like the output and electrical
  ones.
- **Migration.** A config entry migration to minor version 3 moves an existing planned `defrost_heat` value into
  the Heating section. The price source stays in the planned section, stored only.
- Diagnostics show the defrost statistics of each service, their start, and the defrost energies.
- README: the defrost correction, where to map the defrost statistic (a unit that always takes defrost heat from
  one circuit: under that service; a reverse-cycle unit with split counters: one per service; with one counter:
  under the dominant service, Overall exact and the split approximate), a warning that a water-side heat meter
  that already counts both directions needs no defrost statistic (it would be subtracted twice), the attributes
  and flags, and why the correction holds per day or longer, not per hour.
- Out of scope:
  - cost per kWh of heat from the price source (its own follow-up change, listed in the backlog);
  - a per-service split of the defrost heat in the firmware (the esphome-ecoforest-ecogeo repository);
  - hourly corrected figures (no hourly figures exist; a defrost and the reheating after it fall in different
    hours);
  - publishing or a release (a separate step after this change).

## Capabilities

### New Capabilities

- `defrost-correction`: subtracting the mapped defrost heat from the Heating, Hot water and Overall figures, which
  statistics each service subtracts, how the defrost statistic's history is treated (0 before its first hour,
  never moving the effective start), when a corrected figure is unknown, and the defrost attributes and flags.

### Modified Capabilities

- `efficiency-setup`: the defrost heat field in the Heating and Hot water sections with its validation, replacing
  the planned defrost slot (requirement "Cost and defrost slots" removed, "Price source slot" added); the
  migration of an existing slot value; "Mapping changed later" names the defrost statistics.
- `period-efficiency`: "Efficiency is a ratio of energy changes" uses the corrected output when a defrost statistic
  is mapped; "Period start limited to the mapped history" is limited by the output and electrical statistics only.
- `statistics-health`: the repair issues also cover the mapped defrost statistics.

## Impact

- Code: `custom_components/heatpump_efficiency/` (`efficiency.py` corrected ratio and defrost flags, `seasons.py`
  season points, `engine.py` services and results, `validation.py` field, errors and migration helper,
  `config_flow.py` form and `MINOR_VERSION = 3`, `__init__.py` migration, `sensor_model.py`, `sensor.py`,
  `issues.py`, `diagnostics.py`, `translations/en.json`), `tests/`, `README.md`.
- Home Assistant APIs (ha-core 2026.11.2), all already in use: `recorder/statistics.py`
  `statistics_during_period` (energy converted to kWh by `units`) and `async_list_statistic_ids` (validation and
  health); `config_entries.py` entry migration (`async_migrate_entry`, `MINOR_VERSION`, `async_update_entry`);
  `helpers/selector.py` `StatisticSelector`; `helpers/entity.py` `_unrecorded_attributes`. Read-only towards
  statistics, as before; no new reads: the defrost statistics join the existing reads.
- Live installation (final task group, each step with the user's go-ahead): copy the updated integration to the
  Home Assistant host and restart (backup offered); check that the entry migrated to minor version 3 and the
  existing setup works unchanged; map the defrost statistic under Heating in the options flow; verify today's and
  the current season's corrected figures against a direct statistics read and `defrost_since` on earlier
  periods; optionally add the `defrost_partial` note to the owner's season table.
