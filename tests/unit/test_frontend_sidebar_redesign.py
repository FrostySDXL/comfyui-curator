from pathlib import Path

from tests.unit.frontend_source import read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def test_sidebar_controls_use_structured_library_header() -> None:
    html = read_index_html()

    assert 'class="sidebar-library-header"' in html
    assert 'class="sidebar-title-group"' in html
    assert 'class="sidebar-action-row"' in html
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


def test_selected_and_ai_status_have_clear_sidebar_states() -> None:
    css = read_frontend_css()

    assert ".batch-name.selected::before" in css
    assert ".batch-name:hover .batch-breakdown" in css
    assert ".batch-name.selected .batch-breakdown" in css
    assert ".batch-ai-dot" in css
    assert "box-shadow: 0 0 0 3px rgba(0,102,204,0.12)" in css
