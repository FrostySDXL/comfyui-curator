"""Intermediate 901-1279px reflow invariants for the uncovered desktop range."""

import re
from pathlib import Path

RESPONSIVE_CSS = Path("static/css/responsive.css")


def _block(max_width: int) -> str:
    css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    marker = f"@media (max-width: {max_width}px) and (min-width: 901px)"
    assert marker in css, f"missing intermediate block {marker}"
    return css.split(marker, 1)[1].split("@media", 1)[0]


def _rule_body(block: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{(?P<body>.*?)\}", block, re.DOTALL)
    assert match, f"missing rule {selector} in intermediate block"
    return match.group("body")


def test_header_and_selection_surfaces_wrap_below_1280() -> None:
    block = _block(1279)
    assert "min-width: 200px;" in _rule_body(block, ".workspace-context")
    assert "flex-wrap: wrap;" in _rule_body(block, ".header-actions")
    assert "flex-wrap: wrap;" in _rule_body(block, ".action-bar")
    assert "flex-wrap: wrap;" in _rule_body(block, ".action-group")


def test_lightbox_controls_wrap_below_1100() -> None:
    body = _rule_body(_block(1100), ".lightbox-controls")
    assert "left: 20px;" in body
    assert "right: 20px;" in body
    assert "transform: none;" in body
    assert "flex-wrap: wrap;" in body
    nav = _rule_body(_block(1100), ".lightbox-nav")
    assert "top: 50%;" in nav
    assert "bottom: auto;" in nav
    assert "transform: translateY(-50%);" in nav
