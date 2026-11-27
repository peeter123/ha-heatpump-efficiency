# Tasks: reach-silver-quality-scale

The change touches `custom_components/` and `tests_ha/`, so it is built on the work branch
`change/reach-silver-quality-scale`, created from `main` before the first planning-artifact commit. After each group,
the branch is pushed with the owner's go, and the next group starts only when CI is green. Only group 5 touches the
live installation.

## 1. Core's test package

- [x] 1.1 Amend `openspec/config.yaml` as in design D8: the Tooling paragraph lets `tests_ha/` use
  `pytest-homeassistant`, `pytest-cov` and `coverage` at exact versions through uv, in CI and locally only on Linux
  or macOS, with the pin rule (the release equal to the target Home Assistant version, or the newest before it);
  `pytest-cov` and `coverage` are core's pins in `requirements_test.txt` at the target tag and move with it; the
  CI coverage run of `tests/` uses the `scripts/lint.py` pins plus those two tools, the one run of `tests/`
  outside the lint entry point; the `ha-test-harness` source tag names `pytest-homeassistant`. Make the same edits in `AGENTS.md`'s Layout and
  "Rules in short". Verify: neither file names `pytest-homeassistant-custom-component`, and
  `openspec validate reach-silver-quality-scale --strict` passes.
- [x] 1.2 Move `tests_ha/` to the new package (design D1):
  - imports from `pytest_homeassistant`;
  - the autouse wrapper fixture removed from `tests_ha/conftest.py`;
  - the comments that cite `pytest-homeassistant-custom-component` 0.13.375 or Home Assistant 2026.10.4 re-cited
    against the 2026.11.2 wheel or core.

  First check whether the integration loads from the repository's `custom_components/` with the conftest's early
  import. If it does not, use D1's fallback (`-o ha_test_root=tests_ha` with an empty `tests_ha/testing_config/`)
  and record the outcome in design D1 with the date. Verify: `python scripts/lint.py` exits 0; the CI run of the
  group is the check of the harness.
- [x] 1.3 Update the `ha-tests` job in `.github/workflows/validate.yml` (design D1, D2 step 1): `--with
  pytest-homeassistant==2026.11.2 --with pytest-cov==7.1.0 --with coverage==7.16.2`, `-p no:respx`, the
  `--cov=custom_components/heatpump_efficiency` path source, and the config flow gate on the same pins. Update
  the workflow tests in `tests/test_integration_files.py` for the scenario "Pinned test package": an exact
  `pytest-homeassistant==` pin, no `pytest-homeassistant-custom-component`, Python 3.14, `tests_ha`. Verify:
  `python scripts/lint.py` exits 0.
- [x] 1.4 Update the README's Development section: the Home Assistant test commands with the new pins and
  `-p no:respx`. Verify: the commands in the README equal those in the workflow, and the README does not name the
  old package.

## 2. Unavailable while a needed read fails

- [x] 2.1 In `engine.py`, as in design D4:
  - add `read_failed: bool = False` to `PeriodResult` and `SeasonResult`;
  - add `EngineState.first_hours_failed`, set in `_refresh_first_hours`;
  - add the pure helper `failed_sources(state)`;
  - mark the periods, the running and the finished shown seasons, and the whole service for a never-read metadata
    or first hour;
  - count the reads that depend on the recent tables as D4 says: a range whose table does not cover a statistic
    whose last-row-end source failed, and a boundary read made while such a source failed (through
    `after_failed_read`);
  - show `first_hours_failed` in `diagnostics_data`.

  Add tests to `tests/test_engine.py` for:
  - the `period-efficiency` scenarios "Month read fails", "Month read fails for one update", "Recent read fails",
    "Hourly service while the 5-minute read fails", "Metadata never read", "Later metadata failure" and "Unknown
    is not unavailable";
  - the `season-efficiency` scenarios "Boundary read fails", "Repeated boundary read fails", "Boundary read while
    the recent read fails" and "Running season needs a failed read";
  - a failed first-hours read before the first success.

  Verify: `python scripts/lint.py` exits 0.
- [x] 2.2 In `sensor.py`, add `available` to `EfficiencySensor` and `SeasonEfficiencySensor` (design D5): the
  coordinator's availability and not `read_failed` of the sensor's own result, with the ha-core citations. Verify:
  `python scripts/lint.py` exits 0; the sensor behaviour is tested in group 3.
