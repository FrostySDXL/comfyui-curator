import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def read_curator_html() -> str:
    return Path("templates/curator.html").read_text(encoding="utf-8")


def test_workspace_shell_places_physical_stages_in_local_navigation_rail() -> None:
    html = read_index_html()
    native = read_curator_html()
    css = read_frontend_css()

    for markup in (html, native):
        assert 'class="workspace-frame"' in markup
        assert '<nav class="workspace-stage-rail" aria-label="Batch folders">' in markup
        assert 'class="workspace-column"' in markup
        rail_start = markup.index('class="workspace-stage-rail"')
        tabs_start = markup.index('id="folder-tabs"')
        column_start = markup.index('class="workspace-column"')
        toolbar_start = markup.index('id="workspace-toolbar"')
        workspace_start = markup.index('class="workspace"')
        assert rail_start < tabs_start < column_start < toolbar_start < workspace_start

    assert ".workspace-frame" in css
    assert ".workspace-stage-rail" in css
    assert ".workspace-column" in css
    assert "width: 140px;" in css


def test_stage_rail_drag_feedback_targets_the_destination_not_the_container() -> None:
    js = read_frontend_js()
    events = extract_function_body(js, "function _bindDelegatedEvents()")
    drag_over = extract_function_body(js, "function onDragOver(event, target)")
    drag_leave = extract_function_body(js, "function onDragLeave(event, target)")
    drop = extract_function_body(js, "function onDrop(event, folder, target)")

    assert "if (tab) onDragOver(e, tab);" in events
    assert "if (tab) onDragLeave(e, tab);" in events
    assert "onDrop(e, tab.dataset.folder, tab);" in events
    assert "target.classList.add('drag-over');" in drag_over
    assert "target.classList.remove('drag-over');" in drag_leave
    assert "target.classList.remove('drag-over');" in drop


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
    assert "updateThumbElement(thumb, img, index);" in update_grid_body
    assert "displayIndexByName" in js
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
    loader_start = js.index("async function loadCurrentFolderImages(options = {})")
    folder_loader = js[loader_start : loader_start + 7000]
    assert "if (currentFolder === 'public')" in folder_loader
    assert "await loadBatchPublic(batch);" in folder_loader
    assert (
        "activityComplete(activityId, 'completed', {detail: 'Public folder ready'})"
        in folder_loader
    )


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
    assert "let pendingPublicMoveConfirmDestination = null;" in js
    assert "pendingPublicMoveConfirmDestination = destination;" in js
    assert "Confirm Move" in js
    assert "window.prompt('Copy public copies" not in js
    assert "window.prompt('Move public copies" not in js
    assert "window.confirm(" not in js


def test_public_destination_modal_has_folder_browser_and_shared_history() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="public-destination-history"' in html
    assert 'id="public-destination-browser-list"' in html
    assert 'id="public-destination-up-btn"' in html
    assert 'id="public-destination-refresh-btn"' in html
    assert 'id="public-destination-current-path"' in html
    assert "const PUBLIC_DESTINATION_HISTORY_KEY = 'imageCurator.publicDestinationHistory';" in js
    assert "function getPublicDestinationHistory()" in js
    assert "function savePublicDestinationHistory(destination)" in js
    assert "async function loadPublicDestinationBrowser(path = '')" in js
    assert "function renderPublicDestinationBrowser(data)" in js
    assert "function setPublicDestinationInput(destination)" in js
    assert "apiGetPublicDestinations" in js
    assert "showPublicDestinationModal('copy')" in js
    assert "showPublicDestinationModal('move')" in js
    assert "public-destination-browser" in css
    assert "public-destination-history" in css


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
    html = read_index_html()
    lightbox_body = extract_function_body(js, "function syncLightboxPublicActions()")
    lightbox_publish_body = extract_function_body(js, "function showLightboxPublishModal()")
    destination_body = extract_function_body(js, "async function submitPublicDestinationAction()")

    assert 'id="lightbox-publish-btn"' in html
    assert '<div class="key-hint">P</div>' in html
    assert "function showLightboxPublishModal()" in js
    assert "showLightboxPublishModal();" in js
    assert "case 'p': e.preventDefault(); showLightboxPublishModal(); break;" in js
    assert "isVirtualCollectionView() || isPublicView()" in lightbox_publish_body
    assert "#lightbox-actions .btn-shortlist" in lightbox_body
    assert "#lightbox-actions .btn-finals" in lightbox_body
    assert "#lightbox-actions .btn-reject" in lightbox_body
    assert "#lightbox-publish-btn" in lightbox_body
    assert "isVirtualCollectionView() || isPublicView()" in lightbox_body
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

    assert "modal.querySelector('.help-modal-scroll').scrollTop = 0;" in js
    assert ".help-modal-scroll" in css
    assert "overflow-y: auto;" in css
    assert ".help-modal-content .modal-buttons" in css
    assert "flex-shrink: 0;" in css


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


