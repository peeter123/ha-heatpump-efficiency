# Tasks

Validation for every group: `python -m unittest discover tests` and `python -m compileall -q custom_components`
exit 0 (from the repository root, standard library only).

## 1. Pure season arithmetic and the cooling factor

- [x] 1.1 Add `custom_components/heatpump_efficiency/seasons.py` (standard library only; design D3) with `default_seasons(latitude)`, `Season`, `seasons_since`, the running-season ranges, boundary energies from readings and `season_points`; make `efficiency._cover` public as `cover` and keep its callers working; verify a test checks that `seasons.py` imports nothing from `homeassistant`
- [x] 1.2 Add the `factor` argument to `efficiency.ratio` and `period_summary` and the constant `BTU_PER_WH = 3.412142` (design D5), applied before rounding and after the 0.1 kWh rule; verify the existing efficiency tests still pass unchanged
- [x] 1.3 Add `tests/test_seasons.py` covering the `season-efficiency` scenarios that need no Home Assistant (1 October 2026 to the start of 1 May 2027, 1 June to 1 October 2026, 29 February 2028 included, 9000/2500 = 3.60, the cut season from 14 November 2026, a finished season equal to its day-by-day sum on the same synthetic rows, 15 January 2027 running, 15 July 2027 the last season, no season before 1 June 2027, four seasons from a history starting 1 September 2023, the 0.05 kWh season kept with efficiency null, the complete and ended flags, estimated seasons before 13 November 2026), both hemisphere defaults (52.0 and -33.9), a half-hour time zone and a DST day as boundaries, and the `period-efficiency` unit scenarios (470/100 = 16.04, 0.05 kWh unknown); verify the unittest run passes

## 2. Setup: season dates, cooling unit, migration

- [x] 2.1 Extend `validation.py` (design D1, D5, D6): the `seasons` section fields to and from `MM-DD`, the errors `season_invalid_day` (31 April, 29 February) and `season_same_day`, the Cooling `unit` (`w_per_w` default dropped, `btu_per_wh` kept only when Cooling is configured), and the pure decision whether a unit change needs the warning; verify `tests/test_validation.py` covers each `efficiency-setup` season and unit scenario that needs no Home Assistant
- [x] 2.2 Extend `config_flow.py`: the collapsed `seasons` section (month `SelectSelector`, day `NumberSelector`) with stored dates or `default_seasons(hass.config.latitude)` as suggested values, the Cooling `unit` selector, `MINOR_VERSION = 2`, and the options step `unit_change` shown when the Cooling unit changes and a Cooling sensor has long-term statistics (design D6); verify `python -m compileall` passes and the Home Assistant APIs used are cited in comments as in the existing flow
- [x] 2.3 Add `async_migrate_entry` to `__init__.py` (design D2): minor version 1 gets the latitude defaults added to its options, every other key unchanged; keep the merge in a pure function in `seasons.py` or `validation.py` and verify a test that a version 1 mapping keeps every key and gains the four dates
- [x] 2.4 Add the strings to `translations/en.json`: the `seasons` section and its fields, the month names (`selector.month`), the cooling unit options (`selector.cooling_unit`), both season errors and the `unit_change` step with its description (no emoji); verify `tests/test_integration_files.py` checks that every new error key, section, selector and step has a translation
- [x] 2.5 Update README.md: the season dates and their hemisphere defaults, the cooling unit, and the warning step with what Home Assistant does to the Cooling sensors' own statistics; verify the README names every new form field

Note (group 2 review, decisions of 2026-11-20): a date left empty or a non-integer day is an error
(`season_missing`, `season_invalid_day`), so all four dates are always stored; the unit warning checks stored
statistics metadata (`get_metadata`), names the affected sensors and is skipped when Cooling is removed. The
README and form texts that describe the unit and the seasons applying to the figures are accepted ahead of groups 3
and 4, which deliver that behaviour within this change.

## 3. Engine: season reads and results

