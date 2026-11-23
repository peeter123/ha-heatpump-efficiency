# Design

## Context

See proposal.md for why. The integration code is finished and unchanged by this change; everything here is
packaging around it. The constitution allows only the Python standard library for tooling and validation, the
public GitHub repository exists and is empty, and nothing has ever been pushed, so the local history can still be
rewritten. The packaging requirements are in `specs/packaging/spec.md`.

## Goals / Non-Goals

**Goals:**

- A tree that passes hassfest and the HACS action on its first push.
- An icon that reads at 20 to 40 px in the Home Assistant UI and can be redrawn by anyone from the repository.
- A public history that holds nothing the constitution or the owner's publishing rules keep private.

**Non-Goals:**

- No change to integration behaviour, entities, translations or the config flow.
- No dark or logo variants of the icon, and no README screenshots in this change.

## Decisions

### D1. Manifest values

`documentation` becomes `https://github.com/peeter123/ha-heatpump-efficiency`, `issue_tracker` that URL plus
`/issues`, and `codeowners` `["@peeter123"]`. hassfest validates a custom integration's manifest with
`CUSTOM_INTEGRATION_MANIFEST_SCHEMA`; `custom_documentation_url` only requires an `https` URL that is not under the
Core documentation base, `validate_manifest` reports a missing `codeowners` and calls `validate_version`, which
requires `version` (ha-core: `script/hassfest/manifest.py`, `custom_documentation_url`, `validate_manifest`,
`validate_version`). `sort_manifest` in the same file requires domain and name first and the other keys sorted;
the current key order already satisfies it and the edit keeps it. The version stays `0.1.0`.

`tests/test_integration_files.py` `ManifestTest.test_placeholders_are_marked` is replaced by a test of the real
values and of the absence of `PLACEHOLDER` in any manifest value.

### D2. Brand files: icon only

Home Assistant serves a custom integration's images from its `brand/` folder when the integration has one
(ha-core: `homeassistant/loader.py`, `Integration.has_branding`; `homeassistant/components/brands/__init__.py`,
`_BrandsBaseView._serve_from_custom_integration`, `_read_brand_file`). A missing image falls back along
`IMAGE_FALLBACKS`: `logo.png` and `dark_icon.png` to `icon.png`, `dark_icon@2x.png` to `icon@2x.png` and then
`icon.png`, and the logo variants through `logo.png` to `icon.png` (ha-core: `homeassistant/components/brands/const.py`,
`IMAGE_FALLBACKS`, `ALLOWED_IMAGES`). The tile icon works on light and dark backgrounds and is square, which also
suits the logo slot, so only `icon.png` (256 px) and `icon@2x.png` (512 px) ship.

Alternative considered: a wide logo with the name in text. Rejected: it needs a font in the generator, and the
fallback already shows the icon wherever a logo is asked for.

### D3. Icon geometry

The icon was chosen from drafts compared at 20 to 512 px on light and dark cards (option C, revised and centred).
Design units are a 256 by 256 grid; every line is white, 12 units wide, with round caps and joins:

| Element | Geometry (design units) |
| --- | --- |
| Tile | rounded square 0..256, corner radius 56, fill #44882e; transparent outside |
| Cabinet | rounded rectangle outline x 32..224, y 62..190, corner radius 20 |
| Grille | three lines x 152..200 at y 102, 126 and 150 |
| Fan ring | circle outline, centre (88, 126), radius 32 |
| Arrow cut-out | the arrow path below, 26 units wide, in the tile colour, drawn over the ring |
| Arrow | line (58, 156) to (116, 98), head lines (98, 98) to (116, 98) to (116, 116) |
| Feet | two filled rounded rectangles x 58..92 and 164..198, y 192..208, corner radius 5 |

The cut-out separates the arrow from the ring so the arrow reads as breaking out of it; at the arrow head it clears
the cabinet's top and the grille by about 17 units, and at the tail the cabinet's left side by about 7 units. The cabinet's centre (y 126) is 2 units below the tile's centre, so the art with its light feet looks centred.

