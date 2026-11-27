"""Tests of the coverage gate script: the scenarios of the requirement "Integration coverage gate"."""

import ast
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "coverage_gate_script", ROOT / "scripts" / "coverage_gate.py"
)
gate = importlib.util.module_from_spec(_spec)
sys.modules["coverage_gate_script"] = gate
_spec.loader.exec_module(gate)

PACKAGE = "custom_components/heatpump_efficiency/"


def summary(percent: float) -> dict:
    """The part of a coverage.py report that holds a percentage."""
    return {"summary": {"percent_covered": percent}}


def write_report(
    tmp_path: Path, files: dict[str, float], total: float, name: str = "coverage.json"
) -> Path:
    """Write a JSON report of the shape coverage.py writes, reduced to what the gate reads."""
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "meta": {"format": 3},
                "files": {key: summary(value) for key, value in files.items()},
                "totals": summary(total)["summary"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_module_below_the_threshold_fails_and_is_named(tmp_path, capsys):
    """Scenario "Module below the threshold": one module at 94 % and a total of 97 % exit non-zero and name it."""
    report = write_report(
        tmp_path,
        {
            f"{PACKAGE}engine.py": 99.0,
            f"{PACKAGE}coordinator.py": 94.0,
            f"{PACKAGE}sensor.py": 100.0,
        },
        97.0,
    )

    status = gate.main([str(report), "95"])

    output = capsys.readouterr().out
    assert status == 1
    assert f"{PACKAGE}coordinator.py: 94.00 %" in output
    assert "engine.py" not in output
    assert "sensor.py" not in output
    assert "Total: 97.00 %" in output


def test_every_module_covered_exits_with_0(tmp_path, capsys):
    """Scenario "Every module covered": the total and every module at 95 % or more exit with 0."""
    report = write_report(
        tmp_path, {f"{PACKAGE}engine.py": 95.0, f"{PACKAGE}sensor.py": 100.0}, 97.5
    )

    assert gate.main([str(report), "95"]) == 0
    assert "Total: 97.50 %" in capsys.readouterr().out


def test_a_total_below_the_threshold_fails_even_when_every_module_reaches_it(
    tmp_path, capsys
):
    """The total counts too, so a report that says 94 % in total fails with every listed module at 95 %."""
    report = write_report(tmp_path, {f"{PACKAGE}engine.py": 95.0}, 94.0)

    assert gate.main([str(report), "95"]) == 1
    assert "The total is below 95 %" in capsys.readouterr().out


def test_only_files_of_the_integration_count(tmp_path):
    """A file outside the integration folder never changes the result, whichever way its path is written."""
    report = write_report(
        tmp_path,
        {
            f"{PACKAGE}engine.py": 96.0,
            "tests/test_engine.py": 10.0,
            "custom_components/other/engine.py": 10.0,
            "custom_components\\heatpump_efficiency_other\\engine.py": 10.0,
        },
        96.0,
    )

    assert gate.main([str(report), "95"]) == 0


def test_paths_with_windows_separators_and_a_prefix_count(tmp_path, capsys):
    """An absolute path or a path with backslashes of the integration folder is a module of the integration."""
    report = write_report(
        tmp_path,
        {
            "custom_components\\heatpump_efficiency\\engine.py": 90.0,
            f"/work/repo/{PACKAGE}sensor.py": 100.0,
        },
        95.0,
    )

    assert gate.main([str(report), "95"]) == 1
    assert "engine.py: 90.00 %" in capsys.readouterr().out


def test_a_report_without_a_file_of_the_integration_fails(tmp_path, capsys):
    """A report that measured nothing of the integration is not a pass."""
    report = write_report(tmp_path, {"tests/test_engine.py": 100.0}, 100.0)

    assert gate.main([str(report), "95"]) == 1
    assert "no file of the integration" in capsys.readouterr().out


def test_the_threshold_is_a_number_and_may_have_decimals(tmp_path):
    """A threshold of 95.5 fails a module at 95.2."""
    report = write_report(tmp_path, {f"{PACKAGE}engine.py": 95.2}, 99.0)

    assert gate.main([str(report), "95"]) == 0
    assert gate.main([str(report), "95.5"]) == 1


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        "{}",
        '{"files": {}}',
        '{"files": [], "totals": {"percent_covered": 90}}',
        '{"files": {"a/custom_components/heatpump_efficiency/x.py": {}}, "totals": {"percent_covered": 90}}',
        '{"files": {"a/custom_components/heatpump_efficiency/x.py": {"summary": {"percent_covered": null}}}, "totals": {"percent_covered": 90}}',
    ],
)
def test_an_unreadable_report_exits_with_2(tmp_path, capsys, content):
    """A file that is not a coverage report in the expected shape exits with 2 and says it cannot be read."""
    report = tmp_path / "coverage.json"
    report.write_text(content, encoding="utf-8")

    assert gate.main([str(report), "95"]) == 2
    assert "cannot be read" in capsys.readouterr().out


def test_a_missing_report_exits_with_2(tmp_path, capsys):
    """A report path that does not exist exits with 2."""
    assert gate.main([str(tmp_path / "missing.json"), "95"]) == 2
    assert "cannot be read" in capsys.readouterr().out


def test_a_threshold_that_is_not_a_number_is_a_usage_error(tmp_path):
    """A bad command line is rejected by the parser, which exits with 2."""
    report = write_report(tmp_path, {f"{PACKAGE}engine.py": 100.0}, 100.0)

    with pytest.raises(SystemExit) as raised:
        gate.main([str(report), "many"])

    assert raised.value.code == 2


def test_script_uses_only_the_standard_library():
    """The coverage gate imports only the standard library."""
    tree = ast.parse(
        (ROOT / "scripts" / "coverage_gate.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import is not standard library"
            roots = [node.module.split(".")[0]]
        else:
            continue
        for root in roots:
            assert root in sys.stdlib_module_names
