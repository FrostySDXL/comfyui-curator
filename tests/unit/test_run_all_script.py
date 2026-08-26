import importlib.util
import sys
from pathlib import Path

from tests.unit.frontend_source import CSS_FILES as FRONTEND_CSS_FILES
from tests.unit.frontend_source import JS_FILES as FRONTEND_JS_FILES


def load_run_all_module():
    script_path = Path(__file__).parents[2] / "scripts" / "run_all.py"
    spec = importlib.util.spec_from_file_location("run_all", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["run_all"] = module
    spec.loader.exec_module(module)
    return module


def test_default_plan_uses_python_modules_and_all_test_layers():
    run_all = load_run_all_module()

    checks = run_all.build_checks(mode="default", skip_js=False)
    names = [check.name for check in checks]

    assert names == [
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
    ]
    assert checks[0].command[:3] == [sys.executable, "-m", "ruff"]
    # ruff-check is the second check (right after ruff-format-check).
    ruff_check = next(c for c in checks if c.name == "ruff-check")
    assert ruff_check.command[:3] == [sys.executable, "-m", "ruff"]
    assert "check" in ruff_check.command
    assert checks[3].command == [sys.executable, "scripts/run_all.py", "--check-css-assets"]
    assert checks[4].command == [sys.executable, "-m", "pytest", "tests/unit"]


def test_quick_plan_is_smaller_and_can_skip_js():
    run_all = load_run_all_module()

    checks = run_all.build_checks(mode="quick", skip_js=True)
    names = [check.name for check in checks]

    assert names == ["compileall", "css-assets", "unit-tests"]


def test_quick_plan_includes_all_javascript_checks():
    run_all = load_run_all_module()

    checks = run_all.build_checks(mode="quick", skip_js=False)
    names = [check.name for check in checks]

    assert names[-2:] == ["javascript-syntax", "javascript-duplicate-declarations"]


def test_css_asset_check_validates_expected_files_and_template_order():
    run_all = load_run_all_module()

    assert run_all.CSS_FILES == [
        "base.css",
        "sidebar.css",
        "layout.css",
        "grid.css",
        "lightbox.css",
        "modals.css",
        "prompts.css",
        "toast.css",
        "ai.css",
        "activity-center.css",
        "responsive.css",
    ]
    assert run_all.validate_css_assets() == 0


def test_javascript_checks_use_ordered_split_file_list():
    run_all = load_run_all_module()

    assert run_all.JS_FILES == [
        "state.js",
        "dom-utils.js",
        "api.js",
        "activity-center.js",
        "sidebar.js",
        "batches.js",
        "grid.js",
        "viewport-loader.js",
        "favorites.js",
        "publish.js",
        "moves.js",
        "lightbox.js",
        "metadata.js",
        "prompts.js",
        "ai-state.js",
        "ai-sidebar.js",
        "ai-panel.js",
        "ai-history.js",
        "ai-job.js",
        "ai-inspector.js",
        "ai-overlays.js",
        "ai.js",
        "view-menu.js",
        "polling.js",
        "modals.js",
        "settings.js",
        "combobox.js",
        "keyboard.js",
        "events.js",
        "bootstrap.js",
        "app.js",
    ]


def test_frontend_source_file_lists_match_runner_order():
    run_all = load_run_all_module()

    assert [path.name for path in FRONTEND_JS_FILES] == run_all.JS_FILES
    assert [path.name for path in FRONTEND_CSS_FILES] == run_all.CSS_FILES


def test_template_script_tags_match_ordered_split_file_list():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    script_srcs = [
        line.split('src="', 1)[1].split('"', 1)[0]
        for line in template.splitlines()
        if "<script" in line and 'src="' in line
    ]

    assert script_srcs == [f"/static/js/{path.name}" for path in FRONTEND_JS_FILES]


def test_format_plan_mutates_only_when_requested():
    run_all = load_run_all_module()

    checks = run_all.build_checks(mode="format", skip_js=False)

    assert [check.name for check in checks] == ["ruff-format"]
    assert checks[0].command[:4] == [sys.executable, "-m", "ruff", "format"]


def test_full_plan_includes_mypy():
    run_all = load_run_all_module()

    checks = run_all.build_checks(mode="full", skip_js=False)
    names = [check.name for check in checks]

    # The full plan must include everything the default plan does...
    default_names = [c.name for c in run_all.build_checks(mode="default", skip_js=False)]
    assert all(name in names for name in default_names), (
        f"full plan missing default checks: {set(default_names) - set(names)}"
    )
    # ...and add mypy on top.
    assert "mypy" in names, f"full plan should include mypy, got: {names}"
    # mypy must declare its executable requirement so it is skipped cleanly
    # on hosts where mypy is not installed.
    mypy_check = next(c for c in checks if c.name == "mypy")
    assert mypy_check.requires == "mypy"
    # mypy must be the last (added) check, after the default-plan ordering.
    assert names[-1] == "mypy"
    # mypy must use --explicit-package-bases so hyphenated repo dirnames
    # with a root __init__.py do not cause "not a valid Python package name".
    assert "--explicit-package-bases" in mypy_check.command


def test_format_command_display_basenames_absolute_paths():
    run_all = load_run_all_module()

    command = [sys.executable, "-m", "pytest", "tests/unit"]
    rendered = run_all._format_command_display(command)

    assert sys.executable not in rendered
    assert Path(sys.executable).name in rendered
    # Relative tokens are passed through unchanged.
    assert "-m pytest tests/unit" in rendered


def test_format_command_display_preserves_relative_tokens():
    run_all = load_run_all_module()

    rendered = run_all._format_command_display(["node", "--check", "static/js/app.js"])

    assert rendered == "node --check static/js/app.js"


def test_run_check_echo_uses_basename_by_default(monkeypatch, capsys):
    run_all = load_run_all_module()
    check = run_all.Check(
        "unit-tests",
        [sys.executable, "-m", "pytest", "tests/unit"],
    )

    def fake_run(cmd, **kwargs):
        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(run_all.subprocess, "run", fake_run)

    rc = run_all.run_check(check)
    out = capsys.readouterr().out

    assert rc == 0
    assert "$" in out
    assert sys.executable not in out
    assert Path(sys.executable).name in out
    assert "==> unit-tests" in out


def test_run_check_quiet_suppresses_command_echo(monkeypatch, capsys):
    run_all = load_run_all_module()
    check = run_all.Check(
        "unit-tests",
        [sys.executable, "-m", "pytest", "tests/unit"],
    )

    def fake_run(cmd, **kwargs):
        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(run_all.subprocess, "run", fake_run)

    rc = run_all.run_check(check, quiet=True)
    out = capsys.readouterr().out

    assert rc == 0
    # The check-name banner stays so the operator still sees what's running.
    assert "==> unit-tests" in out
    # The '$ ...' command echo is suppressed entirely.
    assert "$" not in out


def test_parse_args_recognises_quiet_flag():
    run_all = load_run_all_module()

    args = run_all.parse_args(["--quick", "--quiet"])

    assert args.quick is True
    assert args.quiet is True
    assert run_all.mode_from_args(args) == "quick"
