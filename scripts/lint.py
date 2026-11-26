"""Run every local check of the repository: ruff, the tests in tests/ and a compile check.

Usage: python scripts/lint.py [--fix]

The only program taken from PATH, besides Python, is uv. Every tool runs through uv at an exact version, from the
repository root. With --fix, ruff's fixes and the formatter are applied before the checks. Every step runs, even
after a failure, so that one run shows all findings.

Exit status: 0 when every step passes, 1 when any step fails, 2 when uv is missing or a program cannot be started.

The Home Assistant tests in tests_ha/ are not run here: Home Assistant's test harness does not load on Windows, and
CI runs them in their own job.
"""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import shutil
import subprocess
import sys

RUFF_VERSION = "0.17.3"
PYTEST_VERSION = "9.0.3"
PYTEST_ASYNCIO_VERSION = "1.4.0"
TZDATA_VERSION = "2026.6"
PYTHON = "3.14"

ROOT = Path(__file__).resolve().parents[1]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNAVAILABLE = 2

Runner = Callable[[Sequence[str], Path], int]


def log(message: str) -> None:
    """Print one line of progress, flushed so that it comes before the output of a tool."""
    print(message, flush=True)


def find_uv() -> str | None:
    """Return the path of uv, or None when uv is not on PATH."""
    return shutil.which("uv")


def uv_version(uv: str) -> str:
    """Return the version line of uv.

    Raises:
        OSError: uv cannot be started.
    """
    return subprocess.run(
        [uv, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()


def run(command: Sequence[str], cwd: Path) -> int:
    """Run a command in a folder, print it first, and return its exit code.

    Raises:
        OSError: The program cannot be started.
    """
    log("")
    log("$ " + " ".join(command))
    return subprocess.run(command, cwd=cwd, check=False).returncode


def ruff(uv: str, *arguments: str) -> list[str]:
    """Return the command that runs ruff at its pinned version through uv."""
    return [uv, "tool", "run", f"ruff@{RUFF_VERSION}", *arguments]


def uv_run(uv: str, *arguments: str, packages: Sequence[str] = ()) -> list[str]:
    """Return the command that runs a program on the pinned Python, with packages, through uv."""
    command = [uv, "run", "--no-project", "--python", PYTHON]
    for package in packages:
        command += ["--with", package]
    return [*command, *arguments]


def step_fix(uv: str, runner: Runner, root: Path) -> int:
    """Apply ruff's fixes and the formatter; return the first non-zero exit code, or 0."""
    codes = [
        runner(ruff(uv, "check", "--fix", "."), root),
        runner(ruff(uv, "format", "."), root),
    ]
    return next((code for code in codes if code), EXIT_OK)


def step_check(uv: str, runner: Runner, root: Path) -> int:
    """Run ruff check."""
    return runner(ruff(uv, "check", "."), root)


def step_format(uv: str, runner: Runner, root: Path) -> int:
    """Run ruff format in check mode."""
    return runner(ruff(uv, "format", "--check", "."), root)


def step_tests(uv: str, runner: Runner, root: Path) -> int:
    """Run the tests in tests/ under pytest, in an environment without Home Assistant."""
    packages = (
        f"pytest=={PYTEST_VERSION}",
        f"pytest-asyncio=={PYTEST_ASYNCIO_VERSION}",
        f"tzdata=={TZDATA_VERSION}",
    )
    return runner(uv_run(uv, "pytest", "tests", "-q", packages=packages), root)


def step_compile(uv: str, runner: Runner, root: Path) -> int:
    """Compile every Python folder on the target Python, whichever Python started this script."""
    folders = ("custom_components", "tests", "tests_ha", "scripts")
    return runner(uv_run(uv, "python", "-m", "compileall", "-q", *folders), root)


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = run,
    find: Callable[[], str | None] = find_uv,
    version: Callable[[str], str] = uv_version,
    root: Path = ROOT,
) -> int:
    """Run the steps and return the exit status.

    Args:
        argv: The command-line arguments; None reads sys.argv.
        runner: Runs one command in a folder and returns its exit code; tests inject a fake.
        find: Returns the path of uv, or None; tests inject a fake.
        version: Returns the version line of uv; tests inject a fake.
        root: The repository root, where every step runs.

    Returns:
        0 when every step passes, 1 when any step fails, 2 when uv is missing or a program cannot be started.
    """
    parser = argparse.ArgumentParser(
        description="Run ruff, the tests and the compile check."
    )
    parser.add_argument(
        "--fix", action="store_true", help="apply ruff's fixes and the formatter first"
    )
    arguments = parser.parse_args(argv)

    log(f"Repository root: {root}")
    uv = find()
    if uv is None:
        log(
            "uv is needed to run the checks and was not found on PATH. See https://docs.astral.sh/uv/"
        )
        return EXIT_UNAVAILABLE

    try:
        uv_line = version(uv)
    except OSError as err:
        log(f"uv could not be started: {err}")
        return EXIT_UNAVAILABLE
    log(f"uv: {uv_line or uv}")
    log(
        f"Pins: ruff {RUFF_VERSION}, pytest {PYTEST_VERSION}, pytest-asyncio {PYTEST_ASYNCIO_VERSION}, "
        f"tzdata {TZDATA_VERSION}, Python {PYTHON}"
    )

    steps = [("ruff check", step_check), ("ruff format check", step_format)]
    steps += [("tests", step_tests), ("compile check", step_compile)]
    if arguments.fix:
        steps.insert(0, ("ruff fix and format", step_fix))

    failed = []
    for name, step in steps:
        try:
            code = step(uv, runner, root)
        except OSError as err:
            log(f"{name}: the program could not be started: {err}")
            if failed:
                log("Failed before that: " + ", ".join(failed))
            return EXIT_UNAVAILABLE
        if code:
            failed.append(name)

    log("")
    if failed:
        log("Failed: " + ", ".join(failed))
        return EXIT_FAILED
    log("All checks passed.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
