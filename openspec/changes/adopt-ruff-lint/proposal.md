# Proposal: adopt-ruff-lint

## Why

The repository runs hassfest, the HACS action and the tests, but no linter or formatter. Home Assistant holds its
own integrations to the ruff rules in core's `pyproject.toml`; holding this integration to the same rules keeps it
in the style of core and catches bugs that tests miss. A probe of the current tree with core's settings found 41
findings in `custom_components/`, 15 in `tests_ha/`, 2 in `scripts/` and 2127 in `tests/`, and the formatter would
change 23 files (derived: ruff 0.17.3 run on a copy of the tree on 2026-11-26).

Nearly all the `tests/` findings come from the standard-library `unittest` style (1464 `self.assert*` calls, 16
`assertRaises`) and from missing docstrings (about 590). The owner decided on 2026-11-26 to convert `tests/` to
pytest rather than exempt it from core's rules.

This change comes before the Silver change, so that the Silver work is written against the linted code.

## What Changes

- **Ruff with core's settings.** A new root `pyproject.toml` carries the ruff sections of Home Assistant core's
  `pyproject.toml` at tag 2026.11.2, with ruff pinned to core's version at that tag, 0.17.3 (ha-core:
  `pyproject.toml` and `requirements_test_pre_commit.txt` at 2026.11.2). Only the paths are adapted to this
  repository, each adaptation with a comment. This includes core's complexity limit (`C90`, `max-complexity` 25).
- **One lint entry point.** A new standard-library script `scripts/lint.py` runs:
  - ruff check;
  - ruff format check;
  - the tests in `tests/` under pytest;
  - `compileall` of `custom_components/`, `tests_ha/` and `scripts/`.

  Every tool runs through `uv run` or `uvx` at an exact version. `--fix` applies ruff's fixes and the formatter
  first.
- **CI.** The workflow's Tests job becomes a Lint and tests job that runs `python scripts/lint.py`. The Home
  Assistant tests job names its folder explicitly.
- **The integration, `tests_ha/` and `scripts/`.** Fix the findings and format the code:
  - drop `from __future__ import annotations`, which core bans on Python 3.14;
  - import order;
  - docstrings;
  - `zip(strict=)`.

  There is no behaviour change.
- **`tests/` becomes pytest.**
  - Plain `assert` statements and plain test classes, without `unittest.TestCase`.
  - Fixtures instead of `setUp`; `caplog` instead of `assertLogs`; `pytest.raises` and `pytest.approx`.
  - Docstrings on every test.
  - The 469 tests are all kept; the collected test count never drops.
  - The tests still run on Windows: their environment contains no Home Assistant, so no Home Assistant plugin
    loads.
- **The pytest configuration** moves from `pytest.ini` into `pyproject.toml`, which is shared by both test
  folders.
- **Constitution.** `openspec/config.yaml` is amended:
  - Tooling: `tests/` may use pytest and pytest-asyncio, and ruff runs through uvx, all at exact versions through
    uv.
  - Validation becomes `python scripts/lint.py`.
  - The same edits go in `AGENTS.md`.
- **README.** The Development section names the lint command.
- **BREAKING (contributors only).**
  - `python -m unittest discover tests` no longer runs the tests.
  - The Windows `pip install tzdata` step goes away, because `tzdata` comes in through uv.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `packaging`:
  - "Automated checks" now runs the lint entry point instead of `unittest discover`.
  - The "Pinned test package" scenario of "Home Assistant tests" now allows pytest in `tests/`.
  - Added requirements:
    - "Lint with Home Assistant core's ruff settings";
    - "One lint entry point";
    - "Tests in the pytest style".

## Tools checked

- **ruff:** used.
  - It is core's linter and formatter, and the owner's rule for integrations is to copy core's ruff settings at a
    pinned point.
  - The pinned point is the tag 2026.11.2, the same tag every other Home Assistant fact in this repository is
    verified against, so the lint settings and the code target move together.
  - Core's dev branch is at ruff 0.17.5 (ha-core: `requirements_test_pre_commit.txt` on dev, 2026-11-25), with the
    same settings apart from the version. It is not used, because it would split the source of truth.
- **ruff's own fixes for `PT009` and `PT027`:** used for the assertion conversion.
  - They rewrite `self.assert*` and `assertRaises` as plain `assert` and `pytest.raises`.
  - They are marked unsafe, so every rewrite is checked by the test count and by the review.
- **unittest2pytest (pytest-dev):** not used. It overlaps ruff's fixes, and it would be one more tool to pin.
- **pre-commit:** not used. The owner's standard is one lint script per repository, run by CI and before every
  group commit.
- **codespell and yamllint:** not adopted in this change. Core pins both, but the owner's rule names only ruff;
  adopting them can be a later change.

## Out of scope

- **The Silver tier**, in the follow-up change `reach-silver-quality-scale`:
  - the move from `pytest-homeassistant-custom-component` to core's `pytest-homeassistant==2026.11.2`;
  - the setup, coordinator, sensor and diagnostics tests and the 95 % coverage gate;
  - unavailable sensors on a failed read.
- **Strict typing with mypy** (Platinum `strict-typing`): no change planned.
- **No release.** There is no user-visible change. The reformatted code ships with the next release, the Silver
  release.

## Impact

- **New files:** `pyproject.toml` and `scripts/lint.py`.
- **Removed:** `pytest.ini`.
- **Changed:** every Python file under `custom_components/`, `tests/`, `tests_ha/` and `scripts/` (lint fixes and
  format); `.github/workflows/validate.yml`; `tests/test_integration_files.py` (workflow and tooling checks);
  `openspec/config.yaml`; `AGENTS.md`; `README.md`.
- **Work branch:** the change touches `custom_components/` and `tests_ha/`, so it is built on the work branch
  `change/adopt-ruff-lint`.
- **Live installation:** not touched. Nothing is installed, restarted or reconfigured, and there is no release.
