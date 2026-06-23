/* Ordered classic script.
 * Defines: keyboard shortcuts, modal helpers, delegated browser event bindings.
 */
function showNewBatchModal() {
            const modal = document.getElementById('new-batch-modal');
            modal.classList.add('active');
            _trapFocus(modal);
            document.getElementById('new-batch-name').focus();
        }

function hideNewBatchModal() {
            document.getElementById('new-batch-modal').classList.remove('active');
            document.getElementById('new-batch-name').value = '';
            _releaseFocusTrap();
        }

function showHelpModal() {
            const modal = document.getElementById('help-modal');
            modal.classList.add('active');
            _trapFocus(modal);
            modal.querySelector('.modal-content').scrollTop = 0;
        }

function hideHelpModal() {
            document.getElementById('help-modal').classList.remove('active');
            _releaseFocusTrap();
        }

function closeModalOnBackdropClick(event, hideFn) {
            if (event.target !== event.currentTarget) return;
            hideFn();
        }

        // Keyboard navigation + live-filter (input-based, no stopPropagation needed
        // because the document keyboard handler already skips INPUT elements)
        function _bindCustomSelectKeys() {
            const input = document.getElementById('active-batch-input');
            if (!input) return;

            input.addEventListener('focus', () => {
                _openCustomDropdown();
            });

            input.addEventListener('blur', () => {
                _customSelectBlurTimer = setTimeout(() => {
                    const wrapper = document.getElementById('active-batch-custom');
                    if (!wrapper || !wrapper.classList.contains('open')) return;
                    const query = (input.value || '').trim();
                    // Case-insensitive exact match against option text
                    const options = document.querySelectorAll('#active-batch-dropdown .custom-select-option');
                    for (const opt of options) {
                        if (opt.textContent.trim().toLowerCase() === query.toLowerCase() && opt.dataset.value) {
                            _commitCustomSelectSelection(opt.dataset.value);
                            return;
                        }
                    }
                    // No match found — close dropdown but leave input as-is
                    // so the user can return and correct their search
                    _closeCustomDropdown(false);
                }, 150);
            });

            input.addEventListener('input', () => {
                if (!document.getElementById('active-batch-custom').classList.contains('open')) {
                    _openCustomDropdown();
                }
                _populateCustomDropdown(input.value);
            });

            input.addEventListener('keydown', (e) => {
                const wrapper = document.getElementById('active-batch-custom');
                if (!wrapper || !wrapper.classList.contains('open')) return;
                switch (e.key) {
                    case 'ArrowDown':
                        e.preventDefault();
                        _customSelectMoveFocus(1);
                        break;
                    case 'ArrowUp':
                        e.preventDefault();
                        _customSelectMoveFocus(-1);
                        break;
                    case 'Enter':
                        e.preventDefault();
                        const focused = document.querySelector('#active-batch-dropdown .custom-select-option.focus');
                        if (focused) {
                            clearTimeout(_customSelectBlurTimer);
                            _commitCustomSelectSelection(focused.dataset.value);
                        }
                        break;
                    case 'Escape':
                        _closeCustomDropdown(true);
                        break;
                }
            });
        }

        // Close custom dropdown when clicking outside
        document.addEventListener('mousedown', (e) => {
            const wrapper = document.getElementById('active-batch-custom');
            if (wrapper && wrapper.classList.contains('open') && !wrapper.contains(e.target)) {
                _closeCustomDropdown(true);
            }
        });

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

        // --- Keyboard shortcuts ---

        document.addEventListener('keydown', (e) => {
            const activeEl = document.activeElement;
            const searchInput = document.getElementById('batch-search');
            const isTypingTarget = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable;
            const lightboxActive = document.getElementById('lightbox').classList.contains('active');

            if (e.key === "/" && !isTypingTarget) {
                e.preventDefault();
                ensureBatchSidebarOpen();
                if (searchInput) searchInput.focus();
                return;
            }

            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                ensureBatchSidebarOpen();
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
                return;
            }

            if (e.key === 'Escape' && searchInput && activeEl === searchInput) {
                e.preventDefault();
                clearBatchSearch();
                return;
            }

            if (e.key === 'Escape' && document.getElementById('help-modal').classList.contains('active')) {
                e.preventDefault();
                hideHelpModal();
                return;
            }

            if (e.key === 'Escape' && document.getElementById('prompts-modal').classList.contains('active')) {
                e.preventDefault();
                hidePromptsModal();
                return;
            }

            if (e.key === 'Escape' && document.getElementById('publish-modal').classList.contains('active')) {
                e.preventDefault();
                hidePublishModal();
                return;
            }

            if (isTypingTarget) return;

            if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
                e.preventDefault();
                undoLastMove();
                return;
            }

            if (!lightboxActive && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a' && currentBatch && currentFolder && images.length > 0) {
                e.preventDefault();
                selectedImages = new Set(images.map(img => img.name));
                lastSelectIndex = images.length - 1;
                updateSelectionVisuals();
                updateActionBar();
                return;
            }

            if (!lightboxActive) {
                switch (e.key.toLowerCase()) {
                    case 'b':
                        if (aiActiveRun) {
                            e.preventDefault();
                            const toggle = document.getElementById('ai-overlay-toggle');
                            if (toggle) {
                                toggle.checked = !toggle.checked;
                                aiToggleOverlays();
                            }
                        }
                        return;
                    case 'v':
                        if (aiActiveRun) {
                            e.preventDefault();
                            setSort(currentSort === 'score-desc' ? 'date' : 'score-desc');
                        }
                        return;
                    case 'i':
                        if (currentBatch) {
                            e.preventDefault();
                            toggleAiSidebar();
                        }
                        return;
                    case 'f':
                        if (!e.shiftKey && currentBatch) {
                            e.preventDefault();
                            toggleFavoritesFilter();
                        }
                        return;
                    case 'u':
                        e.preventDefault();
                        toggleBatchSidebar();
                        return;
                }
                return;
            }

            switch(e.key.toLowerCase()) {
                case 's': e.preventDefault(); moveImage('shortlisted'); break;
                case 'f': e.preventDefault(); if (e.shiftKey) toggleLightboxFavorite(); else moveImage('finals'); break;
                case 'r': e.preventDefault(); moveImage('rejects'); break;
                case 'arrowleft': e.preventDefault(); navigate(-1); break;
                case 'arrowright': e.preventDefault(); navigate(1); break;
                case '[': e.preventDefault(); navigateScored(-1); break;
                case ']': e.preventDefault(); navigateScored(1); break;
                case 'm': e.preventDefault(); toggleLightboxMetadata(); break;
                case 'i': e.preventDefault(); toggleLightboxAiPanel(); break;
                case '+':
                case '=': e.preventDefault(); zoomLightbox(0.2); break;
                case '-': e.preventDefault(); zoomLightbox(-0.2); break;
                case '0': e.preventDefault(); resetLightboxZoom(); break;
                case 'escape': e.preventDefault(); closeLightbox(); break;
            }
        });

        document.getElementById('lightbox-image-wrap').addEventListener('wheel', (event) => {
            if (!document.getElementById('lightbox').classList.contains('active')) return;
            if (!event.ctrlKey) return;
            event.preventDefault();
            zoomLightbox(event.deltaY < 0 ? 0.2 : -0.2);
        }, {passive: false});

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

            const selectAllBtn = document.getElementById('workspace-select-all-btn');
            if (selectAllBtn) selectAllBtn.addEventListener('click', selectAllDisplayedImages);

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
                folderTabs.addEventListener('dragover', onDragOver);
                folderTabs.addEventListener('dragleave', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab) onDragLeave(e);
                });
                folderTabs.addEventListener('drop', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab && tab.dataset.folder) {
                        e.preventDefault();
                        onDrop(e, tab.dataset.folder);
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

            document.querySelectorAll('#help-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hideHelpModal);
            });
            const helpModal = document.getElementById('help-modal');
            if (helpModal) helpModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hideHelpModal); });

            document.querySelectorAll('#prompts-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hidePromptsModal);
            });
            const promptsModal = document.getElementById('prompts-modal');
            if (promptsModal) promptsModal.addEventListener('click', function(event) { closeModalOnBackdropClick(event, hidePromptsModal); });
            const promptsBuildBtn = document.getElementById('prompts-build-btn');
            if (promptsBuildBtn) promptsBuildBtn.addEventListener('click', buildPromptIndex);
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
                        case 'Enter':
                            e.preventDefault();
                            const focused = document.querySelector('#prompts-batch-list .prompts-batch-option.focus');
                            if (focused && focused.dataset.value) {
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
            const promptsAllBatchesBtn = document.getElementById('prompts-all-batches-btn');
            if (promptsAllBatchesBtn) promptsAllBatchesBtn.addEventListener('click', () => _commitPromptSelection(''));
            const promptsSearch = document.getElementById('prompts-search');
            if (promptsSearch) promptsSearch.addEventListener('input', renderPromptsList);
            const promptsCollapseBtn = document.getElementById('prompts-collapse-all');
            if (promptsCollapseBtn) promptsCollapseBtn.addEventListener('click', function() {
                promptsCollapseAll = !promptsCollapseAll;
                this.textContent = promptsCollapseAll ? 'Expand all' : 'Collapse all';
                renderPromptsList();
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

            // Element history select
            const aiHistorySelect = document.getElementById('ai-history-select');
            if (aiHistorySelect) {
                aiHistorySelect.addEventListener('change', function() {
                    if (this.value) {
                        document.getElementById('ai-elements').value = this.value;
                        this.selectedIndex = 0; // reset display to placeholder
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

            // AI compare run selector
            const aiCompareRunSelect = document.getElementById('ai-compare-run-select');
            if (aiCompareRunSelect) aiCompareRunSelect.addEventListener('change', function() {
                aiSetCompareRun(this.value);
            });

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
                        clearSelection();
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
