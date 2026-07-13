import re
from pathlib import Path

from tests.unit.frontend_source import read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def rule_body(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert match, selector
    return match.group("body")


def test_sidebar_controls_use_structured_library_header() -> None:
    html = read_index_html()

    assert 'class="sidebar-library-header"' in html
    assert 'class="sidebar-title-group"' in html
    assert 'class="sidebar-action-row"' in html
    assert 'data-bsort="ai"' in html
    assert 'style="margin-bottom:0;"' not in html
    assert 'style="border-color:#2a2a2a;"' not in html


def test_batch_rows_render_titles_breakdowns_and_count_pills() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "function formatBatchBreakdown(counts)" in js
    assert "batchTitle.className = 'batch-title';" in js
    assert "breakdown.className = 'batch-breakdown';" in js
    assert "countSpan.className = 'batch-count batch-count-pill';" in js
    assert "inbox" in js and "shortlisted" in js and "finals" in js and "rejects" in js
    assert ".batch-title" in css
    assert ".batch-breakdown" in css
    assert ".batch-count-pill" in css


def test_all_favorites_entry_reads_as_pinned_collection() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "favTitle.className = 'batch-title batch-favorites-title';" in js
    assert "favTitle.textContent = '★ All Favorites';" in js
    assert "favSubtitle.className = 'batch-breakdown batch-favorites-subtitle';" in js
    assert "favSubtitle.textContent = 'Universal review set';" in js
    assert ".batch-item-favorites .batch-name" in css
    assert ".batch-favorites-title" in css


def test_all_public_entry_reads_as_pinned_generated_collection() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "publicDiv.dataset.batch = '__public__';" in js
    assert "publicTitle.textContent = 'All Public';" in js
    assert "publicSubtitle.textContent = 'Generated posting copies';" in js
    assert "id = 'all-public-count'" in js
    assert ".batch-item-public .batch-name" in css
    assert ".batch-public-title" in css


def test_selected_and_ai_status_have_clear_sidebar_states() -> None:
    css = read_frontend_css()

    assert ".batch-name.selected::before" in css
    assert ".batch-name:hover .batch-breakdown" in css
    assert ".batch-name.selected .batch-breakdown" in css
    assert ".batch-ai-dot" in css
    assert "sortByAiHistory" in read_frontend_js()
    assert "batchSort === 'ai'" in read_frontend_js()
    assert "box-shadow: 0 0 0 3px rgba(0,102,204,0.12)" in css


def test_sidebar_microcopy_stays_single_line_when_narrow() -> None:
    css = read_frontend_css()

    assert ".sidebar-subtitle" in css
    assert "white-space: nowrap;" in css
    assert "text-overflow: ellipsis;" in css


def test_batch_library_header_wraps_before_overlapping_sort_buttons() -> None:
    css = read_frontend_css()

    assert ".sidebar-library-header" in css
    assert "flex-wrap: wrap;" in css
    assert "align-items: flex-start;" in css
    assert ".sidebar-title-group" in css
    assert "flex: 1 1 78px;" in css
    assert ".sidebar-title-group h2" in css
    assert "overflow: hidden;" in css
    assert ".batch-sort-group" in css
    assert "max-width: 100%;" in css


def test_workspace_sort_geometry_does_not_leak_into_batch_sort_controls() -> None:
    layout = Path("static/css/layout.css").read_text(encoding="utf-8")

    assert re.search(r"(?m)^\s*\.sort-btn\s*\{", layout) is None
    assert re.search(r"(?m)^\s*\.sort-group\s*,", layout) is None
    assert ".workspace-toolbar .sort-btn" in layout
    assert ".workspace-toolbar .sort-group" in layout


def test_batch_sort_buttons_have_comfortable_segmented_geometry() -> None:
    css = Path("static/css/sidebar.css").read_text(encoding="utf-8")
    group = rule_body(css, ".batch-sort-group")
    button = rule_body(css, ".batch-sort-btn")

    assert "height: 30px;" in group
    assert "border: 1px solid var(--border-subtle);" in group
    assert "height: 100%;" in button
    assert "padding: 0 9px;" in button
    assert "line-height: 1;" in button
    assert ".batch-sort-btn:hover" in css
    assert ".batch-sort-btn.active" in css
    assert ".batch-sort-btn:focus-visible" in css


def test_batch_library_region_uses_cohesive_semantic_sidebar_surfaces() -> None:
    css = Path("static/css/sidebar.css").read_text(encoding="utf-8")
    batches = rule_body(css, ".sidebar-batches")
    controls = rule_body(css, ".batch-controls")
    search = rule_body(css, ".batch-search")
    batch_list = rule_body(css, ".batch-list")

    assert "background: var(--surface-1);" in batches
    assert "background: var(--surface-1);" in controls
    assert "border-bottom: 1px solid var(--border-subtle);" in controls
    assert "background: var(--surface-2);" in search
    assert "border: 1px solid var(--border-subtle);" in search
    assert "background: var(--surface-1);" in batch_list
    assert "#202020" not in controls
