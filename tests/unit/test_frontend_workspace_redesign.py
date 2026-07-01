from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


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


def test_public_views_have_specific_empty_states_and_followup_action() -> None:
    js = read_frontend_js()
    html = read_index_html()

    assert "No public copies yet" in js
    assert "No generated public copies" in js
    assert "Select images from inbox, shortlisted, or finals" in js
    assert "Public copies appear here after you prepare selected originals" in js
    assert "function viewCreatedPublicCopies()" in js
    assert 'id="publish-view-public-btn"' in html
    assert "publish-view-public-btn" in js


def test_initial_no_batch_grid_has_stable_empty_layout() -> None:
    html = read_index_html()

    assert 'id="grid" class="grid is-empty"' in html
    assert '<div class="empty-title">Select a batch</div>' in html
    assert (
        '<div class="empty-detail">Choose a batch from the sidebar to begin reviewing images.</div>'
        in html
    )


def test_thumbnail_cards_expose_metadata_and_state_layers() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "meta.className = 'thumb-meta';" in js
    assert (
        'meta.innerHTML = \'<span class="meta-name"></span><span class="meta-detail"></span>\';'
        in js
    )
    assert "if (metaSize) metaSize.textContent =" in js
    assert ".thumb::after" in css
    assert ".thumb.selected::before" in css
    assert ".thumb .favorite-star.active" in css


def test_all_favorites_sorts_without_folder_api_reload() -> None:
    js = read_frontend_js()

    assert "function sortImagesForDisplay(imgList)" in js
    assert "currentBatch === '__favorites__'" in js
    assert "return sortImagesForDisplay(filtered);" in js
    assert "if (isVirtualCollectionView() || isPublicView()) { updateGrid(); return; }" in js


def test_lightbox_navigation_uses_display_order_for_virtual_collections() -> None:
    js = read_frontend_js()
    update_grid_body = extract_function_body(js, "function updateGrid()")
    lightbox_body = extract_function_body(js, "function showCurrentImage()")
    navigation_body = extract_function_body(js, "function navigate(delta)")
    info_body = extract_function_body(js, "function updateLightboxInfo(img, w, h)")

    assert "function getLightboxImages()" in js
    assert "function getImageDisplayIndexByName(name)" in js
    assert "const displayIndex = getImageDisplayIndexByName(img.name);" in update_grid_body
    assert "updateThumbElement(thumb, img, displayIndex);" in update_grid_body
    assert "const lightboxImages = getLightboxImages();" in lightbox_body
    assert "const img = lightboxImages[currentIndex];" in lightbox_body
    assert "const lightboxImages = getLightboxImages();" in navigation_body
    assert (
        "currentIndex = (currentIndex + delta + lightboxImages.length) % lightboxImages.length;"
        in navigation_body
    )
    assert "${currentIndex+1} / ${getLightboxImages().length}" in info_body


def test_public_views_sort_without_review_folder_api_reload() -> None:
    js = read_frontend_js()

    assert "function isPublicView()" in js
    assert "currentBatch === '__public__'" in js
    assert "if (isVirtualCollectionView() || isPublicView()) { updateGrid(); return; }" in js
    assert "if (currentFolder === 'public') { await loadBatchPublic(batch); return; }" in js


def test_public_actions_replace_review_moves_in_public_views() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'id="public-copy-btn"' in html
    assert 'id="public-move-btn"' in html
    assert 'id="public-delete-btn"' in html
    assert "const showPublicActions = isPublicView();" in js
    assert "const showReviewMove = !isVirtualCollectionView() && !isPublicView()" in js


def test_public_action_bar_groups_review_and_public_actions() -> None:
    html = read_index_html()
    css = read_frontend_css()

    assert 'class="action-group action-group-review"' in html
    assert 'class="action-group action-group-public"' in html
    assert ".action-group" in css
    assert ".action-divider" in css


def test_public_export_refreshes_batch_counts() -> None:
    js = read_frontend_js()
    body = extract_function_body(js, "async function submitPublicExport()")

    assert "await loadBatches();" in body


