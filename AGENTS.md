# AGENTS.md

A Home Assistant custom integration that shows a heat pump's real efficiency over any period (today, month to
date, year to date, rolling 12 months, per day and per month) as a ratio of energy changes from long-term
statistics, never as a time average of live COPs. Universal: the owner maps their own energy statistics in the
setup UI. Planned and built with OpenSpec; `openspec/config.yaml` is the constitution and its rules are binding.
Read it, and the active change in `openspec/changes/`, before any work.

## Layout

- `openspec/`: `config.yaml` (context, rules, apply workflow), `specs/` (accepted capabilities), `changes/`
  (active changes and `archive/`).
- `custom_components/<domain>/`: the integration (HACS layout), created by the first change.
- `tests/`: tests of the pure modules, run by `python scripts/lint.py` under pytest, pytest-asyncio and tzdata at
  exact versions through uv, without Home Assistant. The time zone tests use `zoneinfo`. CI also runs them under
  coverage (`--cov-append`, the `scripts/lint.py` pins plus pytest-cov and coverage), adding to the data of
  `tests_ha/`.
- `tests_ha/`: pytest tests that run the integration in Home Assistant's test harness
  (`pytest-homeassistant`, with `pytest-cov` and `coverage`, the third-party test dependencies of this folder, each
  at an exact version through uv, in CI and locally only on Linux or macOS; the package version is the release equal
  to the target Home Assistant version, or the newest before it, and `pytest-cov` and `coverage` are core's pins at
  that tag; the lint entry point checks that they compile).
- `pyproject.toml`: the ruff settings, copied from Home Assistant core's `pyproject.toml` at tag 2026.11.2 with
  only the adaptations commented in it, and the pytest settings (asyncio mode, `testpaths`) of both test folders.
- `LICENSE`: the MIT licence.
- `docs/`: images used by `README.md`.
- `.github/workflows/`: the `validate.yml` workflow (hassfest, HACS action, the lint job that runs
  `scripts/lint.py`, and the Home Assistant tests job: `tests_ha/`, then `tests/` under coverage, the config flow
  gate at 100 %, and `scripts/coverage_gate.py` at 95 % for the total and every module).
- `scripts/`: `lint.py`, the one entry point of every local check (ruff check, ruff format check, the tests in
  `tests/` and a compile check; `--fix` applies ruff's fixes and the formatter first; needs uv), and `brand.py`,
  the standard-library script that draws the brand images in `custom_components/<domain>/brand/`; its geometry is
  the icon's source.
  It also holds `coverage_gate.py`, the standard-library coverage gate that CI runs on coverage's JSON report (exit 0;
  1 when the total or a module is below the threshold, or the report has no file of the integration; 2 for an
  unreadable report).
- `private/` (git-ignored): `installation.md` and captures specific to the live installation.

## Rules in short

- Read-only towards statistics: never import, adjust or clear statistics, never call other integrations'
  services, never control a heat pump.
- Nothing installation-specific in tracked files; it goes in `private/`.
- Verify every Home Assistant API against the Core 2026.11.2 source and cite it.
- No emoji; all user-facing text through translations.
- Standard library only for the integration and `scripts/`; `tests/` may use pytest, pytest-asyncio and tzdata,
  and `tests_ha/` `pytest-homeassistant`, `pytest-cov` and `coverage`; ruff lints all Python. Every tool runs at an
  exact version through uv from `scripts/lint.py` (`tests_ha/` and the CI coverage run of `tests/` excepted;
  `pytest-cov` and `coverage` are at core's pins at the target tag); uv is the one program taken from PATH besides
  Python.
- Validation: `python scripts/lint.py`, which must exit with 0.
- Uncommitted planning artifacts of a change get their own commit before each task group; then one commit per
  task group, after its validation passes and its review is clean; never push, except the work branch
  `change/<change-id>` that every change touching `custom_components/` or `tests_ha/` is built on: pushed with the
  user's go after each group's commit and leak check, the next group only when CI is green, one "Fix group <n> of
  <change-id>: ..." commit for a red run (amended and force-pushed with the user's go if that is red too; the only
  history rewrite allowed, on the work branch only, never on `main`), and a fast-forward of `main` at the end,
  pushed with the user's go; commits after that fast-forward that touch neither `custom_components/` nor
  `tests_ha/` (`tasks.md` check-offs, docs, the archive) go to `main` directly, after the leak check; each push has
  the user's go (details in `openspec/config.yaml`).
- Live-installation steps (install, restart, config entry, dashboard) only with the user's explicit go-ahead.