- [x] 2.3 In `coordinator.py`, log the failure line at info level instead of warning (design D6). Update the
  coordinator docstring: a failed read makes the affected sensors unavailable, not unknown. Verify:
  `python scripts/lint.py` exits 0.
- [x] 2.4 Update the README:
  - the failed-read sentences ("A failed read never breaks the sensors ..." and the missing-statistic note under
    the repair issues) say which sensors become unavailable;
  - the definitions of unknown say that unknown means the data was read;
  - one sentence says that an available sensor's series attributes can miss points while a history read fails
    (D4);
  - the troubleshooting text names the info log line.

  Verify: the README describes no behaviour the code does not have, and every "unknown" that came from a failed
  read now says "unavailable".

## 3. Home Assistant tests and the coverage gate

- [x] 3.1 Add `scripts/coverage_gate.py` (design D3) and `tests/test_coverage_gate.py` for the `packaging`
  scenarios "Module below the threshold" and "Every module covered", plus an unreadable report (exit 2). Verify:
  `python scripts/lint.py` exits 0.
- [x] 3.2 Add the Home Assistant tests of design D7: `tests_ha/test_init.py`, `test_coordinator.py`,
  `test_sensor.py`, `test_diagnostics.py` and `test_issues.py`.
  - `test_coordinator.py` covers the `period-efficiency` scenarios "Month read fails for one update" (the states
    `unavailable` and back), "Recent read fails" and "Logged once" (`caplog`, info level), through the harness.
  - In `tests_ha/test_config_flow.py`, drop the setup and unload patches where the real setup now runs (D7; group 1
    already removed the 2026.10.4 comment).

  Verify: `python scripts/lint.py` exits 0 (compile and ruff); the CI run is the check of the harness.
- [x] 3.3 Extend the `ha-tests` job with D2 steps 2 to 5: the `tests/` run under coverage with `--cov-append`, the
  config flow gate, `coverage json`, and `python scripts/coverage_gate.py coverage.json 95`. Add a test in
  `tests/test_integration_files.py`:
  - it covers the scenario "Gate in the workflow": both folders under coverage, `--cov-append`, the gate at 95;
  - it checks that the `tests/` pins in the job equal those in `scripts/lint.py`.

  Verify: `python scripts/lint.py` exits 0. In CI, the first combined report shows `engine.py` covered by `tests/`
  (D2), and the job passes with every module at 95 % or more. If a module is under it, add tests in the same
  group until it is not.

## 4. Gold

- [x] 4.1 Update `quality_scale.yaml` as in design D8: `entity-unavailable` and `test-coverage` `done` with their
  comments, the `log-when-unavailable` comment, and the four Gold comments. Set the manifest's `quality_scale` to
  `gold`. In `tests_ha/test_quality_scale.py`, add a test for the scenario "Gold declared" (the generic tier tests
  covered "Bronze after this change"), and cite the requirement "Declared tier matches the record". Verify: `python scripts/lint.py`
  exits 0; the record test in CI passes.
- [x] 4.2 Set the manifest `version` to `0.3.0`. Update the README's Status section: version 0.3.0, the Gold
  tier with a link to `quality_scale.yaml`. Verify: the README's version matches the manifest, and
  `python scripts/lint.py` exits 0.

## 5. Release and live update

- [ ] 5.1 [User authorization: pushes `main`] After the whole-change review, fast-forward `main` to the work branch,
  run the leak check, and push `main`. Delete the remote work branch with the owner's go. Verify: all CI jobs pass
  on `main`.
- [ ] 5.2 [User authorization: tag and release] Tag `v0.3.0` on that commit and publish a GitHub release with
  notes:
  - Gold;
  - unavailable sensors on a failed read, and the info log;
  - the coverage gate;
  - the ruff settings and the reformatted code of `adopt-ruff-lint`.

  Verify: `gh release view v0.3.0`, and the Marketplace offers 0.3.0.
- [ ] 5.3 [User authorization: updates the live installation and restarts Home Assistant; offer a backup first]
  Update to 0.3.0 through the Marketplace and restart. Verify:
  - the entry loads;
  - the sensors keep their entity IDs and states, and every one is available;
  - there are no log entries for the integration.

  Record the update in `private/installation.md`.

## Workflow follow-up

- "Harness runs in CI (live check)", "Gate met (live check)" and "Coverage met (live check)" are the CI runs of
  the work branch and of `main`.
- Sync the `period-efficiency`, `season-efficiency` and `packaging` deltas, archive, and commit to `main` after the
  leak check.
