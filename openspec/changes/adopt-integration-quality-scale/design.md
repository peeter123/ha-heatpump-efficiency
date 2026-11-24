# Design

## Context

See proposal.md for why. Version 0.1.0 is released and installed through HACS. All Home Assistant glue
(`__init__.py`, `config_flow.py`, `coordinator.py`, `sensor.py`, `diagnostics.py`, `issues.py`) is verified only on
the live installation; the pure modules have standard-library `unittest` tests in `tests/`. The project rules allow
no third-party packages, and every Home Assistant API is verified against Core 2026.11.2.

Facts this design rests on:

- hassfest checks a custom integration's manifest with `CUSTOM_INTEGRATION_MANIFEST_SCHEMA`: `categories` is a
  list of 1 to 3 unique values matching `^[a-z0-9_]+(\.[a-z0-9_]+)?$`, and `quality_scale` one of the scaled tiers
  (bronze to platinum) or `custom`, `no_score`, `internal`, `legacy` (ha-core: `script/hassfest/manifest.py`,
  `INTEGRATION_MANIFEST_SCHEMA`, `SUPPORTED_QUALITY_SCALES`). `validate_categories` warns about an unknown category
  for a custom integration and errors when a parent is listed with its own subcategory; a tier of silver or higher
  requires `codeowners` (`validate_manifest`). Keys are sorted domain, name, then alphabetically (`sort_manifest`).
- hassfest skips `quality_scale.yaml` for custom integrations: `validate_iqs_file` returns at once when
  `integration.core` is false (ha-core: `script/hassfest/quality_scale.py`). Its `SCHEMA` and `ALL_RULES` (54
  rules: 20 bronze, 10 silver, 21 gold, 3 platinum) define the file's format and the rules per tier.
- `pytest-homeassistant-custom-component` releases pin one exact Home Assistant version; the newest, 0.13.375,
  pins `homeassistant==2026.10.4`, needs Python 3.14 and brings `pytest-cov` (PyPI). No release for 2026.11.x
  exists yet.
- Between 2026.10.4 and 2026.11.2 every API the integration imports exists with the same names, and the three
  recorder functions (`statistics_during_period`, `async_list_statistic_ids`, `get_metadata`) have the same
  signatures, except: 2026.10.4 requires `async_setup_entry` and `async_unload_entry` to return a boolean and has
  no `async_unload_platforms_or_raise` (ha-core 2026.10.4: `homeassistant/config_entries.py`,
  `ConfigEntry.async_setup`); 2026.11.2 accepts `None` and has that method (ha-core 2026.11.2:
  `homeassistant/config_entries.py`, `_async_process_entry_method_result`). Our `__init__.py` uses the 2026.11
  form.
- The test plugin does not load on Windows: `homeassistant/runner.py` imports `fcntl` (checked with uv and
  Python 3.14.8).

## Goals / Non-Goals

**Goals:**

- A Bronze claim that the repository's own checks back, rule by rule.
- Every Silver and Gold rule that does not need setup and unload tests closed or exempt with a reason, except
  `entity-unavailable`, which a follow-up change closes (decision of 2026-11-24 in D2).
- No behaviour change for the existing entry beyond icons.

**Non-Goals:**

- No change to the efficiency arithmetic, the sensors' states or attributes, options, entity IDs or unique IDs.
- No new duplicate check in the options flow.
- No code written for Home Assistant versions older than the `hacs.json` minimum (2026.11.0).

## Decisions

### D1. Manifest categories

`"categories": ["climate.heat_pumps_air_conditioning", "energy.meters_monitoring"]`, placed after `name` in key
order (`categories` sorts before `codeowners`). Both are known values (ha-core:
`homeassistant/components/homeassistant/strings.json`, `integration_category.climate.subcategory` and
`integration_category.energy.subcategory`). Alternatives: `helpers.calculate_value` (accurate, but the helpers
category is for entities a user creates without a device, and the integration has a device per entry); one value
only (loses the energy listing). No `connectivity`: its 22 known values (same strings file,
`integration_connectivity`) all name a device link or the host, and the integration reads only the recorder.

