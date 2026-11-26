## MODIFIED Requirements

### Requirement: Automated checks
GitHub Actions SHALL run hassfest, the HACS action for category integration, the repository's lint entry point
(`python scripts/lint.py`, see "One lint entry point") and the Home Assistant tests on every push and pull request.

#### Scenario: Workflow file
- **WHEN** the test suite reads the workflow file in `.github/workflows/`
- **THEN** it triggers on push and pull request and has a hassfest job, a HACS job with category integration, a
  job that runs `python scripts/lint.py`, and a Home Assistant tests job

#### Scenario: First push (live check)
- **WHEN** `main` is pushed to GitHub
- **THEN** all four jobs pass before a release is created

### Requirement: Home Assistant tests
The repository SHALL have tests that run the integration inside Home Assistant's test harness, kept apart from the
tests of the pure modules, using `pytest-homeassistant-custom-component` at an exact version that pins the target
Home Assistant version or the newest version before it, run through uv on Python 3.14.

#### Scenario: Pinned test package
- **WHEN** the test suite reads the workflow file in `.github/workflows/`
- **THEN** the Home Assistant tests job installs `pytest-homeassistant-custom-component` with an exact `==` version
  and Python 3.14 and runs the tests in `tests_ha/`, and the tests in `tests/` import only the standard library,
  pytest and the repository's own modules

#### Scenario: Harness runs in CI (live check)
- **WHEN** a commit is pushed
- **THEN** the Home Assistant tests job starts Home Assistant's test instance, loads the integration as a custom
  integration and passes

## ADDED Requirements

### Requirement: Lint with Home Assistant core's ruff settings
The repository SHALL lint and format its Python code with ruff, using the ruff settings of Home Assistant core's
`pyproject.toml` at the target Home Assistant tag and the ruff version core pins at that tag, changed only where a
path names core's layout. The source tag and the version SHALL be named in the configuration, and the
configuration SHALL keep core's complexity limit.

#### Scenario: Settings name their source
- **WHEN** the test suite reads `pyproject.toml`
- **THEN** a comment names core's `pyproject.toml`, the tag and the ruff version, ruff's `required-version` names
  that version, `C` is selected and `max-complexity` is 25

#### Scenario: Version matches the lint entry point
- **WHEN** the test suite reads `pyproject.toml` and `scripts/lint.py`
- **THEN** the ruff version in `required-version` equals the exact version the lint entry point runs

#### Scenario: No exemptions left for the tests
- **WHEN** the test suite reads the per-file ignores in `pyproject.toml`
- **THEN** no entry for `tests/` ignores the pytest-style rules (`PT009`, `PT027`) or the docstring rules (`D1`)

#### Scenario: Clean tree (live check)
- **WHEN** a commit is pushed
- **THEN** the lint job's ruff check and ruff format check pass with no findings

### Requirement: One lint entry point
The repository SHALL have one lint entry point, `scripts/lint.py`, using only the Python standard library, that
runs ruff check, ruff format check, the tests in `tests/` and a compile check of the Python folders. It SHALL run
every tool through uv or uvx at an exact version, never from PATH, and print the versions it uses.

#### Scenario: Pinned tools
- **WHEN** the test suite reads `scripts/lint.py`
- **THEN** ruff, pytest, pytest-asyncio and tzdata each appear with an exact version

#### Scenario: uv missing
- **WHEN** the lint entry point runs and uv cannot be found
- **THEN** it prints that uv is needed and exits with 2

#### Scenario: Exit status
- **WHEN** the lint entry point finishes
- **THEN** it exits with 0 when every check passes, 1 when any check fails, and 2 when uv is missing or a
  program cannot be started

#### Scenario: Fix mode
- **WHEN** the lint entry point runs with `--fix`
- **THEN** it applies ruff's fixes and the formatter first, then runs every check

#### Scenario: Runs on Windows
- **WHEN** the lint entry point runs on Windows
- **THEN** the tests in `tests/` run in an environment without Home Assistant, so no Home Assistant plugin loads,
  and they pass

### Requirement: Tests in the pytest style
The tests in `tests/` SHALL be pytest tests: plain `assert` statements, pytest fixtures and helpers, no
`unittest.TestCase`, and a docstring on every test module, class and function. Converting the tests SHALL NOT
lose a test.

#### Scenario: No unittest test cases
- **WHEN** the test suite reads the files in `tests/`
- **THEN** none imports `unittest` other than `unittest.mock`, and none defines a `TestCase` subclass

#### Scenario: No test lost
- **WHEN** pytest collects `tests/` after the conversion
- **THEN** it collects at least 469 tests, and every test name from before the conversion (taken from the
  inventory file `test-inventory.txt` in the change folder) is still collected, or is listed there with the tests
  that replace it