def test_hidden_main_lightbox_image_stays_out_of_layout_for_typed_media() -> None:
    css = read_frontend_css()

    hidden_rule = re.search(
        r"[^{}]*#lightbox-img\[hidden\][^{}]*\{\s*display:\s*none;\s*\}",
        css,
    )

    assert hidden_rule is not None


def test_lightbox_zoom_has_anchor_pan_and_status_affordances() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="lightbox-zoom-indicator"' in html
    assert "function zoomLightbox(delta, anchorEvent = null)" in js
    assert "zoomLightbox(event.deltaY < 0 ? 0.2 : -0.2, event);" in js
    assert "function startLightboxPan(event)" in js
    assert "function moveLightboxPan(event)" in js
    assert "function endLightboxPan(event)" in js
    assert ".lightbox-zoom-indicator" in css
    assert ".lightbox-image-wrap.panning" in css
    assert ".lightbox-image-wrap.zoomed img" in css
    assert "Drag zoomed images to pan" in html


def test_lightbox_compare_mode_has_two_panes_and_action_bar_entry() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="compare-lightbox-btn"' in html
    assert "Compare in Lightbox" in html
    assert 'id="lightbox-compare"' in html
    assert 'data-compare-pane="0"' in html
    assert 'data-compare-pane="1"' in html
    assert "!serverSelection && selectedCount === 2" in js
    assert (
        "compareBtn.disabled = !(showReviewMove && !serverSelection && selectedCount === 2 && selectedMediaAreStill);"
        in js
    )
    assert "compareBtn.style.display = showReviewMove ? '' : 'none';" in js
    assert ".action-btn.action-compare" in css
    assert ".action-btn.action-compare:disabled" in css
    assert "function getSelectedImagesInDisplayOrder()" in js
    assert "function openCompareLightbox()" in js
    assert "function setLightboxCompareActivePane(paneIndex)" in js
    assert ".lightbox.compare-mode" in css
    assert ".lightbox-compare-pane.active" in css


def test_lightbox_compare_mode_guards_single_image_navigation() -> None:
    js = read_frontend_js()
    navigation_body = extract_function_body(js, "function navigate(delta)")
    scored_body = extract_function_body(js, "function navigateScored(delta)")

    assert "let lightboxCompareMode = false;" in js
    assert "function isLightboxCompareMode()" in js
    assert "function getActiveLightboxImage()" in js
    assert "lightboxCompareMode" in navigation_body
    assert "lightboxCompareMode" in scored_body


def test_lightbox_compare_mode_has_independent_active_pane_zoom() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "let lightboxCompareViewState" in js
    assert "function zoomComparePane(paneIndex, delta, anchorEvent = null)" in js
    assert "function resetComparePaneZoom(paneIndex)" in js
    assert "function getActiveComparePaneIndexFromEvent(event)" in js
    assert "zoomComparePane(lightboxCompareActivePane" in js
    assert "updateCompareZoomIndicator(paneIndex);" in js
    assert "singleIndicator.hidden = false;" in js
    assert ".lightbox-compare-wrap.zoomed" in css
    assert ".lightbox-compare-pane {" in css
    assert "overflow: hidden;" in css
    assert "height: calc(100vh - 190px);" in css


def test_lightbox_compare_active_pane_is_click_sticky_not_hover_driven() -> None:
    js = read_frontend_js()
    events_body = extract_function_body(js, "function _bindDelegatedEvents()")

    assert "lightboxCompare.addEventListener('click'" in events_body
    assert "lightboxCompare.addEventListener('focusin'" in events_body
    assert "lightboxCompare.addEventListener('pointerenter'" not in events_body


