# Design: adopt-ruff-lint

## Context

- **Current checks:** hassfest, the HACS action, `python -m unittest discover tests` (469 tests, standard library
  only), `compileall`, and the Home Assistant tests in `tests_ha/`. Those run through uv with
  `pytest-homeassistant-custom-component==0.13.375`; `pytest.ini` sets their path and asyncio mode.
- **No linter or formatter** has run on the code so far.
- **The tests in `tests/` load the pure modules by path,** under a bare package (`hpe_engine_pkg` in
  `test_engine.py`), so they never execute the integration's `__init__.py` and need no Home Assistant.
  - `test_repairs.py` reuses that loader with `import test_engine`, after putting `tests/` on `sys.path` itself.
  - `tests/` has no `__init__.py`.
- **unittest features in use** (counted on 2026-11-26):
  - `setUp` (4);
  - `assertAlmostEqual` (15);
  - `assertRaises` (16);
  - `assertLogs` (1);
  - `subTest` (3);
  - `asyncio.run` (6);
  - the rest is plain `assert*`.
- **The probe:** core's settings were run on a copy of the tree with ruff 0.17.3 (derived, 2026-11-26). The
  findings per folder are in the proposal. No function exceeds the complexity limit of 25.

## Goals / Non-Goals

**Goals:**

- The repository passes ruff check and ruff format check with core's settings at tag 2026.11.2.
- One command runs every local check, on Windows too: `python scripts/lint.py`.
- `tests/` is written in plain pytest style, with no test lost.
- CI green after every group.

**Non-Goals:**

- Changing the test package of `tests_ha/`, and new Home Assistant tests (the Silver change).
- mypy, codespell and yamllint.
- Any behaviour change, and any release.

## Decisions

### D1. Ruff settings: core's at tag 2026.11.2, ruff 0.17.3

- **Source.** The `[tool.ruff*]` sections of core's `pyproject.toml` at tag 2026.11.2 are copied into a new root
  `pyproject.toml`, verbatim and in order. ruff is pinned to core's version at that tag:
  - ha-core: `pyproject.toml` at 2026.11.2 (`required-version = ">=0.17.3"`);
  - ha-core: `requirements_test_pre_commit.txt` at 2026.11.2 (`ruff==0.17.3`).
- **A header comment** names the source file, the tag, the ruff version and when to refresh: when the target Home
  Assistant tag in `openspec/config.yaml` moves, recopy at the new tag and move the pin.
- **The complexity limit stays:** `C` selected, `[tool.ruff.lint.mccabe] max-complexity = 25`.
- **The tag rather than core's dev branch.** The dev branch (ruff 0.17.5 since 2026-11-12) has the same settings
  apart from `required-version` (derived: diff of the two files on 2026-11-26). The tag is used because the
  repository verifies every Home Assistant fact against 2026.11.2, so the lint settings and the code target move
  together.

**Adaptations.** Each has a comment in the file. Everything else stays core's.

| Core setting | Here | Why |
| --- | --- | --- |
| `extend-exclude` (`tests/components/marketplace/fixtures/proxy`) | dropped | the path does not exist here |
| `target-version`, inferred from `[project] requires-python = ">=3.14.2"` | `target-version = "py314"` | this repository has no `[project]` table: it is not an installable package, and uv runs with `--no-project` |
| `isort.known-first-party = ["homeassistant"]` | `["custom_components", "homeassistant"]` | the integration's own package sorts with core's, as in a core component |
| `"homeassistant/components/*/*/*" = ["TID252"]` | `"custom_components/*/*" = ["TID252"]` | relative imports inside the integration, as inside a core component |
| `"tests/components/*/*/*" = ["TID252"]` | `"tests_ha/*" = ["TID252"]` | `tests_ha/` is this integration's counterpart of `tests/components/<domain>/` |
| `"script/*" = ["T20"]` and `"homeassistant/scripts/*" = ["T201"]` | `"scripts/*" = ["T20"]` | command-line scripts write to stdout |
| `"script/hassfest/*" = ["INP001"]` | `"scripts/*" = ["INP001"]` | stand-alone scripts, not a package |
| none | `"tests/*" = ["INP001"]` | see D4: `tests/` stays without `__init__.py` |
| temporary `"homeassistant/**"` and `"tests/**"` `PTH` | `"custom_components/**"`, `"tests/**"`, `"tests_ha/**"` `PTH` | the same temporary exemption, on this repository's paths |

