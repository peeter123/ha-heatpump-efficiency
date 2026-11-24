"""Tests of the static integration files: manifest, hacs.json and translations."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "heatpump_efficiency"
_spec = importlib.util.spec_from_file_location("validation_for_files", PACKAGE / "validation.py")
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
    return json.loads(path.read_text(encoding="utf-8"))


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = load(PACKAGE / "manifest.json")

    def test_keys(self):
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
            self.assertIn(key, self.manifest)
        self.assertEqual(self.manifest["domain"], "heatpump_efficiency")
        self.assertEqual(self.manifest["name"], "Heat Pump Efficiency")
        self.assertIs(self.manifest["config_flow"], True)
        self.assertEqual(self.manifest["dependencies"], ["recorder"])
        self.assertEqual(self.manifest["integration_type"], "service")
        self.assertEqual(self.manifest["iot_class"], "calculated")
        self.assertNotIn("requirements", self.manifest)
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_real_repository_values_and_no_placeholders(self):
        self.assertEqual(self.manifest["documentation"], "https://github.com/peeter123/ha-heatpump-efficiency")
        self.assertEqual(self.manifest["issue_tracker"], "https://github.com/peeter123/ha-heatpump-efficiency/issues")
        self.assertEqual(self.manifest["codeowners"], ["@peeter123"])
        self.assertEqual(self.manifest["version"], "0.2.0")

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
            self.assertNotIn("PLACEHOLDER", text)

    def test_categories(self):
        # ha-core 2026.11.2 script/hassfest/manifest.py validate_categories: a parent
        # category listed with its own subcategory is an error.
        categories = self.manifest["categories"]
        self.assertEqual(
            categories, ["climate.heat_pumps_air_conditioning", "energy.meters_monitoring"]
        )
        for category in categories:
            parent, _, subcategory = category.partition(".")
            if subcategory:
                self.assertNotIn(parent, categories)
        self.assertEqual(len(set(categories)), len(categories))
        self.assertNotIn("connectivity", self.manifest)

    def test_readme_status_matches_manifest(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"Version {self.manifest['version']}.", readme)
        self.assertIn(f"declares the {self.manifest['quality_scale'].capitalize()} tier", readme)
        self.assertIn("custom_components/heatpump_efficiency/quality_scale.yaml", readme)

    def test_keys_sorted(self):
        # ha-core 2026.11.2 script/hassfest/manifest.py sort_manifest: domain, name,
        # then alphabetical order.
        keys = list(self.manifest)
        self.assertEqual(keys[:2], ["domain", "name"])
        self.assertEqual(keys[2:], sorted(keys[2:]))

    def test_domain_matches_const(self):
        self.assertIn(
            f'DOMAIN: Final = "{self.manifest["domain"]}"',
            (PACKAGE / "const.py").read_text(encoding="utf-8"),
        )


class HacsTest(unittest.TestCase):
    def test_minimum_home_assistant_version(self):
        hacs = load(ROOT / "hacs.json")
        self.assertEqual(hacs["name"], "Heat Pump Efficiency")
        self.assertEqual(hacs["homeassistant"], "2026.11.0")


class TranslationsTest(unittest.TestCase):
    def setUp(self):
        self.translations = load(PACKAGE / "translations" / "en.json")
        self.steps = {
            "config": self.translations["config"]["step"]["user"],
            "options": self.translations["options"]["step"]["init"],
        }

    def test_every_step_has_text(self):
        for name, step in self.steps.items():
            self.assertTrue(step["title"], name)
            self.assertTrue(step["description"], name)
        self.assertTrue(self.steps["config"]["data"][val.FIELD_NAME])
        self.assertTrue(self.steps["config"]["data_description"][val.FIELD_NAME])
        self.assertNotIn("data", self.steps["options"])  # the options form has no name

    def test_every_section_and_field_has_text(self):
        expected = {section: val.SERVICE_FIELDS for section in val.SERVICES}
        expected[val.SERVICE_COOLING] = val.COOLING_FIELDS  # the unit is a Cooling field only
        for service in val.DEFROST_SERVICES:  # the defrost heat field: Heating and Hot water only
            expected[service] = (*val.SERVICE_FIELDS, val.FIELD_DEFROST_HEAT)
        expected[val.SECTION_SEASONS] = val.SEASON_FIELDS
        for name, step in self.steps.items():
            self.assertEqual(set(step["sections"]), set(expected), name)
            self.assertNotIn(val.SECTION_PLANNED, step["sections"], name)  # no planned section
            for section, fields in expected.items():
                text = step["sections"][section]
                self.assertTrue(text["name"] and text["description"], (name, section))
                for key in ("data", "data_description"):
                    self.assertEqual(set(text[key]), set(fields), (name, section, key))
                    self.assertTrue(all(text[key].values()), (name, section, key))

    def test_defrost_field_text(self):
        for name, step in self.steps.items():
            for service in val.DEFROST_SERVICES:
                text = step["sections"][service]
                self.assertEqual(text["data"][val.FIELD_DEFROST_HEAT], "Defrost heat statistics")
                self.assertIn("subtracted", text["data_description"][val.FIELD_DEFROST_HEAT])
                self.assertIn("Overall", text["data_description"][val.FIELD_DEFROST_HEAT])
                self.assertIn("already counts", text["data_description"][val.FIELD_DEFROST_HEAT])
                self.assertIn("Overall", text["description"])  # a defrost field alone corrects Overall
            for service in (val.SERVICE_COOLING, val.SERVICE_OVERALL):
                self.assertNotIn(val.FIELD_DEFROST_HEAT, step["sections"][service]["data"])
        self.assertIn("defrost heat statistics", self.steps["options"]["description"])

    def test_config_flow_has_the_defrost_field_in_the_service_sections_only(self):
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("schema[vol.Optional(FIELD_DEFROST_HEAT)] = _STATISTICS", source)
        self.assertEqual(source.count("FIELD_DEFROST_HEAT)"), 1)  # only in the service schema
        self.assertIn("if service in DEFROST_SERVICES", source)
        self.assertIn("MINOR_VERSION = 4", source)
        self.assertNotIn("_planned_schema", source)
        self.assertNotIn("SECTION_PLANNED", source)

    def test_no_translation_mentions_a_price_source_or_a_planned_section(self):
        text = (PACKAGE / "translations" / "en.json").read_text(encoding="utf-8").lower()
        for phrase in ("price", "planned", "cost"):
            self.assertNotIn(phrase, text, phrase)  # no cost settings

    def test_defrost_errors_have_text_and_the_duplicate_placeholder(self):
        for flow in ("config", "options"):
            errors = self.translations[flow]["error"]
            self.assertIn("{duplicate}", errors[val.ERROR_DEFROST_DUPLICATE], flow)
            self.assertNotRegex(errors[val.ERROR_DEFROST_UNUSED], r"{\w+}", flow)
            self.assertIn("only once", errors[val.ERROR_DEFROST_DUPLICATE])
            self.assertIn("correct nothing", errors[val.ERROR_DEFROST_UNUSED])
            for key in (val.ERROR_DEFROST_DUPLICATE, val.ERROR_DEFROST_UNUSED):
                self.assertIn(key, val._ERROR_PRIORITY)

    def test_season_keys_match_the_pure_season_module(self):
        self.assertEqual(val.SEASON_DATES, seasons.DATE_KEYS)

    def test_every_selector_option_has_text(self):
        selector = self.translations["selector"]
        self.assertEqual(set(selector), {"month", "cooling_unit"})
        self.assertEqual(set(selector["month"]["options"]), {str(m) for m in range(1, 13)})
        self.assertEqual(set(selector["cooling_unit"]["options"]), set(val.COOLING_UNITS))
        for name, options in selector.items():
            self.assertTrue(all(options["options"].values()), name)

    def test_config_flow_selectors_use_translation_keys(self):
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('translation_key="month"', source)
        self.assertIn('translation_key="cooling_unit"', source)

    def test_unit_change_step_is_translated_and_explains_the_warning(self):
        step = self.translations["options"]["step"]["unit_change"]
        self.assertTrue(step["title"])
        for phrase in ("cannot convert", "repair", "statistics developer tools", "never changes"):
            self.assertIn(phrase, step["description"])
        self.assertNotIn("data", step)  # a form without fields
        self.assertIn("{sensors}", step["description"])  # names the affected sensors
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("async_step_unit_change", source)
        self.assertIn('step_id="unit_change"', source)

    def test_already_configured_abort_names_the_shared_statistics(self):
        text = self.translations["config"]["abort"]["already_configured"]
        self.assertIn("{statistics}", text)
        self.assertEqual(set(re.findall(r"{(\w+)}", text)), {"statistics"})
        source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('reason="already_configured"', source)
        self.assertIn('{"statistics":', source)

    def test_every_error_has_text_and_known_placeholders(self):
        known = set(val.PLACEHOLDERS.values())
        for flow in ("config", "options"):
            errors = self.translations[flow]["error"]
            expected = set(val.ERRORS)
            if flow == "options":
                expected.discard(val.ERROR_NAME_REQUIRED)  # no name in the options form
            self.assertEqual(set(errors), expected, flow)
            for key, text in errors.items():
                self.assertTrue(text, key)
                self.assertLessEqual(set(re.findall(r"{(\w+)}", text)), known, key)
        # Each statistic error names its failing choices through its placeholder.
        for code, placeholder in val.PLACEHOLDERS.items():
            self.assertIn("{" + placeholder + "}", self.translations["config"]["error"][code])

    def test_every_issue_has_a_title_and_a_description_with_known_placeholders(self):
        issues = self.translations["issues"]
        self.assertEqual(set(issues), set(repairs_model.TRANSLATION_KEYS))
        known = set(repairs_model.PLACEHOLDERS) | {repairs_model.LAST_STATISTICS}
        for key, text in issues.items():
            self.assertEqual(set(text), {"title", "description"}, key)  # non-fixable layout
            for field, value in text.items():
                self.assertTrue(value, (key, field))
                self.assertLessEqual(set(re.findall(r"{(\w+)}", value)), known, (key, field))
                self.assertNotRegex(value, r"'[^']*{", (key, field))  # hassfest: none in quotes
            self.assertIn("{statistic_id}", text["description"], key)
            self.assertIn("{heat_pump}", text["description"], key)
        # Only statistic_stale has a last statistics time (design D7); no other text may use it.
        self.assertIn("{last_statistics}", issues["statistic_stale"]["description"])
        for key, text in issues.items():
            if key != "statistic_stale":
                self.assertNotIn("{last_statistics}", text["title"] + text["description"], key)

    def test_plain_ascii_text(self):
        text = (PACKAGE / "translations" / "en.json").read_text(encoding="utf-8")
        self.assertTrue(text.isascii())

    def test_validation_errors_use_translated_keys(self):
        result = val.validate({}, [], "")
        for code in result.errors.values():
            self.assertIn(code, self.translations["config"]["error"])
        self.assertEqual(set(result.errors), {"name", "base"})


class LicenseTest(unittest.TestCase):
    def test_mit_licence_with_copyright_line(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License"))
        self.assertTrue(any(line.startswith("Copyright (c) 2026") for line in text.splitlines()))


class WorkflowTest(unittest.TestCase):
    def test_validate_workflow_runs_the_checks_on_push_and_pull_request(self):
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        lines = [line.rstrip() for line in text.splitlines()]
        for trigger in ("  push:", "  pull_request:"):
            self.assertIn(trigger, lines)
        self.assertIn("home-assistant/actions/hassfest", text)
        self.assertIn("hacs/action", text)
        self.assertIn("category: integration", text)
        self.assertIn('python-version: "3.14"', text)
        self.assertIn("python -m unittest discover tests", text)
        self.assertIn("python -m compileall custom_components", text)

    def test_workflow_has_four_jobs_and_a_pinned_home_assistant_tests_job(self):
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        jobs = text.split("\njobs:\n", 1)[1]
        self.assertEqual(len(re.findall(r"^  [a-z][\w-]*:$", jobs, re.M)), 4)
        section = re.split(r"^  [a-z][\w-]*:$", jobs.split("\n  ha-tests:\n", 1)[1], maxsplit=1, flags=re.M)[0]
        self.assertIn("name: Home Assistant tests", section)
        self.assertIn("astral-sh/setup-uv@v", section)
        self.assertRegex(section, r"astral-sh/setup-uv@v\d+\.\d+\.\d+\s")  # an exact release tag
        self.assertIn("uv run --no-project", section)
        self.assertRegex(section, r"--python\s+3\.14\b")
        self.assertRegex(section, r"--with\s+pytest-homeassistant-custom-component==\d+\.\d+\.\d+\b")
        self.assertRegex(section, r"version:\s*\"?\d+\.\d+\.\d+\"?\s")  # an exact uv version
        self.assertIn("pytest --cov=custom_components.heatpump_efficiency", section)

    def test_home_assistant_tests_job_gates_config_flow_coverage_at_100_percent(self):
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        section = re.split(r"^  [a-z][\w-]*:$", text.split("\n  ha-tests:\n", 1)[1], maxsplit=1, flags=re.M)[0]
        self.assertIn("--cov-branch", section)  # every branch counts, not only every line
        self.assertIn('coverage report --include="*/config_flow.py" --fail-under=100', section)
        # The gate runs after the pytest step, in the same uv environment: same Python and same pins.
        commands = [" ".join(step.split()) for step in re.split(r"^      - ", section, flags=re.M) if "uv run" in step]
        self.assertEqual(len(commands), 2)
        self.assertLess(section.index("pytest --cov"), section.index("coverage report"))
        pins = {tuple(re.findall(r"--python \S+|--with \S+", command)) for command in commands}
        self.assertEqual(len(pins), 1, commands)

    def test_standard_library_tests_import_only_the_standard_library_and_the_repository(self):
        siblings = {path.stem for path in (ROOT / "tests").glob("*.py")}
        allowed = set(sys.stdlib_module_names) | siblings | {"custom_components"}
        for path in (ROOT / "tests").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    roots = [node.module.split(".")[0]]
                else:
                    continue
                for root in roots:
                    self.assertIn(root, allowed, (path.name, root))
                    self.assertNotEqual(root, "tests_ha", path.name)


class IconsTest(unittest.TestCase):
    """The scenario "An icon for every translation key" of the period-efficiency spec."""

    def setUp(self):
        self.icons = load(PACKAGE / "icons.json")["entity"]["sensor"]
        self.translations = load(PACKAGE / "translations" / "en.json")["entity"]["sensor"]

    def test_keys_equal_the_sensor_translation_keys(self):
        self.assertEqual(set(self.icons), set(self.translations))
        names = (*sensor_model.eff.PERIODS, *set(sensor_model.SEASONS.values()))
        code_keys = {
            sensor_model.translation_key(service, name)
            for service in val.SERVICES
            for name in names
            if name in sensor_model.eff.PERIODS or sensor_model.SEASONS.get(service) == name
        }
        self.assertEqual(set(self.icons), code_keys)

    def test_every_icon_is_a_default_mdi_icon(self):
        for key, icon in self.icons.items():
            self.assertEqual(list(icon), ["default"], key)
            self.assertTrue(icon["default"].startswith("mdi:"), key)

    def test_one_icon_per_service_and_four_different_icons(self):
        by_service = {}
        for key, icon in self.icons.items():
            service = max((s for s in val.SERVICES if key.startswith(s + "_")), key=len)
            by_service.setdefault(service, set()).add(icon["default"])
        self.assertEqual(set(by_service), set(val.SERVICES))
        for service, found in by_service.items():
            self.assertEqual(len(found), 1, service)
        self.assertEqual(len({next(iter(found)) for found in by_service.values()}), 4)

    def test_sensors_set_no_icon_in_code(self):
        for path in PACKAGE.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("_attr_icon", text, path.name)
            self.assertNotRegex(text, r"\bicon\s*=", path.name)
            self.assertNotRegex(text, r"def icon\b", path.name)


class ReadmeTest(unittest.TestCase):
    def test_season_and_unit_fields_are_named(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for label in ("Season dates", "Cooling efficiency unit", "W/W", "BTU/Wh", "3.412142"):
            self.assertIn(label, readme)
        for default in (
            "1 October to 30 April",
            "1 June to 30 September",
            "1 April to 31 October",
            "1 December to 28 February",
        ):
            self.assertIn(default, readme)

    def test_defrost_setup_is_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        setup = readme.split("\n## Setup", 1)[1].split("\n## Sensors", 1)[0]
        translations = load(PACKAGE / "translations" / "en.json")
        label = translations["config"]["step"]["user"]["sections"]["heating"]["data"][val.FIELD_DEFROST_HEAT]
        self.assertIn("**" + label, setup)
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
            self.assertIn(phrase, setup, phrase)
        self.assertNotIn("Defrost heat statistic:", setup)  # the superseded planned slot text
        self.assertNotIn("two optional slots", setup)
        self.assertNotIn("Planned (not used yet)", readme)  # the removed section
        self.assertNotIn("**Price source:**", readme)
        self.assertIn("Entries from earlier versions", setup)
        self.assertIn("Cost is not part of the integration", readme)
        self.assertIn("five sections", setup)  # Heating, Hot water, Cooling, Overall, Season dates
        self.assertNotIn("six sections", readme)

    def test_firmware_entity_ids_are_only_written_as_device_placeholders(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("sensor.<device>_total_defrost_energy", readme)
        pattern = re.compile(r"sensor\.[a-z0-9_<>]+_total_[a-z_]*energy[a-z0-9_]*")
        paths = (
            ROOT / "README.md",
            PACKAGE / "translations" / "en.json",
            *PACKAGE.glob("**/*.py"),
            *(ROOT / "tests").glob("*.py"),
        )
        for path in paths:
            for found in pattern.findall(path.read_text(encoding="utf-8")):
                self.assertTrue(found.startswith("sensor.<device>_"), (path.name, found))

    def test_every_form_label_is_explained(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        translations = load(PACKAGE / "translations" / "en.json")
        step = translations["config"]["step"]["user"]
        labels = set(step["data"].values())
        for text in step["sections"].values():
            labels.add(text["name"])
            labels.update(text["data"].values())
        for label in labels:
            self.assertIn("**" + label.split(" (")[0], readme, label)
        self.assertTrue(readme.isascii())

    def test_every_issue_title_is_named_in_the_troubleshooting(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Troubleshooting", readme)
        troubleshooting = readme.split("## Troubleshooting", 1)[1].split("\n## ", 1)[0]
        translations = load(PACKAGE / "translations" / "en.json")
        for key, text in translations["issues"].items():
            title = text["title"].split(" {")[0]  # the title without its placeholder
            self.assertIn("**" + title, troubleshooting, key)
        for phrase in ("Diagnostics", "restarts at 0", "at most 2 hours behind"):
            self.assertIn(phrase, troubleshooting)

    def test_examples_never_use_statistics_mean(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        blocks = re.findall(r"```yaml\n(.*?)```", readme, re.S)
        self.assertGreaterEqual(len(blocks), 4)  # entities, daily and monthly charts and the season table
        for block in blocks:
            self.assertNotRegex(block, r"stat_type\s*:\s*mean")
            self.assertNotRegex(block, r"stat_types\s*:[^\n]*mean")
            self.assertNotRegex(block, r"stat_types\s*:\s*\n(\s*-\s*\w+\s*\n)*\s*-\s*mean")
            self.assertNotRegex(block, r"statistics\s*:\s*\n\s+type\s*:\s*mean")
        joined = "\n".join(blocks)
        self.assertIn("data_generator", joined)
        self.assertIn("entity.attributes.daily", joined)
        self.assertIn("entity.attributes.monthly", joined)
        self.assertRegex(joined, r"state_attr\([^)]*'seasons'\)")  # the season table
        self.assertNotRegex(joined, r"stat_types?:\s*(\[\s*)?mean")


if __name__ == "__main__":
    unittest.main()
