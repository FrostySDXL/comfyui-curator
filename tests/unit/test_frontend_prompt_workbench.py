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
        "prompts-search",
        "prompts-sort",
        "prompts-collapse-all",
        "prompts-selection-status",
        "prompts-view-positive",
        "prompts-view-negative",
        "prompts-view-images",
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
    assert "prompts-entry-heading" in entry
    assert "prompts-copy-actions" in entry
    assert "prompts-copy-pair" in entry
    assert "prompts-image-references-label" in images
    assert "Image references" in images
    assert "document.createElement('span')" in images
    assert "addEventListener" not in images
    assert "show in grid" not in source.lower()
    assert "open first image" not in source.lower()


def test_prompt_empty_states_are_compact_contextual_and_cardless() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    css = PROMPTS_CSS.read_text(encoding="utf-8")
    unbuilt = extract_function_body(source, "function _buildEmptyCta(")
    empty_all = extract_function_body(source, "function _buildAllEmptyState()")
    no_matches = extract_function_body(source, "function _buildNoMatchesState(")
    state = _rule_body(css, ".prompts-empty-state")

    assert "prompts-empty-state" in unbuilt
    assert "Build Index for" in unbuilt
    assert "prompts-empty-state" in empty_all
    assert "if (!query)" in no_matches
    assert "No prompts found" in no_matches
    assert 'No prompts match "${query}"' in no_matches
    assert 'No prompts match ""' not in source
    assert "border" not in state
    assert "background" not in state
    assert "padding: 12px 0;" in state


def test_prompt_selection_uses_a_dedicated_keyboard_button_without_option_semantics() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    entry = extract_function_body(source, "function _buildEntry(entry, query)")
    select = extract_function_body(source, "function _selectPromptEntry(")

    assert "prompts-select-entry" in entry
    assert "aria-pressed" in entry
    assert "prompts-entry selected" in source or "classList.add('selected')" in entry
    assert "promptsSelectedEntryKey" in select
    assert "role', 'option" not in entry
    assert "role', 'button" not in entry


def test_prompt_selector_is_compact_legible_and_geometry_stable() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    css = PROMPTS_CSS.read_text(encoding="utf-8")
    entry = extract_function_body(source, "function _buildEntry(entry, query)")
    selector = _rule_body(css, ".prompts-select-entry")

    assert "isSelected ? 'Selected' : 'Select'" in entry
    assert "width: 64px;" in selector
    assert "font-size: var(--type-label);" in selector
    assert "padding: 3px 8px;" in selector


def test_prompt_button_selection_restores_focus_without_row_click_focus_theft() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    entry = extract_function_body(source, "function _buildEntry(entry, query)")
    select = extract_function_body(source, "function _selectPromptEntry(")

    assert "_selectPromptEntry(entryKey);" in entry
    assert "_selectPromptEntry(entryKey, true);" in entry
    assert "restoreFocus = false" in select
    assert "if (!restoreFocus) return;" in select
    assert "#prompts-list .prompts-entry.selected .prompts-select-entry" in select
    assert "selectedButton.focus()" in select
    assert "data-entry-key" not in select


def test_contextual_detail_modes_are_independent_and_survive_positive_rerenders() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    render = extract_function_body(source, "function renderPromptsList()")
    sync = extract_function_body(source, "function _syncPromptSelectionControls()")

    assert "promptsDetailModes" in source
    for mode in ("positive", "negative", "images"):
        assert mode in sync
    assert "promptsSelectedEntryKey" in render
    assert "_syncPromptSelectionControls()" in render
    assert "promptsDetailModes.negative" in source
    assert "promptsDetailModes.images" in source


def test_full_positive_control_reports_effective_global_and_selected_state() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    sync = extract_function_body(source, "function _syncPromptSelectionControls()")
    collapse = extract_function_body(source, "function _setPromptsCollapse(value)")

    assert "const globalPositiveExpanded = !promptsCollapseAll;" in sync
    assert "globalPositiveExpanded || promptsDetailModes.positive" in sync
    assert "mode === 'positive' && globalPositiveExpanded" in sync
    assert "All positive prompts are expanded" in sync
    assert "promptsDetailModes.positive" not in collapse


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

    for selector in (".prompts-negative", ".prompts-image-groups"):
        disclosure = _rule_body(css, selector)
        assert "background: var(--surface-2);" in disclosure
        assert "var(--surface-canvas)" not in disclosure