**Dropped as having no counterpart here:**

- `homeassistant/__main__.py`;
- `homeassistant/util/*` (`N806`);
- `homeassistant/auth/*/*`;
- `benchmarks/**`.

`known-third-party = ["hassfest"]` is kept as is: it is harmless, and keeping it keeps the copy verbatim.

### D2. One pytest configuration in `pyproject.toml`

- `[tool.pytest.ini_options]` in `pyproject.toml` replaces `pytest.ini`, and holds:
  - `asyncio_mode = "auto"`;
  - `asyncio_default_fixture_loop_scope = "function"`;
  - `testpaths = ["tests"]`.
- **Commands name their folder.** The Home Assistant tests job runs `pytest tests_ha ...`; the lint entry point
  runs `pytest tests`.
- **pytest-asyncio is in the `tests/` environment** as well, at core's pin `pytest-asyncio==1.4.0` (ha-core:
  `requirements_test.txt` at 2026.11.2):
  - A spike on 2026-11-26 showed pytest 9.0.3 warns `PytestConfigWarning: Unknown config option: asyncio_mode`
    when the configuration names asyncio options and pytest-asyncio is not installed.
  - Installing it keeps one configuration and a warning-free run.
  - Rejected alternatives: two configuration files; passing the asyncio options with `-o` on the `tests_ha`
    command line; filtering the warning, which would also hide misspelt options.
- **pytest is pinned at `pytest==9.0.3`.** It is core's pin at 2026.11.2 and also the version the current
  `tests_ha` package installs.
- **tzdata is always installed in the `tests/` environment** (`tzdata==2026.6`, the newest release on 2026-11-26).
  - On Windows Python ships no time zone database, and the time zone tests need it.
  - On Linux zoneinfo prefers the system database, so the package is harmless there.
  - The manual `pip install tzdata` step goes away.

### D3. `scripts/lint.py`

- **Standard library only.** Pins at the top:
  - `RUFF_VERSION = "0.17.3"`;
  - `PYTEST_VERSION = "9.0.3"`;
  - `PYTEST_ASYNCIO_VERSION = "1.4.0"`;
  - `TZDATA_VERSION = "2026.6"`;
  - `PYTHON = "3.14"`.
- **uv is the only program taken from PATH.** It is found with `shutil.which("uv")`; if it is missing, the script
  prints that uv is needed and exits 2. `uv tool run` is used rather than the `uvx` alias, so that only uv must be
  found.
- **At start** it prints the repository root, `uv --version` and the pins, through one `log()` function.
- **Steps, in order, all from the repository root:**

  1. With `--fix` only: `uv tool run ruff@<v> check --fix .`, then `uv tool run ruff@<v> format .`.
  2. `uv tool run ruff@<v> check .`
  3. `uv tool run ruff@<v> format --check .`
  4. `uv run --no-project --python <py> --with pytest==<v> --with pytest-asyncio==<v> --with tzdata==<v> pytest tests -q`
  5. `uv run --no-project --python <py> python -m compileall -q custom_components tests tests_ha scripts`, on
     Python 3.14, so the compile check matches the target interpreter whatever Python started the script.

- **Every step runs**, even after a failure, so one run shows all findings.
- **An `OSError` stops the run** with exit 2 after listing the steps already failed: every step goes through uv,
  so if one program cannot be started, the rest cannot either (review of group 1, 2026-11-26).
- **Exit status:**
  - 0 when all steps pass;
  - 1 when any step exits non-zero (findings, failing tests, or a tool uv could not fetch, whose message uv
    prints);
  - 2 only when uv is missing or a program cannot be started (`OSError`).
  - A step's own exit code is not passed on: pytest's exit code 2 (collection errors) and uv's error code would
    otherwise be indistinguishable from each other.
