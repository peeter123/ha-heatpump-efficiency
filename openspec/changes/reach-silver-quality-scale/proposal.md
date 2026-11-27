# Proposal: reach-silver-quality-scale

## Why

The integration is at Bronze. Two Silver rules are still `todo` in `quality_scale.yaml`:

- **`entity-unavailable`:** a failed statistics read makes the affected sensors unknown, but they stay available.
  The rule asks for unavailable when the data cannot be fetched, and unknown only when it was fetched but a piece
  is missing (ha-docs: `docs/core/integration-quality-scale/rules/entity-unavailable.md`).
- **`test-coverage`:** only the config flow is tested in Home Assistant's harness. The rule asks for more than
  95 % coverage of all integration modules (ha-docs: `rules/test-coverage.md`).

The Home Assistant tests still run on `pytest-homeassistant-custom-component==0.13.375`, which pins Home Assistant
2026.10.4. Home Assistant core now publishes its own test package, `pytest-homeassistant`, versioned like Home
Assistant; 2026.11.2 was published on 2026-11-16 and pins `homeassistant==2026.11.2`, the target version
(derived: PyPI metadata of `pytest-homeassistant` 2026.11.2, read 2026-11-27). Its README says it replaces the
old package and must not be installed with it.

The owner decided on 2026-11-26 that only the sensors whose data depends on a failed read become unavailable, and
that this change comes after `adopt-ruff-lint`, which is archived.

## What Changes

- **Test package.** `tests_ha/` moves to `pytest-homeassistant==2026.11.2`, with `pytest-cov==7.1.0` and
  `coverage==7.16.2`, core's pins at that tag (ha-core: `requirements_test.txt` at 2026.11.2). The new package
  does not bring pytest-cov, as the old one did. Imports move from `pytest_homeassistant_custom_component` to
  `pytest_homeassistant`, and the conftest wrapper that enabled custom integrations goes, because the `hass`
  fixture now enables them by default (the package's README, "Migrating from
  pytest-homeassistant-custom-component").
- **Unavailable on a failed read.** A sensor becomes unavailable while a read that its own value needs has failed,
  and available again when the read works. Every other sensor stays available.
  - A period sensor: the recent table (5-minute or hourly) of its service or Overall, or a table one of its
    ranges needs (for example the month table for year to date).
  - A season sensor: the tables its running season needs, or a boundary read of the shown season that failed
    with no earlier readings kept.
  - All sensors: the metadata read before it has ever worked; the sensors of a service: its first-hours read
    before it has ever worked.
  - Unknown keeps its meaning: the data was read, but the period has not begun, a statistic has no data, a read
    did not cover the whole period yet, or the 0.1 kWh rule applies.
  - The coordinator still never raises `UpdateFailed`. The failure and the recovery are logged once each, at info
    level as the `log-when-unavailable` rule asks (ha-docs: `rules/log-when-unavailable.md`); today the failure
    is logged as a warning.
- **Home Assistant tests** for setup, unload, the entry migration, the coordinator, the sensors, the diagnostics
  and the repair issues, on synthetic statistics in the test recorder.
- **Coverage gate.** CI measures the coverage of `custom_components/heatpump_efficiency/` over both test folders
  combined, and fails when the total or any module is below 95 %. `config_flow.py` keeps its 100 % gate.
- **Record and tier.** `entity-unavailable` and `test-coverage` become `done`; the manifest declares `silver`.
- **Constitution.** `openspec/config.yaml` and `AGENTS.md` name `pytest-homeassistant` and the two coverage tools
  for `tests_ha/`.
- **README.** The failed-read text, the Development section and the Status section.
- **Release 0.3.0** at Silver, which also ships the reformatted code of `adopt-ruff-lint`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `period-efficiency`: "Never a partial figure" separates unknown from unavailable; new requirements "Unavailable
  while a needed read fails" (which sensors) and "Failed reads logged once" (info level).
- `season-efficiency`: "Finished seasons read once" makes a failed boundary read unavailable instead of unknown.
- `packaging`:
  - "Home Assistant tests" names `pytest-homeassistant`;
  - "Declared tier backed by the record" is replaced by "Declared tier matches the record", the same rule with a
    Silver scenario instead of the Bronze one;
  - a new requirement "Integration coverage gate" adds the 95 % gate.

## Tools checked

- **`pytest-homeassistant` (core's test package):** used. It is the maintained successor of
  `pytest-homeassistant-custom-component` and has a release for the target version.
- **`pytest-cov` and `coverage`:** used, at core's pins. `coverage combine` merges the two test runs.
- **The coordinator's own availability (`UpdateFailed`):** not used. It makes every sensor of the entry
  unavailable on any failure, while the owner decided on only the affected ones.
  `CoordinatorEntity.available` is still part of each sensor's `available` (ha-core:
  `homeassistant/helpers/update_coordinator.py` at 2026.11.2).
- **A per-module coverage threshold in coverage itself:** none exists (`fail_under` is a total). A
  standard-library script in `scripts/` checks each module.

## Out of scope

- **Gold and Platinum.** `strict-typing` stays `todo`; no follow-up change is planned yet.
- **A repair issue for a failed read.** The log lines are what the rule asks for; the statistics health check
  keeps its own repair issues.
- **Running `tests_ha/` on Windows.** The harness does not load there; CI and Linux or macOS only, as before.

## Impact

- **Code:**
  - `engine.py` marks which results depend on a failed read;
  - `sensor.py` adds `available`;
  - `coordinator.py` logs at info level.
- **Tests:** new files in `tests_ha/`; `tests/test_engine.py` and `tests/test_integration_files.py` extended.
- **CI:** `.github/workflows/validate.yml`, the `ha-tests` job.
- **New file:** `scripts/coverage_gate.py`.
- **Docs and rules:** `README.md`, `openspec/config.yaml`, `AGENTS.md`, `quality_scale.yaml`, `manifest.json`
  (tier and version).
- **Work branch:** the change touches `custom_components/` and `tests_ha/`, so it is built on
  `change/reach-silver-quality-scale`.
- **Live installation:** touched only by the release group, each step with the owner's go:
  - update to 0.3.0 through the Marketplace and restart, after offering a backup;
  - check that the sensors keep their entity IDs and states.
