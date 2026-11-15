import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_batch_sidebar_peek_lifecycle_executes_real_sources():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for batch peek lifecycle regression")
    result = subprocess.run(
        [node, str(ROOT / "tests/unit/batch_sidebar_peek_lifecycle_test.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "batch sidebar peek lifecycle checks passed" in result.stdout


def test_peek_reuses_navigation_and_has_accessible_touch_disclosure():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/css/sidebar.css").read_text(encoding="utf-8")
    assert html.count('id="batch-list"') == 1
    assert 'id="batch-peek-trigger"' in html
    assert 'aria-label="Peek at batches" aria-controls="batch-sidebar"' in html
    assert 'aria-label="Dismiss batch peek"' in html
    assert ".sidebar.collapsed.peek-open" in css
    assert "@media (pointer: coarse)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
