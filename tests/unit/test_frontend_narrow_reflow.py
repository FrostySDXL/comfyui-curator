"""Narrow-viewport reflow invariants for the 200%-equivalent breakpoint."""

import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body

RESPONSIVE_CSS = Path("static/css/responsive.css")
AI_SIDEBAR_JS = Path("static/js/ai-sidebar.js")
ACTIVITY_CSS = Path("static/css/activity-center.css")
LIGHTBOX_CSS = Path("static/css/lightbox.css")
MODALS_CSS = Path("static/css/modals.css")
PROMPTS_CSS = Path("static/css/prompts.css")


def _narrow_block() -> str:
    css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    return css.split("@media (max-width: 900px)", 1)[1].split("@media (max-width: 760px)", 1)[0]


def _rule_body(block: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{(?P<body>.*?)\}", block, re.DOTALL)
    assert match, f"missing rule {selector} in narrow block"
    return match.group("body")


def test_header_actions_wrap_within_narrow_main() -> None:
    assert "flex-wrap: wrap;" in _rule_body(_narrow_block(), ".header-actions")


def test_selection_action_bar_wraps_instead_of_overflowing() -> None:
    block = _narrow_block()
    assert "flex-wrap: wrap;" in _rule_body(block, ".action-bar")
    assert "flex-wrap: wrap;" in _rule_body(block, ".action-group")


def test_narrow_folder_tabs_wrap_instead_of_scrolling_offscreen() -> None:
    body = _rule_body(_narrow_block(), ".folder-tabs.visible")
    assert "flex-direction: row;" in body
    assert "flex-wrap: wrap;" in body


def test_narrow_lightbox_controls_wrap_full_width() -> None:
    body = _rule_body(_narrow_block(), ".lightbox-controls")
    assert "flex-wrap: wrap;" in body
    assert "left: 20px;" in body
    assert "right: 20px;" in body
    assert "transform: none;" in body


def test_narrow_lightbox_nav_arrows_clear_the_control_bar() -> None:
    body = _rule_body(_narrow_block(), ".lightbox-nav")
    assert "top: 50%;" in body
    assert "bottom: auto;" in body
    assert "transform: translateY(-50%);" in body


def test_inspector_overlay_defaults_closed_on_narrow_viewports() -> None:
    js = AI_SIDEBAR_JS.read_text(encoding="utf-8")
    init = extract_function_body(js, "function initializeAiSidebarState()")
    handler = extract_function_body(js, "function onAiSidebarNarrowChange(event)")

    assert "matchMedia('(max-width: 1012px)')" in js
    assert "isAiSidebarNarrowViewport()" in init
    assert "addEventListener('change', onAiSidebarNarrowChange)" in js
    assert "addListener(onAiSidebarNarrowChange)" in js
    assert "aiSidebarOpen = false;" in handler
    assert "syncAiSidebarUi(false)" in handler
    assert "localStorage.setItem" not in handler


def test_narrow_overlays_and_library_search_keep_content_reachable() -> None:
    activity = ACTIVITY_CSS.read_text(encoding="utf-8")
    assert "width: min(390px, calc(100vw - 28px));" in activity
    assert "max-height: min(600px, calc(100vh - 78px));" in activity
    assert ".activity-center-list" in activity
    assert "overflow-y: auto;" in _rule_body(activity, ".activity-center-list")

    modals = MODALS_CSS.read_text(encoding="utf-8")
    history = _rule_body(modals, ".move-history-content")
    assert "width: min(680px, calc(100vw - 32px));" in history
    assert "max-height: calc(100vh - 40px);" in history
    assert "overflow: hidden;" in history
    assert "overflow-y: auto;" in _rule_body(modals, ".move-history-list")

    prompts = PROMPTS_CSS.read_text(encoding="utf-8")
    narrow_prompts = prompts.split("@media (max-width: 760px)", 1)[1]
    assert "width: min(100vw - 16px, 680px);" in narrow_prompts
    assert (
        ".prompts-workbench-body { grid-template-columns: minmax(0, 1fr); overflow-y: auto; }"
        in narrow_prompts
    )
    assert ".prompts-workbench-footer { flex-wrap: wrap; }" in narrow_prompts

    lightbox = LIGHTBOX_CSS.read_text(encoding="utf-8")
    panel = _rule_body(
        lightbox,
        ".lightbox-metadata-panel,\n        .lightbox-ai-panel",
    )
    assert "max-height: calc(100vh - 180px);" in panel
    assert "overflow-y: auto;" in panel


def test_short_narrow_shell_scrolls_rows_with_bounded_grid_viewport() -> None:
    css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    marker = "@media (max-width: 900px) and (max-height: 500px)"
    assert marker in css
    block = css.split(marker, 1)[1].split("@media", 1)[0]

    main = _rule_body(block, ".main")
    assert "overflow-y: auto;" in main
    assert "overflow-x: hidden;" in main

    frame = _rule_body(block, ".workspace-frame")
    assert "flex: 0 0 auto;" in frame

    column = _rule_body(block, ".workspace-column")
    assert "flex: 0 0 auto;" in column
    assert "height: clamp(240px, calc(100vh - 120px), 420px);" in column
    assert "min-height: 0;" in column
