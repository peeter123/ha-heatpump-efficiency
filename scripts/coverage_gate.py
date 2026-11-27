"""Fail when the integration, or one of its modules, is below a coverage threshold.

Usage: python scripts/coverage_gate.py REPORT THRESHOLD

REPORT is the JSON report of coverage.py (``coverage json -o coverage.json``) and THRESHOLD a percentage, for
example 95. Only the files under ``custom_components/heatpump_efficiency/`` count as modules, so a stray file is never
checked as a module; the total is coverage's own and counts every measured file, which the ``--cov`` path source limits to
the integration. The total of the report and every one of those files must reach the threshold. Coverage's own
``fail_under`` checks the total only, and the Home Assistant quality scale rule names every module.

Standard library only: it reads ``files`` (a ``summary`` with ``percent_covered`` per path) and ``totals`` (the same
``summary`` keys) of the report (coverage.py documentation, "JSON reporting").

Exit status: 0 when the total and every module reach the threshold, 1 when one does not (each module below it is
printed with its percentage, and the total) or when the report has no file of the integration, 2 when the report
cannot be read.
"""

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

SCOPE = "/custom_components/heatpump_efficiency/"

EXIT_OK = 0
EXIT_BELOW = 1
EXIT_UNREADABLE = 2


def log(message: str) -> None:
    """Print one line, flushed so that it comes before the output of a tool."""
    print(message, flush=True)


def in_scope(path: str) -> bool:
    """Whether a path of the report is a file of the integration (either kind of path separator)."""
    return SCOPE in "/" + path.replace("\\", "/")


def read_report(path: Path) -> tuple[dict[str, float], float]:
    """Return the percentage of each integration file and the total of a coverage JSON report.

    Raises:
        OSError: The file cannot be read.
        ValueError: The file is not JSON.
        KeyError: The report has no ``files`` or ``totals`` or a ``summary``.
        TypeError: A part of the report has another type than coverage.py writes.
        AttributeError: ``files`` is not a mapping.
    """
    report = json.loads(path.read_text(encoding="utf-8"))
    files = {
        name: float(entry["summary"]["percent_covered"])
        for name, entry in report["files"].items()
        if in_scope(name)
    }
    return files, float(report["totals"]["percent_covered"])


def main(argv: Sequence[str] | None = None) -> int:
    """Check a coverage report against a threshold and return the exit status.

    Args:
        argv: The command-line arguments (the report path and the threshold); None reads sys.argv.

    Returns:
        0 when the total and every module reach the threshold, 1 when one does not, 2 when the report cannot be read.
    """
    parser = argparse.ArgumentParser(
        description="Fail when the integration or one of its modules is below a coverage threshold."
    )
    parser.add_argument("report", type=Path, help="the JSON report of coverage.py")
    parser.add_argument(
        "threshold", type=float, help="the least percentage, for example 95"
    )
    arguments = parser.parse_args(argv)

    try:
        files, total = read_report(arguments.report)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
        log(f"The coverage report {arguments.report} cannot be read: {err!r}")
        return EXIT_UNREADABLE

    threshold = arguments.threshold
    if not files:
        log(f"The coverage report {arguments.report} has no file of the integration.")
        return EXIT_BELOW
    below = sorted(name for name, percent in files.items() if percent < threshold)
    for name in below:
        log(f"{name}: {files[name]:.2f} % is below {threshold:g} %")
    log(f"Total: {total:.2f} %, threshold {threshold:g} %")
    if below or total < threshold:
        if total < threshold:
            log(f"The total is below {threshold:g} %")
        return EXIT_BELOW
    log("Every module and the total reach the threshold.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
