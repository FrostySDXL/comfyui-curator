"""Run local verification checks for Image Curator."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections import Counter
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
CSS_FILES = [
    "base.css",
    "sidebar.css",
    "layout.css",
    "grid.css",
    "lightbox.css",
    "modals.css",
    "prompts.css",
    "toast.css",
    "ai.css",
    "responsive.css",
]
JS_FILES = [
    "state.js",
    "dom-utils.js",
    "api.js",
    "sidebar.js",
    "batches.js",
    "grid.js",
    "favorites.js",
    "moves.js",
    "lightbox.js",
    "metadata.js",
    "prompts.js",
    "ai.js",
    "polling.js",
    "events.js",
    "bootstrap.js",
    "app.js",
]


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
        "css-assets": Check(
            "css-assets",
            [sys.executable, "scripts/run_all.py", "--check-css-assets"],
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
            [sys.executable, "scripts/run_all.py", "--check-js-syntax"],
            requires="node",
        ),
        "javascript-duplicate-declarations": Check(
            "javascript-duplicate-declarations",
            [sys.executable, "scripts/run_all.py", "--check-js-duplicates"],
        ),
        "git-diff-check": Check(
            "git-diff-check",
            # Compare against HEAD so the check covers both staged and
            # unstaged changes; ``git diff --check`` alone would only see
            # unstaged working-tree edits and miss whitespace errors in
            # files that have been ``git add``-ed.
            ["git", "diff", "HEAD", "--check"],
            requires="git",
        ),
    }


def build_checks(mode: str = "default", skip_js: bool = False) -> list[Check]:
    checks = _all_checks()
    mode_names = {
        "quick": [
            "compileall",
            "css-assets",
            "unit-tests",
            "javascript-syntax",
            "javascript-duplicate-declarations",
        ],
        "default": [
            "ruff-format-check",
            "ruff-check",
            "compileall",
            "css-assets",
            "unit-tests",
            "component-tests",
            "integration-tests",
            "javascript-syntax",
            "javascript-duplicate-declarations",
            "git-diff-check",
        ],
        "full": [
            "ruff-format-check",
            "ruff-check",
            "compileall",
            "css-assets",
            "unit-tests",
            "component-tests",
            "integration-tests",
            "javascript-syntax",
            "javascript-duplicate-declarations",
            "git-diff-check",
            "mypy",
        ],
        "format": ["ruff-format"],
    }[mode]
    selected = [checks[name] for name in mode_names]
    if skip_js:
        selected = [check for check in selected if not check.name.startswith("javascript-")]
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


def validate_css_assets() -> int:
    css_dir = REPO_ROOT / "static" / "css"
    expected_hrefs = [f"/static/css/{name}" for name in CSS_FILES]

    missing = [name for name in CSS_FILES if not (css_dir / name).is_file()]
    if missing:
        print("Missing CSS files: " + ", ".join(missing), flush=True)
        return 1

    template = (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    hrefs = [
        line.split('href="', 1)[1].split('"', 1)[0]
        for line in template.splitlines()
        if 'rel="stylesheet"' in line and 'href="' in line
    ]
    if hrefs != expected_hrefs:
        print("CSS link order mismatch", flush=True)
        print("Expected: " + ", ".join(expected_hrefs), flush=True)
        print("Actual: " + ", ".join(hrefs), flush=True)
        return 1

    print("CSS assets verified", flush=True)
    print("- Files: " + ", ".join(CSS_FILES), flush=True)
    print("- Template order: OK", flush=True)
    return 0


def _existing_js_paths() -> list[Path]:
    js_dir = REPO_ROOT / "static" / "js"
    return [js_dir / name for name in JS_FILES if (js_dir / name).is_file()]


def validate_js_syntax() -> int:
    paths = _existing_js_paths()
    if not paths:
        print("No JavaScript files found", flush=True)
        return 1

    for path in paths:
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        result = subprocess.run(["node", "--check", rel_path], cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"JavaScript syntax failed: {rel_path}", flush=True)
            return result.returncode

    print("JavaScript syntax verified", flush=True)
    print(
        "- Files: " + ", ".join(path.relative_to(REPO_ROOT).as_posix() for path in paths),
        flush=True,
    )
    return 0


def _top_level_declarations(source: str) -> list[str]:
    declarations: list[str] = []
    depth = 0
    in_string: str | None = None
    in_block_comment = False
    pattern = re.compile(r"^\s*(?:let|const)\s+(.+?);?\s*(?://.*)?$")
    identifier = re.compile(r"^([A-Za-z_$][\w$]*)")
    for line in source.splitlines():
        if depth == 0 and not in_string and not in_block_comment:
            match = pattern.match(line)
            if match:
                for declaration in match.group(1).split(","):
                    name = identifier.match(declaration.strip())
                    if name:
                        declarations.append(name.group(1))
        in_line_comment = False
        escaped = False
        index = 0
        while index < len(line):
            char = line[index]
            next_char = line[index + 1] if index + 1 < len(line) else ""
            if in_line_comment:
                break
            if in_block_comment:
                if char == "*" and next_char == "/":
                    in_block_comment = False
                    index += 2
                    continue
                index += 1
                continue
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = None
                index += 1
                continue
            if char == "/" and next_char == "/":
                in_line_comment = True
            elif char == "/" and next_char == "*":
                in_block_comment = True
            if char in {'"', "'", "`"}:
                in_string = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
            index += 1
    return declarations


def validate_js_duplicate_declarations() -> int:
    paths = _existing_js_paths()
    declarations: list[str] = []
    for path in paths:
        declarations.extend(_top_level_declarations(path.read_text(encoding="utf-8")))

    duplicates = sorted(name for name, count in Counter(declarations).items() if count > 1)
    if duplicates:
        print(
            "Duplicate top-level JS declarations: " + ", ".join(duplicates),
            flush=True,
        )
        return 1

    print("JavaScript duplicate declarations verified", flush=True)
    print(
        "- Files: " + ", ".join(path.relative_to(REPO_ROOT).as_posix() for path in paths),
        flush=True,
    )
    return 0


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
    parser.add_argument(
        "--check-css-assets",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--check-js-syntax",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--check-js-duplicates",
        action="store_true",
        help=argparse.SUPPRESS,
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
    if args.check_css_assets:
        return validate_css_assets()
    if args.check_js_syntax:
        return validate_js_syntax()
    if args.check_js_duplicates:
        return validate_js_duplicate_declarations()

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
        print("- Skipped: javascript-syntax, javascript-duplicate-declarations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
