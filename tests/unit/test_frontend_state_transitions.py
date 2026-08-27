"""Executable lifecycle checks for inspector/selection view transitions."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.unit
def test_state_transition_node_lifecycle() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node executable not found")
    script = Path(__file__).with_name("state_transitions_lifecycle_test.js")
    result = subprocess.run([node, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "state transition lifecycle checks passed" in result.stdout
