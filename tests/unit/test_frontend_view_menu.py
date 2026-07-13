from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def test_toolbar_separates_stage_navigation_primary_actions_and_view_settings() -> None:
    html = read_index_html()

    assert 'class="workspace-toolbar-primary"' in html
    assert 'class="workspace-primary-actions"' in html
    assert 'class="workspace-sort-group"' in html
    assert 'class="workspace-view-control"' in html
    assert html.index('id="folder-tabs"') < html.index('class="workspace-toolbar-primary"')
    assert html.index('id="browse-mode-btn"') < html.index('id="view-menu-button"')
    assert html.index('id="sort-controls"') < html.index('id="view-menu-button"')


def test_view_disclosure_has_native_trigger_options_panel_and_active_summary() -> None:
    html = read_index_html()

    assert 'id="view-menu-button"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="view-menu"' in html
    assert 'aria-label="View options"' in html
    assert 'id="view-menu" class="view-menu" role="group" aria-label="View options" hidden' in html
    assert 'id="view-summary" class="view-summary" aria-live="polite"' in html
    assert 'role="menu"' not in html
    assert 'role="menuitemradio"' not in html
    assert 'role="menuitemcheckbox"' not in html


def test_view_menu_preserves_existing_view_control_ids_and_state_semantics() -> None:
    html = read_index_html()

    for control_id in (
        "density-controls",
        "favorites-filter-btn",
        "ai-display-controls",
        "ai-overlay-toggle",
        "ai-filter-mode",
        "sort-btn-score-desc",
    ):
        assert f'id="{control_id}"' in html
    assert 'id="density-controls" role="group" aria-label="Thumbnail density"' in html
    assert 'data-density="compact" type="button" aria-pressed="false"' in html
    assert 'data-density="comfortable" type="button" aria-pressed="true"' in html
    assert 'data-density="large" type="button" aria-pressed="false"' in html
    assert 'id="favorites-filter-btn"' in html and 'aria-pressed="false"' in html
    assert 'id="ai-overlay-toggle" tabindex="-1"' not in html
    assert 'id="ai-filter-mode" class="ai-select ai-select-sm" tabindex="-1"' not in html


def test_view_panel_closes_on_keyboard_exit_outside_pointer_and_escape() -> None:
    js = read_frontend_js()
    open_menu = extract_function_body(js, "function openViewMenu()")
    close_menu = extract_function_body(js, "function closeViewMenu(restoreFocus = false)")
    keydown = extract_function_body(js, "function handleViewPanelKeydown(event)")
    focusout = extract_function_body(js, "function handleViewPanelFocusout()")
    bind = extract_function_body(js, "function initializeViewMenu()")

    assert "trigger.setAttribute('aria-expanded', 'true');" in open_menu
    assert "getViewMenuItems()" in open_menu
    assert "trigger.setAttribute('aria-expanded', 'false');" in close_menu
    assert "if (restoreFocus) trigger.focus();" in close_menu
    assert "if (event.key !== 'Escape') return;" in keydown
    assert "closeViewMenu(true);" in keydown
    assert "requestAnimationFrame(() =>" in focusout
    assert "if (!wrapper.contains(document.activeElement)) closeViewMenu();" in focusout
    assert "if (!menu.hidden && !wrapper.contains(event.target)) closeViewMenu();" in bind
    assert "menu.addEventListener('keydown', handleViewPanelKeydown);" in bind
    assert "wrapper.addEventListener('focusout', handleViewPanelFocusout);" in bind
    assert "setViewMenuItemTabStops" not in js
    assert "moveViewMenuFocus" not in js


def test_view_state_summary_tracks_sort_density_favorites_and_ai() -> None:
    js = read_frontend_js()
    summary = extract_function_body(js, "function updateViewSummary()")

    assert "currentSort" in summary
    assert "currentOrder" in summary
    assert "gridDensity" in summary
    assert "favoritesFilterOn" in summary
    assert "aiShowOverlays" in summary
    assert "aiFilterMode" in summary
    assert "aiActiveRun" in summary
    assert "if (aiShowOverlays) parts.push('AI badges');" in summary
    assert "if (aiFilterMode !== 'all')" in summary
    for signature in (
        "function setSort(sort)",
        "function toggleOrder()",
        "function setGridDensity(density)",
        "function toggleFavoritesFilter()",
        "function aiToggleOverlays()",
        "function aiApplyFilter()",
        "function aiShowHeaderControls(show)",
    ):
        assert "updateViewSummary();" in extract_function_body(js, signature), signature


def test_view_menu_layout_is_anchored_and_narrow_toolbar_stays_intentional() -> None:
    css = read_frontend_css()
    responsive = Path("static/css/responsive.css").read_text(encoding="utf-8")

    assert ".workspace-toolbar-primary" in css
    assert ".workspace-primary-actions" in css
    assert ".view-menu" in css
    assert "position: absolute;" in css
    assert "min-width: 260px;" in css
    assert ".view-menu-item" in css
    assert "min-height: 36px;" in css
    assert "@media (max-width: 1280px)" in responsive
    assert ".workspace-toolbar-primary" in responsive
    assert ".workspace-primary-actions" in responsive
    assert "@media (max-width: 700px)" in responsive
    assert ".view-summary" in responsive


def test_sort_controls_have_semantic_grouping() -> None:
    html = read_index_html()

    assert 'class="workspace-sort-group" role="group" aria-label="Image sorting"' in html


def test_view_menu_script_order_matches_templates_and_source_reader() -> None:
    html = read_index_html()
    source_reader = Path("tests/unit/frontend_source.py").read_text(encoding="utf-8")

    assert '<script src="/static/js/view-menu.js"></script>' in html
    assert html.index("/static/js/ai.js") < html.index("/static/js/view-menu.js")
    assert html.index("/static/js/view-menu.js") < html.index("/static/js/polling.js")
    assert 'Path("static/js/view-menu.js")' in source_reader
