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
  exact versions through uv, without Home Assistant. The time zone tests use `zoneinfo`.
- `tests_ha/`: pytest tests that run the integration in Home Assistant's test harness
  (`pytest-homeassistant-custom-component`, the one third-party test dependency, run through uv, in CI and locally
  only on Linux or macOS; the lint entry point checks that they compile).
- `pyproject.toml`: the ruff settings, copied from Home Assistant core's `pyproject.toml` at tag 2026.11.2 with
  only the adaptations commented in it, and the pytest settings (asyncio mode, `testpaths`) of both test folders.
- `LICENSE`: the MIT licence.
- `docs/`: images used by `README.md`.
- `.github/workflows/`: the `validate.yml` workflow (hassfest, HACS action, the lint job that runs
  `scripts/lint.py`, and the Home Assistant tests).
- `scripts/`: `lint.py`, the one entry point of every local check (ruff check, ruff format check, the tests in
  `tests/` and a compile check; `--fix` applies ruff's fixes and the formatter first; needs uv), and `brand.py`,
  the standard-library script that draws the brand images in `custom_components/<domain>/brand/`; its geometry is
  the icon's source.
- `private/` (git-ignored): `installation.md` and captures specific to the live installation.

## Rules in short

- Read-only towards statistics: never import, adjust or clear statistics, never call other integrations'
  services, never control a heat pump.
- Nothing installation-specific in tracked files; it goes in `private/`.
- Verify every Home Assistant API against the Core 2026.11.2 source and cite it.
- No emoji; all user-facing text through translations.
- Standard library only for the integration and `scripts/`; `tests/` may use pytest, pytest-asyncio and tzdata,
  and `tests_ha/` `pytest-homeassistant-custom-component`; ruff lints all Python. Every tool runs at an exact
  version through uv from `scripts/lint.py`; uv is the one program taken from PATH besides Python.
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
