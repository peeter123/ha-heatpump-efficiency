# Spec Delta

## ADDED Requirements

### Requirement: Manifest categories
The manifest SHALL list the categories `climate.heat_pumps_air_conditioning` and `energy.meters_monitoring`, in that
order, and no `connectivity`. Its keys SHALL be sorted with `domain` and `name` first and the others in alphabetical
order.

#### Scenario: Categories in the manifest
- **WHEN** the test suite reads `manifest.json`
- **THEN** `categories` is `["climate.heat_pumps_air_conditioning", "energy.meters_monitoring"]`, no category is
  listed together with its own subcategory, there is no `connectivity` key, and the keys after `domain` and `name`
  are in alphabetical order

#### Scenario: No categories warning (live check)
- **WHEN** the HACS action runs on a pushed commit of this change
- **THEN** its log has no "manifest has no categories" warning

### Requirement: Quality scale record
`custom_components/heatpump_efficiency/quality_scale.yaml` SHALL list every rule of Home Assistant's Integration
Quality Scale at the target Core version, each as `done` or `todo`, or as a status with a comment; every `exempt`
and every `todo` SHALL carry a comment that gives the reason.

#### Scenario: Every rule listed
- **WHEN** the Home Assistant tests in CI load the record
- **THEN** its rule names equal the 54 rules of the scale at the target Core version, and every value is `done`,
  `todo`, or a mapping with a status of `done`, `todo` or `exempt` and a non-empty comment

#### Scenario: Exempt without a reason
- **WHEN** a rule in the record is `exempt` without a comment, or `todo` without a comment
- **THEN** the record test fails

### Requirement: Declared tier backed by the record
The manifest's `quality_scale` SHALL be the highest tier (bronze, silver, gold or platinum) for which every rule of
that tier and of the tiers below it is `done` or `exempt` in the record.

#### Scenario: Bronze after this change
- **WHEN** the Home Assistant tests in CI compare the manifest with the record, and every bronze rule is `done` or
  `exempt` while `test-coverage` (silver) is `todo`
- **THEN** the manifest's `quality_scale` is `bronze` and the test passes

#### Scenario: Claimed tier not met
- **WHEN** the manifest declares a tier for which a rule of that tier or a tier below is `todo`
- **THEN** the record test fails and names the rule

#### Scenario: Higher tier not claimed
- **WHEN** every rule of a tier above the declared one and of the tiers in between is `done` or `exempt`
- **THEN** the record test fails, so the manifest always shows the tier the record supports

### Requirement: Home Assistant tests
The repository SHALL have tests that run the integration inside Home Assistant's test harness, kept apart from the
standard-library tests, using `pytest-homeassistant-custom-component` at an exact version that pins the target Home
Assistant version or the newest version before it, run through uv on Python 3.14.

#### Scenario: Pinned test package
- **WHEN** the test suite reads the workflow file in `.github/workflows/`
- **THEN** the Home Assistant tests job installs `pytest-homeassistant-custom-component` with an exact `==` version
  and Python 3.14, and `python -m unittest discover tests` imports no third-party package

#### Scenario: Harness runs in CI (live check)
- **WHEN** a commit is pushed
- **THEN** the Home Assistant tests job starts Home Assistant's test instance, loads the integration as a custom
  integration and passes

### Requirement: Config flow fully covered
The Home Assistant tests SHALL cover every line and branch of the config flow module, and the CI job SHALL fail when
that coverage is below 100 %.

#### Scenario: Coverage gate in the workflow
- **WHEN** the test suite reads the workflow file
- **THEN** the Home Assistant tests job measures coverage of the integration and fails under 100 % for
  `config_flow.py`

#### Scenario: Coverage met (live check)
- **WHEN** the Home Assistant tests job runs on a pushed commit of this change
- **THEN** its coverage report shows 100 % for `config_flow.py` and the job passes

### Requirement: Work branch for changes to the integration or its tests
A change that touches `custom_components/` or `tests_ha/` SHALL be built on a work branch named
`change/<change-id>`. After each task group's commit and the leak check, the branch SHALL be pushed with the owner's
go, and the next group SHALL start only when CI passes. History SHALL be rewritten only for a group's fix commit on
the work branch, never on `main`.

#### Scenario: Group passes (live check)
- **WHEN** a group's commit is pushed to the work branch and every CI job passes
- **THEN** the next group starts from that commit

#### Scenario: Group fails in CI (live check)
- **WHEN** a CI job fails on a group's commit
- **THEN** one commit with the subject "Fix group <n> of <change-id>: ..." fixes it, is pushed the same way, and the
  next group starts only on green

#### Scenario: Fix commit fails in CI (live check)
- **WHEN** a CI job fails on a group's fix commit
- **THEN** the fix commit is amended, the work branch is force-pushed with the owner's go, and the group still has
  exactly one fix commit

#### Scenario: Change complete (live check)
- **WHEN** the last group passes CI
- **THEN** `main` is fast-forwarded to the work branch, keeping every group commit, pushed with the owner's go, and
  the remote work branch is deleted with the owner's go

## MODIFIED Requirements

### Requirement: Automated checks
GitHub Actions SHALL run hassfest, the HACS action for category integration, the repository's validation
(`python -m unittest discover tests` and `python -m compileall custom_components`) and the Home Assistant tests on
every push and pull request.

#### Scenario: Workflow file
- **WHEN** the test suite reads the workflow file in `.github/workflows/`
- **THEN** it triggers on push and pull request and has a hassfest job, a HACS job with category integration, a
  job that runs both validation commands, and a Home Assistant tests job

#### Scenario: First push (live check)
- **WHEN** `main` is pushed to GitHub
- **THEN** all four jobs pass before a release is created
