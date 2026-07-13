import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body


INDEX_HTML = Path("templates/index.html")
CURATOR_HTML = Path("templates/curator.html")
PROMPTS_JS = Path("static/js/prompts.js")
PROMPTS_CSS = Path("static/css/prompts.css")
EVENTS_JS = Path("static/js/events.js")
KEYBOARD_JS = Path("static/js/keyboard.js")


def _prompt_markup() -> str:
    html = INDEX_HTML.read_text(encoding="utf-8")
    return html.split('id="prompts-modal"', 1)[1].split('id="settings-modal"', 1)[0]


def _rule_body(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert match, selector
    return match.group("body")


def test_prompt_history_has_split_workbench_structure() -> None:
    markup = _prompt_markup()

    assert 'class="prompts-workbench-header"' in markup
    assert '<h3 id="prompts-modal-title">Prompt History</h3>' in markup
    assert 'class="prompts-workbench-body"' in markup
    assert '<aside class="prompts-control-rail" aria-label="Prompt history controls">' in markup
    assert '<section class="prompts-results-pane"' in markup
    assert 'class="prompts-results-toolbar"' in markup
    assert 'class="prompts-workbench-footer"' in markup
    assert markup.index('class="prompts-control-rail"') < markup.index(
        'class="prompts-results-pane"'
    )
    assert markup.index('id="prompts-search"') < markup.index('id="prompts-list"')


def test_prompt_history_results_use_a_labeled_region_without_another_main() -> None:
    markup = _prompt_markup()

    assert "<main" not in markup
    assert '<section class="prompts-results-pane" aria-label="Prompt history results">' in markup


def test_prompt_history_live_region_is_limited_to_concise_result_status() -> None:
    markup = _prompt_markup()
    status_tag = markup.split('id="prompts-total"', 1)[1].split(">", 1)[0]
    list_tag = markup.split('id="prompts-list"', 1)[1].split(">", 1)[0]

    assert 'aria-live="polite"' in status_tag
    assert "aria-live" not in list_tag


def test_prompt_workbench_preserves_unique_control_contracts() -> None:
    markup = _prompt_markup()
    ids = re.findall(r'id="([^"]+)"', markup)
    assert len(ids) == len(set(ids))

    for control_id in (
        "prompts-scope-chip",
        "prompts-batch-filter",
        "prompts-batch-list",
        "prompts-all-batches-btn",
        "prompts-search",
        "prompts-sort",
        "prompts-group-toggle",
        "prompts-collapse-all",
        "prompts-list",
        "prompts-stale-warning",
        "prompts-rebuild-btn",
        "prompts-total",
        "prompts-built-at",
        "prompts-build-all-confirm",
        "prompts-build-btn",
    ):
        assert markup.count(f'id="{control_id}"') == 1, control_id


def test_prompt_results_render_as_labeled_rows_with_display_only_image_references() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    entry = extract_function_body(source, "function _buildEntry(entry, query)")
    images = extract_function_body(source, "function _buildImageChipList(images)")

    assert "document.createElement('article')" in entry
    assert "prompts-entry-main" in entry
    assert "prompts-field-label" in entry
    assert "Positive prompt" in entry
    assert "prompts-entry-actions" in entry
    assert "prompts-copy-pair" in entry
    assert "prompts-image-references-label" in images
    assert "Image references" in images
    assert "document.createElement('span')" in images
    assert "addEventListener" not in images
    assert "show in grid" not in source.lower()
    assert "open first image" not in source.lower()


def test_prompt_disclosures_remain_native_keyboard_controls() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    action = extract_function_body(source, "function _buildActionChip(label, className, onClick)")
    negative = extract_function_body(source, "function _buildNegativeDisclosure(negText)")
    images = extract_function_body(source, "function _buildImageDisclosure(images)")
    full = extract_function_body(source, "function _buildFullDisclosure(promptText)")

    assert "document.createElement('button')" in action
    assert "btn.type = 'button'" in action
    for disclosure in (negative, images, full):
        assert "aria-expanded" in disclosure


def test_prompt_workbench_collapses_without_horizontal_overflow() -> None:
    css = PROMPTS_CSS.read_text(encoding="utf-8")
    body = _rule_body(css, ".prompts-workbench-body")
    pane = _rule_body(css, ".prompts-results-pane")
    modal = _rule_body(css, ".prompts-modal-content")

    assert "grid-template-columns: 248px minmax(0, 1fr);" in body
    assert "min-width: 0;" in pane
    assert "width: min(1080px, calc(100vw - 32px));" in modal
    assert "overflow: hidden;" in modal
    assert "@media (max-width: 760px)" in css
    assert ".prompts-workbench-body { grid-template-columns: minmax(0, 1fr);" in css
    assert ".prompts-control-rail { border-right: 0;" in css


def test_prompt_workbench_uses_semantic_surfaces_and_accessible_primary_pair() -> None:
    css = PROMPTS_CSS.read_text(encoding="utf-8")

    assert "background: var(--surface-1);" in _rule_body(css, ".prompts-modal-content")
    assert "background: var(--surface-2);" in _rule_body(css, ".prompts-control-rail")
    assert "border-bottom: 1px solid var(--border-subtle);" in _rule_body(css, ".prompts-entry")
    copy_pair = _rule_body(css, ".prompts-copy-pair")
    assert "background: var(--button-accent-fill);" in copy_pair
    assert "color: var(--button-accent-text);" in copy_pair


def test_prompt_build_feedback_is_truthful_and_indeterminate() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    render = extract_function_body(source, "function renderPromptsList()")
    markup = _prompt_markup()

    assert "prompts-spinner" in render
    assert "Building index for" in render
    assert "progress" not in render.lower()
    assert "prompts-progress" not in markup
    assert 'role="progressbar"' not in markup


def test_prompt_state_performance_and_focus_contracts_remain_explicit() -> None:
    prompts = PROMPTS_JS.read_text(encoding="utf-8")
    events = EVENTS_JS.read_text(encoding="utf-8")
    keyboard = KEYBOARD_JS.read_text(encoding="utf-8")

    assert "const PROMPTS_RENDER_CAP = 200;" in prompts
    assert "const PROMPTS_IMAGES_CAP = 20;" in prompts
    assert "}, 180);" in prompts
    assert "promptsRequestToken" in prompts
    assert "localStorage.getItem(PROMPTS_COLLAPSE_KEY)" in prompts
    assert "localStorage.getItem(PROMPTS_SORT_KEY)" in prompts
    assert "localStorage.getItem(PROMPTS_GROUP_KEY)" in prompts
    assert "search.focus()" in prompts
    assert "_trapFocus(modal)" in prompts
    assert "_releaseFocusTrap()" in prompts
    for key in ("ArrowDown", "ArrowUp", "Home", "End", "PageDown", "PageUp", "Enter"):
        assert f"case '{key}':" in events
    assert "case 'Escape':" in events
    assert "hidePromptsModal();" in keyboard


def test_prompt_copy_pair_contract_remains_exact() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    formatter = extract_function_body(source, "function _formatCopyPair(prompt, negative)")

    assert "if (!negative) return prompt;" in formatter
    assert "return `${prompt}\\n\\nNegative: ${negative}`;" in formatter
    assert "copy negative" in source


def test_prompt_template_keeps_exact_native_two_transform_parity() -> None:
    index = INDEX_HTML.read_text(encoding="utf-8")
    curator = CURATOR_HTML.read_text(encoding="utf-8")
    expected = index.replace("/static/", "/curator_static/")
    first_script = expected.index('<script src="')
    expected = (
        expected[:first_script]
        + "<script>window.CURATOR_NATIVE = true;</script>\n    "
        + expected[first_script:]
    )

    assert curator == expected