`tests/test_integration_files.py` checks the two values and that no parent is listed with its own subcategory.

### D2. Quality scale record and its check

`manifest.json` gets `"quality_scale": "bronze"`. `custom_components/heatpump_efficiency/quality_scale.yaml`
follows hassfest's `SCHEMA`: under `rules`, every rule of `ALL_RULES` at 2026.11.2, each `done` or `todo`, or a
mapping with `status` and `comment` (`exempt` requires the mapping). Every `exempt` and every `todo` carries a
comment.

Because hassfest skips the file for custom integrations, a test in `tests_ha/` (D4) checks it the way
`validate_iqs_file` would: the set of rule names equals a copy of `ALL_RULES` with their tiers, kept in the test with
a citation; every value matches the schema; and every rule of the declared tier and the tiers below it is `done` or
`exempt`. The test loads the file with `homeassistant.util.yaml.load_yaml_dict`, the loader hassfest uses. A
standard-library test was rejected: Python ships no YAML parser.

Status per rule after this change, except the last group (`*` = closed by this change):

| Tier | done | exempt (reason) | todo |
|---|---|---|---|
| Bronze | appropriate-polling, brands, common-modules, config-flow, config-flow-test-coverage*, dependency-transparency, docs-high-level-description, docs-installation-instructions, docs-removal-instructions*, entity-event-setup, entity-unique-id, has-entity-name, runtime-data, test-before-configure, unique-config-entry* | action-setup, docs-actions, docs-conditions, docs-triggers (no actions, conditions or triggers); test-before-setup (a pure local calculation from the recorder, the rule's own exception; nothing remote to test before setup) | |
| Silver | config-entry-unloading, docs-configuration-parameters, docs-installation-parameters, integration-owner, log-when-unavailable, parallel-updates | action-exceptions (no actions); reauthentication-flow (no credentials) | entity-unavailable (a failed read logs a warning once and makes the affected periods unknown, but the sensors stay available; a follow-up change makes them unavailable); test-coverage (last group) |
| Gold | devices, diagnostics, docs-data-update, docs-examples*, docs-known-limitations*, docs-supported-devices*, docs-supported-functions, docs-troubleshooting, docs-use-cases*, entity-category, entity-disabled-by-default, entity-translations, icon-translations*, repair-issues | discovery, discovery-update-info (nothing to discover); dynamic-devices, stale-devices (one service device per entry, removed with it); entity-device-class (no device class for an efficiency ratio); exception-translations (the integration raises no exceptions of its own); reconfiguration-flow (the entry data holds only the name; everything else changes in the options flow, which reloads the entry) | |
| Platinum | | async-dependency, inject-websession (no library, no HTTP) | strict-typing |

Decisions of 2026-11-24 (group 4 review, against the rule pages on developers.home-assistant.io):
`config-flow-test-coverage` requires that each error test fixes the cause and finishes the flow, so the tests in
`tests_ha/test_config_flow.py` resubmit valid input on the same flow after every error; `docs-examples` means
automation examples, so the README gets one; `test-before-setup` is exempt under the rule's own "pure local
calculation" exception; `entity-unavailable` is `todo` with the correct reason (a failed read raises no repair
issue), so Silver also waits for the follow-up change that makes sensors unavailable on a failed read.

`entity-category`: every sensor is a primary figure, so none gets a category (done, with that comment).
`entity-disabled-by-default`: sensors exist only for mapped services and every period is a primary figure, so all
stay enabled (done, with that comment). The comments in the file give these reasons in full.

### D3. Duplicate entries

A pure function `shared_outputs(mapping, other_mappings)` in `validation.py` returns the output statistic IDs of
`mapping` (all sections, Overall included) that are an output statistic in any of `other_mappings`, sorted. Inputs:
the normalized mapping of the submitted form and the stored options of the other entries of the domain. It is
derived and tested in `tests/test_validation.py`. Overall reusing a service's output within the same entry is
unaffected: only other entries count.

