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
    selectors: set[str] = set()
    for match in re.finditer(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}", css):
        if declaration in match.group("body"):
            selectors.update(selector.strip() for selector in match.group("selectors").split(","))
    return selectors


def rule_body(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert match, selector
    return match.group("body")


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


def test_forced_colors_preserves_focus_and_operational_state_distinctions() -> None:
    css = Path("static/css/responsive.css").read_text(encoding="utf-8")
    assert css.count("@media (forced-colors: active)") == 1
    forced = css.split("@media (forced-colors: active)", 1)[1]

    for system_color in (
        "Canvas",
        "CanvasText",
        "ButtonText",
        "Highlight",
        "HighlightText",
        "GrayText",
        "LinkText",
    ):
        assert system_color in forced

    assert ":where(button, input, select, textarea, [tabindex]):focus-visible" in forced
    assert "outline: 3px solid Highlight;" in forced
    assert ".folder-tab.active" in forced
    assert ".thumb.selected" in forced
    assert ".thumb.inspected" in forced
    assert ".action-bar" in forced
    assert ".action-btn:disabled" in forced
    assert ".thumbnail-error" in forced
    assert ".activity-failed" in forced
    assert ".activity-partial" in forced
    assert ".lightbox-controls" in forced
    assert "box-shadow: none;" in forced
    assert "forced-color-adjust" not in forced


def test_operational_states_have_distinct_non_color_visual_grammar() -> None:
    """Keep location, selection, inspection, focus, and compare states legible together."""
    base = read_base_css()
    grid = Path("static/css/grid.css").read_text(encoding="utf-8")
    layout = Path("static/css/layout.css").read_text(encoding="utf-8")
    lightbox = Path("static/css/lightbox.css").read_text(encoding="utf-8")
    lightbox_js = Path("static/js/lightbox.js").read_text(encoding="utf-8")

    assert "--inspection-ring:" in base
    focus = rule_body(base, ":where(button, input, select, textarea, [tabindex]):focus-visible")
    assert "outline: var(--focus-ring-width) solid var(--focus-ring);" in focus
    assert "outline-offset: var(--focus-ring-offset);" in focus
    assert "z-index:" in focus

    location = rule_body(layout, ".folder-tab.active::before")
    assert "content:" in location
    assert "box-shadow: inset" in location

    selected = rule_body(grid, ".thumb.selected::before")
    assert "border:" in selected
    select_control = rule_body(grid, ".thumb-select.selected")
    assert "background: var(--accent-primary);" in select_control
    assert ".thumb-select.selected svg" in grid

    inspected = rule_body(grid, ".thumb.inspected")
    assert "outline: 2px dashed var(--inspection-ring);" in inspected
    focused_thumb = rule_body(grid, ".thumb:focus-visible")
    assert "outline: var(--focus-ring-width) solid var(--focus-ring);" in focused_thumb
    assert "outline-offset: var(--focus-ring-offset);" in focused_thumb

    compare = rule_body(lightbox, ".lightbox-compare-pane.active::before")
    assert "content: 'ACTIVE';" in compare
    assert "border:" in compare
    active_label = rule_body(lightbox, ".lightbox-compare-pane.active .lightbox-compare-label")
    assert "padding-left: 72px;" in active_label
    assert "aria-selected" in lightbox_js


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
        ".media-search-chip",
    }
    assert "font-size: 9px;" not in css


def test_visible_text_does_not_use_legacy_low_contrast_grays() -> None:
    css = read_frontend_css()

    assert not re.search(r"(?:^|[;{])\s*color:\s*#(?:555|666|777)\b", css, re.MULTILINE)


def test_help_actions_share_the_modal_surface() -> None:
    css = Path("static/css/modals.css").read_text(encoding="utf-8")
    footer = rule_body(css, ".help-modal-content .modal-buttons")

    assert "background: var(--surface-2);" in footer
    assert "border-top: 1px solid var(--border-subtle);" in footer
    assert "#252525" not in footer


def test_help_footer_is_outside_dedicated_scroll_region() -> None:
    html = Path("templates/index.html").read_text(encoding="utf-8")
    css = Path("static/css/modals.css").read_text(encoding="utf-8")
    js = Path("static/js/modals.js").read_text(encoding="utf-8")
    help_markup = html.split('id="help-modal"', 1)[1].split('id="prompts-modal"', 1)[0]

    scroll_start = help_markup.index('class="help-modal-scroll"')
    footer_start = help_markup.index('class="modal-buttons"')
    assert scroll_start < footer_start
    assert '</div>\n            <div class="modal-buttons">' in help_markup

    content = rule_body(css, ".help-modal-content")
    scroll = rule_body(css, ".help-modal-scroll")
    footer = rule_body(css, ".help-modal-content .modal-buttons")
    assert "overflow: hidden;" in content
    assert "overflow-y: auto;" in scroll
    assert "flex-shrink: 0;" in footer
    assert "position: sticky;" not in footer
    assert "modal.querySelector('.help-modal-scroll').scrollTop = 0;" in js


