# Design: reach-silver-quality-scale

## Context

See proposal.md, "Why". The current state that the decisions build on:

- **Engine.** `engine.py` turns every failed read into data, never an exception:
  - a failed table read is a `TableRead` with `rows=None`;
  - a failed boundary read is a `BoundaryRead` with `readings=None` (`after_failed_read` keeps earlier good
    readings);
  - a failed metadata or first-hours read leaves the old values and sets `EngineState.errors`.

  `efficiency.period_energy` and `efficiency.coverage_end` then give None or `NO_COVERAGE`, so the period is
  unknown. Nothing in `EngineResult` says why a value is None.
- **Coordinator and sensors.** `HeatPumpEfficiencyCoordinator._async_update_data` never raises `UpdateFailed`, so
  `CoordinatorEntity.available` is always true after the first refresh (ha-core:
  `homeassistant/helpers/update_coordinator.py` at 2026.11.2, `CoordinatorEntity.available` returns
  `self.coordinator.last_update_success`). It logs a read error as a warning when it appears or changes, and at
  info when it clears (`engine.error_changes`).
- **Tests.**
  - `tests/` covers the pure modules (engine, efficiency, seasons, validation, sensor model, repairs model) and
    loads them by file path under a stand-in package (`tests/test_engine.py`).
  - `tests_ha/` covers the config flow (100 % gate) and the quality scale record.
  - The `ha-tests` job runs `pytest-homeassistant-custom-component==0.13.375`, which also brought pytest-cov and
    coverage.

## Goals / Non-Goals

**Goals:**
- Each sensor knows whether its own value depends on a failed read.
- One coverage figure per module over both test folders.

**Non-Goals:**
- No change to which reads are made or when they are retried.
- No change to the figures themselves.
- No repair issue for a failed read.
- `tests/` keeps running without Home Assistant, on Windows too.

## Decisions

### D1. Core's test package

- **Pins:**
  - `pytest-homeassistant==2026.11.2` (requires `homeassistant==2026.11.2`, pytest 9.0.3, pytest-asyncio 1.4.0;
    derived: its PyPI metadata, read 2026-11-27);
  - `pytest-cov==7.1.0` and `coverage==7.16.2`, core's pins at the tag (ha-core: `requirements_test.txt` at
    2026.11.2). The new package lists neither.
- **Respx.** Core runs its tests with `addopts = "-p no:respx"` because the respx plugin imports httpx before Home
  Assistant can alias it (ha-core: `pyproject.toml` `[tool.pytest.ini_options]` at 2026.11.2; the package's README,
  "Writing tests"). The `ha-tests` command passes `-p no:respx`.
  - It is not put in `pyproject.toml`, because the `tests/` run there has no Home Assistant.
- **Imports.** `pytest_homeassistant_custom_component` becomes `pytest_homeassistant` (`common.MockConfigEntry`,
  `components.recorder.common.async_wait_recording_done`).
- **Custom integrations.** The `hass` fixture loads them by default: it pops `loader.DATA_CUSTOM_COMPONENTS` when
  the fixture `custom_integrations_enabled` is true, which is its default (derived: `pytest_homeassistant/plugins.py`
  in the 2026.11.2 wheel, fixtures `hass` and `custom_integrations_enabled`).
  - The autouse wrapper in `tests_ha/conftest.py` goes.
  - Tests that write statistics keep requesting `recorder_mock` before `hass`. `recorder_db_url` still asserts
    that hass is not set up yet (same file, `recorder_db_url`).
