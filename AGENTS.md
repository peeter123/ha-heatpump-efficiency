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
- `tests/`: standard-library `unittest` tests of the pure modules; run `python -m unittest discover tests`. The
  time zone tests use `zoneinfo`; on Windows, where Python ships no time zone database, the `tzdata` package must
  be installed (`python -m pip install tzdata`).
- `tests_ha/`: pytest tests that run the integration in Home Assistant's test harness
  (`pytest-homeassistant-custom-component`, the one third-party test dependency, run through uv, in CI and locally
  only on Linux or macOS; check that they compile with `python -m compileall tests_ha`). `pytest.ini` at the root
  sets their path and asyncio mode.
- `LICENSE`: the MIT licence.
- `.github/workflows/`: the `validate.yml` workflow (hassfest, HACS action, the standard-library tests and the Home
  Assistant tests).
- `scripts/`: `brand.py`, the standard-library script that draws the brand images in
  `custom_components/<domain>/brand/`; its geometry is the icon's source.
- `private/` (git-ignored): `installation.md` and captures specific to the live installation.

## Rules in short

- Read-only towards statistics: never import, adjust or clear statistics, never call other integrations'
  services, never control a heat pump.
- Nothing installation-specific in tracked files; it goes in `private/`.
- Verify every Home Assistant API against the Core 2026.11.2 source and cite it.
- No emoji; all user-facing text through translations.
- Standard library only, except `tests_ha/` (exact-pinned `pytest-homeassistant-custom-component`, run through uv,
  which is also pinned exactly); on Windows the time zone tests also need the `tzdata` package.
- Validation: `python -m unittest discover tests`, `python -m compileall custom_components` and
  `python -m compileall tests_ha`.
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
