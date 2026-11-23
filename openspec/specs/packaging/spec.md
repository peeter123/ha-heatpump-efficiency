# packaging Specification

## Purpose

Describes how the integration is distributed and checked so that other Home Assistant owners can install it through
HACS: the repository layout and manifest, the licence, the brand image, the automated checks, the absence of private
text in tracked files, and releases.

## Requirements

### Requirement: Installable as a HACS custom repository
The repository SHALL be installable as a HACS custom repository of type integration: a root `hacs.json` with the
display name "Heat Pump Efficiency" and a minimum Home Assistant version, and the integration in
`custom_components/heatpump_efficiency/` with a manifest whose `documentation` and `issue_tracker` URLs point to the
public GitHub repository and whose `codeowners` names the owner's GitHub handle.

#### Scenario: Manifest has no placeholders
- **WHEN** the test suite reads `manifest.json`
- **THEN** `documentation` is `https://github.com/peeter123/ha-heatpump-efficiency`, `issue_tracker` is that URL
  followed by `/issues`, `codeowners` is `["@peeter123"]`, and no manifest value contains the text `PLACEHOLDER`

#### Scenario: Add as custom repository (live check)
- **WHEN** an owner adds the repository URL in HACS as an integration, downloads it and restarts Home Assistant
- **THEN** "Heat Pump Efficiency" can be added from Settings, Devices and services

### Requirement: Open source licence
The repository SHALL carry an MIT licence in a root `LICENSE` file, naming the copyright holder and the year 2026.

#### Scenario: Licence file present
- **WHEN** the test suite reads `LICENSE`
- **THEN** it starts with "MIT License" and contains a "Copyright (c) 2026" line

### Requirement: Own brand image
The integration SHALL ship its icon in `custom_components/heatpump_efficiency/brand/` as `icon.png` (256 by 256 px) and
`icon@2x.png` (512 by 512 px): a #44882e rounded tile, transparent outside the tile, with white line art of an
outdoor unit whose fan ring a bold arrow breaks out of to the upper right. No logo or dark files are shipped.

#### Scenario: Icon files
- **WHEN** the test suite decodes both PNG files
- **THEN** each is RGBA at its stated size, a corner pixel is fully transparent, a pixel inside the tile away from
  the line art is opaque #44882e, and a pixel on the cabinet outline is opaque white

#### Scenario: Integrations list (live check)
- **WHEN** an owner with the released version opens Settings, Devices and services
- **THEN** the Heat Pump Efficiency entry shows the green tile icon, not the placeholder, in light and in dark mode

### Requirement: Reproducible brand image
The repository SHALL contain a script that uses only the Python standard library and redraws the brand images
from the icon's geometry, writing the same pixels as the committed files.

#### Scenario: Committed icon matches the generator
- **WHEN** the test suite draws the 256 px icon with the script's drawing function
- **THEN** every pixel matches the committed `icon.png` within one step per channel

### Requirement: Automated checks
GitHub Actions SHALL run hassfest, the HACS action for category integration, and the repository's validation
(`python -m unittest discover tests` and `python -m compileall custom_components`) on every push and pull request.

#### Scenario: Workflow file
- **WHEN** the test suite reads the workflow file in `.github/workflows/`
- **THEN** it triggers on push and pull request and has a hassfest job, a HACS job with category integration, and a
  job that runs both validation commands

#### Scenario: First push (live check)
- **WHEN** `main` is pushed to GitHub
- **THEN** all three jobs pass before a release is created

### Requirement: Leak check before every push
Before every push, the tracked files SHALL be checked against two pattern lists kept in the git-ignored `private/`
folder: one of installation identifiers, host names and personal paths, and one of AI model names. The messages of
the commits to be pushed SHALL be checked against the first list only, so a co-author line naming a model is
allowed. A push SHALL NOT happen while any pattern matches.

#### Scenario: Clean tree (live check)
- **WHEN** the squashed tree is checked with both lists and its commit message with the first list before the first
  push
- **THEN** no tracked file and no commit message matches, and only then is `main` pushed

#### Scenario: Co-author line (live check)
- **WHEN** a commit to be pushed has a co-author line that names a model, and its tree and the rest of its message
  match no pattern
- **THEN** the leak check passes

#### Scenario: Match found (live check)
- **WHEN** a pattern matches a tracked file
- **THEN** the push is stopped, the file is fixed in a new commit (or the squash is redone before the first push),
  and the check runs again

### Requirement: Releases
Each version SHALL be published as a GitHub release, not only a tag, whose tag is `v` followed by the manifest
`version`, created only after the checks of that commit pass.

#### Scenario: First release (live check)
- **WHEN** version 0.1.0 is released
- **THEN** the tag `v0.1.0` points at a commit whose manifest version is `0.1.0` and whose checks passed, and HACS
  offers 0.1.0 as the latest version