- **Configuration folder.** `hass_config_dir` defaults to `<ha_test_root>/testing_config`, and `ha_test_root`
  defaults to `tests` (same wheel, `_paths.configure` and `common.get_test_config_dir`). The repository has no
  such folder. Group 1 checks first whether the integration loads from the repository's own `custom_components/`
  as today:
  - if it does, the conftest keeps its early import, with the comment updated to the new package;
  - if not, the command sets `-o ha_test_root=tests_ha` with an empty `tests_ha/testing_config/`, the layout the
    README describes. That folder is a test fixture and must not be imported as a test package.
  - **Outcome, 2026-11-27: the early import is enough; no fallback.** Read in the 2026.11.2 wheel (not run) and in
    core at the tag:
    - `_paths.configure` and `common.get_test_config_dir` give the configuration folder
      `<ha_test_root>/testing_config`, with `ha_test_root` defaulting to `tests`, a folder this repository lacks; `plugins.py` `hass_config_dir` returns it and `async_test_home_assistant` in
      `common.py` passes it to `HomeAssistant` and calls `loader.async_setup`, which runs
      `loader.async_mount_config_dir` (ha-core: `homeassistant/loader.py`). That function puts the folder on
      `sys.path`, tries `import custom_components` and ignores an `ImportError`; the missing folder is harmless.
    - `loader._get_custom_components` then imports `custom_components` and lists every folder in its `__path__`.
      The conftest's early import puts the repository's `custom_components` into `sys.modules` during
      collection, so that import finds it whether or not the configuration folder exists.
    - The wheel's own `testing_config/` is imported only through relative imports inside the package
      (`common.py`), never as a top-level `custom_components`, so it does not shadow ours. Nothing in `plugins.py`
      needs the folder to exist (`hass_tmp_config_dir` is used only when a test requests it).
    - The conftest comment is rewritten against this. The CI run of group 1 is the check of the harness.

### D2. Coverage over both test folders

The `ha-tests` job runs, in order:

1. **The Home Assistant tests.**

   ```
   uv run --no-project --python 3.14 --with pytest-homeassistant==2026.11.2 --with pytest-cov==7.1.0 --with coverage==7.16.2 pytest tests_ha -p no:respx --cov=custom_components/heatpump_efficiency --cov-branch --cov-report=
   ```
2. **The tests of the pure modules,** in an environment without Home Assistant, with the same pins as
   `scripts/lint.py` plus the two coverage tools. `--cov-append` adds to the same data file.

   ```
   uv run --no-project --python 3.14 --with pytest==9.0.3 --with pytest-asyncio==1.4.0 --with tzdata==2026.6 --with pytest-cov==7.1.0 --with coverage==7.16.2 pytest tests --cov=custom_components/heatpump_efficiency --cov-branch --cov-append --cov-report=term-missing
   ```
3. **The existing config flow gate:** `coverage report --include="*/config_flow.py" --fail-under=100`.
4. **The JSON report:** `coverage json -o coverage.json`.
5. **The gate:** `python scripts/coverage_gate.py coverage.json 95`.

- **The `--cov` source is a path,** not a module name. coverage then measures the files under that folder however
  they are imported, so `tests/`' loading under a stand-in package name counts for the same files. Group 3 checks
  this with the first combined report: `engine.py` must show the coverage of `tests/`, not only that of
  `tests_ha/`.
- **The `tests/` pins in the workflow** must equal those in `scripts/lint.py`. A test in
  `tests/test_integration_files.py` compares them, so the two cannot drift.
- **Alternatives:**
  - Running `tests/` inside the Home Assistant environment was rejected: its plugin would load (pytest-socket,
    the `hass` hooks), which is what the `tests/` design avoids.
  - Measuring `tests_ha/` alone was rejected: `engine.py` and `efficiency.py` (2,500 lines) are tested in
    `tests/`, and duplicating that in the harness gains nothing.

### D3. The coverage gate script

- **`scripts/coverage_gate.py`:**
  - standard library only;
  - `main(argv)` with the report path and the threshold;
  - it reads coverage's JSON report: `files` maps each path to a `summary` with `percent_covered`, and `totals`
    has the same `summary` keys (coverage.py docs, "JSON reporting", for 7.16).
