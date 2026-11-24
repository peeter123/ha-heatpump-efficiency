"""Checks of the quality scale record against the manifest (design D2).

hassfest skips quality_scale.yaml for custom integrations (ha-core 2026.11.2
script/hassfest/quality_scale.py validate_iqs_file returns when integration.core is false), so
these tests apply the same schema and the tier rule themselves.
"""

import json
from pathlib import Path

import pytest

from homeassistant.util.yaml import load_yaml_dict

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "heatpump_efficiency"

TIERS = ("bronze", "silver", "gold", "platinum")

# ha-core 2026.11.2, script/hassfest/quality_scale.py, ALL_RULES (rule names and tiers, in the same order).
ALL_RULES = {
    "bronze": [
        "action-setup",
        "appropriate-polling",
        "brands",
        "common-modules",
        "config-flow",
        "config-flow-test-coverage",
        "dependency-transparency",
        "docs-actions",
        "docs-conditions",
        "docs-high-level-description",
        "docs-installation-instructions",
        "docs-removal-instructions",
        "docs-triggers",
        "entity-event-setup",
        "entity-unique-id",
        "has-entity-name",
        "runtime-data",
        "test-before-configure",
        "test-before-setup",
        "unique-config-entry",
    ],
    "silver": [
        "action-exceptions",
        "config-entry-unloading",
        "docs-configuration-parameters",
        "docs-installation-parameters",
        "entity-unavailable",
        "integration-owner",
        "log-when-unavailable",
        "parallel-updates",
        "reauthentication-flow",
        "test-coverage",
    ],
    "gold": [
        "devices",
        "diagnostics",
        "discovery",
        "discovery-update-info",
        "docs-data-update",
        "docs-examples",
        "docs-known-limitations",
        "docs-supported-devices",
        "docs-supported-functions",
        "docs-troubleshooting",
        "docs-use-cases",
        "dynamic-devices",
        "entity-category",
        "entity-device-class",
        "entity-disabled-by-default",
        "entity-translations",
        "exception-translations",
        "icon-translations",
        "reconfiguration-flow",
        "repair-issues",
        "stale-devices",
    ],
    "platinum": [
        "async-dependency",
        "inject-websession",
        "strict-typing",
    ],
}

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    """Override the conftest fixture of the same name: these tests only read files and need no hass.

    pytest: a fixture defined in a test module overrides a conftest fixture of the same name for that module
    (docs.pytest.org, "Override a fixture on a test module level"), so no Home Assistant or recorder is started.
    """


RULE_TIER = {rule: tier for tier, rules in ALL_RULES.items() for rule in rules}


def rule_status(value):
    """The status of a rule value: a bare string, a mapping with a status, or None when missing."""
    return value.get("status") if isinstance(value, dict) else value


def unmet_rules(rules, tier):
    """Rules of the given tier and the tiers below it that are neither done nor exempt."""
    unmet = []
    for name in TIERS[: TIERS.index(tier) + 1]:
        unmet.extend(r for r in ALL_RULES[name] if rule_status(rules.get(r)) not in ("done", "exempt"))
    return unmet


def supported_tier(rules):
    """The highest tier whose rules and those of the tiers below are all done or exempt."""
    supported = None
    for tier in TIERS:
        if unmet_rules(rules, tier):
            break
        supported = tier
    return supported


@pytest.fixture(scope="module")
def rules():
    record = load_yaml_dict(PACKAGE / "quality_scale.yaml")
    # ha-core 2026.11.2 script/hassfest/quality_scale.py SCHEMA allows only the top-level key "rules".
    assert set(record) == {"rules"}
    return record["rules"]


@pytest.fixture(scope="module")
def manifest():
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def test_rule_count():
    assert [len(ALL_RULES[tier]) for tier in TIERS] == [20, 10, 21, 3]
    assert len(RULE_TIER) == 54


def test_every_rule_listed(rules):
    assert set(rules) == set(RULE_TIER)


def check_value(name, value):
    """Assert that one rule value has the shape of the record.

    Same shape as ha-core 2026.11.2 script/hassfest/quality_scale.py SCHEMA, plus the packaging spec: exempt and
    todo always carry a comment.
    """
    if isinstance(value, str):
        assert value in ("done", "todo", "exempt"), f"{name}: bare value {value!r}"
        assert value == "done", f"{name}: a {value} needs a comment with the reason"
        return
    assert isinstance(value, dict), f"{name}: expected a string or a mapping"
    assert set(value) == {"status", "comment"}, f"{name}: keys {sorted(value)}"
    assert value["status"] in ("done", "todo", "exempt"), f"{name}: status {value['status']!r}"
    assert isinstance(value["comment"], str) and value["comment"].strip(), f"{name}: empty comment"


def test_values_valid(rules):
    for name, value in rules.items():
        check_value(name, value)


def test_value_check_rejects_missing_reasons():
    check_value("ok", "done")
    check_value("ok", {"status": "exempt", "comment": "A reason."})
    for bad in ("exempt", "todo", {"status": "todo"}, {"status": "exempt", "comment": ""}):
        with pytest.raises(AssertionError):
            check_value("bad", bad)


def test_exempt_and_todo_have_comments(rules):
    for name, value in rules.items():
        if rule_status(value) in ("exempt", "todo"):
            assert isinstance(value, dict) and value["comment"].strip(), f"{name}: needs a comment"


def test_declared_tier_is_backed_by_the_record(rules, manifest):
    declared = manifest["quality_scale"]
    assert declared in TIERS
    unmet = unmet_rules(rules, declared)
    assert not unmet, f"the manifest claims {declared} but these rules are not done or exempt: {unmet}"


def test_declared_tier_is_the_highest_supported(rules, manifest):
    supported = supported_tier(rules)
    assert manifest["quality_scale"] == supported, (
        f"the record supports {supported} but the manifest declares {manifest['quality_scale']}"
    )


def test_tier_helper_names_the_failing_rule(rules):
    broken = dict(rules, **{"brands": {"status": "todo", "comment": "x"}})
    assert unmet_rules(broken, "bronze") == ["brands"]
    assert supported_tier(broken) is None
    complete = {name: "done" for name in RULE_TIER}
    assert supported_tier(complete) == "platinum"
    complete["strict-typing"] = {"status": "todo", "comment": "x"}
    assert supported_tier(complete) == "gold"
