# Tasks

This change is built on the work branch `change/adopt-integration-quality-scale` (design D6, `packaging` "Work
branch for changes to the integration or its tests"). The branch is created from `main` before the first
planning-artifact commit. After each group's commit and the leak check, the branch is pushed with the owner's go,
and the next group starts only when every CI job passes; a red run gets one commit "Fix group <n> of
adopt-integration-quality-scale: ...", and if that is red too, the fix commit is amended and the branch
force-pushed with the owner's go. Local validation per group: `python -m unittest discover tests` and
`python -m compileall custom_components`; tasks are checked off after it passes. The Home Assistant tests
(`tests_ha/`) run in CI (on Windows they cannot run).

Decisions of 2026-11-24 (group 1 review): the work-branch loop covers every change that touches
`custom_components/` or `tests_ha/`; uv is pinned to an exact version in the workflow; `openspec/config.yaml` gets
the source tag `ha-test-harness`; a red fix commit is amended and force-pushed on the work branch only;
`pytest.ini` also sets `asyncio_default_fixture_loop_scope = function`, as the test package does.

## 1. Project rules, test harness and CI job

- [x] 1.1 Amend `openspec/config.yaml` as in design D6: the tooling paragraph allows `pytest-homeassistant-custom-component` for `tests_ha/` only, at an exact version run through uv in CI, with the pin rule (the target Home Assistant version or the newest before it); the validation and commit paragraphs describe the work branch, the push with the owner's go after each group's commit and leak check, the next group only on green, the one "Fix group <n> of <change-id>: ..." commit for a red run, and the fast-forward of `main` at the end; the specs rule names the Home Assistant tests in CI as a third way to check a scenario; update `AGENTS.md`'s Layout (`tests_ha/`, `pytest.ini`) and Rules in short to match; verify `openspec validate adopt-integration-quality-scale --strict` passes and both validation commands pass
- [x] 1.2 Add a root `pytest.ini` (`testpaths = tests_ha`, `asyncio_mode = auto`) and `tests_ha/conftest.py` that enables custom integrations through the `enable_custom_integrations` fixture (design D4), and `tests_ha/test_smoke.py` with one test that starts the config flow's user step with the `recorder_mock` fixture and gets the form; verify `python -m unittest discover tests` runs the same number of tests as before and imports nothing from `tests_ha/`
- [x] 1.3 Add the `ha-tests` job to `.github/workflows/validate.yml` (design D4): checkout, `astral-sh/setup-uv` at a pinned tag, and `uv run --no-project --python 3.14 --with pytest-homeassistant-custom-component==0.13.375 pytest --cov=custom_components.heatpump_efficiency --cov-report=term-missing`; extend the workflow test in `tests/test_integration_files.py` to find this job, Python 3.14 and an exact `==` pin; verify the unittest run passes
- [x] 1.4 Update README.md's Development section: the two test sets (standard-library tests run anywhere; the Home Assistant tests need Linux or macOS and run in CI, with the `uv run` command for running them locally there), and that GitHub runs four jobs; verify the documented `unittest` and `compileall` commands run as written

## 2. Duplicate check and config flow tests

- [x] 2.1 Add `shared_outputs(mapping, other_mappings)` to `validation.py` (design D3): the sorted output statistic IDs of `mapping`, across all sections and Overall, that are an output statistic in any of the other mappings; add tests in `tests/test_validation.py` for the `efficiency-setup` scenarios (output used by another entry, different outputs, Overall reusing its own Heating output, only electricity shared, no other entry); verify the unittest run passes
- [x] 2.2 Call it in the config flow's user step after validation, with the options of the other entries from `_async_current_entries`, and abort with reason `already_configured` and a placeholder naming the shared statistics (design D3); add the English text under `config.abort.already_configured` in `translations/en.json`; verify the translation tests in `tests/test_integration_files.py` still pass and `compileall` passes
- [x] 2.3 Add `tests_ha/test_config_flow.py`: synthetic statistics in the test recorder (made-up IDs, energy unit, running sum), `async_setup_entry` patched to return `True` where an entry is created; cover every line and branch of `config_flow.py`: the user step (created entry, each validation error, the name error, the duplicate abort), the options flow (saved options, each error, the Cooling unit-change step and its confirmation); verify locally that the file compiles and, in CI, that the job passes
- [x] 2.4 Add the coverage gate to the `ha-tests` job: `coverage report --include="*/config_flow.py" --fail-under=100` after the pytest run (design D4); extend the workflow test to find it; verify the unittest run passes
- [x] 2.5 Update README.md's Setup section: a second heat pump must use its own output statistics, and adding one whose output statistic another entry already uses ends with an already-configured message that names it; verify the text matches the abort message in `translations/en.json`

## 3. Icons and documentation

- [x] 3.1 Add `custom_components/heatpump_efficiency/icons.json` (design D5) with `entity.sensor.<translation key>.default` for all 19 sensor translation keys: Heating `mdi:radiator`, Hot water `mdi:water-boiler`, Cooling `mdi:snowflake`, Overall `mdi:heat-pump` (design D5, settled in review on 2026-11-24); check each name by hand against the Material Design Icons list; add a test in `tests/test_integration_files.py` for the `period-efficiency` scenario "An icon for every translation key"; verify the unittest run passes
- [x] 3.2 Update README.md for the Gold and Bronze documentation rules (design D2): a "Removing the integration" section (delete the entry from Devices and services, then uninstall it through the Marketplace; the long-term statistics of its sensors stay in the recorder until deleted under Settings, Tools, Statistics), the Installation section and every other mention describing the Marketplace only, with one line that HACS is now built in as the Marketplace (design Open Questions, user decision 2026-11-24), and use cases, supported heat pumps (any with energy statistics in kWh), and known limitations (5-minute delay, external statistics hourly, no cost figures, figures only as good as the mapped counters) in the matching sections, and the sensor icons in the Sensors section; verify each new section exists and the README describes no behaviour the code does not have

## 4. Categories and the quality scale record

- [x] 4.1 Add `categories` (design D1) and `"quality_scale": "bronze"` to `manifest.json` in sorted key order; extend `ManifestTest` in `tests/test_integration_files.py` for the `packaging` scenario "Categories in the manifest" (values and order, no parent with its own subcategory, no `connectivity`, keys after `domain` and `name` sorted); verify the unittest run passes
- [x] 4.2 Add `custom_components/heatpump_efficiency/quality_scale.yaml` with all 54 rules of hassfest's `ALL_RULES` at 2026.11.2 and the statuses and reasons of design D2's table (every `exempt` and `todo` with a comment; `test-coverage` and `strict-typing` `todo`); verify by reading that every Bronze rule is `done` or `exempt`
- [x] 4.3 Add `tests_ha/test_quality_scale.py` (design D2): the rule names and tiers copied from `script/hassfest/quality_scale.py` `ALL_RULES` at 2026.11.2, cited in the file; load the record with `homeassistant.util.yaml.load_yaml_dict`; check the `packaging` scenarios of "Quality scale record" and "Declared tier backed by the record" (every rule listed, valid values, comments on `exempt` and `todo`, the declared tier is the highest one the record supports, a failing rule named in the message); verify in CI that it passes
- [x] 4.4 Set the manifest `version` to `0.2.0`, and update README.md's Status section (version 0.2.0, the declared Bronze tier with a link to `quality_scale.yaml`); verify the README's version matches the manifest and the unittest run passes
- [x] 4.5 Extend `tests_ha/test_config_flow.py` for the `config-flow-test-coverage` rule (design D2, decision of 2026-11-24): after every error form in the user step (each validation error and the name error) and in the options flow, resubmit valid input on the same `flow_id` and assert the created entry or the saved options; keep `config_flow.py` at 100 % line and branch coverage; verify `compileall` locally and the job in CI
- [x] 4.6 Apply the other decisions of 2026-11-24 in design D2: `test-before-setup` `exempt` (a pure local calculation from the recorder), `entity-unavailable` `todo` with the correct reason (a failed read logs a warning once and makes the affected periods unknown; no repair issue; a follow-up change makes the sensors unavailable), and add one short automation example to README.md (for `docs-examples`) that uses only the integration's sensors and states that are real, for example a notification when a month-to-date efficiency drops below a threshold; the declared tier stays `bronze`; verify the record test's expectations and the unittest run

## 5. Home Assistant 2026.11 test package

Moved to a follow-up change (design D7). On 2026-11-24, after group 4, the newest
`pytest-homeassistant-custom-component` release on PyPI was 0.13.375, which pins `homeassistant==2026.10.4`; no
release pins 2026.11.x. The follow-up moves the pin, adds the setup, unload, coordinator, sensor and diagnostics
tests and the 95 % total coverage gate, and closes `test-coverage`. The change continues with groups 6 and 7 at Bronze.

## 6. Whole-change review fixes

Decisions of 2026-11-24 from the whole-change review: the packaging delta renames "Installable as a HACS custom
repository" to "Installable through the Marketplace" and updates "Releases"; commits after the fast-forward of
`main` that touch neither `custom_components/` nor `tests_ha/` go to `main` directly (design D6).

- [ ] 6.1 Fix the stale UI text: `translations/en.json` `options.step.unit_change.description` names the statistics tools as in the README (Settings, Tools, Statistics), and `config.step.user.data_description.name` says a second heat pump needs its own output statistics; verify the translation tests and that the README and the UI text agree
- [ ] 6.2 Project rules: in `openspec/config.yaml`, the product paragraph says the integration is installed through the Marketplace, the validation paragraph also runs `python -m compileall tests_ha`, and the work-branch paragraph states the design D6 exception for commits after the fast-forward; `AGENTS.md` matches (the validation commands, the exception, and the Windows `tzdata` note in Rules in short); `.gitignore` ignores `.pytest_cache/`; verify `openspec validate adopt-integration-quality-scale --strict`
- [ ] 6.3 Record and its test: the `test-coverage` comment in `quality_scale.yaml` names everything the follow-up adds (the 2026.11 test package, setup, unload, coordinator, sensor and diagnostics tests, and the 95 % gate); `tests_ha/test_quality_scale.py` gets a negative check that a bare `exempt`, and a `todo` or `exempt` without a comment, fail the value check; verify `compileall` locally and the job in CI

## 7. Release and live update

- [ ] 7.1 [User authorization: pushes `main`] Fast-forward `main` to the work branch, run the leak check, push `main`, and delete the remote work branch; verify all CI jobs pass on `main` and the HACS job log has no categories warning
- [ ] 7.2 [User authorization: tag and release] Tag `v0.2.0` on that commit and publish a GitHub release with notes (categories, quality scale record, duplicate check, icons, documentation, tests); verify `gh release view v0.2.0` and that the Marketplace offers 0.2.0
- [ ] 7.3 [User authorization: updates the live installation and restarts Home Assistant; offer a backup first] Update to 0.2.0 through the Marketplace and restart; verify the entry loads, the 19 sensors keep their entity IDs and states, each shows its service's icon (`period-efficiency` live check), and there are no log entries for the integration
- [ ] 7.4 [User authorization: starts a config flow on the live installation] Start adding the integration with the live Heating output statistic; verify the flow ends with the already-configured message naming it and no entry is created; record 7.3 and 7.4 in `private/installation.md`
- [ ] 7.5 [User authorization: takes a screenshot of the live installation; pushes `main`] After 7.3, take a light-mode screenshot of the integration's sensors with their icons (the device page, or a dashboard view of the sensors), and check that it shows no installation-specific identifiers (entity IDs, hostnames, other devices; crop or blur them otherwise); save it as `docs/sensors.png` and show it near the top of README.md, with alt text, and add `docs/` to `AGENTS.md`'s Layout; verify the image renders on the repository page after the push and the leak check passes

## Workflow follow-up

- Whole-change review, then sync the delta specs and archive the change.
