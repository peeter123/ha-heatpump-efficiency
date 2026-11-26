# Tasks: adopt-ruff-lint

The change touches `custom_components/` and `tests_ha/`, so it is built on the work branch
`change/adopt-ruff-lint`, created from `main` before the first planning-artifact commit. After each group, the
branch is pushed with the owner's go, and the next group starts only when CI is green. No group touches the live
installation.

## 1. Ruff, the lint entry point and the integration

- [x] 1.1 Amend `openspec/config.yaml` as in design D8. Change Tooling (pytest, pytest-asyncio and tzdata for
  `tests/`; ruff for all Python; exact versions through uv from `scripts/lint.py`; uv the one program from PATH
  besides Python; the `tests_ha/` exception unchanged) and Validation (`python scripts/lint.py`, exit code 0). Make
  the same edits in `AGENTS.md`'s Layout and "Rules in short", and drop the tzdata note there. Verify: both files
  name `python scripts/lint.py` as the validation, and neither names `unittest discover` or `pytest.ini`.
- [x] 1.2 Create `pyproject.toml`. Copy the `[tool.ruff*]` sections of core's `pyproject.toml` at tag 2026.11.2
  verbatim and in order, with the header comment of D1 (source file, tag, ruff 0.17.3, when to refresh) and only
  the adaptations in D1's table, each commented. Add the temporary ignore `"tests/*" = ["PT009", "PT027", "D1"]`
  (D5), with a comment that this change removes it. Move `pytest.ini`'s settings into `[tool.pytest.ini_options]`
  with `testpaths = ["tests"]` (D2), and delete `pytest.ini`. Verify: a diff of the copied sections against the
  file at the tag shows only the D1 adaptations and the temporary ignore.
- [x] 1.3 Write `scripts/lint.py` as in design D3: standard library only, the pins, `find_uv` (exit 2 when
  missing), the start-up log of root, uv version and pins, the five steps (`--fix` first), every step run, and exit
  0, 1 or 2. Verify: `python scripts/lint.py` prints the pins and runs every step, and running it with uv
  unavailable on PATH exits 2.
- [x] 1.4 Fix every ruff finding in `custom_components/`, `tests_ha/` and `scripts/`, and every finding in
  `tests/` other than `PT009`, `PT027` and `D1xx`:
  - Remove `from __future__ import annotations` (D6).
  - Add docstrings in Google style.
  - Add `zip(..., strict=True)` where the lengths must match; use `strict=False` only where shorter input is
    intended, with a comment.
  - Rename unused unpacked variables and resolve the private-member access in the tests.
  - Prefer `ruff check --fix` (safe fixes only) for the fixable ones.

  Then run `ruff format` over the repository. No behaviour change. Verify: `python scripts/lint.py` exits 0.
- [x] 1.5 Update `.github/workflows/validate.yml` as in design D7. The `tests` job becomes `lint` ("Lint and
  tests": checkout, Python 3.14, `setup-uv@v10.4.0` with uv 0.13.9 and `cache-dependency-glob: scripts/lint.py`,
  then `python scripts/lint.py`). The `ha-tests` pytest command names `tests_ha`. Verify: the workflow parses and
  the job names and commands match D7.
- [x] 1.6 Update `tests/test_integration_files.py` for the spec scenarios that hold after this group:
  - "Workflow file": four jobs, the lint job running `python scripts/lint.py`, and `ha-tests` naming `tests_ha`.
  - "Pinned test package": `tests/` imports only the standard library, `pytest` and the repository.
  - "Settings name their source": header comment, `required-version`, `C` selected, `max-complexity` 25.
  - "Version matches the lint entry point".
  - "Pinned tools": ruff, pytest, pytest-asyncio and tzdata with exact versions in `lint.py`.

  Add a test of "uv missing" and "Exit status" that imports `scripts/lint.py` by path and runs `main` with
  `find_uv` returning nothing, and with a fake runner returning 0, 1 and `OSError`. Verify: `python scripts/lint.py`
  exits 0 and the new tests are collected.
- [x] 1.7 Update the README's Development section as in design D8: `python scripts/lint.py` and `--fix`, uv needed,
  and the Home Assistant tests in CI or on Linux and macOS. Remove the `unittest discover` and `pip install tzdata`
  text. Verify: the README names neither.

## 2. The tests in pytest style

- [ ] 2.1 Before changing any test, write `openspec/changes/adopt-ruff-lint/test-inventory.txt`: the output of
  `pytest --collect-only -q tests` in the lint environment (design D4, step 1), one node ID per line. Verify: 469
  node IDs.
- [ ] 2.2 Convert the assertions with `uv tool run ruff@0.17.3 check --select PT009,PT027 --fix --unsafe-fixes
  tests` (D4, step 2), then read the diff of every rewritten file. Verify: the suite passes and no `self.assert`
  call is left.
- [ ] 2.3 Finish the conversion by hand, as in D4 steps 3 and 4:
  - plain classes renamed to `TestX`;
  - `setup_method`;
  - `pytest.approx` with the same tolerance;
  - `caplog`;
  - `subTest` to `parametrize`;
  - the `unittest.main()` blocks and the manual `sys.path` insertion in `test_repairs.py` removed.
  - module docstrings that say "standard library only" reworded (the tests now use pytest, without Home
    Assistant).

  Verify: no file in `tests/` imports `unittest` other than `unittest.mock`, and no class subclasses `TestCase`.
- [ ] 2.4 Check the inventory as in D4 step 6. Every node ID of `test-inventory.txt` is collected, with the class
  renamed, or parametrized cases counted under their function. Any other entry is annotated in the file with the
  tests that replace it. Verify: at least 469 tests are collected and the suite passes.
- [ ] 2.5 Remove `PT009` and `PT027` from the temporary ignore in `pyproject.toml`. Add the test of "No unittest
  test cases" to `tests/test_integration_files.py`. Verify: `python scripts/lint.py` exits 0.

## 3. Test docstrings

- [ ] 3.1 Add a one-line docstring in Google style to every test module, class and function in `tests/` (D4 step
  5): the behaviour checked, without repeating the name. Verify: `ruff check --select D1 tests` reports nothing.
- [ ] 3.2 Remove the temporary ignore from `pyproject.toml`, leaving only the D1 adaptation `"tests/*" =
  ["INP001"]` and the `PTH` entry. Add the test of "No exemptions left for the tests" to
  `tests/test_integration_files.py`. Verify: `python scripts/lint.py` exits 0, and the diff of the ruff sections
  against core's at tag 2026.11.2 shows only D1's adaptations.

## Workflow follow-up

- Whole-change review, then fast-forward `main` to `change/adopt-ruff-lint` and push, each push with the owner's
  go. "Clean tree (live check)", "Harness runs in CI (live check)" and "First push (live check)" are the CI runs of
  the work branch and of `main`.
- Sync the `packaging` delta, archive, and commit to `main` after the leak check.
- No release: the reformatted code ships with the Silver release (`reach-silver-quality-scale`).
