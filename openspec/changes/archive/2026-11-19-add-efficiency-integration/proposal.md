# Proposal

## Why

Home Assistant compiles long-term statistics of a `measurement` sensor as a time-weighted hourly mean, so a
dashboard that shows a heat pump's COP for a day, month or year from those statistics shows a time average of
instantaneous COPs, not the ratio of heat delivered to electricity used (ha-docs: "Sensor entity", state
classes). For one installation the difference was about 4.0 against an energy-weighted 3.1 for a single day
(firmware-entity, observation 2026-11-15 in esphome-ecoforest-ecogeo). The exact figure for any period is the
`change` of an output energy counter divided by the `change` of an electrical energy counter; most heat pump
installations already have such counters, but Home Assistant has no built-in way to show their ratio per period.

A first attempt as a template package (trigger-based template, Jinja macro, apexcharts `data_generator`) in the
esphome-ecoforest-ecogeo repository worked but read about 70 000 hourly rows every 5 minutes, could publish a
plausible wrong figure when one of its statistics reads failed, and was tied to one installation. Its review
(2026-11-17) and the verified Home Assistant facts carry over into this change.

## What Changes

- A new custom integration (HACS layout) that an owner adds through the UI and configures per heat pump:
  - Services Heating, Hot water and Cooling, each optional, each mapped to one or more output energy statistics and
    one or more electrical energy statistics, summed.
  - Overall, mapped the same way, so it can use a whole-unit meter that includes standby.
  - Optionally, per service and for Overall, the date from which the history is measured rather than estimated.
- Efficiency sensors per service and Overall for today, month to date, year to date and the rolling 12 months:
  energy ratio, no unit, state class measurement, 2 decimals, unknown below 0.1 kWh of electricity or when a
  statistics read fails, never a partial figure. Each carries the output and electrical energy of its period and
  its effective start as attributes.
- Daily ratios for the last 31 days and monthly ratios for the last 24 months as attributes (kept out of the
  recorder), each point marked when it includes estimated history, for daily and monthly charts.
- Repair issues for a mapped statistic that is missing, has no running sum, has a non-energy unit, or has stopped
  updating.
- Completed days and months are cached; only today is read every 5 minutes, after the recorder's 5-minute compile.
- Config slots, without entities or computation yet, for a price source (cost per kWh of heat) and a defrost heat
  statistic (how much heat goes into defrost).
- README with setup, definitions, example dashboard cards (energy-based figures and charts, no `mean` of a live
  COP) and the Ecoforest ecoGEO mapping as a labelled example.
- Out of scope, each for a follow-up change in this repository: computing cost per kWh of heat and defrost heat
  (the Ecoforest firmware has no defrost heat counter yet; that is a firmware change in esphome-ecoforest-ecogeo);
  writing or backfilling statistics (the esphome-ecoforest-ecogeo backfill tool does that for its installation);
  publishing to the HACS default list.

## Capabilities

### New Capabilities

- `efficiency-setup`: adding and changing a heat pump through the UI: the service and Overall mappings, the
  measured-since dates, validation of the chosen statistics, and the cost and defrost slots.
- `period-efficiency`: the efficiency sensors for today, month to date, year to date and rolling 12 months, their
  definition as a ratio of energy changes, the 0.1 kWh rule, unknown on failure, the period start limited to the
  mapped statistics' history, the energy attributes, and the update timing.
- `efficiency-series`: the daily and monthly ratio series for charts, with the estimated-history marker.
- `statistics-health`: repair issues for missing, unsuitable or stale mapped statistics.

### Modified Capabilities

None (first change in this repository).

## Impact

- New repository content: `custom_components/<domain>/` (manifest, config flow, coordinator, sensors, a pure
  arithmetic module, translations, diagnostics), `hacs.json`, `tests/` (standard library), `README.md`.
- Home Assistant APIs (ha-core 2026.11.2): recorder statistics reads and metadata, config and options flows,
  `DataUpdateCoordinator`, sensor entities, the issue registry; read-only towards statistics.
- Live installation (final task group, each step with the user's go-ahead): copy the integration to the Home
  Assistant host, restart (backup offered), add the config entry with the ecoGEO mapping, verify the figures
  against a direct statistics read, then replace the Heatpump dashboard's time-averaged Performance cards and COP
  bars with the integration's entities and charts. The esphome-ecoforest-ecogeo backfill can run before or after;
  until it runs, the period start limit keeps the ecoGEO service figures to the measured history.