- **Exit codes:**
  - 0 when the total and every file reach the threshold;
  - 1 otherwise, printing each file below it with its percentage, and the total;
  - 2 when the report cannot be read.
- **Scope:** only files under `custom_components/heatpump_efficiency/` count, so a stray path never affects the
  result.
- **Tests** in `tests/test_coverage_gate.py`, on small JSON files written to `tmp_path`: one module below, all at
  or above, an unreadable report.
- **Alternative rejected:** coverage's `fail_under` checks only the total, and the rule names every module
  (ha-docs: `rules/test-coverage.md`, "Above 95% test coverage for all integration modules").

### D4. Which results depend on a failed read

The engine marks each result with `read_failed: bool`, on `PeriodResult` and `SeasonResult` (default False). It is
computed in the engine from the state of this update, as pure functions unit-tested in `tests/test_engine.py`.

- **The failed tables:** `failed_sources(state)` gives the sources whose cached `TableRead.rows` is None.
- **A period** of a service is `read_failed` when:
  - the service's recent source (`hour` when `reads_hourly`, otherwise `5minute`) is failed, because
    `coverage_end` then gives `NO_COVERAGE` for every period;
  - or a source of one of the period's ranges is failed.
- **A running season** is `read_failed` under the same rule over its `running_ranges`.
- **A finished, shown season** is `read_failed` when the `BoundaryRead` at its covered start or natural end has
  `readings` None. `after_failed_read` already keeps an earlier good read, so a failed repeat read keeps
  `readings` and the sensor stays available.
- **A whole service** (every period and its season) is `read_failed` in two cases:
  - **The metadata has never been read** (`metadata_ok` false) and its last read failed (`errors["metadata"]` set).
    A later failure keeps `metadata_ok` and the last good metadata, so nothing is unavailable then.
  - **A first hour of one of its statistics has never been read** because that statistic's read failed.
    `EngineState` gains `first_hours_failed: frozenset[str]`, the IDs whose read failed at the last attempt, set
    in `_refresh_first_hours`. The service is `read_failed` when `resolve_effective` reports it not known and
    one of its `all_ids` is in that set.
- **Reads that depend on the recent tables** (owner's decision 2026-11-27, after the group 2 review). The recent
  tables give each statistic's last row end (`efficiency.last_row_ends`: `5minute` for a recorder statistic, also
  when its service reads hourly; `hour` for an hourly-only one). Two other reads use it:
  - **A history table** (day or month) records which statistics it covers when it is read. A range of a period or
    running season also counts as failed when its table does not cover one of the service's IDs and the source
    table of that ID's last row end failed at this update. So an hourly service such as Overall is unavailable,
    not unknown, while the 5-minute read fails during an update that reads its day or month table, and stays
    available while its cached tables cover its statistics.
  - **A boundary read** takes its readings' last row end from the same tables. In `_refresh_boundaries`, a
    boundary read made while the source table of the last row end of a statistic it needs failed at this update
    counts as a failed read, through `after_failed_read`: earlier good readings are kept, so the season keeps its
    figure and stays available, and a first read gives `readings` None, so the shown season is `read_failed`. Such
    a boundary is not read while that source has failed, so no extra reads are made during an outage; it is read at
    the first update at which the source works again. The statistics a boundary needs are those of every service
    that shares it, so an Overall with only hourly statistics shares Heating's unavailable first read; this rare
    case is accepted.
- **Series attributes:** availability follows the sensor's value only. While a history read fails, an available
  sensor's series attributes (`daily`, `monthly`) can miss the points that read gives; the README says so (owner's
  decision 2026-11-27).
- **Not affected:** an unknown period whose reads all worked keeps `read_failed` False, and the sensor shows
  unknown. Examples: not begun, no data, a lagging or incomplete read, the 0.1 kWh rule, a defrost statistic
  behind.
