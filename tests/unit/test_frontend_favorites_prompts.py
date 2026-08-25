from pathlib import Path

INDEX_HTML = Path("templates/index.html")
from tests.unit.frontend_source import read_frontend_js


def test_favorites_frontend_functions_and_virtual_batch_handling_exist():
    source = read_frontend_js()
    for name in (
        "toggleFavorite",
        "toggleFavoritesFilter",
        "toggleLightboxFavorite",
        "updateLightboxFavorite",
        "loadUniversalFavorites",
    ):
        assert f"function {name}(" in source
    assert "__favorites__" in source
    assert "/api/favorites" in source


def test_public_frontend_functions_and_virtual_batch_handling_exist():
    source = read_frontend_js()
    for name in (
        "showPublishModal",
        "hidePublishModal",
        "submitPublicExport",
        "loadBatchPublic",
        "loadAllPublic",
        "updateAllPublicCount",
        "copySelectedPublicCopies",
        "moveSelectedPublicCopies",
        "deleteSelectedPublicCopies",
    ):
        assert f"function {name}(" in source
    assert "__public__" in source
    assert "/api/publish/export" in source
    assert "/api/public" in source


def test_native_mode_all_public_count_request_no_longer_skipped():
    source = read_frontend_js()
    function_source = source.split("async function updateAllPublicCount() {", 1)[1].split(
        "function normalizePublicItems", 1
    )[0]

    assert "if (CURATOR_NATIVE)" not in function_source
    assert "apiGetAllPublic()" in function_source


def test_prompt_history_frontend_functions_exist():
    source = read_frontend_js()
    for name in (
        "showPromptsModal",
        "hidePromptsModal",
        "loadPromptsData",
        "renderPromptsList",
        "updatePromptsFooter",
        "buildPromptIndex",
        "_setPromptsCollapse",
        "_setPromptsSort",
        "_schedulePromptsRender",
        "_selectPromptEntry",
        "_syncPromptSelectionControls",
        "updateScopeChip",
        "updateBuildBtn",
    ):
        assert f"function {name}(" in source
    assert "/api/prompt-history" in source
    # Request token guard pattern mirrors folderRequestToken usage.
    assert "promptsRequestToken" in source
    # Search debounce + render cap are present.
    assert "PROMPTS_RENDER_CAP" in source
    assert "_schedulePromptsRender" in source
    # Search-match highlight + image chip rendering.
    assert "prompts-match" in source
    assert "prompts-image-chip" in source
    assert "copy positive" in source
    assert "buildAllPromptIndexes" in source
    assert "showBuildAllConfirm" in source
    assert "Build All Indexes" in source
    assert "PROMPTS_IMAGES_CAP" in source


def test_prompts_render_timer_is_declared():
    """Verify _promptsRenderTimer is declared (not an implicit global).

    The duplicate-declaration checker only scans explicit `let`/`const`/`var`
    + function declarations, so an undeclared identifier can slip through.
    Pin the declaration to keep the debounce safe.
    """
    source = read_frontend_js()
    assert "let _promptsRenderTimer" in source or "var _promptsRenderTimer" in source


def test_prompts_modal_html_uses_rebuild_index_label_and_aria_live():
    """Verify the stale badge uses Rebuild Index (not "Rebuild") and has aria-live in HTML.

    The aria-live attribute must be present at page load (not just toggled in JS)
    so screen readers monitor the region from initial render.
    """
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="prompts-stale-warning"' in html
    assert 'aria-live="polite"' in html.split('id="prompts-stale-warning"')[1].split(">", 1)[0]
    assert ">Rebuild Index<" in html


def test_prompt_history_keyboard_shortcut_and_aria_wiring():
    html = INDEX_HTML.read_text(encoding="utf-8")
    # The batch filter input must be normally tabbable (no tabindex="-1").
    assert 'id="prompts-batch-filter"' in html
    assert 'id="prompts-batch-filter" type="text" placeholder="All Batches"' in html
    # Sort selector is rendered; aggregate grouping is scope-driven.
    assert 'id="prompts-sort"' in html
    assert 'id="prompts-group-toggle"' not in html
    # Scope chip is rendered.
    assert 'id="prompts-scope-chip"' in html
    # Stale badge has aria-live for screen reader announcements.
    assert 'id="prompts-stale-warning"' in html

    source = read_frontend_js()
    # 'p' shortcut opens the prompt history modal.
    assert "case 'p':" in source
    assert "showPromptsModal();" in source
    # Combobox keyboard parity: Home/End/PageUp/PageDown handled.
    assert "case 'Home':" in source
    assert "case 'End':" in source
    assert "case 'PageDown':" in source
    assert "case 'PageUp':" in source
    # ARIA on selected-prompt controls and committed combobox options.
    assert "aria-pressed" in source
    assert "aria-selected" in source
    # aria-activedescendant wiring for combobox active option.
    assert "aria-activedescendant" in source


def test_prompt_history_help_section_documented():
    html = INDEX_HTML.read_text(encoding="utf-8")
    # Help modal covers unified library search and its prompt-group view.
    assert ">Library Search</h4>" in html
    assert "<strong>Prompt groups</strong>" in html
    # Shortcut entry for opening the modal is documented in Help.
    assert "<strong>P</strong>" in html
    assert "<strong>copy positive</strong>" in html
    assert 'id="prompts-build-all-confirm"' in html


def test_favorites_and_prompts_controls_are_rendered():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="favorites-filter-btn"' in html
    assert 'id="prompts-btn"' in html
    assert 'id="prompts-modal"' in html
    assert 'id="publish-btn"' in html
    assert 'id="publish-modal"' in html
    assert 'data-folder="public"' in html
