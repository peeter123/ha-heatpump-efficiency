# Tasks

## 1. Manifest, licence and checks

- [x] 1.1 Set the manifest values of design D1 (`documentation`, `issue_tracker`, `codeowners`), keeping the key order and version `0.1.0`; replace `ManifestTest.test_placeholders_are_marked` in `tests/test_integration_files.py` with a test of the real values and of no `PLACEHOLDER` in any manifest value; verify the unittest run passes
- [x] 1.2 Add the root `LICENSE`: the MIT licence text, "Copyright (c) 2026 Peter Oostewechel", the same text as the owner's other published integration; add a test that it starts with "MIT License" and has a "Copyright (c) 2026" line; verify the unittest run passes
- [x] 1.3 Add `.github/workflows/validate.yml` as in design D6 (push and pull request, read-only permissions, jobs `hassfest`, `hacs` with `category: integration`, and `tests` with Python 3.14 running both validation commands); add a test that reads the file as text and finds both triggers, the hassfest action, the HACS action with `category: integration`, Python 3.14, and both validation commands; verify the unittest run passes
- [x] 1.4 Update README.md: replace the Status section with the released state (version 0.1.0, installed through HACS as a custom repository), name `https://github.com/peeter123/ha-heatpump-efficiency` in the HACS installation step, and add a Development section (the two validation commands, the `tzdata` note for Windows, the checks that run on GitHub) and a License section (MIT, link to `LICENSE`); update AGENTS.md's Layout with `LICENSE` and `.github/workflows/`; verify the README no longer says "Under development" and both validation commands pass

## 2. Brand image

- [x] 2.1 Add `scripts/brand.py` (design D3 and D4): the geometry table as data, the signed distance functions, the coverage and compositing, the PNG writer, and a `main` that writes `icon.png` (256) and `icon@2x.png` (512) into `custom_components/heatpump_efficiency/brand/` or into a folder given as argument; standard library only, with a module docstring giving its usage; verify `python scripts/brand.py <scratch folder>` writes both files and they open in an image viewer as the chosen icon (green tile, transparent corners, cabinet centred)
- [x] 2.2 Run `python scripts/brand.py` to write the two files into the integration's `brand/` folder; verify only `icon.png` and `icon@2x.png` are in that folder
- [x] 2.3 Add `tests/test_brand.py` (design D5): decode both committed files, check size and colour type, a transparent corner, an opaque #44882e pixel inside the tile away from the line art, an opaque white pixel on the cabinet's top edge, and redraw the 256 px icon and compare every channel within one step; test the PNG writer and reader round trip on a small synthetic image; test `coverage` and `pixel_colour` directly (the clamp and midpoint, the size scaling, the cut-out over the ring, the arrow over the cut-out, the alpha from the tile); verify the unittest run passes and its time stays under about ten seconds
- [x] 2.4 Update README.md's Development section with the brand script (what it draws, how to run it, that the geometry in the script is the icon's source) and AGENTS.md's Layout with `scripts/`; verify the documented command runs as written

## 3. Public-safety scrub and leak check

- [x] 3.1 Create the two pattern lists of design D8 (git-ignored): `private/leak-patterns.txt` with the live installation's host names and IP range, its entity ID prefixes, the owner's personal paths and mail domain and the private repositories' host, taken from `private/installation.md`; `private/leak-patterns-tree.txt` with AI model names; one extended regular expression per line; never print them in full; verify `git check-ignore` reports both ignored
- [x] 3.2 Reword the four review-model mentions in the archived changes (design D7) to "review" without changing their meaning; verify `git grep -n -I -E -f <list>` over the tracked files reports no match for either list (any other match is fixed in this group, or the pattern narrowed in `private/` when it is a false positive)
- [x] 3.3 Describe the leak check in `private/installation.md` (git-ignored; the owner's procedure, design D8): the two pattern lists, `git grep -f` over the tree with both, the messages of the commits to be pushed with the first list only, before every push, never print the lists; verify no tracked file changed in this task and the 3.2 check still reports no match
- [x] 3.4 Mark the firmware of the README example as the author's own and not public (design D7, owner's decision 2026-11-23): in README.md's example heading and text, and in `openspec/config.yaml`'s context and its `firmware-entity` source tag, replace the firmware repository's name with "the author's own ESPHome firmware (not public)" or equivalent wording, and drop the backfill script's path while keeping what the backfill means for the statistics; the archived changes stay as they are; verify `git grep` finds the repository name and the script path only under `openspec/changes/archive/`, the example entity names and units are unchanged, and both validation commands pass

## 4. Publish the first release

- [ ] 4.1 [User authorization: rewrites the local history] Create `backup/pre-release` at `main`, then replace `main` with one root commit of the same tree (design D8), message "Heat Pump Efficiency 0.1.0" with a body summarising the integration; verify `git rev-list --count main` is 1, `git diff backup/pre-release main` is empty and the working tree is clean
- [ ] 4.2 Run the leak check on the new `main` (the tree with both lists, the commit message with `private/leak-patterns.txt`, design D8); verify no match. On a match, stop, fix it, redo 4.1 and run the check again
- [ ] 4.3 [User authorization: changes the GitHub repository settings] Set the description and topics of design D9 with `gh repo edit` and confirm issues are enabled; verify `gh repo view peeter123/ha-heatpump-efficiency --json description,repositoryTopics,hasIssuesEnabled` shows them
- [ ] 4.4 [User authorization: pushes to GitHub] Add the remote `origin` (`https://github.com/peeter123/ha-heatpump-efficiency.git`) and push `main` with upstream; never push `backup/pre-release`; verify `git ls-remote origin` lists only `main` at the squash commit
- [ ] 4.5 Watch the three jobs of the push; verify all pass with `gh run list` and `gh run view`. A failure is fixed in a new commit on `main`, checked by the leak check and pushed only with the owner's go, until all pass
- [ ] 4.6 [User authorization: tags and releases] Tag `v0.1.0` on the green commit, push the tag, and create the release "Heat Pump Efficiency 0.1.0" with notes summarising the features from the README (design D9); verify `gh release view v0.1.0` shows it as the latest release on the tagged commit, and that the manifest version at that commit is `0.1.0`

## Workflow follow-up

- Archive the change after the final whole-change review; the archive commit is pushed only with the owner's go, after the leak check.
- The live checks "Add as custom repository" and "Integrations list" of the packaging spec are done in the follow-up change that switches the live installation to the HACS-managed release.
- Later follow-up: the pull request to the HACS default list.
- Replace the Publishing entry in `private/BACKLOG.md` with those two follow-ups once the change is archived.
