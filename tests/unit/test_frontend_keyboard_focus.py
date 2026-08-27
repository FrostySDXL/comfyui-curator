from pathlib import Path
import shutil
import subprocess


def test_keyboard_focus_lifecycle_executes_real_frontend_sources():
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node is required for keyboard/focus lifecycle regression")
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, str(repo_root / "tests/unit/keyboard_focus_lifecycle_test.js")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "keyboard focus lifecycle checks passed" in result.stdout
