import re
from pathlib import Path

from tests.unit.frontend_source import read_frontend_css


def read_base_css() -> str:
    return Path("static/css/base.css").read_text(encoding="utf-8")


def parse_root_tokens(css: str) -> dict[str, str]:
    root = re.search(r":root\s*\{(?P<body>.*?)\}", css, re.DOTALL)
    assert root
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", root.group("body")))


def relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def selectors_with_declaration(css: str, declaration: str) -> set[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    selectors = set()
    for match in re.finditer(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}", css):
        if declaration in match.group("body"):
            selectors.update(selector.strip() for selector in match.group("selectors").split(","))
    return selectors


def test_dark_theme_exposes_semantic_visual_tokens() -> None:
    base = read_base_css()

    required_tokens = {
        "surface-0",
        "surface-1",
        "surface-2",
        "surface-raised",
        "text-primary",
        "text-secondary",
        "text-muted",
        "text-disabled",
        "border-subtle",
        "border-strong",
        "accent-primary",
        "focus-ring",
        "success",
        "warning",
        "danger",
    }

    for token in required_tokens:
        assert f"--{token}:" in base
    assert "color-scheme: dark;" in base


def test_keyboard_focus_uses_a_shared_focus_visible_ring() -> None:
    css = read_frontend_css()
    base = read_base_css()

    assert ":where(button, input, select, textarea, [tabindex]):focus-visible" in base
    assert "outline: var(--focus-ring-width) solid var(--focus-ring);" in base
    assert "outline-offset: var(--focus-ring-offset);" in base
    assert not re.search(r"(?<!-):focus\s*\{[^}]*outline:\s*none", css, re.DOTALL)


def test_core_operational_labels_keep_a_readable_type_floor() -> None:
    css = read_frontend_css()

    selectors = (
        ".context-kicker",
        ".folder-tab-label",
        ".sidebar h2",
        ".ai-curate-advisory",
        ".metadata-label",
        ".key-hint",
    )
    for selector in selectors:
        rule = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
        assert rule, f"missing rule for {selector}"
        size = re.search(r"font-size:\s*(?:(\d+)px|var\(--type-label\))", rule.group("body"))
        assert size, f"missing readable type size in {selector}"
        assert not size.group(1) or int(size.group(1)) >= 11, (
            f"undersized operational text in {selector}"
        )


def test_primary_surfaces_and_states_consume_semantic_tokens() -> None:
    css = read_frontend_css()

    assert "body {" in css and "background: var(--surface-0);" in css
    assert ".sidebar {" in css and "background: var(--surface-1);" in css
    assert ".content {" in css and "background: var(--surface-canvas);" in css
    assert "color: var(--text-secondary);" in css
    assert "var(--success)" in css
    assert "var(--warning)" in css
    assert "var(--danger)" in css


def test_filled_semantic_button_pairs_meet_wcag_aa() -> None:
    tokens = parse_root_tokens(read_base_css())

    for role in ("accent", "success", "warning", "danger"):
        foreground = tokens[f"button-{role}-text"]
        background = tokens[f"button-{role}-fill"]
        assert contrast_ratio(foreground, background) >= 4.5, role


def test_semantic_button_fills_use_their_accessible_foreground_token() -> None:
    css = re.sub(r"/\*.*?\*/", "", read_frontend_css(), flags=re.DOTALL)

    for role in ("accent", "success", "warning", "danger"):
        fill = f"background: var(--button-{role}-fill);"
        text = f"color: var(--button-{role}-text);"
        matching_rules = [
            match.group("body")
            for match in re.finditer(r"[^{}]+\{(?P<body>[^{}]*)\}", css)
            if fill in match.group("body")
        ]
        assert matching_rules, role
        assert all(text in body for body in matching_rules), role


def test_only_nonessential_badges_use_compact_10px_text() -> None:
    css = read_frontend_css()
    compact_selectors = selectors_with_declaration(css, "font-size: 10px;")

    assert compact_selectors == {
        ".ai-run-badge",
        ".shortcut-hint",
        ".thumb .ai-score-badge",
        ".prompts-count-label",
        ".prompts-image-chip",
    }
    assert "font-size: 9px;" not in css


def test_visible_text_does_not_use_legacy_low_contrast_grays() -> None:
    css = read_frontend_css()

    assert not re.search(r"(?:^|[;{])\s*color:\s*#(?:555|666|777)\b", css, re.MULTILINE)
