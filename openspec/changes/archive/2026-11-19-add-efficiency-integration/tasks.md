# Tasks

Validation for every group: `python -m unittest discover tests` and `python -m compileall -q custom_components`
exit 0 (from the repository root, standard library only).

## 1. Pure efficiency module

- [x] 1.1 Add `custom_components/heatpump_efficiency/efficiency.py` (standard library only, time zone and `now` passed in; design D2) with `period_ranges`, `effective_start`, `period_energy`, `ratio`, `daily_series`, `monthly_series`, `cache_actions` and `health`; verify it imports nothing from `homeassistant` (a test checks the import list)
- [x] 1.2 Add `tests/test_efficiency.py` covering the `period-efficiency` scenarios (3.60, unknown at 0.05 kWh, summed outputs 4.00, Wh conversion input, 3.12 against the time average, month to date 3.35, 1 March, both leap-day rolling starts, both DST days in Europe/Amsterdam, effective start 13 November 00:00 and 14 November 00:00 for a 14:00 first hour, limited period not begun, month read failed with today and month to date still reported, statistic without data, energies kept when the ratio is unknown, the 00:05 update counting no energy twice, ten updates in a day reading history once), the `efficiency-series` scenarios (cooling month without point, November 2025 and 2026 points, estimated marks around 13 November, no date no marks) and the `statistics-health` classifications (missing, no sum, W unit, stale after 3 hours, recovered); verify the unittest run passes
- [x] 1.3 Add `README.md` with the purpose, the definitions (ratio of energy changes, the 0.1 kWh rule, the periods in the Home Assistant time zone, the period start limit, the estimated marks) and a status note that setup follows; verify the README's definitions match the spec scenarios

Note (round 1 review, decisions of 2026-11-18): the fix round extends 1.1-1.3 with the statistics day for
half-hour time zones, per-table read windows and coverage, hourly-only (external) statistics, the covered start
for estimated marks and the reordered health checks (design D2-D4, D7), with tests for the new spec scenarios
(half-hour time zone, history extended by a backfill, lagging statistic, external statistic, month starting at
the measured history).

## 2. Integration skeleton and setup UI

