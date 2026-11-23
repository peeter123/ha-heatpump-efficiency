# Proposal

## Why

A heat pump's efficiency is usually judged and compared per heating or cooling season (SCOP and SEER on the data
sheet), but the integration only offers calendar periods (today, month to date, year to date, rolling 12 months).
Owners cannot see what their installation delivered over a season, nor compare one season with the next. The
rated SCOP and SEER (EN 14825) use a reference climate and the bin method; a measured seasonal figure (often
called a seasonal performance factor) is the ratio of energy changes over the owner's own season, which the
integration can compute from the same long-term statistics.

US owners read cooling efficiency in BTU/Wh (SEER, EER), not as a W/W ratio, so the W/W figure for cooling is
hard to compare with a US data sheet.

## What Changes

- A recurring heating season and cooling season, each a start and an end month and day, set in the setup and
  options forms, prefilled from Home Assistant's latitude (northern or southern hemisphere) and stored in the
  entry. Existing entries get the defaults through a config entry migration. Changing the dates recalculates
  every season.
- Season sensors: "Heating season" for Heating and for Overall, "Cooling season" for Cooling, each only when that
  service is configured. The state is the current season to date, or between seasons the last season. The same
  ratio of energy changes, 0.1 kWh rule, period start limit and estimated marks apply as for the period sensors.
- A `seasons` attribute (kept out of the recorder) with one point per season since the mapped history starts,
  with no cap: start, end, efficiency (null when unknown), output and electrical energy, and the flags
  `estimated`, `complete` (the whole season is covered, not cut by the start of the history) and `ended`.
- Finished seasons are computed from the counters' running sums at the season boundaries, read once and cached,
  so a long history costs a few small reads instead of a long day read.
- A cooling efficiency unit, W/W (default) or BTU/Wh (W/W x 3.412142), applied to every Cooling sensor, its series
  points and its season points. Overall stays W/W; energies stay kWh. In BTU/Wh the Cooling sensors get the unit
  `BTU/Wh`; in W/W they stay unitless, so existing entities do not change.
- When the cooling unit changes and the Cooling sensors already have long-term statistics, the options flow shows
  a confirmation step: Home Assistant cannot convert those statistics and raises its own repair issue for the
  unit change (ha-core `sensor/recorder.py` `_update_issues`, `units_changed`, not fixable in core). The
  integration still never adjusts statistics.
- README: seasons, the season attributes and flags, the cooling unit and its warning, the measured figure versus
  the rated SCOP and SEER, and an example season table.
- Out of scope: cost per kWh of heat and defrost heat (follow-up changes listed in the backlog), a seasonal figure
  for Hot water alone or a cooling-season Overall, rated (EN 14825) SCOP or SEER calculations with a reference
  climate, converting or deleting the Cooling sensors' own long-term statistics (the owner uses Home Assistant's
  statistics tools), and a fixable repair of this integration's own.

## Capabilities

### New Capabilities

- `season-efficiency`: the heating and cooling season sensors, the season definition from recurring dates, the
  state between seasons, the season history with its `complete`, `ended` and `estimated` flags, and how finished
  seasons are read and cached.

### Modified Capabilities

- `efficiency-setup`: new requirements for the season dates (latitude prefill, validation, storage, migration of
  existing entries) and for the cooling efficiency unit with its warning step; "Mapping changed later" now also
  covers the season dates and the cooling unit, and their recalculation.
- `period-efficiency`: "Period sensors" no longer says every sensor is unitless (Cooling in BTU/Wh has a unit); a
  new requirement applies the cooling unit to every Cooling figure.

## Impact

- Code: `custom_components/heatpump_efficiency/` (a new pure `seasons.py`, `efficiency.py` ratio factor and
  windows, `validation.py`, `config_flow.py`, `__init__.py` migration, `engine.py`,
  `sensor_model.py`, `sensor.py`, `diagnostics.py`, `translations/en.json`), `tests/`, `README.md`.
- Home Assistant APIs (ha-core 2026.11.2): `recorder/statistics.py` `statistics_during_period` with
  `period="hour"` and `types={"sum"}` for the boundary readings; `recorder/statistics.py` `get_metadata` (on the
  recorder executor) and `helpers/entity_registry.py` `EntityRegistry.async_get_entity_id` for the Cooling
  sensors' own statistics (design D6); `config_entries.py` entry migration (`async_migrate_entry`, `MINOR_VERSION`,
  `async_update_entry`); `core_config.py` `Config.latitude`; `helpers/selector.py` `SelectSelector` and
  `NumberSelector`. Read-only towards statistics, as before.
- Live installation (final task group, each step with the user's go-ahead): copy the updated integration to the
  Home Assistant host and restart (backup offered); check that the migration stored the northern defaults; compare
  the current heating season and one finished season against a direct statistics read; open the options flow, pick
  BTU/Wh to see the warning step and close it without saving (the live installation keeps W/W); optionally add a
  season table to the owner's dashboard.
