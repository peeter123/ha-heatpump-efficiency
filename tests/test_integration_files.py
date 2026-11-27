"""Tests of the static integration files: manifest, hacs.json and translations."""

import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tomllib
import types

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "heatpump_efficiency"
_spec = importlib.util.spec_from_file_location(
    "validation_for_files", PACKAGE / "validation.py"
)
val = importlib.util.module_from_spec(_spec)
sys.modules["validation_for_files"] = val
_spec.loader.exec_module(val)
_pkg = types.ModuleType("hpe_files_pkg")
_pkg.__path__ = [str(PACKAGE)]
sys.modules["hpe_files_pkg"] = _pkg
repairs_model = importlib.import_module("hpe_files_pkg.repairs_model")
seasons = importlib.import_module("hpe_files_pkg.seasons")
sensor_model = importlib.import_module("hpe_files_pkg.sensor_model")


def load(path: Path):
    """Return the parsed JSON of a file."""
    return json.loads(path.read_text(encoding="utf-8"))


class TestManifest:
    """The manifest.json of the integration."""

    def setup_method(self):
        """Load the manifest."""
        self.manifest = load(PACKAGE / "manifest.json")

    def test_keys(self):
        """The manifest has the required keys and the expected fixed values."""
        for key in (
            "domain",
            "name",
            "codeowners",
            "config_flow",
            "dependencies",
            "documentation",
            "integration_type",
            "iot_class",
            "issue_tracker",
            "version",
        ):
            assert key in self.manifest
        assert self.manifest["domain"] == "heatpump_efficiency"
        assert self.manifest["name"] == "Heat Pump Efficiency"
        assert self.manifest["config_flow"] is True
        assert self.manifest["dependencies"] == ["recorder"]
        assert self.manifest["integration_type"] == "service"
        assert self.manifest["iot_class"] == "calculated"
        assert "requirements" not in self.manifest
        assert re.search(r"^\d+\.\d+\.\d+$", self.manifest["version"])

    def test_real_repository_values_and_no_placeholders(self):
        """The manifest names the real repository and has no placeholder text."""
        assert (
            self.manifest["documentation"]
            == "https://github.com/peeter123/ha-heatpump-efficiency"
        )
        assert (
            self.manifest["issue_tracker"]
            == "https://github.com/peeter123/ha-heatpump-efficiency/issues"
        )
        assert self.manifest["codeowners"] == ["@peeter123"]
        assert self.manifest["version"] == "0.2.0"

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)

        for text in strings(self.manifest):
            assert "PLACEHOLDER" not in text

    def test_categories(self):
        """The categories are valid and list no parent with its own subcategory."""
        # ha-core 2026.11.2 script/hassfest/manifest.py validate_categories: a parent
        # category listed with its own subcategory is an error.
        categories = self.manifest["categories"]
        assert categories == [
            "climate.heat_pumps_air_conditioning",
            "energy.meters_monitoring",
        ]
        for category in categories:
            parent, _, subcategory = category.partition(".")
            if subcategory:
                assert parent not in categories
        assert len(set(categories)) == len(categories)
        assert "connectivity" not in self.manifest

    def test_readme_status_matches_manifest(self):
        """The README states the manifest version and quality scale tier."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert f"Version {self.manifest['version']}." in readme
        assert (
            f"declares the {self.manifest['quality_scale'].capitalize()} tier" in readme
        )
        assert "custom_components/heatpump_efficiency/quality_scale.yaml" in readme

    def test_keys_sorted(self):
        """The manifest keys are sorted as hassfest wants."""
        # ha-core 2026.11.2 script/hassfest/manifest.py sort_manifest: domain, name,
        # then alphabetical order.
        keys = list(self.manifest)
        assert keys[:2] == ["domain", "name"]
        assert keys[2:] == sorted(keys[2:])

    def test_domain_matches_const(self):
        """The manifest domain equals DOMAIN in const.py."""
        assert f'DOMAIN: Final = "{self.manifest["domain"]}"' in (
            PACKAGE / "const.py"
        ).read_text(encoding="utf-8")


class TestHacs:
    """The hacs.json of the integration."""

    def test_minimum_home_assistant_version(self):
        """hacs.json names the integration and the minimum Home Assistant version."""
        hacs = load(ROOT / "hacs.json")
        assert hacs["name"] == "Heat Pump Efficiency"
        assert hacs["homeassistant"] == "2026.11.0"


class TestTranslations:
    """The English translations against the setup form and the code."""

    def setup_method(self):
        """Load the translations and the config and options steps."""
        self.translations = load(PACKAGE / "translations" / "en.json")
        self.steps = {
            "config": self.translations["config"]["step"]["user"],
            "options": self.translations["options"]["step"]["init"],
        }

    def test_every_step_has_text(self):
        """Each form step has a title and description, and only setup has a name."""
        for name, step in self.steps.items():
            assert step["title"], name
            assert step["description"], name
        assert self.steps["config"]["data"][val.FIELD_NAME]
        assert self.steps["config"]["data_description"][val.FIELD_NAME]
        assert "data" not in self.steps["options"]  # the options form has no name

    def test_every_section_and_field_has_text(self):
        """Every section and field of both forms has a name and a description."""
        expected = dict.fromkeys(val.SERVICES, val.SERVICE_FIELDS)
        expected[val.SERVICE_COOLING] = (
            val.COOLING_FIELDS
        )  # the unit is a Cooling field only
        for (
            service
        ) in val.DEFROST_SERVICES:  # the defrost heat field: Heating and Hot water only
            expected[service] = (*val.SERVICE_FIELDS, val.FIELD_DEFROST_HEAT)
        expected[val.SECTION_SEASONS] = val.SEASON_FIELDS
        for name, step in self.steps.items():
            assert set(step["sections"]) == set(expected), name
            assert val.SECTION_PLANNED not in step["sections"], (
                name
            )  # no planned section
            for section, fields in expected.items():
                text = step["sections"][section]
                assert text["name"] and text["description"], (name, section)
                for key in ("data", "data_description"):
                    assert set(text[key]) == set(fields), (name, section, key)
                    assert all(text[key].values()), (name, section, key)

    def test_defrost_field_text(self):
        """The defrost field is explained in the sections that have it."""
        for step in self.steps.values():
            for service in val.DEFROST_SERVICES:
                text = step["sections"][service]
                assert text["data"][val.FIELD_DEFROST_HEAT] == "Defrost heat statistics"
                assert "subtracted" in text["data_description"][val.FIELD_DEFROST_HEAT]
                assert "Overall" in text["data_description"][val.FIELD_DEFROST_HEAT]
                assert (
                    "already counts" in text["data_description"][val.FIELD_DEFROST_HEAT]
                )
                assert (
                    "Overall" in text["description"]
                )  # a defrost field alone corrects Overall
            for service in (val.SERVICE_COOLING, val.SERVICE_OVERALL):
                assert val.FIELD_DEFROST_HEAT not in step["sections"][service]["data"]
        assert "defrost heat statistics" in self.steps["options"]["description"]

    def test_config_flow_has_the_defrost_field_in_the_service_sections_only(self):
        """The config flow adds the defrost field to the service sections only."""
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        assert "schema[probatio.Optional(FIELD_DEFROST_HEAT)] = _STATISTICS" in source
        assert source.count("FIELD_DEFROST_HEAT)") == 1  # only in the service schema
        assert "if service in DEFROST_SERVICES" in source
        assert "MINOR_VERSION = 4" in source
        assert "_planned_schema" not in source
        assert "SECTION_PLANNED" not in source

    def test_no_translation_mentions_a_price_source_or_a_planned_section(self):
        """No translation mentions a price, planned or cost setting."""
        text = (
            (PACKAGE / "translations" / "en.json").read_text(encoding="utf-8").lower()
        )
        for phrase in ("price", "planned", "cost"):
            assert phrase not in text, phrase  # no cost settings

    def test_defrost_errors_have_text_and_the_duplicate_placeholder(self):
        """The defrost errors have text, and the duplicate one its placeholder."""
        for flow in ("config", "options"):
            errors = self.translations[flow]["error"]
            assert "{duplicate}" in errors[val.ERROR_DEFROST_DUPLICATE], flow
            assert not re.search(r"{\w+}", errors[val.ERROR_DEFROST_UNUSED]), flow
            assert "only once" in errors[val.ERROR_DEFROST_DUPLICATE]
            assert "correct nothing" in errors[val.ERROR_DEFROST_UNUSED]
            for key in (val.ERROR_DEFROST_DUPLICATE, val.ERROR_DEFROST_UNUSED):
                assert key in val.ERROR_PRIORITY

    def test_season_keys_match_the_pure_season_module(self):
        """The season date keys of the form equal those of the season module."""
        assert val.SEASON_DATES == seasons.DATE_KEYS

    def test_every_selector_option_has_text(self):
        """Every month and cooling unit option has a translated label."""
        selector = self.translations["selector"]
        assert set(selector) == {"month", "cooling_unit"}
        assert set(selector["month"]["options"]) == {str(m) for m in range(1, 13)}
        assert set(selector["cooling_unit"]["options"]) == set(val.COOLING_UNITS)
        for name, options in selector.items():
            assert all(options["options"].values()), name

    def test_config_flow_selectors_use_translation_keys(self):
        """The config flow selectors use translation keys."""
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        assert 'translation_key="month"' in source
        assert 'translation_key="cooling_unit"' in source

    def test_unit_change_step_is_translated_and_explains_the_warning(self):
        """The unit change step is translated and explains the warning."""
        step = self.translations["options"]["step"]["unit_change"]
        assert step["title"]
        for phrase in (
            "cannot convert",
            "repair",
            "Settings, Tools, Statistics",
            "never changes",
        ):
            assert phrase in step["description"]
        assert "data" not in step  # a form without fields
        assert "{sensors}" in step["description"]  # names the affected sensors
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        assert "async_step_unit_change" in source
        assert 'step_id="unit_change"' in source

    def test_already_configured_abort_names_the_shared_statistics(self):
        """The already-configured abort names the shared statistics."""
        text = self.translations["config"]["abort"]["already_configured"]
        assert "{statistics}" in text
        assert set(re.findall(r"{(\w+)}", text)) == {"statistics"}
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        assert 'reason="already_configured"' in source
        assert '{"statistics":' in source

    def test_every_error_has_text_and_known_placeholders(self):
        """Every error has text with only known placeholders."""
        known = set(val.PLACEHOLDERS.values())
        for flow in ("config", "options"):
            errors = self.translations[flow]["error"]
            expected = set(val.ERRORS)
            if flow == "options":
                expected.discard(val.ERROR_NAME_REQUIRED)  # no name in the options form
            assert set(errors) == expected, flow
            for key, text in errors.items():
                assert text, key
                assert set(re.findall(r"{(\w+)}", text)) <= known, key
        # Each statistic error names its failing choices through its placeholder.
        for code, placeholder in val.PLACEHOLDERS.items():
            assert "{" + placeholder + "}" in self.translations["config"]["error"][code]

    def test_every_issue_has_a_title_and_a_description_with_known_placeholders(self):
        """Every repair issue has a title and a description with known placeholders."""
        issues = self.translations["issues"]
        assert set(issues) == set(repairs_model.TRANSLATION_KEYS)
        known = set(repairs_model.PLACEHOLDERS) | {repairs_model.LAST_STATISTICS}
        for key, text in issues.items():
            assert set(text) == {"title", "description"}, key  # non-fixable layout
            for field, value in text.items():
                assert value, (key, field)
                assert set(re.findall(r"{(\w+)}", value)) <= known, (key, field)
                assert not re.search(r"'[^']*{", value), (
                    key,
                    field,
                )  # hassfest: none in quotes
            assert "{statistic_id}" in text["description"], key
            assert "{heat_pump}" in text["description"], key
        # Only statistic_stale has a last statistics time (design D7); no other text may use it.
        assert "{last_statistics}" in issues["statistic_stale"]["description"]
        for key, text in issues.items():
            if key != "statistic_stale":
                assert "{last_statistics}" not in text["title"] + text["description"], (
                    key
                )

    def test_plain_ascii_text(self):
        """The English translation file is plain ASCII."""
        text = (PACKAGE / "translations" / "en.json").read_text(encoding="utf-8")
        assert text.isascii()

    def test_validation_errors_use_translated_keys(self):
        """Every error code that validation returns has a translation."""
        result = val.validate({}, [], "")
        for code in result.errors.values():
            assert code in self.translations["config"]["error"]
        assert set(result.errors) == {"name", "base"}


class TestLicense:
    """The LICENSE file."""

    def test_mit_licence_with_copyright_line(self):
        """The licence is MIT with a 2026 copyright line."""
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        assert text.startswith("MIT License")
        assert any(line.startswith("Copyright (c) 2026") for line in text.splitlines())


class TestWorkflow:
    """The validate.yml workflow."""

    def test_validate_workflow_runs_the_checks_on_push_and_pull_request(self):
        """The workflow runs hassfest, HACS and the lint script on push and PR."""
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )
        lines = [line.rstrip() for line in text.splitlines()]
        for trigger in ("  push:", "  pull_request:"):
            assert trigger in lines
        assert "home-assistant/actions/hassfest" in text
        assert "hacs/action" in text
        assert "category: integration" in text
        assert 'python-version: "3.14"' in text
        assert "run: python scripts/lint.py" in text
        assert "unittest discover" not in text

    def test_workflow_has_four_jobs_and_a_pinned_home_assistant_tests_job(self):
        """The workflow has four jobs, and the lint and ha-tests jobs are pinned."""
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )
        jobs = text.split("\njobs:\n", 1)[1]
        assert len(re.findall(r"^  [a-z][\w-]*:$", jobs, re.MULTILINE)) == 4
        lint = re.split(
            r"^  [a-z][\w-]*:$",
            jobs.split("\n  lint:\n", 1)[1],
            maxsplit=1,
            flags=re.MULTILINE,
        )[0]
        assert "name: Lint and tests" in lint
        assert "run: python scripts/lint.py" in lint
        assert re.search(r"astral-sh/setup-uv@v\d+\.\d+\.\d+\s", lint)
        assert "cache-dependency-glob: scripts/lint.py" in lint
        section = re.split(
            r"^  [a-z][\w-]*:$",
            jobs.split("\n  ha-tests:\n", 1)[1],
            maxsplit=1,
            flags=re.MULTILINE,
        )[0]
        assert "name: Home Assistant tests" in section
        assert "astral-sh/setup-uv@v" in section
        assert re.search(
            r"astral-sh/setup-uv@v\d+\.\d+\.\d+\s", section
        )  # an exact release tag
        assert "uv run --no-project" in section
        assert re.search(r"--python\s+3\.14\b", section)
        assert re.search(
            r"--with\s+pytest-homeassistant==\d+\.\d+\.\d+\b(?!-)", section
        )
        assert "pytest-homeassistant-custom-component" not in section
        assert re.search(
            r"version:\s*\"?\d+\.\d+\.\d+\"?\s", section
        )  # an exact uv version
        assert re.search(r"\bpytest tests_ha\b", section)
        assert "--cov=custom_components/heatpump_efficiency" in section  # a path source
        assert (
            "-p no:respx" in section
        )  # respx would import httpx before Home Assistant aliases it

    def test_home_assistant_tests_job_gates_config_flow_coverage_at_100_percent(self):
        """The Home Assistant tests job requires full config flow coverage."""
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )
        section = re.split(
            r"^  [a-z][\w-]*:$",
            text.split("\n  ha-tests:\n", 1)[1],
            maxsplit=1,
            flags=re.MULTILINE,
        )[0]
        assert "--cov-branch" in section  # every branch counts, not only every line
        assert (
            'coverage report --include="*/config_flow.py" --fail-under=100' in section
        )
        # The gate runs after the pytest step, in the same uv environment: same Python and same pins.
        commands = [
            " ".join(step.split())
            for step in re.split(r"^      - ", section, flags=re.MULTILINE)
            if "uv run" in step
        ]
        assert len(commands) == 2
        assert section.index("pytest tests_ha") < section.index("coverage report")
        pins = {
            tuple(re.findall(r"--python \S+|--with \S+", command))
            for command in commands
        }
        assert len(pins) == 1, commands

    def test_tests_import_only_the_standard_library_pytest_and_the_repository(
        self,
    ):
        """The tests import only the standard library, pytest and the repository."""
        siblings = {path.stem for path in (ROOT / "tests").glob("*.py")}
        allowed = (
            set(sys.stdlib_module_names) | siblings | {"custom_components", "pytest"}
        )
        for path in (ROOT / "tests").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    roots = [node.module.split(".")[0]]
                else:
                    continue
                for root in roots:
                    assert root in allowed, (path.name, root)
                    assert root != "tests_ha", path.name


def load_lint():
    """Import scripts/lint.py by path, as the scenarios of the lint entry point do."""
    spec = importlib.util.spec_from_file_location(
        "lint_for_files", ROOT / "scripts" / "lint.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_for_files"] = module
    spec.loader.exec_module(module)
    return module


class TestRuffSettings:
    """The scenarios of the requirement on the ruff settings."""

    def setup_method(self):
        """Read pyproject.toml as text and as parsed settings."""
        self.text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.config = tomllib.loads(self.text)
        self.ruff = self.config["tool"]["ruff"]

    def test_header_comment_names_the_source_tag_and_ruff_version(self):
        """The header comment names the core source, its tag and the ruff version."""
        header = self.text.split("[tool.ruff]", 1)[0]
        assert "Home Assistant core's pyproject.toml" in header
        assert "2026.11.2" in header
        assert "0.17.3" in header

    def test_required_version_names_the_version_of_the_lint_entry_point(self):
        """The required ruff version equals the one the lint script pins."""
        lint = load_lint()
        assert self.ruff["required-version"] == f">={lint.RUFF_VERSION}"

    def test_complexity_is_selected_and_limited_at_25(self):
        """The complexity rules are selected with a limit of 25."""
        assert "C" in self.ruff["lint"]["select"]
        assert self.ruff["lint"]["mccabe"]["max-complexity"] == 25

    def test_target_version_matches_the_lint_python(self):
        """The ruff target version matches the Python of the lint script."""
        lint = load_lint()
        assert self.ruff["target-version"] == "py" + lint.PYTHON.replace(".", "")

    def test_pytest_settings_are_shared_by_both_test_folders(self):
        """The pytest settings sit in pyproject.toml, not in a pytest.ini."""
        options = self.config["tool"]["pytest"]["ini_options"]
        assert options["asyncio_mode"] == "auto"
        assert options["testpaths"] == ["tests"]
        assert not (ROOT / "pytest.ini").exists()

    def test_no_exemptions_left_for_the_tests(self):
        """No per-file ignore of tests/ names the pytest-style or docstring rules."""
        ignores = self.ruff["lint"]["per-file-ignores"]
        paths = [key for key in ignores if key.startswith("tests/")]
        assert paths
        exempt = ("PT009", "PT027", "D1")
        for path in paths:
            for code in ignores[path]:
                # A code ignores a rule when it is the rule, a prefix of it, or ALL.
                assert code != "ALL", (path, code)
                assert not any(
                    rule.startswith(code) or code.startswith(rule) for rule in exempt
                ), (path, code)


class TestLintScript:
    """The scenarios of the requirement "One lint entry point"."""

    def setup_method(self):
        """Import the lint script and start with no recorded calls."""
        self.lint = load_lint()
        self.calls = []

    def run_main(self, argv=(), codes=(), uv="uv", version="uv 0.0.0"):
        """Run main with a fake runner that returns the codes in turn, then 0.

        A code that is an exception instance is raised instead of returned.
        """
        pending = list(codes)

        def runner(command, cwd):
            self.calls.append((list(command), cwd))
            code = pending.pop(0) if pending else 0
            if isinstance(code, BaseException):
                raise code
            return code

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = self.lint.main(
                list(argv),
                runner=runner,
                find=lambda: uv,
                version=lambda _uv: version,
            )
        return status, output.getvalue()

    def test_pinned_tools_have_exact_versions(self):
        """The lint script pins every tool and Python at an exact version."""
        text = (ROOT / "scripts" / "lint.py").read_text(encoding="utf-8")
        for name in (
            "RUFF_VERSION",
            "PYTEST_VERSION",
            "PYTEST_ASYNCIO_VERSION",
            "TZDATA_VERSION",
        ):
            assert re.search(rf'(?m)^{name} = "\d+(\.\d+)+"$', text), name
        assert re.search(r'(?m)^PYTHON = "3\.14"$', text)

    def test_script_uses_only_the_standard_library(self):
        """The lint script imports only the standard library."""
        tree = ast.parse((ROOT / "scripts" / "lint.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [node.module.split(".")[0]]
            else:
                continue
            for root in roots:
                assert root in sys.stdlib_module_names

    def test_missing_uv_exits_with_2_and_says_uv_is_needed(self):
        """Without uv the script exits with 2, says so and runs nothing."""
        status, output = self.run_main(uv=None)
        assert status == 2
        assert "uv is needed" in output
        assert self.calls == []

    def test_all_steps_pass_exits_with_0_and_prints_versions(self):
        """When every step passes the script exits with 0 and prints the pins."""
        status, output = self.run_main()
        assert status == 0
        for text in (
            str(ROOT),
            "uv 0.0.0",
            f"ruff {self.lint.RUFF_VERSION}",
            f"pytest {self.lint.PYTEST_VERSION}",
            f"pytest-asyncio {self.lint.PYTEST_ASYNCIO_VERSION}",
            f"tzdata {self.lint.TZDATA_VERSION}",
        ):
            assert text in output

    def test_steps_run_in_order_from_the_root_with_pinned_tools(self):
        """The four steps run in order from the root with the pinned tools."""
        self.run_main()
        commands = [" ".join(command) for command, _ in self.calls]
        assert len(commands) == 4
        assert commands[0] == f"uv tool run ruff@{self.lint.RUFF_VERSION} check ."
        assert (
            commands[1] == f"uv tool run ruff@{self.lint.RUFF_VERSION} format --check ."
        )
        assert "pytest tests -q" in commands[2]
        assert f"--with pytest=={self.lint.PYTEST_VERSION}" in commands[2]
        assert (
            f"--with pytest-asyncio=={self.lint.PYTEST_ASYNCIO_VERSION}" in commands[2]
        )
        assert f"--with tzdata=={self.lint.TZDATA_VERSION}" in commands[2]
        assert f"--python {self.lint.PYTHON}" in commands[2]
        assert "-m compileall" in commands[3]
        assert f"--python {self.lint.PYTHON}" in commands[3]
        for folder in ("custom_components", "tests", "tests_ha", "scripts"):
            assert folder in commands[3]
        assert {cwd for _, cwd in self.calls} == {ROOT}

    def test_a_failing_step_exits_with_1_after_running_every_step(self):
        """A failing step exits with 1 after every step has run."""
        status, output = self.run_main(codes=(1,))
        assert status == 1
        assert len(self.calls) == 4
        assert "ruff check" in output.rsplit("Failed:", 1)[1]

    def test_any_non_zero_code_exits_with_1(self):
        """Any non-zero step code gives exit status 1."""
        status, _ = self.run_main(codes=(0, 0, 2, 0))
        assert status == 1

    def test_a_program_that_cannot_start_exits_with_2(self):
        """A program that cannot start gives exit status 2."""
        status, _ = self.run_main(codes=(OSError("no such program"),))
        assert status == 2

    def test_a_program_that_cannot_start_names_the_steps_already_failed(self):
        """An unstartable program is reported with the steps that failed before."""
        status, output = self.run_main(codes=(1, OSError("no such program")))
        assert status == 2
        assert "Failed before that: ruff check" in output

    def test_fix_applies_ruff_fixes_and_the_formatter_first(self):
        """The fix option runs ruff's fixes and the formatter before the checks."""
        status, _ = self.run_main(argv=["--fix"])
        assert status == 0
        commands = [" ".join(command) for command, _ in self.calls]
        assert len(commands) == 6
        assert commands[0].endswith("check --fix .")
        assert commands[1].endswith("format .")
        assert commands[2].endswith("check .")

    def test_the_tests_environment_has_no_home_assistant(self):
        """The tests step does not install Home Assistant."""
        self.run_main()
        tests_command = " ".join(self.calls[2][0])
        assert "homeassistant" not in tests_command