def test_prompt_history_uses_cohesive_semantic_surface_layers() -> None:
    css = Path("static/css/prompts.css").read_text(encoding="utf-8")
    expected_layers = {
        ".prompts-modal-content": (
            "background: var(--surface-1);",
            "border-color: var(--border-strong);",
        ),
        ".prompts-controls": ("background: var(--surface-2);",),
        ".prompts-control-rail": (
            "background: var(--surface-2);",
            "border-right: 1px solid var(--border-subtle);",
        ),
        ".prompts-batch-list": (
            "background: var(--surface-raised);",
            "border: 1px solid var(--border-strong);",
        ),
        ".prompts-entry": (
            "background: var(--surface-2);",
            "border-bottom: 1px solid var(--border-subtle);",
        ),
        ".prompts-action-chip": (
            "background: var(--surface-raised);",
            "color: var(--text-secondary);",
        ),
        ".prompts-negative": (
            "background: var(--surface-2);",
            "border: 1px solid var(--border-subtle);",
        ),
        ".prompts-image-groups": (
            "background: var(--surface-2);",
            "border: 1px solid var(--border-subtle);",
        ),
        ".prompts-empty-state": ("color: var(--text-secondary);",),
        ".prompts-workbench-footer": (
            "border-top: 1px solid var(--border-subtle);",
            "background: var(--surface-2);",
        ),
        ".prompts-footer": ("color: var(--text-muted);",),
    }

    for selector, declarations in expected_layers.items():
        body = rule_body(css, selector)
        for declaration in declarations:
            assert declaration in body, selector


def test_prompt_history_keyboard_option_focus_is_visually_distinct() -> None:
    css = Path("static/css/prompts.css").read_text(encoding="utf-8")
    list_body = rule_body(css, ".prompts-batch-list")
    focus_body = rule_body(css, ".prompts-batch-option.focus")

    list_background = re.search(r"background:\s*([^;]+);", list_body)
    focus_background = re.search(r"background:\s*([^;]+);", focus_body)
    assert list_background and focus_background
    assert focus_background.group(1) != list_background.group(1)
    assert "background: var(--accent-surface);" in focus_body
    assert "box-shadow: inset 3px 0 0 var(--accent-primary);" in focus_body


def test_prompt_history_primary_and_cancel_actions_use_control_tokens() -> None:
    css = Path("static/css/prompts.css").read_text(encoding="utf-8")

    body = rule_body(css, ".prompts-primary-action")
    assert "background: var(--button-accent-fill);" in body
    assert "color: var(--button-accent-text);" in body

    hover = rule_body(css, ".prompts-primary-action:hover")
    assert "background: var(--button-accent-fill);" in hover
    assert "filter: brightness(0.88);" in hover

    cancel = rule_body(css, "#prompts-build-all-cancel-btn")
    assert "background: var(--surface-raised);" in cancel
    assert "border: 1px solid var(--border-strong);" in cancel
    assert "color: var(--text-secondary);" in cancel


def test_lightbox_metadata_and_ai_panels_share_a_semantic_panel_family() -> None:
    css = Path("static/css/lightbox.css").read_text(encoding="utf-8")

    shared_shell = rule_body(css, ".lightbox-metadata-panel,\n        .lightbox-ai-panel")
    assert "background: var(--surface-overlay);" in shared_shell
    assert "border: 1px solid var(--border-strong);" in shared_shell
    assert "color: var(--text-secondary);" in shared_shell
    assert "scrollbar-gutter: stable;" in shared_shell

    header = rule_body(css, ".metadata-header")
    assert "position: sticky;" in header
    assert "background: var(--surface-overlay);" in header
    assert "border-bottom: 1px solid var(--border-subtle);" in header

    metadata_field = rule_body(css, ".metadata-field")
    assert "background: var(--surface-2);" in metadata_field
    assert "border: 1px solid var(--border-subtle);" in metadata_field

    ai_header = rule_body(css, ".lightbox-ai-panel .ai-inspector-header")
    assert "background: var(--surface-2);" in ai_header
    assert "border: 1px solid var(--border-subtle);" in ai_header

    ai_empty = rule_body(css, ".lightbox-ai-panel .ai-image-inspector-empty")
    assert "background: var(--surface-2);" in ai_empty
    assert "color: var(--text-muted);" in ai_empty
