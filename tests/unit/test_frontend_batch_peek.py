import re
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


def test_peek_exposes_shared_sort_controls_in_a_separate_compact_header_row():
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/css/sidebar.css").read_text(encoding="utf-8")
    for sort in ("alpha", "count", "recent", "ai"):
        assert html.count(f'data-bsort="{sort}"') == 1
        assert re.search(rf'<button\b[^>]*data-bsort="{sort}"', html)
    # A selector in a comma-separated hiding rule must not hide the shared group.
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if ".sidebar.collapsed .batch-sort-group" in selectors:
            assert "display: none" not in body
            assert "width: 100%;" in body
    header = re.search(r"\.sidebar\.collapsed \.sidebar-library-header\s*\{([^}]+)\}", css)
    assert header is not None
    assert "grid-template-columns: minmax(0, 1fr);" in header[1]
    title = re.search(r"\.sidebar\.collapsed \.sidebar-title-group\s*\{([^}]+)\}", css)
    assert title is not None
    assert "padding-right: 40px;" in title[1]
    assert "min-height: 32px;" in title[1]