The config flow's user step calls it after validation and, when the result is not empty, aborts with reason
`already_configured` (`ConfigFlow.async_abort`, ha-core: `homeassistant/data_entry_flow.py`,
`FlowHandler.async_abort`; the other entries from `ConfigFlow._async_current_entries`, ha-core:
`homeassistant/config_entries.py`), with an English text in `translations/en.json` under `config.abort`.
Alternatives: `_async_abort_entries_match` (ha-core: `homeassistant/config_entries.py`) matches exact data values,
not overlapping lists; a unique ID per entry has no natural value here. hassfest's own `unique-config-entry`
validator looks only for those two calls, but runs only for core integrations; the record's comment names the custom
check.

### D4. Home Assistant tests

- Location: `tests_ha/`, so `python -m unittest discover tests` stays standard-library only. A `conftest.py`
  enables custom integrations (`enable_custom_integrations` fixture) and sets `asyncio_mode = auto` through a root
  `pytest.ini` with `testpaths = tests_ha`.
- Data: tests use the `recorder_mock` fixture and add synthetic statistics to the test recorder (made-up statistic
  IDs). The read-only rule binds the integration, not its tests against a throwaway database.
- Scope now: the config flow and options flow, every branch of `config_flow.py` (rule `config-flow-test-coverage`),
  with `async_setup_entry` patched to return `True` where an entry is created, which also makes the tests independent
  of the 2026.10.4 setup return rule; the quality scale record (D2).
- CI: a new `ha-tests` job in `.github/workflows/validate.yml` installs uv (`astral-sh/setup-uv`, pinned tag) and
  runs `uv run --no-project --python 3.14 --with pytest-homeassistant-custom-component==0.13.375 pytest
  --cov=custom_components.heatpump_efficiency --cov-report=term-missing`, then fails unless `config_flow.py` is at
  100 % (`coverage report --include="*/config_flow.py" --fail-under=100`).
- Alternatives: Core's own test harness at tag 2026.11.2 (exact version, but a full Core checkout and its
  requirements per run); waiting for a 2026.11.x package before any test (blocks the change for an unknown time).

### D5. Icons

`custom_components/heatpump_efficiency/icons.json` gives `entity.sensor.<translation_key>.default` for every sensor
translation key from `sensor_model.translation_key` (periods and seasons), one icon per service: Heating
`mdi:radiator`, Hot water `mdi:water-boiler`, Cooling `mdi:snowflake`, Overall `mdi:heat-pump` (user decision
2026-11-24, replacing `mdi:heat-pump` for Heating and `mdi:heat-pump-outline` for Overall, which differ only in fill
and are hard to tell apart in the entity list). All four are in `@mdi/svg` 7.4.47, the version the frontend of Core
2026.11.2 ships (home-assistant-frontend 20261028.6, `package.json`). A
standard-library test checks that the keys equal the translation keys in `translations/en.json`. hassfest checks `icons.json`'s
structure but only the `mdi:` prefix of a value (ha-core: `script/hassfest/icons.py`, `icon_value_validator`), so
each name is checked once by hand against the Material Design Icons list when the file is written, and on the live
installation after the release.

### D6. Project rules and the work-branch loop

`openspec/config.yaml` and `AGENTS.md` change:

- Tooling: the standard library stays the rule for the integration, scripts and `tests/`; `tests_ha/` may use
  `pytest-homeassistant-custom-component` at a pinned version, run through uv (in CI, and locally only on Linux or
  macOS). The pin moves only to a release that pins the target Home Assistant version or the newest one before it.
  uv itself is pinned to an exact version in the workflow (`astral-sh/setup-uv` `version` input), like the action
  tag.
- Sources of truth: a new tag `ha-test-harness`, `pytest-homeassistant-custom-component` at the pinned version
  (file and fixture); `tests_ha/` cites it where a test depends on fixture behaviour, such as fixture order.