### D4. Standard-library rasteriser and PNG writer

`scripts/brand.py` holds the geometry of D3 as data and draws it with signed distance functions: for each output
pixel centre it computes the distance to each shape in design units, converts it to output pixels (times
size / 256) and takes the coverage as `clamp(0.5 - d, 0, 1)`, one-pixel anti-aliasing without supersampling. Shapes:
a rounded box (tile, feet, and as an outline the cabinet), a capsule for each line segment (round caps; the arrow
and its head are three segments), and a ring. Compositing per pixel: white coverage is the maximum of the arrow's
coverage and the coverage of cabinet, grille, ring and feet times one minus the cut-out's coverage; the colour is
the tile colour blended towards white by that coverage; the alpha is the tile's coverage. Output is 8-bit RGBA,
non-premultiplied.

The PNG writer emits the signature, an `IHDR` chunk (colour type 6, bit depth 8), one `IDAT` chunk with each
scanline prefixed by filter type 0 and compressed with `zlib`, and `IEND`, each chunk with its `zlib.crc32`
checksum.

Derived values and their pure functions, all in `scripts/brand.py`, importing nothing beyond the standard library:
the pixel coverage (inputs: the signed distance in design units and the output size), the per-pixel colour (inputs:
the shape coverages and the tile colour), and the PNG bytes (inputs: width, height and the RGBA rows).

Usage: `python scripts/brand.py`, which writes both files into the integration's `brand/` folder; an optional
argument names another output folder.

Speed: about 262 000 pixels at 512 px, each with about ten shape distances, takes a few seconds in CPython, which is
acceptable for a script run once per icon change and for a test that draws only the 256 px icon.

Alternatives considered: listed in the proposal under Tools checked.

### D5. Tests of the brand images

`tests/test_brand.py` loads `scripts/brand.py` by path (the way `tests/test_integration_files.py` loads modules),
decodes the committed PNG files with a small reader that accepts only what the writer produces (filter type 0,
one image), and checks: size and colour type; a transparent corner pixel; an opaque #44882e pixel inside the tile
away from the line art, for example at (128, 40); an opaque white pixel on the cabinet's top edge, for example at
(128, 62) scaled to the size. It then draws the 256 px icon in memory and compares every channel of every pixel
with the committed file, allowing a difference of one to absorb floating-point rounding between platforms.
The comparison is on pixels, not file bytes, so a different `zlib` build cannot fail it. The derived values of D4
are also tested directly: `coverage` (0.5 at distance 0, clamped to 0 and 1, a distance counting double at 512 px)
and `pixel_colour` (the cut-out cancels the ring, the arrow wins over the cut-out, the alpha comes from the tile
alone).

### D6. Checks in GitHub Actions

One workflow, `.github/workflows/validate.yml`, triggered on push and pull request, with read-only permissions:

- `hassfest`: `actions/checkout` and `home-assistant/actions/hassfest`;
- `hacs`: `hacs/action` with `category: integration`;
- `tests`: `actions/checkout`, `actions/setup-python` with Python 3.14, the version Home Assistant Core 2026.11.2
  requires (ha-core: `homeassistant/const.py`, `REQUIRED_PYTHON_VER` = (3, 14, 2)), then
  `python -m unittest discover tests` and `python -m compileall custom_components`. On Linux the runner's Python has
  the system time zone database, so `tzdata` is not installed.

The action versions follow the owner's other published integration, which passes these checks today. The hassfest
and HACS actions are referenced by their `master` and `main` branches, as their own documentation shows, so they
follow Home Assistant's and HACS's current rules; pinning them to a commit would let the checks drift from what HACS
applies. Each job is a separate check so a failure names its cause.

The HACS action also checks that the repository has a description, topics, issues enabled and an OSI licence
(ha-docs: HACS documentation, publish/action, "Ignorable checks"). Description and topics are GitHub settings, so
they are set before the first push; no check is ignored.

### D7. Public-safety scrub