- **Inputs of each derived value:**
  - the cached `state.tables`, `state.boundaries`, `state.errors`, `state.metadata_ok` and
    `state.first_hours_failed`;
  - the service's IDs and `reads_hourly`;
  - the period ranges from `efficiency.period_ranges` and the season infos from `season_infos`.

  All of it is in `engine.py`.
- **Alternative rejected:** a separate `unavailable` set of sensor keys in `EngineResult`. Putting the flag on the
  result that the sensor already reads keeps the sensor code a one-line property.

### D5. Sensor availability

- `EfficiencySensor.available` returns `super().available and not result.read_failed`, where `result` is the
  sensor's `PeriodResult`; `SeasonEfficiencySensor` uses its `SeasonResult`.
- A missing result (no data yet, or a service not in the data) leaves `super().available`.
- `super().available` is `CoordinatorEntity.available` (ha-core: `helpers/update_coordinator.py` at 2026.11.2), so
  a failure of the coordinator itself still counts, as the rule's example asks (ha-docs:
  `rules/entity-unavailable.md`, "be sure to incorporate the `super().available` value").
- Home Assistant adds `state_attributes` and `extra_state_attributes` only when the entity is available (ha-core:
  `helpers/entity.py` `Entity.__async_calculate_state` at 2026.11.2, the `if available:` branch). So the series
  attributes of an unavailable sensor need no special case.

### D6. Logging once at info level

- The coordinator keeps `error_changes`: one line when a read's error appears or changes, one when it clears.
- The failure line moves from warning to info, as the rule asks (ha-docs: `rules/log-when-unavailable.md`,
  "Logging should happen at `info` level").
- The repair issues of the statistics health check are unchanged.

### D7. The Home Assistant tests

All tests use synthetic statistics written with `async_import_statistics` in the test recorder (made-up IDs), as
`tests_ha/test_config_flow.py` does today, and `freezer` for the clock. Each module gets one file:

