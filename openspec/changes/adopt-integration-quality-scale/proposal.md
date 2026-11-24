# Proposal

## Why

The HACS action warns on every run that the manifest has no categories, and the integration has never been
measured against Home Assistant's Integration Quality Scale. Both matter before the pull request to the HACS
default list: categories decide where people find the integration, and a rule-by-rule quality record shows
reviewers and users what it does and does not cover. A tier can only be claimed honestly with tests of the code
that needs Home Assistant, which the project's standard-library-only tooling rule does not allow today.

## What Changes

- `manifest.json` gets `categories`: `climate.heat_pumps_air_conditioning` first, `energy.meters_monitoring`
  second. Both are known categories (ha-core: `homeassistant/components/homeassistant/strings.json`,
  `integration_category`); hassfest accepts one to three unique values and warns about unknown ones for custom
  integrations (ha-core: `script/hassfest/manifest.py`, `validate_categories`). No `connectivity` value: none of
  the known values fits an integration that only reads the recorder.
- `manifest.json` declares `"quality_scale": "bronze"` (ha-core: `script/hassfest/manifest.py`,
  `SUPPORTED_QUALITY_SCALES`), and a `quality_scale.yaml` next to it records every rule of the scale as `done`,
  `todo` or `exempt` with a comment. hassfest does not validate that file for custom integrations (ha-core:
  `script/hassfest/quality_scale.py`, `validate_iqs_file`), so the repository's own tests check it.
- Tests of the Home Assistant glue: config flow and options flow tests that run with
  `pytest-homeassistant-custom-component` in GitHub CI, with the config flow fully covered (rule
  `config-flow-test-coverage`). The standard-library tests stay as they are.
- The config flow aborts when one of the new entry's output statistics is already the output of a service in
  another entry (rule `unique-config-entry`).
- Entity icons through an `icons.json` per translation key (rule `icon-translations`).
- README: removal instructions, use cases, supported devices and known limitations (rules
  `docs-removal-instructions`, `docs-use-cases`, `docs-supported-devices`, `docs-known-limitations`), and the new
  development workflow.
- Project rules (`openspec/config.yaml` and `AGENTS.md`): the Home Assistant test package is allowed in CI through
  uv at pinned versions; a change that touches `custom_components/` or `tests_ha/` is built on a work branch that
  is pushed after each group's commit, with the user's go each time; a red group gets one fix commit, which is
  amended and force-pushed on the work branch if CI is red again.
- Last group: once a `pytest-homeassistant-custom-component` release for Home Assistant 2026.11.x exists, the pin
  moves to it, setup and unload tests are added, and the declared tier rises to Silver or Gold as the coverage and
  the record allow.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `packaging`: manifest categories and quality scale, the `quality_scale.yaml` record and its check, the CI test
  job with its pinned test package, and the work-branch loop.
- `efficiency-setup`: the config flow refuses an output statistic that another entry already uses as an output.
- `period-efficiency`: every sensor has an icon from `icons.json` (season sensors included, through the same
  translation keys mechanism).

## Impact

- `custom_components/heatpump_efficiency/`: `manifest.json`, new `quality_scale.yaml` and `icons.json`,
  `config_flow.py` and a pure duplicate check in `validation.py`, `translations/en.json` (the abort reason).
- New `tests_ha/` (pytest tests that need Home Assistant), `.github/workflows/validate.yml` (a new job),
  `README.md`, `AGENTS.md`, `openspec/config.yaml`.
- Dependencies: none at runtime; in CI only, `pytest-homeassistant-custom-component==0.13.375` (pins
  `homeassistant==2026.10.4`, PyPI), run through uv on Python 3.14.
- Live installation: no step until the release. Then a Marketplace update to the new version and a restart, with
  the user's go-ahead and an offered backup; the existing entry keeps its entities (no option, entity ID or unique
  ID changes), and the icons appear on its sensors.
- Existing tools checked: hassfest and the HACS action (kept; they do not check a custom integration's quality
  record), Core's own test harness at tag 2026.11.2 (not used: a full Core checkout in CI for a handful of tests),
  local runs on Windows (not possible: Home Assistant's test plugin imports `fcntl`, which exists only on Unix).

## Out of scope

- The pull request to the HACS default list (hacs/default): after this change is released.
- `strict-typing` (Platinum): mypy in strict mode; a follow-up if wanted.
- Duplicate checks in the options flow: the rule covers setup; the options flow keeps today's checks.
