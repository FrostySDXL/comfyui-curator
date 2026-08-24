import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def read_curator_html() -> str:
    return Path("templates/curator.html").read_text(encoding="utf-8")


def rule_body(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert match, selector
    return match.group("body")


def test_toolbar_separates_stage_navigation_primary_actions_and_view_settings() -> None:
    html = read_index_html()

    assert 'class="workspace-toolbar-primary"' in html
    assert 'class="workspace-primary-actions"' in html
    assert 'class="workspace-sort-group"' in html
    assert 'class="workspace-view-control"' in html
    assert html.index('id="folder-tabs"') < html.index('class="workspace-toolbar-primary"')
    assert html.index('id="browse-mode-btn"') < html.index('id="view-menu-button"')
    assert html.index('id="sort-controls"') < html.index('id="view-menu-button"')


def test_desktop_toolbar_is_one_compact_row_with_controls_pushed_right() -> None:
    css = Path("static/css/layout.css").read_text(encoding="utf-8")
    toolbar = rule_body(css, ".workspace-toolbar")
    tabs = rule_body(css, ".folder-tabs")
    primary = rule_body(css, ".workspace-toolbar-primary")

    assert "flex-direction: row;" in toolbar
    assert "align-items: center;" in toolbar
    assert "flex-wrap: wrap;" in toolbar
    assert "min-height: 48px;" in toolbar
    assert "flex: 1 1 560px;" in tabs
    assert "min-width: min(560px, 100%);" in tabs
    assert "width: 100%;" not in tabs
    assert "margin-left: auto;" in primary
    assert "flex-shrink: 0;" in primary


def test_toolbar_wraps_from_available_width_without_waiting_for_viewport_breakpoint() -> None:
    layout = Path("static/css/layout.css").read_text(encoding="utf-8")
    responsive = Path("static/css/responsive.css").read_text(encoding="utf-8")

    assert "flex-wrap: wrap;" in rule_body(layout, ".workspace-toolbar")
    assert ".workspace-toolbar { flex-wrap: wrap; }" not in responsive
    assert "@media (max-width: 900px)" in responsive
    narrow_toolbar = responsive.split("@media (max-width: 900px)", 1)[1]
    assert "flex-direction: column;" in narrow_toolbar


def test_view_disclosure_has_native_trigger_and_options_panel() -> None:
    html = read_index_html()

    assert 'id="view-menu-button"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="view-menu"' in html
    assert 'aria-label="View options"' in html
    assert 'id="view-menu" class="view-menu" role="group" aria-label="View options" hidden' in html
    assert 'id="view-summary"' not in html
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


def test_view_menu_persists_lightbox_video_autoplay_and_loop_preference() -> None:
    for html in (read_index_html(), read_curator_html()):
        assert 'id="lightbox-video-autoplay-loop-toggle" checked' in html
        assert "Autoplay + loop lightbox videos" in html

    state = Path("static/js/state.js").read_text(encoding="utf-8")
    events = Path("static/js/events.js").read_text(encoding="utf-8")
    lightbox = Path("static/js/lightbox.js").read_text(encoding="utf-8")

    assert (
        "const LIGHTBOX_VIDEO_AUTOPLAY_LOOP_KEY = 'imageCurator.lightboxVideoAutoplayLoop';"
        in state
    )
    assert (
        "let lightboxVideoAutoplayLoopEnabled = "
        "localStorage.getItem(LIGHTBOX_VIDEO_AUTOPLAY_LOOP_KEY) !== 'false';"
    ) in state
    assert "videoPlaybackToggle.checked = lightboxVideoAutoplayLoopEnabled;" in events
    assert "setLightboxVideoAutoplayLoopEnabled(videoPlaybackToggle.checked);" in events
    setter = extract_function_body(
        lightbox,
        "function setLightboxVideoAutoplayLoopEnabled(enabled)",
    )
    assert "localStorage.setItem(LIGHTBOX_VIDEO_AUTOPLAY_LOOP_KEY" in setter
    assert "video.autoplay = lightboxVideoAutoplayLoopEnabled;" in setter
    assert "video.loop = lightboxVideoAutoplayLoopEnabled;" in setter


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
    prevent_default = keydown.index("event.preventDefault();")
    stop_propagation = keydown.index("event.stopPropagation();")
    close_and_restore = keydown.index("closeViewMenu(true);")
    assert prevent_default < stop_propagation < close_and_restore
    assert "requestAnimationFrame(() =>" in focusout
    assert "if (!wrapper.contains(document.activeElement)) closeViewMenu();" in focusout
    assert "if (!menu.hidden && !wrapper.contains(event.target)) closeViewMenu();" in bind
    assert "menu.addEventListener('keydown', handleViewPanelKeydown);" in bind
    assert "wrapper.addEventListener('focusout', handleViewPanelFocusout);" in bind
    assert "setViewMenuItemTabStops" not in js
    assert "moveViewMenuFocus" not in js


def test_redundant_view_summary_is_removed_from_markup_behavior_and_docs() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()
    static_readme = Path("static/README.md").read_text(encoding="utf-8")

    assert "view-summary" not in html
    assert "view-summary" not in css
    assert "updateViewSummary" not in js
    assert "summary beside it" not in html
    toolbar_docs = static_readme.split("The workspace toolbar", 1)[1].split("\n-", 1)[0]
    assert "summary" not in toolbar_docs
    assert "active-setting summary" not in static_readme


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
    assert "@media (max-width: 1280px)" not in responsive
    assert "@media (max-width: 900px)" in responsive
    assert ".workspace-primary-actions" in responsive
    assert "@media (max-width: 700px)" in responsive
    assert ".view-summary" not in responsive


def test_toolbar_controls_share_one_compact_geometry_token() -> None:
    css = Path("static/css/layout.css").read_text(encoding="utf-8")
    toolbar = rule_body(css, ".workspace-toolbar")

    assert "--toolbar-control-height: 30px;" in toolbar
    for selector in (".workspace-select-all-btn", ".sort-dir", ".view-menu-button"):
        body = rule_body(css, selector)
        assert "height: var(--toolbar-control-height);" in body, selector

    for selector in (".workspace-select-all-btn", ".sort-dir", ".view-menu-button"):
        body = rule_body(css, selector)
        assert "border-radius: var(--toolbar-control-radius);" in body, selector

    segmented = rule_body(
        css,
        ".workspace-toolbar .sort-group,\n        .selection-mode-control,\n        .density-controls",
    )
    assert "height: var(--toolbar-control-height);" in segmented
    assert "border-radius: var(--toolbar-control-radius);" in segmented
    for selector in (".selection-mode-btn", ".sort-btn", ".density-btn"):
        assert "height: 100%;" in rule_body(css, selector), selector


def test_view_panel_uses_subtle_surfaces_and_quiet_setting_rows() -> None:
    css = Path("static/css/layout.css").read_text(encoding="utf-8")
    panel = rule_body(css, ".view-menu")
    section = rule_body(css, ".view-menu-section")
    favorite = rule_body(css, ".favorites-filter-btn")

    assert "border: 1px solid var(--border-subtle);" in panel
    assert "background: var(--surface-2);" in panel
    assert "border-bottom: 1px solid var(--border-subtle);" in section
    assert "border: 1px solid" not in favorite
    assert "background: transparent;" in favorite
    assert (
        ".workspace-toolbar .sort-group,\n        .selection-mode-control,\n        .density-controls"
        in css
    )


def test_density_segments_are_exempt_from_quiet_row_minimum_height() -> None:
    css = Path("static/css/layout.css").read_text(encoding="utf-8")
    density = rule_body(css, ".density-btn")
    quiet_row = rule_body(css, ".view-menu-item:not(.density-btn)")

    assert ".view-menu-item { min-height: 36px; }" not in css
    assert "min-height: 0;" in density
    assert "height: 100%;" in density
    assert "min-height: 36px;" in quiet_row


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
