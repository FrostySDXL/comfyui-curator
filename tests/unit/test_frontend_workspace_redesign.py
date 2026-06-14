from pathlib import Path

from tests.unit.frontend_source import read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def test_workspace_toolbar_groups_review_controls() -> None:
    html = read_index_html()

    assert 'class="workspace-toolbar"' in html
    assert 'class="workspace-context"' in html
    assert 'id="current-folder-label"' not in html
    assert html.index('id="folder-tabs"') < html.index('id="sort-controls"')
    assert html.index('id="sort-controls"') < html.index('id="ai-display-controls"')


def test_grid_density_controls_are_persistent_and_class_backed() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="density-controls"' in html
    assert 'data-density="compact"' in html
    assert 'data-density="comfortable"' in html
    assert 'data-density="large"' in html
    assert ".grid.density-compact" in css
    assert ".grid.density-comfortable" in css
    assert ".grid.density-large" in css
    assert "const GRID_DENSITY_KEY = 'imageCurator.gridDensity';" in js
    assert "function initializeGridDensity()" in js
    assert "function setGridDensity(density)" in js
    assert "localStorage.setItem(GRID_DENSITY_KEY, gridDensity);" in js


def test_grid_empty_states_distinguish_filters_and_empty_folders() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "function getGridEmptyStateMessage()" in js
    assert "No favorite images in this view" in js
    assert "No images match the active AI filter" in js
    assert "No images in this folder" in js
    assert "grid.classList.add('is-empty');" in js
    assert "grid.classList.remove('is-empty');" in js
    assert ".grid.is-empty" in css
    assert ".grid.is-empty .empty" in css
    assert ".empty-title" in css
    assert ".empty-detail" in css


def test_thumbnail_cards_expose_metadata_and_state_layers() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "meta.className = 'thumb-meta';" in js
    assert "meta.innerHTML = '<span class=\"meta-name\"></span><span class=\"meta-detail\"></span>';" in js
    assert "if (metaSize) metaSize.textContent =" in js
    assert ".thumb::after" in css
    assert ".thumb.selected::before" in css
    assert ".thumb .favorite-star.active" in css


def test_all_favorites_sorts_without_folder_api_reload() -> None:
    js = read_frontend_js()

    assert "function sortImagesForDisplay(imgList)" in js
    assert "currentBatch === '__favorites__'" in js
    assert "return sortImagesForDisplay(filtered);" in js
    assert "if (currentBatch === '__favorites__') { updateGrid(); return; }" in js


def test_sidebar_resize_disables_layout_transitions() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "document.body.classList.toggle('resizing-layout', active);" in js
    assert "document.body.classList.add('resizing-layout');" in js
    assert "document.body.classList.remove('resizing-layout');" in js
    assert "body.resizing-layout .thumb" in css
    assert "body.resizing-layout .sidebar" in css
    assert "body.resizing-layout .ai-sidebar-shell" in css
    assert "body.resizing-layout .grid" in css
    assert "transition: none !important;" in css
    assert "pointer-events: none;" in css


def test_grid_density_uses_fixed_columns_to_avoid_sidebar_snap() -> None:
    css = read_frontend_css()

    assert "repeat(var(--grid-columns, 1), var(--grid-track-size, 180px))" in css
    assert "--grid-track-size: 138px;" in css
    assert "--grid-track-size: 180px;" in css
    assert "--grid-track-size: 250px;" in css
    assert "grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));" not in css


def test_grid_padding_stays_symmetric_with_or_without_ai_sidebar() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert ".content { flex: 1; padding: 14px 18px 18px;" in css
    assert "body.ai-sidebar-open .content { padding-right: 10px; }" not in css
    assert "document.body.classList.toggle('ai-sidebar-open', currentBatch && aiSidebarOpen);" in js


def test_toolbar_controls_stay_right_aligned_without_folder_tabs() -> None:
    css = read_frontend_css()

    assert ".sort-controls" in css
    assert "margin-left: auto;" in css


def test_help_modal_resets_scroll_and_keeps_actions_visible() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "modal.querySelector('.modal-content').scrollTop = 0;" in js
    assert ".help-modal-content .modal-buttons" in css
    assert "position: sticky;" in css
    assert "bottom: -25px;" in css


def test_help_and_prompts_modals_close_on_backdrop_click() -> None:
    js = read_frontend_js()

    assert "function closeModalOnBackdropClick(event, hideFn)" in js
    assert "if (event.target !== event.currentTarget) return;" in js
    assert "helpModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hideHelpModal); });" in js
    assert "promptsModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hidePromptsModal); });" in js


def test_workspace_select_all_button_selects_displayed_images() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="workspace-select-all-btn"' in html
    assert 'class="workspace-select-all-btn"' in html
    assert "function selectAllDisplayedImages()" in js
    assert "const displayedNames = getDisplayImages().map(img => img.name);" in js
    assert "const allDisplayedSelected = displayedNames.length > 0 && displayedNames.every(name => selectedImages.has(name));" in js
    assert "selectedImages = allDisplayedSelected ? new Set() : new Set(displayedNames);" in js
    assert "lastSelectIndex = images.length - 1;" in js
    assert "updateSelectionVisuals();" in js
    assert "updateActionBar();" in js
    assert "selectAllBtn.addEventListener('click', selectAllDisplayedImages);" in js
    assert ".workspace-select-all-btn" in css


def test_action_bar_selection_adds_scroll_clearance_to_ai_panel() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "document.body.classList.add('has-active-selection');" in js
    assert "document.body.classList.remove('has-active-selection');" in js
    assert "body.has-active-selection .ai-curate-body" in css
    assert "padding-bottom: 92px;" in css


def test_lightbox_navigation_sits_below_metadata_panels() -> None:
    css = read_frontend_css()

    assert ".lightbox-nav" in css
    assert "top: auto;" in css
    assert "bottom: 20px;" in css
    assert "transform: none;" in css
    assert ".lightbox-nav.prev { left: 20px; }" in css
    assert ".lightbox-nav.next { right: 20px; }" in css


def test_select_all_matches_compact_toolbar_button_style() -> None:
    css = read_frontend_css()

    assert ".workspace-select-all-btn" in css
    assert "height: 28px;" in css
    assert "background: transparent;" in css
    assert "color: #666;" in css
    assert "font-weight: 600;" in css
