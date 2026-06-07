"""Run local verification checks for Image Curator."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_TARGETS = [
    "app.py",
    "curate.py",
    "image_curator",
    "ai_curate",
    "tests",
    "scripts",
]
COMPILE_TARGETS = ["app.py", "curate.py", "image_curator", "ai_curate"]


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]
    requires: str | None = None


def _python_module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def _format_command_display(command: list[str]) -> str:
    """Render a command list for the terminal without exposing absolute paths.

    Absolute paths (e.g. ``sys.executable``) are replaced with their basename so
    the printed command does not leak the user's home directory, pyenv location,
    or similar host-specific prefixes. Relative tokens are passed through.
    """
    display: list[str] = []
    for token in command:
        if Path(token).is_absolute():
            display.append(Path(token).name)
        else:
            display.append(token)
    return " ".join(display)


def _all_checks() -> dict[str, Check]:
    return {
        "ruff-format-check": Check(
            "ruff-format-check",
            _python_module("ruff", "format", "--check", *PYTHON_TARGETS),
        ),
        "ruff-check": Check(
            "ruff-check",
            _python_module("ruff", "check", *PYTHON_TARGETS),
        ),
        "ruff-format": Check(
            "ruff-format",
            _python_module("ruff", "format", *PYTHON_TARGETS),
        ),
        "compileall": Check(
            "compileall",
            _python_module("compileall", *COMPILE_TARGETS),
        ),
        "mypy": Check(
            "mypy",
            _python_module("mypy", *PYTHON_TARGETS),
            requires="mypy",
        ),
        "unit-tests": Check(
            "unit-tests",
            _python_module("pytest", "tests/unit"),
        ),
        "component-tests": Check(
            "component-tests",
            _python_module("pytest", "tests/component"),
        ),
        "integration-tests": Check(
            "integration-tests",
            _python_module("pytest", "tests/integration"),
        ),
        "javascript-syntax": Check(
            "javascript-syntax",
            ["node", "--check", "static/js/app.js"],
            requires="node",
        ),
        "git-diff-check": Check(
            "git-diff-check",
            ["git", "diff", "--check"],
            requires="git",
        ),
    }


def build_checks(mode: str = "default", skip_js: bool = False) -> list[Check]:
    checks = _all_checks()
    mode_names = {
        "quick": ["compileall", "unit-tests", "javascript-syntax"],
        "default": [
            "ruff-format-check",
            "compileall",
            "unit-tests",
            "component-tests",
            "integration-tests",
            "javascript-syntax",
            "git-diff-check",
        ],
        "full": [
            "ruff-format-check",
            "ruff-check",
            "compileall",
            "unit-tests",
            "component-tests",
            "integration-tests",
            "javascript-syntax",
            "git-diff-check",
            "mypy",
        ],
        "format": ["ruff-format"],
    }[mode]
    selected = [checks[name] for name in mode_names]
    if skip_js:
        selected = [check for check in selected if check.name != "javascript-syntax"]
    return selected


def run_check(check: Check, quiet: bool = False) -> int:
    if check.requires and shutil.which(check.requires) is None:
        print(
            f"SKIP/FAIL {check.name}: required executable not found: {check.requires}",
            flush=True,
        )
        return 127

    print(f"\n==> {check.name}", flush=True)
    if not quiet:
        print("$ " + _format_command_display(check.command), flush=True)
    completed = subprocess.run(check.command, cwd=REPO_ROOT)
    return completed.returncode


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="Run fast edit-loop checks")
    mode.add_argument("--full", action="store_true", help="Run the full local check suite")
    mode.add_argument("--format", action="store_true", help="Apply Ruff formatting and exit")
    parser.add_argument(
        "--skip-js", action="store_true", help="Skip frontend JavaScript syntax checks"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the '$ ...' command echo for each check (still prints the check name banner)",
    )
    return parser.parse_args(argv)


def mode_from_args(args: argparse.Namespace) -> str:
    if args.quick:
        return "quick"
    if args.full:
        return "full"
    if args.format:
        return "format"
    return "default"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    mode = mode_from_args(args)
    checks = build_checks(mode=mode, skip_js=args.skip_js)

    passed: list[str] = []
    for check in checks:
        status = run_check(check, quiet=args.quiet)
        if status != 0:
            print("\nVerification failed")
            print(f"- Failed check: {check.name}")
            print(f"- Passed checks: {', '.join(passed) if passed else 'none'}")
            return status
        passed.append(check.name)

    print("\nVerification passed")
    print(f"- Mode: {mode}")
    print(f"- Checks: {', '.join(passed)}")
    if args.skip_js:
        print("- Skipped: javascript-syntax")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