def test_public_export_modal_guides_watermark_and_next_step() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="publish-source-summary"' in html
    assert 'id="publish-watermark-options"' in html
    assert 'id="publish-watermark-warning"' in html
    assert 'id="publish-watermark-black"' in html
    assert 'id="publish-reset-watermark-btn"' in html
    assert "function syncPublishWatermarkFields()" in js
    assert "function resetPublishWatermarkDefaults()" in js
    assert "function updatePublishSourceSummary()" in js
    assert (
        "color: document.getElementById('publish-watermark-black').checked ? 'black' : 'white'"
        in js
    )
    assert "publish-watermark-options.disabled" in css
    assert "publish-result" in css


def test_public_external_actions_use_destination_modal_not_browser_prompt() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'id="public-destination-modal"' in html
    assert 'id="public-destination-input"' in html
    assert "function showPublicDestinationModal(" in js
    assert "function submitPublicDestinationAction()" in js
    assert "window.prompt('Copy public copies" not in js
    assert "window.prompt('Move public copies" not in js


def test_public_delete_uses_confirmation_modal_not_browser_popup() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'id="public-delete-modal"' in html
    assert 'id="public-delete-count"' in html
    assert 'id="public-delete-confirm-btn"' in html
    assert "function showPublicDeleteModal()" in js
    assert "function hidePublicDeleteModal()" in js
    assert "async function confirmPublicDelete()" in js
    assert "window.confirm('Delete selected public copies" not in js


def test_public_posting_help_section_documents_safety_contracts() -> None:
    html = read_index_html()

    assert "<h4>Public Posting</h4>" in html
    assert "Prepare Public Copies" in html
    assert "Original review images are never modified" in html
    assert "All Public" in html
    assert "IMAGE_CURATOR_PUBLIC_EXPORTS" in html


def test_public_modal_escape_and_focus_release_paths_exist() -> None:
    js = read_frontend_js()
    publish_hide = extract_function_body(js, "function hidePublishModal()")
    destination_hide = extract_function_body(js, "function hidePublicDestinationModal()")

    assert "document.getElementById('publish-modal').classList.contains('active')" in js
    assert "document.getElementById('public-destination-modal').classList.contains('active')" in js
    assert "hidePublishModal();" in js
    assert "hidePublicDestinationModal();" in js
    assert "_releaseFocusTrap();" in publish_hide
    assert "_releaseFocusTrap();" in destination_hide


def test_public_helpers_load_before_grid_consumers() -> None:
    state = Path("static/js/state.js").read_text(encoding="utf-8")
    publish = Path("static/js/publish.js").read_text(encoding="utf-8")

    assert "function isVirtualCollectionView()" in state
    assert "function isPublicView()" in state
    assert "function isVirtualCollectionView()" not in publish
    assert "function isPublicView()" not in publish


def test_lightbox_public_actions_and_copy_count_refresh_are_guarded() -> None:
    js = read_frontend_js()
    lightbox_body = extract_function_body(js, "function syncLightboxPublicActions()")
    destination_body = extract_function_body(js, "async function submitPublicDestinationAction()")

    assert "#lightbox-actions .btn-shortlist" in lightbox_body
    assert "#lightbox-actions .btn-finals" in lightbox_body
    assert "#lightbox-actions .btn-reject" in lightbox_body
    assert "await updateAllPublicCount();" in destination_body


def test_all_public_count_updates_batch_public_tab_counts() -> None:
    js = read_frontend_js()
    body = extract_function_body(js, "async function updateAllPublicCount()")

    assert "allCounts[item.batch].public = (allCounts[item.batch].public || 0) + 1;" in body
    assert "if (currentBatch && !isVirtualCollectionView()) updateFolderTabs();" in body


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
    assert (
        "helpModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hideHelpModal); });"
        in js
    )
    assert (
        "promptsModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hidePromptsModal); });"
        in js
    )


def test_workspace_select_all_button_selects_displayed_images() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="workspace-select-all-btn"' in html
    assert 'class="workspace-select-all-btn"' in html
    assert "function selectAllDisplayedImages()" in js
    assert "const displayedNames = getDisplayImages().map(img => img.name);" in js
    assert (
        "const allDisplayedSelected = displayedNames.length > 0 && displayedNames.every(name => selectedImages.has(name));"
        in js
    )
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
