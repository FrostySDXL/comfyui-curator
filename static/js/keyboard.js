/* Ordered classic script.
 * Defines: document keyboard shortcuts and lightbox wheel zoom binding.
 */
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

            if (e.key === 'Escape' && document.getElementById('public-destination-modal').classList.contains('active')) {
                e.preventDefault();
                hidePublicDestinationModal();
                return;
            }

            if (e.key === 'Escape' && document.getElementById('public-delete-modal').classList.contains('active')) {
                e.preventDefault();
                hidePublicDeleteModal();
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
                    case 'p':
                        e.preventDefault();
                        showPromptsModal();
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