def test_lightbox_sticky_compare_pins_active_and_replaces_inactive() -> None:
    html = read_index_html()
    js = read_frontend_js()
    events_body = extract_function_body(js, "function _bindDelegatedEvents()")
    pin_body = extract_function_body(js, "function enableStickyCompareFromCurrentPanes()")

    assert 'id="lightbox-pin-compare-btn"' in html
    assert "Pin A" in html
    assert "let lightboxStickyCompareMode = false;" in js
    assert "let lightboxComparePinnedIndex = -1;" in js
    assert "let lightboxCompareCandidateIndex = -1;" in js
    assert "let lightboxStickyPinnedPane = 0;" in js
    assert "let lightboxStickyCandidatePane = 1;" in js
    assert "function openStickyCompareLightbox()" in js
    assert "function navigateStickyCompare(delta)" in js
    assert "function enableStickyCompareFromCurrentPanes()" in js
    assert (
        "lightboxCompareItems = [lightboxImages[pinnedIndex], lightboxImages[candidateIndex]];"
        in js
    )
    assert "lightboxStickyPinnedPane = lightboxCompareActivePane;" in js
    assert "lightboxStickyCandidatePane = getInactiveComparePaneIndex();" in js
    assert "lightboxCompareItems[lightboxStickyCandidatePane] = lightboxImages[nextIndex];" in js
    assert "setLightboxCompareActivePane(lightboxStickyPinnedPane);" in pin_body
    assert "setLightboxCompareActivePane(lightboxStickyCandidatePane);" not in pin_body
    assert "case '[':\n                    case ']': e.preventDefault(); break;" in js
    assert "case 'c': e.preventDefault(); toggleStickyComparePin(); break;" in js
    assert (
        "case 'arrowleft': e.preventDefault(); if (e.altKey) advanceComparePair(-1); else navigateStickyCompare(-1); break;"
        in js
    )
    assert (
        "case 'arrowright': e.preventDefault(); if (e.altKey) advanceComparePair(1); else navigateStickyCompare(1); break;"
        in js
    )
    assert "btn.id === 'lightbox-pin-compare-btn'" in events_body


def test_compare_mode_panels_overlay_inactive_pane_for_active_image() -> None:
    js = read_frontend_js()
    css = read_frontend_css()
    metadata_body = extract_function_body(js, "function toggleLightboxMetadata()")
    ai_body = extract_function_body(js, "function toggleLightboxAiPanel()")

    assert "function getInactiveComparePaneIndex()" in js
    assert "function positionCompareOverlayPanels()" in js
    assert "function refreshCompareActiveImagePanels()" in js
    assert "function resetLightboxPanelScroll()" in js
    assert "resetLightboxPanelScroll();" in js
    assert "loadLightboxMetadata(img, metadataToken).finally(() => {" in js
    assert "renderLightboxMetadataPanel();" in js
    assert "const bothPanelsOpen" in js
    assert "const bothPanelsOpen = lightboxMetadataOpen && lightboxAiOpen;" in js
    assert "classList.contains('open')" not in extract_function_body(
        js, "function positionCompareOverlayPanels()"
    )
    assert "const splitHeight" in js
    assert metadata_body.index("positionCompareOverlayPanels();") < metadata_body.index(
        "renderLightboxMetadataPanel();"
    )
    assert "positionCompareOverlayPanels();" in metadata_body
    assert "positionCompareOverlayPanels();" in ai_body
    assert "const img = getActiveLightboxImage();" in js
    assert ".lightbox.compare-mode .lightbox-metadata-panel" in css
    assert ".lightbox.compare-mode .lightbox-ai-panel" in css
    assert ".lightbox.compare-mode.compare-panel-overlay-left" in css
    assert ".lightbox.compare-mode.compare-panel-overlay-right" in css


def test_compare_mode_keeps_metadata_ai_visible_and_pin_compare_scoped() -> None:
    js = read_frontend_js()
    sync_body = extract_function_body(js, "function syncLightboxPublicActions()")
    mode_body = extract_function_body(js, "function syncLightboxModeUi()")

    assert "btn.id === 'metadata-toggle-btn'" not in sync_body
    assert "btn.id === 'lightbox-ai-toggle-btn'" not in sync_body
    assert "const pinCompareBtn = document.getElementById('lightbox-pin-compare-btn');" in mode_body
    assert (
        "if (pinCompareBtn) pinCompareBtn.closest('div').style.display = lightboxCompareMode ? '' : 'none';"
        in mode_body
    )
    assert "const singleOnly = label === 'Prev scored' || label === 'Next scored';" in mode_body


def test_select_all_matches_compact_toolbar_button_style() -> None:
    css = read_frontend_css()

    assert ".workspace-select-all-btn" in css
    assert "--toolbar-control-height: 30px;" in css
    assert "height: var(--toolbar-control-height);" in css
    assert "background: transparent;" in css
    assert "color: var(--text-muted);" in css
    assert "font-weight: 600;" in css