- Validation per group: the standard-library tests and `compileall` locally, after which the group's tasks are
  checked off; for a change on a work branch, the CI run of the group's commit confirms it.
- Specs rule: a scenario is checkable by a standard-library test offline, by the Home Assistant tests in CI, or by
  a named live check.
- Loop: every change that touches `custom_components/` or `tests_ha/` is built on the work branch
  `change/<change-id>` (user decision 2026-11-24), so `main` only gets commits CI has run. Per group: local
  validation, commit, leak check, push the branch with the user's go, wait for CI. A red run gets one commit
  "Fix group <n> of <change-id>: ...", the only allowed second commit of a group; if CI is red again, that fix
  commit is amended and the work branch force-pushed with the user's go (user decision 2026-11-24; this applies
  only to the work branch, never to `main`). The next group starts on green. When the change is done, `main` is
  fast-forwarded to the branch, pushed with the user's go, and the remote branch is deleted.

### D7. Last group: the 2026.11 test package

Blocked until `pytest-homeassistant-custom-component` publishes a release that pins `homeassistant==2026.11.x`.
Then the pin moves to it, tests of `async_setup_entry`, `async_unload_entry`, the coordinator and the sensor
platform are added, the CI job reports total coverage, and `test-coverage` becomes `done` when coverage is above 95 %.
The declared tier is whatever the record supports (the record test decides): it stays `bronze` while
`entity-unavailable` is `todo` (decision of 2026-11-24 in D2), and rises only after the follow-up change for that
rule. If no such release exists
when the other groups are done, this group moves to a follow-up change and the change archives with Bronze.
Outcome (2026-11-24): no such release existed after group 4 (newest 0.13.375, pinning 2026.10.4), so the group,
with the 95 % total coverage gate, moved to a follow-up change.

## Risks / Trade-offs

- [Tests run against 2026.10.4 while the target is 2026.11.2] -> The comparison above found only the setup and
  unload difference, which the patched setup avoids; D7 moves to the matching version.
- [Tests are written without a local run] -> The work-branch loop makes CI the check before the next group; a red
  run gets one fix commit.
- [A self-declared tier that nothing outside the repository checks] -> The D2 test reproduces hassfest's tier
  check; the record states every exemption's reason.
- [Synthetic statistics in the test recorder drift from real recorder behaviour] -> They use the recorder's own API
  in the pinned Home Assistant; the live check after the release covers the rest.
- [An icon name that is not in Material Design Icons; hassfest does not catch it] -> Checked by hand against the
  icon list when written, and seen on the live installation after the release.

## Migration Plan

Groups (refined in tasks.md): 1. project rules, `pytest.ini`, `tests_ha/` scaffold and the CI job, with one smoke
test, to prove the loop; 2. the duplicate check and the config and options flow tests; 3. icons and the README
additions; 4. manifest categories and quality scale, `quality_scale.yaml` and its test, and version 0.2.0 (last, so
the declared tier is backed from its first commit); 5. the 2026.11 test package (D7); 6. release and the live
update, with the user's go and an offered backup. Rollback: the Marketplace reinstalls
0.1.0; no stored option changes.

## Open Questions

None. The icon names (D5) were settled in the group 3 review on 2026-11-24. The same review decided that the README
describes installing and removing only through Home Assistant's built-in Marketplace (Settings, Marketplace),
checked against the UI text of the Core 2026.11.2 frontend, with one line saying HACS is now built in as the
Marketplace (user decision 2026-11-24). Reason: Core 2026.11.2 blocks the HACS custom integration and migrates
existing installs to the Marketplace (ha-core: `homeassistant/loader.py`, `BLOCKED_CUSTOM_INTEGRATIONS`;
`homeassistant/components/marketplace/migration.py`), and the integration requires 2026.11.0. The Marketplace still
reads `hacs.json` (`components/marketplace/repositories/base.py`), so `hacs.json` and the HACS action in CI stay.