def test_prompt_copy_actions_have_stable_horizontal_geometry() -> None:
    css = PROMPTS_CSS.read_text(encoding="utf-8")
    entry = _rule_body(css, ".prompts-entry")
    heading = _rule_body(css, ".prompts-entry-heading")
    copies = _rule_body(css, ".prompts-copy-actions")

    assert "grid-template-columns: 64px minmax(0, 1fr);" in entry
    assert "264px" not in entry
    assert "display: flex;" in heading
    assert "align-items: flex-start;" in heading
    assert "justify-content: space-between;" in heading
    assert "flex-wrap: wrap;" in heading
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in copies
    assert "width: 264px;" in copies
    assert "max-width: 100%;" in copies
    assert "flex-shrink: 0;" in copies
    assert ".prompts-copy-placeholder" in css


def test_prompt_copy_actions_share_the_positive_heading_above_all_disclosures() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    entry = extract_function_body(source, "function _buildEntry(entry, query)")

    assert "prompts-entry-heading" in entry
    assert (
        "heading.appendChild(createTextElement('div', 'prompts-field-label', 'Positive prompt'));"
        in entry
    )
    assert "heading.appendChild(copyActions);" in entry
    assert "textWrap.appendChild(heading);" in entry
    assert entry.index("textWrap.appendChild(heading)") < entry.index("textWrap.appendChild(full)")
    assert entry.index("textWrap.appendChild(full)") < entry.index(
        "if (neg) textWrap.appendChild(neg)"
    )
    assert entry.index("if (neg) textWrap.appendChild(neg)") < entry.index(
        "if (imgs) textWrap.appendChild(imgs)"
    )
    assert "prompts-entry-actions" not in entry


def test_prompt_rows_do_not_repeat_batch_labels_and_details_own_variable_height() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    css = PROMPTS_CSS.read_text(encoding="utf-8")
    entry = extract_function_body(source, "function _buildEntry(entry, query)")
    header = _rule_body(css, ".prompts-entry-header")
    main = _rule_body(css, ".prompts-entry-main")

    assert "_buildBatchChip" not in source
    assert "prompts-batch-chip" not in source
    assert ".prompts-batch-chip" not in css
    assert "grid-row: 1 / span 2;" in header
    assert "grid-column: 2;" in main
    assert "card.appendChild(textWrap)" in entry
    assert "card.appendChild(actions)" not in entry


def test_prompt_scope_drives_grouping_and_all_batches_is_a_combobox_option() -> None:
    markup = _prompt_markup()
    source = PROMPTS_JS.read_text(encoding="utf-8")
    dropdown = extract_function_body(source, "function _populatePromptDropdown(filter = '')")
    render = extract_function_body(source, "function renderPromptsList()")

    assert "prompts-all-batches-btn" not in markup
    assert "prompts-group-toggle" not in markup
    assert "PROMPTS_GROUP_KEY" not in source
    assert "promptsGroupByBatch" not in source
    assert "All Batches" in dropdown
    assert "promptsCurrentBatch === ''" in render or "!promptsCurrentBatch" in render
    assert "_entriesByBatch(visible)" in render


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
    assert "PROMPTS_GROUP_KEY" not in prompts
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


def test_prompt_selection_is_preserved_when_visible_and_cleared_when_absent() -> None:
    source = PROMPTS_JS.read_text(encoding="utf-8")
    render = extract_function_body(source, "function renderPromptsList()")
    commit = extract_function_body(source, "function _commitPromptSelection(batch)")

    assert "promptsSelectedEntryKey" in render
    assert "visible" in render
    assert "promptsSelectedEntryKey = null" in render
    assert "promptsSelectedEntryKey = null" in commit


def test_positive_expansion_label_is_explicit_and_context_details_are_not_reset() -> None:
    markup = _prompt_markup()
    events = EVENTS_JS.read_text(encoding="utf-8")
    collapse_binding = events.split(
        "const promptsCollapseBtn = document.getElementById('prompts-collapse-all');", 1
    )[1].split("[['prompts-view-positive'", 1)[0]

    assert "positive prompts" in markup.lower()
    assert "positive prompts" in collapse_binding.lower()
    assert "promptsDetailModes" not in collapse_binding


def test_prompt_responsive_layout_keeps_copy_actions_and_context_controls_usable() -> None:
    css = PROMPTS_CSS.read_text(encoding="utf-8")

    assert "@media (max-width: 760px)" in css
    assert ".prompts-workbench-body { grid-template-columns: minmax(0, 1fr);" in css
    assert "@media (max-width: 480px)" in css
    assert (
        ".prompts-entry-heading { flex-direction: column; align-items: stretch; gap: 6px; }" in css
    )
    assert ".prompts-copy-actions { width: 100%; }" in css


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