The tree at HEAD has three kinds of text to review (`AGENTS.md` and `CLAUDE.md` stay as they are; `openspec/config.yaml`
changes only as the third bullet says):

- the archived change artifacts that name the review model (four lines in
  `openspec/changes/archive/2026-11-19-add-efficiency-integration/` `proposal.md` and `tasks.md`,
  `2026-11-20-add-season-efficiency/tasks.md` and `2026-11-23-add-defrost-correction/tasks.md`): reworded to
  "review", meaning unchanged;
- `AGENTS.md`, `CLAUDE.md` and the constitution in `openspec/config.yaml`: already in the shared form, with no
  host, path, personal or model detail;
- the README example that names the heat pump model and its firmware: allowed by the constitution as a clearly
  labelled example, and it stays, but the firmware is the author's own and not public (owner's decision,
  2026-11-23). The README and `openspec/config.yaml` therefore say "the author's own ESPHome firmware (not
  public)" instead of the firmware repository's name, and the README drops the path of its backfill script while
  keeping what the backfill means for the statistics. The archived changes keep the name as history.

This change's own artifacts are written without model names, so archiving it adds none.

### D8. Squash and leak check

Before the first push:

1. `git branch backup/pre-release main` keeps the full local history on a branch that is never pushed.
2. A new root commit takes the tree of `main` (`git commit-tree "main^{tree}"` with the release message), and `main`
   is moved to it (`git reset --soft` to that commit while the working tree already equals it).
3. The leak check runs on the new `main`: `git grep -n -I -E -f <list> main` over the tree with each of the two
   lists below, and the messages of the commits to be pushed (`git log --format=%B <range>`) through the first list
   only. Any match stops the push.

Two git-ignored files hold one extended regular expression per line and are never printed in full:

- `private/leak-patterns.txt`: the live installation's host names and IP range, its entity ID prefixes, the
  owner's personal paths and mail domain, and the private repositories' host. Checked against the tree and the
  commit messages.
- `private/leak-patterns-tree.txt`: AI model names. Checked against the tree only: the owner keeps the co-author
  line that names the model in commit messages.

Both are created in the session from `private/installation.md` and the owner's publishing rules. The lists and the
owner's step-by-step procedure stay in `private/installation.md`; this design and the packaging spec describe only
the check itself.

After the first push, the backup branch stays local; the per-group commits made before the squash survive only
there.

### D9. Repository settings and release

Description: "Real heat pump efficiency (COP, SCOP, SEER) for Home Assistant, from long-term energy statistics".
Topics: `home-assistant`, `hacs`, `hacs-integration`, `homeassistant-custom-component`, `heat-pump`, `cop`,
`energy`. Both are set with `gh repo edit` before the push, so the first HACS action run passes.

After all three jobs pass on the pushed commit: `git tag v0.1.0`, `git push origin v0.1.0`, then
`gh release create v0.1.0 --title "Heat Pump Efficiency 0.1.0"` with notes that summarise the features from the
README. HACS takes the remote version from the latest release's tag (ha-docs: HACS documentation, publish/start,
"Versions").

## Risks / Trade-offs

- [hassfest or the HACS action fails on the first push for a reason no local check covers, such as a translation
  schema detail] → The tag and release wait for green checks; fixes go in normal commits on top of the squash commit,
  checked by the leak check before each push.
- [The squash loses the granular history] → It stays on the local backup branch; the owner accepted a squashed public
  history for a first push.
- [Floating-point rounding differs between Windows and the Linux runner] → The brand test allows one step per
  channel and compares pixels, not bytes.
- [A pattern in the private list is too broad and blocks a clean push] → The match is shown by file and line in the
  session; the pattern is narrowed in `private/`, never by editing tracked files to dodge it.
- [The live installation runs a copy without the brand folder and with placeholder URLs] → Harmless; the owner
  switches it to the HACS-managed release in the follow-up change.

## Migration Plan

No migration: config entries, entities and statistics are untouched. Rollback before the push is
`git reset --hard backup/pre-release`; after the push, a release can be deleted on GitHub, and the pushed history
is not rewritten.
