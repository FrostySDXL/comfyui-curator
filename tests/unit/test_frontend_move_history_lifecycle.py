from pathlib import Path
import shutil
import subprocess


def test_move_history_and_drag_lifecycle_executes_real_sources():
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node is required for frontend lifecycle regression")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, str(root / "tests/unit/move_history_lifecycle_test.js")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "move history and drag lifecycle checks passed" in result.stdout
