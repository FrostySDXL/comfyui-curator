import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def test_modifier_click_and_shift_range_have_explicit_precedence() -> None:
    js = read_frontend_js()
    click = extract_function_body(js, "function onThumbClick(index, event)")
    toggle = extract_function_body(js, "function toggleSelect(index, event)")

    assert "const modifierSelect = event.ctrlKey || event.metaKey;" in click
    assert "if (selectionMode || modifierSelect || event.shiftKey)" in click
    assert "setSelectionMode(true);" in click
    assert click.index("toggleSelect(index, event);") < click.index("openLightbox(index);")
    assert "if (event.shiftKey && lastSelectIndex >= 0)" in toggle
    assert toggle.index("event.shiftKey") < toggle.index("selectedImages.has(name)")


def test_browse_select_mode_is_visible_accessible_and_state_driven() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'class="selection-mode-control" role="group"' in html
    assert 'id="browse-mode-btn"' in html
    assert 'id="select-mode-btn"' in html
    assert 'aria-pressed="true"' in html
    assert 'aria-pressed="false"' in html
    assert "let selectionMode = false;" in js
    assert "function setSelectionMode(active)" in js
    assert "browseBtn.setAttribute('aria-pressed', selectionMode ? 'false' : 'true');" in js
    assert "selectBtn.setAttribute('aria-pressed', selectionMode ? 'true' : 'false');" in js
    assert "browseModeBtn.addEventListener('click', () => setSelectionMode(false));" in js
    assert "selectModeBtn.addEventListener('click', () => setSelectionMode(true));" in js


def test_selection_mode_resets_on_context_change_move_and_escape() -> None:
    js = read_frontend_js()

    for signature in (
        "function selectBatch(batch)",
        "async function selectFolder(batch, folder)",
        "async function loadUniversalFavorites()",
        "async function loadBatchPublic(batch)",
        "async function loadAllPublic()",
    ):
        assert "resetSelectionState();" in extract_function_body(js, signature), signature

    move = extract_function_body(js, "async function moveBatch(filenames, destination)")
    lightbox_move = extract_function_body(js, "async function moveImage(destination)")
    public_refresh = extract_function_body(js, "async function refreshPublicViewAfterAction()")
    assert "resetSelectionState();" in move
    assert "resetSelectionState();" in lightbox_move
    assert "resetSelectionState();" in public_refresh
    assert (
        "if (e.key === 'Escape' && !lightboxActive && (selectionMode || serverSelection || selectedImages.size > 0))"
        in js
    )
    assert "resetSelectionState();" in js


def test_select_mode_keeps_zero_selection_action_bar_and_accessible_thumbnails() -> None:
    js = read_frontend_js()
    action_bar = extract_function_body(js, "function updateActionBar()")

    assert "if (hasSelection || selectionMode)" in action_bar
    assert "serverSelection.count - serverSelection.excluded.size" in action_bar
    assert "const hasSelection = selectedCount > 0;" in action_bar
    assert "b.disabled = !hasSelection" in action_bar
    assert "select.type = 'button';" in js
    assert "selectBtn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');" in js
    assert (
        "selectBtn.setAttribute('aria-label', `${isSelected ? 'Deselect' : 'Select'} ${img.name}`);"
        in js
    )


def test_selection_visual_refresh_updates_pressed_state_and_accessible_label() -> None:
    js = read_frontend_js()
    visuals = extract_function_body(js, "function updateSelectionVisuals()")

    assert "const fname = thumb.dataset.name;" in visuals
    assert "selectBtn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');" in visuals
    assert (
        "selectBtn.setAttribute('aria-label', `${isSelected ? 'Deselect' : 'Select'} ${fname}`);"
        in visuals
    )


def test_action_bar_limits_live_region_to_selection_count() -> None:
    html = read_index_html()

    assert (
        'class="action-bar" id="action-bar" role="toolbar" aria-label="Selection actions"' in html
    )
    assert 'id="action-bar" aria-live=' not in html
    assert 'class="action-count" id="action-count" aria-live="polite" aria-atomic="true"' in html


def test_action_bar_uses_semantic_surfaces_and_public_action_tokens() -> None:
    css = read_frontend_css()
    grid_css = Path("static/css/grid.css").read_text(encoding="utf-8")

    action_bar_match = re.search(
        r"^\s*\.action-bar\s*\{(?P<body>.*?)\}", grid_css, re.MULTILINE | re.DOTALL
    )
    assert action_bar_match
    action_bar = action_bar_match.group("body")
    assert "background: var(--surface-raised);" in action_bar
    assert "border-top: 1px solid var(--accent-primary);" in action_bar
    assert "color: var(--text-primary);" in css
    assert ".action-btn.action-public" in css
    assert "var(--button-accent-fill)" in css
    assert ".action-btn.action-public-danger" in css
    assert "var(--button-danger-fill)" in css
    assert ".action-btn:disabled" in css
    assert "color: var(--text-disabled);" in css
    assert ".action-btn:hover:not(:disabled)" in css
    assert ".action-btn:focus-visible" in css


def test_typed_selections_disable_incompatible_compare_and_publish_actions() -> None:
    js = read_frontend_js()
    action_bar = extract_function_body(js, "function updateActionBar()")
    publish = extract_function_body(js, "function showPublishModal()")
    lightbox_publish = extract_function_body(js, "function showLightboxPublishModal()")
    sync_lightbox = extract_function_body(js, "function syncLightboxPublicActions()")

    assert "selectedReviewMedia.every(isStillReviewMedia)" in action_bar
    assert "Compare supports still images only" in action_bar
    assert "Prepare Public supports still images only" in action_bar
    assert "getSelectedSourceImages().some(img => !isStillReviewMedia(img))" in publish
    assert "!isStillReviewMedia(img)" in lightbox_publish
    assert (
        "publishBtn.disabled = !activePublicView && !isStillReviewMedia(activeImage)"
        in sync_lightbox
    )
