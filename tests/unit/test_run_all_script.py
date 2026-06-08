import importlib.util
import sys
from pathlib import Path


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
        "unit-tests",
        "component-tests",
        "integration-tests",
        "javascript-syntax",
        "git-diff-check",
    ]
    assert checks[0].command[:3] == [sys.executable, "-m", "ruff"]
    # ruff-check is the second check (right after ruff-format-check).
    ruff_check = next(c for c in checks if c.name == "ruff-check")
    assert ruff_check.command[:3] == [sys.executable, "-m", "ruff"]
    assert "check" in ruff_check.command
    assert checks[3].command == [sys.executable, "-m", "pytest", "tests/unit"]


def test_quick_plan_is_smaller_and_can_skip_js():
    run_all = load_run_all_module()

    checks = run_all.build_checks(mode="quick", skip_js=True)
    names = [check.name for check in checks]

    assert names == ["compileall", "unit-tests"]


def test_format_plan_mutates_only_when_requested():
    run_all = load_run_all_module()

    checks = run_all.build_checks(mode="format", skip_js=False)

    assert [check.name for check in checks] == ["ruff-format"]
    assert checks[0].command[:4] == [sys.executable, "-m", "ruff", "format"]


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