| File                  | Covers                                                                                                                                                                                                                             |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_init.py`        | setup creates the sensors of each mapped service; the 5-minute tracker refreshes; unload; reload after an options change; the migration from minor versions 1, 2 and 3                                                             |
| `test_coordinator.py` | the recorder reader passes the window, units and types; a failed read of each kind logs once at info and once when it clears; the affected sensors are unavailable and the others available (the scenarios of D4)                  |
| `test_sensor.py`      | state, unit (Cooling in BTU/Wh), attributes, the unrecorded series attributes, the season sensor, removal of the sensors of a service that is no longer mapped                                                                      |
| `test_diagnostics.py` | the diagnostics of a loaded entry: the options, the season dates, the errors and the cached data, through `pytest_homeassistant.components.diagnostics.get_diagnostics_for_config_entry`                                           |
| `test_issues.py`      | repair issues created and deleted through the issue registry for a missing statistic, and the failure path that logs instead of failing the update                                                                                 |

- **Failed reads are injected** by patching `statistics_during_period` or `async_list_statistic_ids` as the
  coordinator module imports them, raising for one source. The engine's own handling is already covered in
  `tests/`.
- **The config flow tests** drop their patches of `async_setup_entry` and `async_unload_entry` where the real
  setup now works on 2026.11.2 (group 1 already removed the comment about the 2026.10.4 difference); the patches
  stay only where a test checks the flow alone.

### D8. Record, manifest and constitution

- **`quality_scale.yaml`:**
  - `entity-unavailable: done`, with a comment that only the sensors whose value needs a failed read become
    unavailable;
  - `test-coverage: done`;
  - `log-when-unavailable` stays `done`, with a comment that each new or changed failure and each recovery is
    logged once at info level;
  - `strict-typing` stays `todo`.
  - **The Gold rules** were re-checked against the code, the README and the rule pages on 2026-11-27: all 21 hold.
    Four comments are completed:
    - `entity-device-class`: no device class for an efficiency ratio (`power_factor` is a different quantity) or
      for BTU/Wh; the energies are state attributes, not entities;
    - `stale-devices`: the sensors of a service removed from the mapping are removed from the entity registry at
      the next load, and the mapping cannot be emptied;
    - `exception-translations`: the integration raises no exceptions of its own; a failed read makes sensors
      unavailable, flow problems are translated form errors and aborts, and the only setup or unload exceptions
      come from Home Assistant itself;
    - `reconfiguration-flow`: everything set up in the config flow except the name changes in the options flow,
      which reloads the entry; the name is the entry title, which Home Assistant renames itself.
- **`manifest.json`:** `quality_scale` becomes `gold`, the highest tier the record supports once the two Silver
  rules are `done` (the requirement "Declared tier matches the record"; owner's decision 2026-11-27). `version`
  becomes `0.3.0`. The change keeps its id `reach-silver-quality-scale`.
- **`openspec/config.yaml` Tooling paragraph:**
  - `tests_ha/` may use `pytest-homeassistant` with `pytest-cov` and `coverage`, each at an exact version through
    uv, in CI and locally only on Linux or macOS;
  - the pin rule reads: the release equal to the target Home Assistant version, or the newest before it;
  - `pytest-cov` and `coverage` are core's pins in `requirements_test.txt` at the target tag, and move with it
    (owner's decision 2026-11-27);
  - the CI coverage run of `tests/` (D2 step 2) uses the pins of `scripts/lint.py` plus `pytest-cov` and
    `coverage`; it is the one run of `tests/` outside the lint entry point (owner's decision 2026-11-27);
  - the source tag `ha-test-harness` names `pytest-homeassistant`.
- **`AGENTS.md`:** its Layout and "Rules in short" match.
- **`scripts/coverage_gate.py`** is standard library like the other scripts, so the rule "standard library only
  for `scripts/`" holds.

### D9. Order of the work, with CI green after every group

1. **The test package, the CI job, the constitution and the Development section.** The existing tests pass on the
   new package; the config flow gate stays.
2. **Unavailable on a failed read:** engine, sensor, coordinator log level, README, and the `tests/` scenarios.
3. **The Home Assistant tests of D7,** the coverage gate script and the combined coverage gate in CI.
4. **The record, the tier, version 0.3.0 and the README Status section.**
5. **Live steps:** fast-forward and push `main`, tag and release, then update the live installation; each with the
   owner's go.

## Risks / Trade-offs

- **[Risk] The new package loads custom integrations differently from the old one, and the repository has no
  `tests/testing_config/`.** → Mitigation: D1's check comes first in group 1; the fallback is the documented
  layout.
- **[Risk] coverage does not attribute the `tests/` run to the integration's files.** → Mitigation: the `--cov`
  path source (D2), checked with the first combined report; if it fails, a `[tool.coverage.run]` `source` path in
  `pyproject.toml` is the fallback.
- **[Risk] A small module stays under 95 % (`issues.py`, `diagnostics.py`).** → Mitigation: D7 gives each module
  its own test file; the gate names the module, so the gap is visible in CI.
- **[Trade-off] A failed recent read now makes every period sensor of the services that read it unavailable,**
  which shows up in dashboards and history, while before they were only unknown. This is the rule's intent and the
  owner's decision of 2026-11-26.
- **[Trade-off] The failure log moves from warning to info,** so a failed read no longer shows in the default
  warning-level log view. The rule asks for info; the repair issues and the unavailable state remain visible.
- **[Risk] Automations that test for `unknown` miss `unavailable`.** → Mitigation: the README's example already
  names both states for `numeric_state`; the README failed-read text says which state means what.

## Migration Plan

- **Upgrade.** Nothing changes in the stored entry, and the entity IDs and unique IDs stay. After the update to
  0.3.0 the sensors behave as before while every read works.
- **Rollback.** Install 0.2.0 through the Marketplace. No stored data depends on 0.3.0.