class TestNoUnittestTestCases:
    """The scenario "No unittest test cases" of the requirement on tests in the pytest style."""

    def test_no_test_module_uses_unittest_other_than_mock_or_a_test_case(self):
        """No module in tests/ imports unittest (except unittest.mock) or subclasses TestCase."""
        for path in sorted((ROOT / "tests").glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    imported = [node.module]
                    if node.module == "unittest":
                        assert all(alias.name == "mock" for alias in node.names), (
                            path.name,
                            "from unittest import",
                            [alias.name for alias in node.names],
                        )
                        imported = []
                elif isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        name = ast.unparse(base)
                        assert not name.split(".")[-1].endswith("TestCase"), (
                            path.name,
                            node.name,
                        )
                    continue
                elif (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "unittest"
                ):
                    # "import unittest.mock" also binds the name unittest.
                    assert node.attr == "mock", (path.name, f"unittest.{node.attr}")
                    continue
                else:
                    continue
                for name in imported:
                    assert name != "unittest", (path.name, name)
                    if name.split(".")[0] == "unittest":
                        assert name == "unittest.mock", (path.name, name)


class TestIcons:
    """The scenario "An icon for every translation key" of the period-efficiency spec."""

    def setup_method(self):
        """Load the icons and the sensor translations."""
        self.icons = load(PACKAGE / "icons.json")["entity"]["sensor"]
        self.translations = load(PACKAGE / "translations" / "en.json")["entity"][
            "sensor"
        ]

    def test_keys_equal_the_sensor_translation_keys(self):
        """The icon keys equal the sensor translation keys of the code."""
        assert set(self.icons) == set(self.translations)
        names = (*sensor_model.eff.PERIODS, *set(sensor_model.SEASONS.values()))
        code_keys = {
            sensor_model.translation_key(service, name)
            for service in val.SERVICES
            for name in names
            if name in sensor_model.eff.PERIODS
            or sensor_model.SEASONS.get(service) == name
        }
        assert set(self.icons) == code_keys

    def test_every_icon_is_a_default_mdi_icon(self):
        """Every icon is a single default mdi icon."""
        for key, icon in self.icons.items():
            assert list(icon) == ["default"], key
            assert icon["default"].startswith("mdi:"), key

    def test_one_icon_per_service_and_four_different_icons(self):
        """Each service has one icon and the four services differ."""
        by_service = {}
        for key, icon in self.icons.items():
            service = max((s for s in val.SERVICES if key.startswith(s + "_")), key=len)
            by_service.setdefault(service, set()).add(icon["default"])
        assert set(by_service) == set(val.SERVICES)
        for service, found in by_service.items():
            assert len(found) == 1, service
        assert len({next(iter(found)) for found in by_service.values()}) == 4

    def test_sensors_set_no_icon_in_code(self):
        """No module sets an icon in code."""
        for path in PACKAGE.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "_attr_icon" not in text, path.name
            assert not re.search(r"\bicon\s*=", text), path.name
            assert not re.search(r"def icon\b", text), path.name


class TestReadme:
    """The README against the code and the translations."""

    def test_season_and_unit_fields_are_named(self):
        """The README names the season and unit fields and the season defaults."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for label in (
            "Season dates",
            "Cooling efficiency unit",
            "W/W",
            "BTU/Wh",
            "3.412142",
        ):
            assert label in readme
        for default in (
            "1 October to 30 April",
            "1 June to 30 September",
            "1 April to 31 October",
            "1 December to 28 February",
        ):
            assert default in readme

    def test_defrost_setup_is_documented(self):
        """The README documents the defrost setup and drops the superseded text."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        setup = readme.split("\n## Setup", 1)[1].split("\n## Sensors", 1)[0]
        translations = load(PACKAGE / "translations" / "en.json")
        label = translations["config"]["step"]["user"]["sections"]["heating"]["data"][
            val.FIELD_DEFROST_HEAT
        ]
        assert "**" + label in setup
        for phrase in (
            "one per",  # split counters, one per service
            "dominant service",
            "Overall",
            "twice",  # the double-counting warning for a water-side meter
            "Total Defrost Energy",
            "18 November 2026",
            "not backfilled",
            "may be mapped only once",  # defrost_duplicate
            "correct nothing",  # defrost_unused
            "moved once",  # the migration of the planned slot
        ):
            assert phrase in setup, phrase
        assert (
            "Defrost heat statistic:" not in setup
        )  # the superseded planned slot text
        assert "two optional slots" not in setup
        assert "Planned (not used yet)" not in readme  # the removed section
        assert "**Price source:**" not in readme
        assert "Entries from earlier versions" in setup
        assert "Cost is not part of the integration" in readme
        assert (
            "five sections" in setup
        )  # Heating, Hot water, Cooling, Overall, Season dates
        assert "six sections" not in readme

    def test_firmware_entity_ids_are_only_written_as_device_placeholders(self):
        """Firmware entity IDs are written only with a device placeholder."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "sensor.<device>_total_defrost_energy" in readme
        pattern = re.compile(r"sensor\.[a-z0-9_<>]+_total_[a-z_]*energy[a-z0-9_]*")
        paths = (
            ROOT / "README.md",
            PACKAGE / "translations" / "en.json",
            *PACKAGE.glob("**/*.py"),
            *(ROOT / "tests").glob("*.py"),
        )
        for path in paths:
            for found in pattern.findall(path.read_text(encoding="utf-8")):
                assert found.startswith("sensor.<device>_"), (path.name, found)

    def test_every_form_label_is_explained(self):
        """Every form label is explained in the README."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        translations = load(PACKAGE / "translations" / "en.json")
        step = translations["config"]["step"]["user"]
        labels = set(step["data"].values())
        for text in step["sections"].values():
            labels.add(text["name"])
            labels.update(text["data"].values())
        for label in labels:
            assert "**" + label.split(" (")[0] in readme, label
        assert readme.isascii()

    def test_every_issue_title_is_named_in_the_troubleshooting(self):
        """Every repair issue title is named in the troubleshooting section."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "## Troubleshooting" in readme
        troubleshooting = readme.split("## Troubleshooting", 1)[1].split("\n## ", 1)[0]
        translations = load(PACKAGE / "translations" / "en.json")
        for key, text in translations["issues"].items():
            title = text["title"].split(" {")[0]  # the title without its placeholder
            assert "**" + title in troubleshooting, key
        for phrase in ("Diagnostics", "restarts at 0", "at most 2 hours behind"):
            assert phrase in troubleshooting

    def test_examples_never_use_statistics_mean(self):
        """The YAML examples never use the mean statistic type."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        blocks = re.findall(r"```yaml\n(.*?)```", readme, re.DOTALL)
        assert (
            len(blocks) >= 4
        )  # entities, daily and monthly charts and the season table
        for block in blocks:
            assert not re.search(r"stat_type\s*:\s*mean", block)
            assert not re.search(r"stat_types\s*:[^\n]*mean", block)
            assert not re.search(
                r"stat_types\s*:\s*\n(\s*-\s*\w+\s*\n)*\s*-\s*mean", block
            )
            assert not re.search(r"statistics\s*:\s*\n\s+type\s*:\s*mean", block)
        joined = "\n".join(blocks)
        assert "data_generator" in joined
        assert "entity.attributes.daily" in joined
        assert "entity.attributes.monthly" in joined
        assert re.search(r"state_attr\([^)]*'seasons'\)", joined)  # the season table
        assert not re.search(r"stat_types?:\s*(\[\s*)?mean", joined)
