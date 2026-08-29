"""Narrow-viewport reflow invariants for the 200%-equivalent breakpoint."""

import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body

RESPONSIVE_CSS = Path("static/css/responsive.css")
AI_SIDEBAR_JS = Path("static/js/ai-sidebar.js")


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