- [x] 2.1 Add `manifest.json` (design D1; `documentation`, `issue_tracker` and `codeowners` as clearly marked placeholders per the design's open question), `hacs.json`, `const.py`, `__init__.py` (`async_setup_entry` and `async_unload_entry` returning `None`, `entry.runtime_data`, platforms forwarded) and `translations/en.json`; verify `python -m compileall` passes and a test checks the manifest keys and that `hacs.json` names the minimum Home Assistant version
- [x] 2.2 Add `config_flow.py` with the `user` step and an `OptionsFlowWithReload` (design D6): name, sections per service and Overall with multiple statistic selectors and an optional measured-since date, the collapsed `planned` section with the price and defrost slots, validation through `async_list_statistic_ids` (exists, running sum, energy unit class; external statistics accepted) with field errors for power units, missing sum, output without electricity and an empty mapping; keep the validation rules in `efficiency.py` or a pure helper with standard-library tests for every `efficiency-setup` scenario that does not need Home Assistant; every step, section, field, error and description in `translations/en.json`; verify the unittest run passes
- [x] 2.3 Extend the README with installation (HACS custom repository or manual copy, restart) and setup (the form, choosing statistics, measured-since dates, the planned slots that do nothing yet, changing the mapping later); verify every field in `translations/en.json` is explained

## 3. Coordinator, statistics reads and sensors

- [x] 3.1 Add `coordinator.py` (design D3, D4): one coordinator per entry with `update_interval=None`, the 5-minute tracker at second 30, setup and reload refreshes, reads with `statistics_during_period` on `get_instance(hass).async_add_executor_job` with `types={"change"}` and `units={"energy": "kWh"}`, first statistics hours, the `hour` read for services with an external statistic, the cache with per-table read windows and coverage driven by `cache_actions`, per-read failures and uncovered reads turned into `None` periods without `UpdateFailed`; verify `compileall` passes and a test checks with a fake reader that the coordinator's read plan per update matches `cache_actions` for setup, a normal update, the first update after midnight, the 1st of a month, a moved effective start and a retried uncovered read, and that every read passes `units={"energy": "kWh"}`
- [x] 3.2 Add `sensor.py` (design D5): four sensors per configured service and Overall, translation keys and names in `translations/en.json`, state class measurement, no unit, precision 2, the energy, `period_start` and `includes_estimated` attributes, `daily` on the today sensor and `monthly` on the month-to-date sensor as class-level `_unrecorded_attributes`, unique IDs `<entry_id>_<service>_<period>`, one service device per entry, removal of this entry's registry entries for services no longer mapped; verify a test checks that unconfigured services get no sensors, that the unique IDs to remove are computed by a pure function, and that the series attributes are unrecorded
- [x] 3.3 Add `diagnostics.py` (design D8); verify `compileall` passes
- [x] 3.4 Extend the README with the sensors, their attributes, the update timing and caching, reloading after a statistics backfill, and example dashboard cards (entity cards per period, an apexcharts-card chart of `daily` and of `monthly` through `data_generator`, no statistics `mean`); add a test that no example in the README uses `stat_type: mean` or `stat_types` with `mean`; verify the unittest run passes

## 4. Statistics health and repairs

- [x] 4.1 Add the health check to the coordinator and `repairs.py` (renamed `issues.py` after the whole-change review) (design D7): one non-fixable warning issue per entry and statistic with `config_entry_id`, the five translation keys with placeholders in `translations/en.json`, deleted when healthy, staleness from the hourly table for external statistics; verify a test checks with a fake issue registry that issues are created and deleted for each `statistics-health` scenario, including removal with the entry
- [x] 4.2 Extend the README with troubleshooting: each repair issue and what to do, diagnostics, the restart-at-0 edge case, external statistics that must be at most 2 hours behind; verify the README names every issue translation key's title

## 5. Live installation

These tasks change the live Home Assistant installation. They run only after groups 1-4 have clean reviews and
commits, in the session with the user, each with the user's explicit go-ahead; they edit no repository files.
The installation details are in `private/installation.md`.

- [x] 5.1 [User authorization: copies files to the Home Assistant host and restarts it] Offer a Home Assistant backup, copy `custom_components/heatpump_efficiency/` to the host's `/config/custom_components/`, restart; verify the integration loads without errors in the log
- [x] 5.2 [User authorization: adds a config entry] Add the heat pump with the mapping and measured-since dates from `private/installation.md`; verify the sensors exist with state class measurement and no unit, write no logbook entries, update every 5 minutes, and that hot water month to date equals the ratio of a direct monthly statistics read; verify no repair issue is raised; before creating the entry, submit a power statistic and see the error on its section; after creating it, open Configure and see the statistics, measured-since dates and slots filled in, save unchanged and confirm no reload, then change one statistic and confirm the reload keeps the entity IDs (spec scenarios Date stored, Slots stored only, Meter replaced, Power instead of energy; Two heat pumps is covered by the validation and unique-ID tests only, since the installation has one heat pump); download diagnostics and check the windows, first hours, coverage and that no read error is set; confirm updates land at second 30 of every fifth minute, that `daily` and `monthly` are not in the recorder, and that `period_start` and `includes_estimated` match the measured-since dates; after the first update past midnight, confirm yesterday is in `daily`; compare the oldest monthly point and any backfill junction day with a direct statistics read for a negative or implausible change
- [x] 5.3 [User authorization: changes the Heatpump dashboard] Save the current `dashboard-heatpump` config under `private/`, replace the Performance cards and the Statistics view's mean-based COP bars with the README's example cards for the integration; verify the cards show the sensors and the charts show daily and monthly points

## Workflow follow-up

- Archive the change after the final whole-change review.
- Follow-up changes: cost per kWh of heat, defrost heat (after a firmware defrost heat counter in
  esphome-ecoforest-ecogeo), publishing (brand assets, releases, HACS default list).
