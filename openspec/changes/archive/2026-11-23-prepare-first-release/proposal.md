# Proposal

## Why

The integration is feature-ready and runs on the live installation, but it cannot be installed by anyone else: the
public GitHub repository peeter123/ha-heatpump-efficiency is empty, the manifest still carries placeholder URLs and
codeowners, there is no licence, no brand image and no automated check, and the local history contains text that
must not be published. This change makes the repository publishable through HACS as a custom repository and
publishes the first release, 0.1.0.

## What Changes

- Manifest: `documentation` and `issue_tracker` point to the GitHub repository and `codeowners` names the owner's
  GitHub handle, replacing the placeholders. The test that asserted the placeholders asserts the real values.
- Licence: an MIT `LICENSE` at the repository root, the same licence as the owner's other published integration.
  The HACS action checks for an OSI licence (ha-docs: HACS documentation, publish/action, "license" check).
- Brand image: an icon of an outdoor unit on a single-colour #44882e rounded tile, white line art, with a fan ring
  that a bold arrow breaks out of to the upper right. It ships as `custom_components/heatpump_efficiency/brand/`
  `icon.png` (256 px) and `icon@2x.png` (512 px). Home Assistant serves local brand images of custom integrations
  and, for the logo and the dark variants, falls back to the icon files (ha-core: `homeassistant/components/brands/`
  `__init__.py`, `_BrandsBaseView._serve_from_custom_integration` and `_read_brand_file`; `const.py`,
  `IMAGE_FALLBACKS`). HACS requires a `brand` folder with at least `icon.png` or an entry in the brands repository
  (ha-docs: HACS documentation, publish/include, "Check brands").
- A standard-library script, `scripts/brand.py`, draws the icon from its geometry and writes the PNG files; the
  geometry in that script is the icon's source.
- GitHub Actions: hassfest, the HACS action (category integration) and the repository's own validation
  (`python -m unittest discover tests`, `python -m compileall custom_components`) on every push and pull request.
- A leak check runs before every push: `git grep` over the tracked tree and the commit messages to be pushed, with
  pattern lists in the git-ignored `private/` folder (the patterns themselves are private, so they cannot live in a
  tracked test). The pattern lists and the owner's step-by-step procedure stay in `private/`.
- Public-safety scrub: the archived changes' mentions of the review model are rewritten to "review". The README's
  labelled example and `openspec/config.yaml` call the firmware the author's own and not public, without its
  repository name or script path. `AGENTS.md` and `CLAUDE.md` are already public-safe and stay as they are.
- README: the Status section describes a released integration, the installation names the repository URL, and new
  Development and License sections describe the tests, the brand script, the checks and the licence. `AGENTS.md`
  lists the new files.
- Publishing (outward steps, each with the owner's explicit go): the local history is squashed into one commit (the
  old history is kept on a local backup branch that is never pushed), a leak check runs on that tree with patterns
  kept in `private/`, `main` is pushed, the repository gets a description and topics, and after the checks pass
  the tag v0.1.0 and a GitHub release "Heat Pump Efficiency 0.1.0" are created. HACS takes the version from the
  latest release, not from a tag alone (ha-docs: HACS documentation, publish/start, "Versions").

## Capabilities

### New Capabilities

- `packaging`: how the integration is distributed and checked: HACS layout and manifest, licence, brand image and
  its generator, automated checks, the absence of private text in tracked files, and the release.

### Modified Capabilities

None. No integration behaviour changes.

## Tools checked

- Brand image rendering:
  - a Pillow script run through uv, as the owner's other integration does: third-party, and the constitution allows
    only the standard library;
  - cairosvg through uvx: needs the native Cairo library, which Windows does not ship;
  - the resvg command line through bunx: a downloaded third-party binary, and the repository has no Node tooling;
  - Chrome in headless mode: a program from PATH beyond Python, with no guaranteed transparent background, and not
    reproducible in the checks;
  - Inkscape and ImageMagick: not installed.

  None fits. The icon is built from rounded rectangles, round-capped lines and one ring, which a standard-library
  rasteriser (signed distances with one-pixel anti-aliasing) and PNG writer (`zlib`, `struct`) draw exactly; that
  is what `scripts/brand.py` does.
- Checks: the official hassfest action (home-assistant/actions) and HACS action (hacs/action) are used as they are,
  as HACS requires both before inclusion (ha-docs: HACS documentation, publish/include).
- History squash and publishing: git and the GitHub CLI, already in use; nothing new is installed.
- Leak check: the patterns are private, so no tracked tool can hold them; `git grep` with pattern files (`-f`) in
  `private/` does the job without a script.

## Out of scope

- Switching the live installation from the copied folder to a HACS-managed install: a later follow-up change.
- The pull request to the HACS default list (hacs/default): a later follow-up change, once the release has been
  out for a while.
- A Home Assistant quality scale file and a Core submission: not planned.

## Live installation

The change does not touch the live installation: no install, restart, config entry or dashboard change. The
installed copy stays as it is; the release contains the same integration code with only the manifest URLs and the
brand folder added. The outward steps (squash, push, repository settings, tag and release) change the GitHub
repository, not Home Assistant, and each needs the owner's explicit go.

## Impact

- New files: `LICENSE`, `.github/workflows/validate.yml`, `scripts/brand.py`,
  `custom_components/heatpump_efficiency/brand/icon.png` and `icon@2x.png`, `tests/test_brand.py`; in the
  git-ignored folder, `private/leak-patterns.txt` and `private/leak-patterns-tree.txt`.
- Changed files: `custom_components/heatpump_efficiency/manifest.json`, `tests/test_integration_files.py`,
  `README.md`, `AGENTS.md`, `openspec/config.yaml`, four files in three archived changes.
- Git: local `main` is replaced by one squashed commit before the first push; the previous history stays on a local
  backup branch.
- GitHub: the repository gets its first push, a description, topics, the tag v0.1.0 and a release.