- **Functions in blocks:** `log`, `find_uv`, `run`, one function per step, `main`.
- **What the script does not do:**
  - It does not run `tests_ha/`: Home Assistant's harness does not load on Windows, and CI runs those tests in
    their own job.
  - It runs no Docker or remote runner. The sibling scripts that do have drifted (see "Risks").
- **Ruff's file selection:** ruff respects `.gitignore`, so `private/` is never linted. The `openspec/` and
  `.claude/` folders hold no Python.

### D4. Converting `tests/` to pytest

1. **Inventory first.** Before any conversion, the implementer writes `test-inventory.txt` in the change folder:
   - the output of `pytest --collect-only -q tests`, run in the D2 environment (pytest collects the `unittest`
     classes as they are);
   - one node ID per line: 485 lines, the 469 of the proposal and the 16 tests group 1 added (2026-11-27).
2. **Assertions by ruff.** `uv tool run ruff@0.17.3 check --select PT009,PT027 --fix --unsafe-fixes tests`
   rewrites `self.assert*` and `assertRaises` into `assert` and `pytest.raises`. The fixes are marked unsafe, so
   every rewritten file is reviewed in the diff.
3. **By hand:**
   - **Classes:** drop the `unittest.TestCase` base and rename the classes to pytest's default prefix: `XTest`
     becomes `TestX`. Plain classes are collected only when their name starts with `Test` (pytest's default
     `python_classes`), and the default is kept rather than widened.
   - **`setUp`** becomes `setup_method` (pytest's xunit-style hook on plain classes), so the per-test state is
     unchanged.
   - **`assertAlmostEqual(a, b)`**, where ruff leaves it, becomes `assert a == pytest.approx(b, rel=0, abs=1e-7)`.
     Calls with `places=` or `delta=` keep their tolerance: `abs=10**-places` or `abs=delta`.
   - **`assertLogs`** becomes the `caplog` fixture, checking the same logger, level and message.
   - **`subTest` loops** become `@pytest.mark.parametrize` over the same cases. Each case then counts as its own
     test, so the count can only rise.
   - **`asyncio.run`** stays. The engine tests drive pure coroutines with a fake reader, and making them async
     tests would change more than the style.
   - **The `if __name__ == "__main__": unittest.main()` blocks** are removed. `unittest.mock` stays allowed.
4. **The `test_engine` loader.** `test_repairs.py` keeps importing it. pytest's default import mode (`prepend`)
   puts `tests/` on `sys.path` for a folder without `__init__.py`, so the manual `sys.path` insertion is dropped.
   - `tests/` stays without `__init__.py`. With one, the modules would import as `tests.test_engine`, and core's
     banned-api entry for `tests` and its relative-import rule (`TID252`) would forbid both ways of sharing the
     loader.
   - Hence the `INP001` adaptation for `tests/` in D1.
5. **Docstrings.** Every test module, class and function gets a docstring in Google style (core's
   `pydocstyle.convention`). Each states the behaviour checked in one line, and does not repeat the name.
6. **Check.** After the conversion, `pytest --collect-only -q tests` must list every inventory entry, with the
   class renamed as in step 3 and parametrized cases counted under their function. Anything else is added to
   `test-inventory.txt` with the tests that replace it. The total is at least 469.

### D5. Order of the work, with CI green after every group

- **Group 1, tooling:** `pyproject.toml`, `lint.py`, CI, the constitution, and the fixes in `custom_components/`,
  `tests_ha/` and `scripts/`.
  - All ruff findings in `tests/` are fixed too, except the pytest style and the docstrings.
  - Those are exempted temporarily with a per-file ignore: `"tests/*" = ["PT009", "PT027", "D1"]`. Its comment
    says it is removed by this change.
  - pytest runs the still-unittest `tests/` unchanged.
- **Group 2, pytest style:** the conversion (D4 steps 1 to 4 and 6), and the removal of `PT009` and `PT027` from
  the temporary ignore.
- **Group 3, docstrings:** D4 step 5, and the removal of the temporary ignore.
- **Tests:** the tests that check the spec scenarios arrive in the group that makes them true. "No exemptions left
  for the tests" and "No unittest test cases" are written in groups 2 and 3, with their assertions tightened
  there.

### D5a. Private names used by the tests

- Core's `SLF001` forbids the tests to reach private module members.
- Four helpers the tests call are made public rather than exempted with `noqa` (group 1, 2026-11-26):
  - `efficiency.daily_plan` and `efficiency.monthly_plan`;
  - `validation.ERROR_PRIORITY`;
  - `engine.resolve_effective`.
- The integration has no public Python API that other code imports, so the wider module surface costs nothing.

### D6. `from __future__ import annotations`

- Core bans it (banned-api, "It should not be needed because Home Assistant requires Python 3.14+"), and the
  integration targets Python 3.14.
- On 3.14, annotations are evaluated lazily by default (PEP 649 and PEP 749, Python 3.14 "What's new"). So
  removing the import keeps forward references working, for example `HeatPumpEfficiencyConfigEntry` in
  `coordinator.py`.
- The Home Assistant tests and hassfest in CI confirm it.

### D7. CI

- **The `tests` job becomes `lint`, named "Lint and tests".** It uses:
  - `actions/checkout@v7`;
  - `actions/setup-python@v7` with 3.14;
  - `astral-sh/setup-uv@v10.4.0` with `version: "0.13.9"` and `cache-dependency-glob: scripts/lint.py`;
  - then `python scripts/lint.py`.
- **The `ha-tests` job** changes only its pytest command, to `pytest tests_ha --cov=...`, and keeps its coverage
  gate. The pytest configuration now comes from `pyproject.toml`.
- **`tests/test_integration_files.py` checks:**
  - four jobs, the lint job running `python scripts/lint.py`, and the `ha-tests` job naming `tests_ha`;
  - the pins of D1 to D3 in `pyproject.toml` and `lint.py`;
  - that `tests/` imports only the standard library, `pytest` and the repository.

### D8. Documents

- **`openspec/config.yaml`.**
  - Tooling:
    - the integration and `scripts/` stay standard library only;
    - `tests/` may use pytest, pytest-asyncio and tzdata;
    - ruff lints all Python;
    - every tool runs at an exact version through uv, from the one entry point `scripts/lint.py`;
    - uv is the one program taken from PATH besides Python;
    - the `tests_ha/` exception stays as written.
  - Validation becomes `python scripts/lint.py` (exit code 0). The work-branch and commit rules are unchanged.
- **`AGENTS.md`:**
  - the Layout lines for `tests/`, `scripts/` and `pyproject.toml`, with `pytest.ini` removed;
  - "Rules in short";
  - the tzdata note goes away.
- **`README.md`:** the Development section gives `python scripts/lint.py` and `--fix`, says that uv is needed, and
  says that the Home Assistant tests run in CI or on Linux and macOS.

## Risks / Trade-offs

- **Unsafe assertion rewrites can change a test.** ruff marks the `PT009` and `PT027` fixes unsafe because they
  can drop comments inside the call, or change an expression with operator precedence. Mitigation:
  - the inventory and count check;
  - the whole suite must still pass;
  - the reviewer reads every rewritten file.
- **Formatting touches every file of the integration.** That makes `git blame` noisier, and the diff hides
  nothing but is large. Mitigation:
  - group 1 keeps format-only changes and lint fixes in one reviewed commit;
  - the Home Assistant tests in CI confirm there is no behaviour change.
- **Pins drift from core.** The pins are tied to the target tag, and the header comment says when to refresh
  them.
- **Sibling repositories** use a different lint script, with a remote runner and Docker. This repository needs
  neither, because its Home Assistant tests run only in CI. Keeping this script minimal is deliberate.
- **The two test environments differ:** `tests/` runs without Home Assistant, `tests_ha/` with it. This is
  intended: it keeps `tests/` runnable on Windows, and it proves the pure modules need no Home Assistant.