- [x] 3.1 Extend `engine.py` (design D3, D4): `efficiency.history_windows` takes the running season start of each service as an extra input so the month and day windows include it, `EngineState.boundaries` caches the boundary reads (`read("hour", ids, Window(b - 31 days, b), {"energy": "kWh"}, {"sum"})`), with the refresh rules (new boundary, failed or uncovered, read before `b` + 1 day, first hours changed) in a pure function; verify `tests/test_engine.py` with a fake reader shows ten updates in a day reading finished seasons at most once and a failed boundary read retried at the next update
- [x] 3.2 Compute the season results per service with a season (Heating and Overall: heating season, Cooling: cooling season), the running season from the tables and finished seasons from the readings, and apply the Cooling factor to Cooling's periods, series and seasons (design D5; this adds a `factor` argument to `efficiency._points`, `daily_series` and `monthly_series`, default 1.0); verify engine tests for the first update after a season ends (ended, whole season, no hour missed or counted twice), a season unknown when a boundary reading is not covered, and Overall not converted
- [x] 3.3 Update README.md: the definitions of a season, the state between seasons, finished seasons read once from the counters at the boundaries, and the reload after a backfill; verify the README's season definitions match the spec scenarios

Note (group 3 review, decisions of 2026-11-20): the boundary retry reasons, the kept readings after a failed
re-read and the bounded first-hours read are recorded in design D4 and Risks. A service with a season kind but no
valid season dates has `ServiceResult.season` None; the group 4 season sensors must handle that (unknown).

## 4. Entities and diagnostics

- [x] 4.1 Extend `sensor_model.py` (design D7): season sensor specs, unique IDs `<entry_id>_<service>_<season>`, translation keys, the season attributes, and the season sensors among the expected IDs in `stale_unique_ids`; verify `tests/test_sensor_model.py` covers three season sensors for Heating, Hot water, Cooling and Overall and none for Cooling when it is not configured
- [x] 4.2 Extend `sensor.py`: the season entity class with `seasons` in `_unrecorded_attributes`, and the Cooling unit (`BTU/Wh` or `None`) on the Cooling period and season sensors; include the Cooling season sensor's unique ID in the `unit_change` lookup of task 2.2; add the season sensor names to `translations/en.json`; extend `diagnostics.py` with the season dates, boundary reads and season points; verify `python -m compileall` passes and the translation test covers the new sensor keys
- [x] 4.3 Update README.md: the season sensors and their attributes and flags, measured versus rated SCOP and SEER, the Cooling unit on the sensors, and an apexcharts-card example chart of `seasons` (no statistics `mean`); verify the example cards use no `stat_type: mean` or `stat_types: [mean]`

## 5. Live installation

- [x] 5.1 [User authorization: copies files to the Home Assistant host and restarts it] Offer a backup, copy the updated `custom_components/heatpump_efficiency/` to the host and restart; verify the entry loads without errors in the log
- [x] 5.2 Check the migrated entry: the options hold the northern defaults (heating 1 October to 30 April, cooling 1 June to 30 September) and the mapping is unchanged; verify the Heating, Overall and Cooling season sensors exist with their `seasons` history
- [x] 5.3 Compare the current heating season and one finished season (where the history has one) of Heating against a direct statistics read of the same range; verify the energies agree to 0.01 kWh
- [x] 5.4 [User authorization: opens the options flow of the live entry] Choose BTU/Wh for Cooling, check the `unit_change` warning step, and close it without saving; verify the Cooling unit is still W/W afterwards
- [x] 5.5 [User authorization: changes the owner's dashboard] Optionally add the README's season chart to the owner's dashboard after saving its current config under `private/`; verify the chart shows the season points

Note (group 5, 2026-11-20): the live entry already held owner-set season dates, which the migration kept (it adds
the defaults only when `seasons` is absent); a change of the heating end in the options flow moved the finished
season by exactly the added month's statistics, and the dates were then restored. On the dashboard the apexcharts
season chart was replaced by a markdown table (one row per season and service with energies and notes): an
apexcharts shared tooltip groups points by index, so series with different season counts do not group. The README
example follows in the final review (user's choice).

## Workflow follow-up

- Archive the change after the final whole-change review.
- Remove the SCOP and SEER entry from `private/BACKLOG.md` once the change is archived.
