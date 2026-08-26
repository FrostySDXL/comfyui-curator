/* Ordered classic script.
 * Defines: delegated browser event bindings.
 */

        // Delegated click handler for batch items (XSS-safe, no inline onclick)
        document.addEventListener('DOMContentLoaded', () => {
            const batchList = document.getElementById('batch-list');
            if (batchList) {
                batchList.addEventListener('click', (e) => {
                    const batchNameEl = e.target.closest('.batch-name');
                    if (batchNameEl && batchNameEl.dataset.batch) {
                        selectBatch(batchNameEl.dataset.batch);
                    }
                });
            }
        });

function _bindDelegatedEvents() {

            const importBtn = document.querySelector('.import-btn');
            if (importBtn) importBtn.addEventListener('click', importAll);

            // Batch sort buttons
            document.querySelectorAll('.batch-sort-btn').forEach(btn => {
                btn.addEventListener('click', function() { setBatchSort(this.dataset.bsort); });
            });

            // Batch search
            const batchSearch = document.getElementById('batch-search');
            if (batchSearch) batchSearch.addEventListener('input', function() {
                setBatchFilter(this.value);
            });

            const batchSearchClear = document.getElementById('batch-search-clear');
            if (batchSearchClear) batchSearchClear.addEventListener('click', clearBatchSearch);

            // New batch button
            const newBatchBtn = document.querySelector('.new-batch-btn');
            if (newBatchBtn) newBatchBtn.addEventListener('click', showNewBatchModal);

            // Sidebar resizer
            const resizer = document.getElementById('sidebar-resizer');
            if (resizer) {
                resizer.addEventListener('mousedown', startSidebarResize);
                resizer.addEventListener('pointerdown', startSidebarResize);
            }

            // Header buttons
            const batchToggleBtn = document.getElementById('batch-sidebar-toggle-btn');
            if (batchToggleBtn) batchToggleBtn.addEventListener('click', toggleBatchSidebar);

            const aiToggleBtn = document.getElementById('ai-sidebar-toggle-btn');
            if (aiToggleBtn) aiToggleBtn.addEventListener('click', toggleAiSidebar);

            const helpBtn = document.getElementById('help-btn');
            if (helpBtn) helpBtn.addEventListener('click', showHelpModal);

            const promptsBtn = document.getElementById('prompts-btn');
            if (promptsBtn) promptsBtn.addEventListener('click', showPromptsModal);
            const settingsBtn = document.getElementById('settings-btn');
            if (settingsBtn) settingsBtn.addEventListener('click', showSettingsModal);

            const autoImportBtn = document.getElementById('set-auto-import-btn');
            if (autoImportBtn) autoImportBtn.addEventListener('click', setCurrentBatchAsAutoImport);

            // Sort controls
            document.querySelectorAll('.sort-btn:not(.batch-sort-btn)').forEach(btn => {
                btn.addEventListener('click', function() { setSort(this.dataset.sort); });
            });

            const sortDirBtn = document.getElementById('sort-dir-btn');
            if (sortDirBtn) sortDirBtn.addEventListener('click', toggleOrder);

            const favFilterBtn = document.getElementById('favorites-filter-btn');
            if (favFilterBtn) favFilterBtn.addEventListener('click', toggleFavoritesFilter);
            const hoverPreviewToggle = document.getElementById('hover-preview-toggle');
            if (hoverPreviewToggle) {
                hoverPreviewToggle.checked = hoverPreviewsEnabled;
                hoverPreviewToggle.addEventListener('change', () => {
                    hoverPreviewsEnabled = hoverPreviewToggle.checked;
                    localStorage.setItem(HOVER_PREVIEWS_KEY, hoverPreviewsEnabled ? 'true' : 'false');
                    if (!hoverPreviewsEnabled) stopActiveHoverPreview();
                });
            }
            const videoPlaybackToggle = document.getElementById('lightbox-video-autoplay-loop-toggle');
            if (videoPlaybackToggle) {
                videoPlaybackToggle.checked = lightboxVideoAutoplayLoopEnabled;
                videoPlaybackToggle.addEventListener('change', () => {
                    setLightboxVideoAutoplayLoopEnabled(videoPlaybackToggle.checked);
                });
            }

            const selectAllBtn = document.getElementById('workspace-select-all-btn');
            if (selectAllBtn) selectAllBtn.addEventListener('click', selectAllDisplayedImages);
            const browseModeBtn = document.getElementById('browse-mode-btn');
            if (browseModeBtn) browseModeBtn.addEventListener('click', () => setSelectionMode(false));
            const selectModeBtn = document.getElementById('select-mode-btn');
            if (selectModeBtn) selectModeBtn.addEventListener('click', () => setSelectionMode(true));

            document.querySelectorAll('.density-btn').forEach(btn => {
                btn.addEventListener('click', function() { setGridDensity(this.dataset.density); });
            });

            // Folder tabs (delegated)
            const folderTabs = document.getElementById('folder-tabs');
            if (folderTabs) {
                folderTabs.addEventListener('click', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab && tab.dataset.folder) {
                        selectFolder(currentBatch, tab.dataset.folder);
                    }
                });
                folderTabs.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        const tab = e.target.closest('.folder-tab');
                        if (tab && tab.dataset.folder) {
                            e.preventDefault();
                            selectFolder(currentBatch, tab.dataset.folder);
                        }
                    }
                });
                folderTabs.addEventListener('dragover', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab) onDragOver(e, tab);
                });
                folderTabs.addEventListener('dragleave', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab) onDragLeave(e, tab);
                });
                folderTabs.addEventListener('drop', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab && tab.dataset.folder) {
                        e.preventDefault();
                        onDrop(e, tab.dataset.folder, tab);
                    }
                });
            }

            // Note: the lightbox S/F/R move buttons are wired by the
            // delegated handler on #lightbox-actions below (single source of
            // truth). Do NOT add direct per-button listeners here -- doing
            // so causes moveImage() to fire twice on every click.

            // Modal buttons
            document.querySelectorAll('#new-batch-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hideNewBatchModal);
            });
            document.querySelectorAll('#new-batch-modal .create').forEach(btn => {
                btn.addEventListener('click', createBatch);
            });
            const newBatchName = document.getElementById('new-batch-name');
            if (newBatchName) newBatchName.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') createBatch();
            });

            document.querySelectorAll('#delete-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hideDeleteModal);
            });
            document.querySelectorAll('#delete-modal .delete-confirm').forEach(btn => {
                btn.addEventListener('click', confirmDeleteRejects);
            });

            document.querySelectorAll('#publish-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hidePublishModal);
            });
            const publishModal = document.getElementById('publish-modal');
            if (publishModal) publishModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hidePublishModal); });
            const publishSubmitBtn = document.getElementById('publish-submit-btn');
            if (publishSubmitBtn) publishSubmitBtn.addEventListener('click', submitPublicExport);
            const publishWatermarkToggle = document.getElementById('publish-watermark-enabled');
            if (publishWatermarkToggle) publishWatermarkToggle.addEventListener('change', () => { syncPublishWatermarkFields(); updatePublishWatermarkOverlay(); });
            ['publish-watermark-text', 'publish-watermark-position', 'publish-watermark-opacity', 'publish-watermark-size', 'publish-watermark-margin'].forEach(id => {
                const input = document.getElementById(id);
                if (input) input.addEventListener('input', () => { syncPublishWatermarkFields(); updatePublishWatermarkOverlay(); });
            });
            const publishWatermarkBlack = document.getElementById('publish-watermark-black');
            if (publishWatermarkBlack) publishWatermarkBlack.addEventListener('change', updatePublishWatermarkOverlay);
            window.addEventListener('resize', () => {
                if (document.getElementById('publish-modal').classList.contains('active')) syncPublishPreviewGeometry();
            });
            const publishResetWatermarkBtn = document.getElementById('publish-reset-watermark-btn');
            if (publishResetWatermarkBtn) publishResetWatermarkBtn.addEventListener('click', () => { resetPublishWatermarkDefaults(); updatePublishWatermarkOverlay(); });
             const publishStripMetadata = document.getElementById('publish-strip-metadata');
             if (publishStripMetadata) publishStripMetadata.addEventListener('change', syncPublishMetadataNote);
             const publishPreviewFrame = document.getElementById('publish-preview-frame');
             if (publishPreviewFrame) {
                 publishPreviewFrame.addEventListener('click', () => setPublishPreviewActive(true));
                 publishPreviewFrame.addEventListener('keydown', handlePublishPreviewKeydown);
                 publishPreviewFrame.addEventListener('wheel', handlePublishPreviewWheel, {passive: false});
                 publishPreviewFrame.addEventListener('pointerdown', startPublishPreviewPan);
                 publishPreviewFrame.addEventListener('pointermove', movePublishPreviewPan);
                 publishPreviewFrame.addEventListener('pointerup', endPublishPreviewPan);
                 publishPreviewFrame.addEventListener('pointercancel', endPublishPreviewPan);
             }
             const publishPreviewActivation = document.getElementById('publish-preview-activation');
             if (publishPreviewActivation) publishPreviewActivation.addEventListener('click', () => setPublishPreviewActive(!publishPreviewActive));
             const publishPreviewZoomOut = document.getElementById('publish-preview-zoom-out-btn');
             if (publishPreviewZoomOut) publishPreviewZoomOut.addEventListener('click', () => zoomPublishPreview(-PUBLISH_PREVIEW_ZOOM_STEP));
             const publishPreviewReset = document.getElementById('publish-preview-reset-btn');
             if (publishPreviewReset) publishPreviewReset.addEventListener('click', () => resetPublishPreviewView(true));
             const publishPreviewZoomIn = document.getElementById('publish-preview-zoom-in-btn');
             if (publishPreviewZoomIn) publishPreviewZoomIn.addEventListener('click', () => zoomPublishPreview(PUBLISH_PREVIEW_ZOOM_STEP));
             const publishPreviewPrevious = document.getElementById('publish-preview-prev-btn');
             if (publishPreviewPrevious) publishPreviewPrevious.addEventListener('click', () => navigatePublishPreview(-1));
             const publishPreviewNext = document.getElementById('publish-preview-next-btn');
             if (publishPreviewNext) publishPreviewNext.addEventListener('click', () => navigatePublishPreview(1));
             const publishViewPublicBtn = document.getElementById('publish-view-public-btn');
            if (publishViewPublicBtn) publishViewPublicBtn.addEventListener('click', viewCreatedPublicCopies);
            const publishPresetSaveBtn = document.getElementById('publish-preset-save-btn');
            if (publishPresetSaveBtn) publishPresetSaveBtn.addEventListener('click', () => {
                const nameInput = document.getElementById('publish-preset-name');
                if (savePublishPreset(nameInput?.value || '') && nameInput) nameInput.value = '';
            });
            const publishPresetNameInput = document.getElementById('publish-preset-name');
            if (publishPresetNameInput) publishPresetNameInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (savePublishPreset(publishPresetNameInput.value)) publishPresetNameInput.value = '';
                }
            });

            document.querySelectorAll('#public-destination-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hidePublicDestinationModal);
            });
            const publicDestinationModal = document.getElementById('public-destination-modal');
            if (publicDestinationModal) publicDestinationModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hidePublicDestinationModal); });
            const publicDestinationSubmit = document.getElementById('public-destination-submit-btn');
            if (publicDestinationSubmit) publicDestinationSubmit.addEventListener('click', submitPublicDestinationAction);
            const publicDestinationInput = document.getElementById('public-destination-input');
            if (publicDestinationInput) publicDestinationInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') submitPublicDestinationAction();
            });
            if (publicDestinationInput) publicDestinationInput.addEventListener('input', handlePublicDestinationInputChanged);
            const publicDestinationUp = document.getElementById('public-destination-up-btn');
            if (publicDestinationUp) publicDestinationUp.addEventListener('click', browsePublicDestinationUp);
            const publicDestinationRefresh = document.getElementById('public-destination-refresh-btn');
            if (publicDestinationRefresh) publicDestinationRefresh.addEventListener('click', refreshPublicDestinationBrowser);

            document.querySelectorAll('#public-delete-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hidePublicDeleteModal);
            });
            const publicDeleteModal = document.getElementById('public-delete-modal');
            if (publicDeleteModal) publicDeleteModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hidePublicDeleteModal); });
            const publicDeleteConfirm = document.getElementById('public-delete-confirm-btn');
            if (publicDeleteConfirm) publicDeleteConfirm.addEventListener('click', confirmPublicDelete);

            document.querySelectorAll('#help-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hideHelpModal);
            });
            const helpModal = document.getElementById('help-modal');
            if (helpModal) helpModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hideHelpModal); });
            document.querySelectorAll('#settings-modal .cancel').forEach(btn => btn.addEventListener('click', hideSettingsModal));
            const settingsClose = document.getElementById('settings-close-btn');
            if (settingsClose) settingsClose.addEventListener('click', hideSettingsModal);
            const settingsSave = document.getElementById('settings-save-btn');
            if (settingsSave) settingsSave.addEventListener('click', saveNativeSettings);
            const settingsModal = document.getElementById('settings-modal');
            if (settingsModal) settingsModal.addEventListener('click', event => closeModalOnBackdropClick(event, hideSettingsModal));

            document.querySelectorAll('#prompts-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hidePromptsModal);
            });
            const promptsModal = document.getElementById('prompts-modal');
            if (promptsModal) promptsModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hidePromptsModal); });
            [['media-search-tab', 'images'], ['prompt-groups-tab', 'prompts']].forEach(([id, tab]) => {
                const button = document.getElementById(id);
                if (!button) return;
                button.addEventListener('click', () => setLibrarySearchTab(tab, {load: true}));
                button.addEventListener('keydown', event => {
                    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                    event.preventDefault();
                    const next = event.key === 'ArrowLeft' || event.key === 'Home' ? 'images' : 'prompts';
                    setLibrarySearchTab(next, {load: true});
                    document.getElementById(next === 'images' ? 'media-search-tab' : 'prompt-groups-tab')?.focus();
                });
            });
            const mediaSearchInput = document.getElementById('media-search-input');
            if (mediaSearchInput) mediaSearchInput.addEventListener('input', scheduleMediaSearch);
            const mediaSearchScope = document.getElementById('media-search-scope');
            if (mediaSearchScope) mediaSearchScope.addEventListener('change', runMediaSearch);
            const mediaSearchBuild = document.getElementById('media-search-build-btn');
            if (mediaSearchBuild) mediaSearchBuild.addEventListener('click', buildCurrentMediaSearchIndex);
            const mediaSearchBuildAll = document.getElementById('media-search-build-all-btn');
            if (mediaSearchBuildAll) mediaSearchBuildAll.addEventListener('click', buildMissingMediaSearchIndexes);
            const mediaSearchBuildConfirm = document.getElementById('media-search-build-confirm-btn');
            if (mediaSearchBuildConfirm) mediaSearchBuildConfirm.addEventListener('click', confirmMissingMediaSearchIndexes);
            const mediaSearchBuildCancel = document.getElementById('media-search-build-cancel-btn');
            if (mediaSearchBuildCancel) mediaSearchBuildCancel.addEventListener('click', hideMediaSearchBuildConfirm);
            const mediaSearchApply = document.getElementById('media-search-apply-btn');
            if (mediaSearchApply) mediaSearchApply.addEventListener('click', applyMediaSearchToWorkspace);
            const workspaceSearchClear = document.getElementById('workspace-search-filter-clear');
            if (workspaceSearchClear) workspaceSearchClear.addEventListener('click', clearWorkspaceSearchFilter);
            const workspaceSearchEdit = document.getElementById('workspace-search-filter-edit');
            if (workspaceSearchEdit) workspaceSearchEdit.addEventListener('click', editWorkspaceSearchFilter);
            const promptsBuildBtn = document.getElementById('prompts-build-btn');
            if (promptsBuildBtn) promptsBuildBtn.addEventListener('click', buildPromptIndex);
            const promptsBuildAllConfirmBtn = document.getElementById('prompts-build-all-confirm-btn');
            if (promptsBuildAllConfirmBtn) promptsBuildAllConfirmBtn.addEventListener('click', buildAllPromptIndexes);
            const promptsBuildAllCancelBtn = document.getElementById('prompts-build-all-cancel-btn');
            if (promptsBuildAllCancelBtn) promptsBuildAllCancelBtn.addEventListener('click', hideBuildAllConfirm);
            const promptsRebuildBtn = document.getElementById('prompts-rebuild-btn');
            if (promptsRebuildBtn) promptsRebuildBtn.addEventListener('click', buildPromptIndex);
            const promptsBatchFilter = document.getElementById('prompts-batch-filter');
            if (promptsBatchFilter) {
                promptsBatchFilter.addEventListener('focus', _promptOpenDropdown);
                promptsBatchFilter.addEventListener('blur', () => {
                    _promptBlurTimer = setTimeout(() => {
                        const wrapper = document.getElementById('prompts-batch-wrap');
                        if (!wrapper || !wrapper.classList.contains('open')) return;
                        _promptCloseDropdown(true);
                        _syncPromptDisplay();
                    }, 150);
                });
                promptsBatchFilter.addEventListener('input', () => {
                    const wrapper = document.getElementById('prompts-batch-wrap');
                    if (wrapper && !wrapper.classList.contains('open')) {
                        _promptOpenDropdown();
                    }
                    _populatePromptDropdown(promptsBatchFilter.value);
                });
                promptsBatchFilter.addEventListener('keydown', (e) => {
                    const wrapper = document.getElementById('prompts-batch-wrap');
                    if (!wrapper || !wrapper.classList.contains('open')) return;
                    switch (e.key) {
                        case 'ArrowDown':
                            e.preventDefault();
                            _promptMoveFocus(1);
                            break;
                        case 'ArrowUp':
                            e.preventDefault();
                            _promptMoveFocus(-1);
                            break;
                        case 'PageDown':
                            e.preventDefault();
                            _promptJumpFocus((_promptVisibleOptions().length || 1) - 1);
                            break;
                        case 'PageUp':
                            e.preventDefault();
                            _promptJumpFocus(0);
                            break;
                        case 'Home':
                            e.preventDefault();
                            _promptJumpFocus(0);
                            break;
                        case 'End':
                            e.preventDefault();
                            _promptJumpFocus((_promptVisibleOptions().length || 1) - 1);
                            break;
                        case 'Enter':
                            e.preventDefault();
                            const focused = document.querySelector('#prompts-batch-list .prompts-batch-option.focus');
                            if (focused && focused.hasAttribute('data-value')) {
                                clearTimeout(_promptBlurTimer);
                                _commitPromptSelection(focused.dataset.value);
                            }
                            break;
                        case 'Escape':
                            e.preventDefault();
                            e.stopPropagation();
                            _promptCloseDropdown(true);
                            _syncPromptDisplay();
                            break;
                    }
                });
            }
            const promptsSearch = document.getElementById('prompts-search');
            if (promptsSearch) promptsSearch.addEventListener('input', _schedulePromptsRender);
            const promptsSortSelect = document.getElementById('prompts-sort');
            if (promptsSortSelect) {
                promptsSortSelect.value = (typeof promptsSort === 'string' && PROMPTS_SORT_OPTIONS.includes(promptsSort)) ? promptsSort : 'count';
                promptsSortSelect.addEventListener('change', function() {
                    _setPromptsSort(this.value);
                    renderPromptsList();
                });
            }
            const promptsCollapseBtn = document.getElementById('prompts-collapse-all');
            if (promptsCollapseBtn) {
                promptsCollapseBtn.textContent = promptsCollapseAll ? 'Expand positive prompts' : 'Collapse positive prompts';
                promptsCollapseBtn.addEventListener('click', function() {
                    _setPromptsCollapse(!promptsCollapseAll);
                    this.textContent = promptsCollapseAll ? 'Expand positive prompts' : 'Collapse positive prompts';
                    renderPromptsList();
                });
            }
            [['prompts-view-positive', 'positive'], ['prompts-view-negative', 'negative'], ['prompts-view-images', 'images']].forEach(([id, mode]) => {
                const button = document.getElementById(id);
                if (button) button.addEventListener('click', () => _setPromptDetailMode(mode, !promptsDetailModes[mode]));
            });

            // Close prompt batch dropdown when clicking outside
            document.addEventListener('mousedown', (e) => {
                const wrapper = document.getElementById('prompts-batch-wrap');
                if (wrapper && wrapper.classList.contains('open') && !wrapper.contains(e.target)) {
                    _promptCloseDropdown(true);
                    _syncPromptDisplay();
                }
            });

            // Toast undo
            const toastUndo = document.getElementById('toast-undo');
            if (toastUndo) toastUndo.addEventListener('click', undoLastMove);

            // AI sidebar resizer
            const aiResizer = document.getElementById('ai-sidebar-resizer');
            if (aiResizer) {
                aiResizer.addEventListener('mousedown', startAiSidebarResize);
                aiResizer.addEventListener('pointerdown', startAiSidebarResize);
            }

            document.querySelectorAll('.ai-panel-tab').forEach(tab => {
                tab.addEventListener('click', function() { aiSetPanelTab(this.dataset.aiTab); });
                tab.addEventListener('keydown', aiHandlePanelTabKeydown);
            });

            // AI overlay toggle
            const aiOverlayToggle = document.getElementById('ai-overlay-toggle');
            if (aiOverlayToggle) aiOverlayToggle.addEventListener('change', aiToggleOverlays);

            // AI filter mode
            const aiFilterMode = document.getElementById('ai-filter-mode');
            if (aiFilterMode) aiFilterMode.addEventListener('change', aiApplyFilter);

            // AI preview elements button
            const aiPreviewBtn = document.querySelector('.ai-btn-secondary');
            if (aiPreviewBtn) aiPreviewBtn.addEventListener('click', aiPreviewElements);

            // Optional elements section toggle
            const aiOptionalHeader = document.getElementById('ai-optional-header');
            if (aiOptionalHeader) {
                aiOptionalHeader.addEventListener('click', toggleAiOptionalSection);
            }
            const aiOptionalBody = document.getElementById('ai-optional-body');
            if (aiOptionalBody) aiOptionalBody.addEventListener('change', aiUpdateScoreSummary);

            ['ai-elements', 'ai-source-folder', 'ai-top-n', 'ai-model', 'ai-dest-folder'].forEach(id => {
                const control = document.getElementById(id);
                if (!control) return;
                control.addEventListener(control.tagName === 'SELECT' ? 'change' : 'input', aiUpdateScoreSummary);
            });

            // Element history select
            const aiHistorySelect = document.getElementById('ai-history-select');
            if (aiHistorySelect) {
                aiHistorySelect.addEventListener('change', function() {
                    if (this.value) {
                        document.getElementById('ai-elements').value = this.value;
                        this.selectedIndex = 0; // reset display to placeholder
                        aiUpdateScoreSummary();
                    }
                });
            }

            // AI move toggle
            const aiMoveToggle = document.getElementById('ai-move-toggle');
            if (aiMoveToggle) aiMoveToggle.addEventListener('change', aiToggleMoveMode);

            // AI submit button
            const aiSubmitBtn = document.getElementById('ai-submit-btn');
            if (aiSubmitBtn) aiSubmitBtn.addEventListener('click', aiSubmitJob);

            // AI cancel button
            const aiCancelBtn = document.getElementById('ai-cancel-btn');
            if (aiCancelBtn) aiCancelBtn.addEventListener('click', aiCancelJob);

            // AI run history selectors
            const aiRunSelect = document.getElementById('ai-run-select');
            if (aiRunSelect) aiRunSelect.addEventListener('change', function() {
                aiLoadRun(this.value || null);
            });

            // AI Inspect run selector
            const aiInspectRunSelect = document.getElementById('ai-inspect-run-select');
            if (aiInspectRunSelect) aiInspectRunSelect.addEventListener('change', function() {
                aiLoadRun(this.value || null);
            });

            // AI compare run selector
            const aiCompareRunSelect = document.getElementById('ai-compare-run-select');
            if (aiCompareRunSelect) aiCompareRunSelect.addEventListener('change', function() {
                aiSetCompareRun(this.value);
            });

            aiUpdateScoreSummary();

            // Delete rejects button
            const deleteRejectsBtn = document.getElementById('delete-rejects-btn');
            if (deleteRejectsBtn) deleteRejectsBtn.addEventListener('click', showDeleteModal);

            // Action bar (multi-select) buttons - delegated
            const actionBar = document.querySelector('.action-bar');
            if (actionBar) {
                actionBar.addEventListener('click', function(e) {
                    const btn = e.target.closest('.action-btn');
                    if (!btn) return;
                    if (btn.classList.contains('action-clear')) {
                        if (serverSelection || selectedImages.size > 0) clearSelection();
                        else setSelectionMode(false);
                    } else if (btn.id === 'compare-lightbox-btn') {
                        openCompareLightbox();
                    } else if (btn.id === 'publish-btn') {
                        showPublishModal();
                    } else if (btn.id === 'public-copy-btn') {
                        copySelectedPublicCopies();
                    } else if (btn.id === 'public-move-btn') {
                        moveSelectedPublicCopies();
                    } else if (btn.id === 'public-delete-btn') {
                        deleteSelectedPublicCopies();
                    } else if (btn.dataset.dest) {
                        moveSelected(btn.dataset.dest);
                    }
                });
            }

            // Lightbox close button
            const lightboxClose = document.querySelector('.lightbox-close');
            if (lightboxClose) {
                lightboxClose.addEventListener('click', closeLightbox);
                lightboxClose.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') closeLightbox();
                });
            }

            // Lightbox nav buttons
            document.querySelectorAll('.lightbox-nav.prev').forEach(el => {
                el.addEventListener('click', function() { navigate(-1); });
                el.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') navigate(-1);
                });
            });
            document.querySelectorAll('.lightbox-nav.next').forEach(el => {
                el.addEventListener('click', function() { navigate(1); });
                el.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') navigate(1);
                });
            });

            const lightboxImageWrap = document.getElementById('lightbox-image-wrap');
            if (lightboxImageWrap) {
                lightboxImageWrap.addEventListener('pointerdown', startLightboxPan);
                lightboxImageWrap.addEventListener('pointermove', moveLightboxPan);
                lightboxImageWrap.addEventListener('pointerup', endLightboxPan);
                lightboxImageWrap.addEventListener('pointercancel', endLightboxPan);
            }

            const lightboxCompare = document.getElementById('lightbox-compare');
            if (lightboxCompare) {
                lightboxCompare.addEventListener('pointerdown', startLightboxPan);
                lightboxCompare.addEventListener('pointermove', moveLightboxPan);
                lightboxCompare.addEventListener('pointerup', endLightboxPan);
                lightboxCompare.addEventListener('pointercancel', endLightboxPan);
                lightboxCompare.addEventListener('click', function(event) {
                    setLightboxCompareActivePane(getActiveComparePaneIndexFromEvent(event));
                });
                lightboxCompare.addEventListener('focusin', function(event) {
                    setLightboxCompareActivePane(getActiveComparePaneIndexFromEvent(event));
                });
                window.addEventListener('resize', positionCompareOverlayPanels);
            }

            // Lightbox toolbar buttons - delegate on #lightbox-actions
            const lightboxActions = document.getElementById('lightbox-actions');
            if (lightboxActions) {
                lightboxActions.addEventListener('click', function(e) {
                    const btn = e.target.closest('button');
                    if (!btn) return;
                    if (btn.classList.contains('btn-shortlist')) moveImage('shortlisted');
                    else if (btn.classList.contains('btn-finals')) moveImage('finals');
                    else if (btn.classList.contains('btn-reject')) moveImage('rejects');
                    else if (btn.id === 'metadata-toggle-btn') toggleLightboxMetadata();
                    else if (btn.id === 'lightbox-ai-toggle-btn') toggleLightboxAiPanel();
                    else if (btn.id === 'lightbox-publish-btn') showLightboxPublishModal();
                    else if (btn.id === 'lightbox-pin-compare-btn') openStickyCompareLightbox();
                });
                // Map button text to handlers for generic buttons
                lightboxActions.querySelectorAll('button').forEach(btn => {
                    const text = btn.textContent.trim();
                    if (text === 'Prev scored') btn.addEventListener('click', function() { navigateScored(-1); });
                    else if (text === 'Next scored') btn.addEventListener('click', function() { navigateScored(1); });
                    else if (text === 'Zoom \u2212') btn.addEventListener('click', function() { zoomLightbox(-0.2); });
                    else if (text === 'Reset zoom') btn.addEventListener('click', resetLightboxZoom);
                    else if (text === 'Zoom +') btn.addEventListener('click', function() { zoomLightbox(0.2); });
                });
            }
        }
