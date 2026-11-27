## MODIFIED Requirements

### Requirement: Home Assistant tests
The repository SHALL have tests that run the integration inside Home Assistant's test harness, kept apart from the
tests of the pure modules, using Home Assistant's test package `pytest-homeassistant` at an exact version that
equals the target Home Assistant version or the newest version before it, run through uv on Python 3.14.

#### Scenario: Pinned test package
- **WHEN** the test suite reads the workflow file in `.github/workflows/`
- **THEN** the Home Assistant tests job installs `pytest-homeassistant` with an exact `==` version, and no
  `pytest-homeassistant-custom-component`, with Python 3.14, and runs the tests in `tests_ha/`, and the tests in
  `tests/` import only the standard library, pytest and the repository's own modules

#### Scenario: Harness runs in CI (live check)
- **WHEN** a commit is pushed
- **THEN** the Home Assistant tests job starts Home Assistant's test instance, loads the integration as a custom
  integration and passes

## ADDED Requirements

### Requirement: Declared tier matches the record
The manifest's `quality_scale` SHALL be the highest tier (bronze, silver, gold or platinum) for which every rule of
that tier and of the tiers below it is `done` or `exempt` in the record.

#### Scenario: Gold declared
- **WHEN** the Home Assistant tests in CI compare the manifest with the record, and every bronze, silver and gold
  rule is `done` or `exempt` while `strict-typing` (platinum) is `todo`
- **THEN** the manifest's `quality_scale` is `gold` and the test passes

#### Scenario: Claimed tier not met
- **WHEN** the manifest declares a tier for which a rule of that tier or a tier below is `todo`
- **THEN** the record test fails and names the rule

#### Scenario: Higher tier not claimed
- **WHEN** every rule of a tier above the declared one and of the tiers in between is `done` or `exempt`
- **THEN** the record test fails, so the manifest always shows the tier the record supports

### Requirement: Integration coverage gate
CI SHALL measure the line and branch coverage of `custom_components/heatpump_efficiency/` over the tests in
`tests/` and `tests_ha/` together, and SHALL fail when the total or any single module is below 95 %.

#### Scenario: Gate in the workflow
- **WHEN** the test suite reads the workflow file
- **THEN** the Home Assistant tests job runs both test folders under coverage of the integration, combines the
  results, and runs the coverage gate with a threshold of 95

#### Scenario: Module below the threshold
- **WHEN** the coverage gate reads a report in which one module is at 94 % and the total is at 97 %
- **THEN** it exits non-zero and names that module

#### Scenario: Every module covered
- **WHEN** the coverage gate reads a report in which the total and every module are at 95 % or more
- **THEN** it exits with 0

#### Scenario: Gate met (live check)
- **WHEN** the Home Assistant tests job runs on a pushed commit of this change
- **THEN** the total and every module are at 95 % or more, `config_flow.py` is at 100 %, and the job passes

## REMOVED Requirements

### Requirement: Declared tier backed by the record
**Reason**: Its scenario "Bronze after this change" described the Bronze state of an earlier change.
**Migration**: Replaced by "Declared tier matches the record", the same rule with the scenario "Gold declared".
