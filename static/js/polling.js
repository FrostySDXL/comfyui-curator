/* Ordered classic script.
 * Defines: interaction-aware polling helpers.
 */
function isInteractionBusy() {
            return document.getElementById('lightbox').classList.contains('active')
                || isDraggingImages
                || isSidebarResizing
                || isAiSidebarResizing;
        }

function buildImageSignature(list) {
            return list.map(img => `${img.name}:${img.size}:${img.mtime || img.modified_at || 0}`).join('|');
        }

async function pollForChanges() {
            if (isInteractionBusy()) return;
            if (!CURATOR_NATIVE) await loadBatches();
            if (!currentBatch || isVirtualCollectionView() || isPublicView() || !currentFolder || serverSelection || selectedImages.size > 0 || isInteractionBusy()) return;
            const transitionToken = viewTransitionToken;
            const scopeKey = getViewScopeKey();
            if (CURATOR_NATIVE && folderSnapshot) {
                const [snapshotResp, runResp] = await Promise.all([
                    apiPollFolderSnapshot(
                        currentBatch, currentFolder, _folderTransportSort(), currentOrder, folderSnapshot.revision,
                        folderShuffleSeed,
                    ),
                    fetch(ccApiPath(`/api/ai-curate/batches/${currentBatch}/runs`)),
                ]);
                if (!snapshotResp.ok || !runResp.ok) return;
                const [snapshotData, runData] = await Promise.all([snapshotResp.json(), runResp.json()]);
                if (transitionToken !== viewTransitionToken || scopeKey !== getViewScopeKey() || isInteractionBusy() || serverSelection || selectedImages.size > 0) return;
                if (snapshotData.status === 'ready' && snapshotData.changed) {
                    await loadCurrentFolderImages({preserveScroll: true});
                }
                if (transitionToken !== viewTransitionToken || scopeKey !== getViewScopeKey() || isInteractionBusy() || serverSelection || selectedImages.size > 0) return;
                const latestRunId = runData.runs && runData.runs.length > 0 ? runData.runs[runData.runs.length - 1] : null;
                if ((aiLatestRun?.run_id || null) !== latestRunId) {
                    await aiRefreshRunData(runData.runs || []);
                    if (transitionToken !== viewTransitionToken || scopeKey !== getViewScopeKey() || isInteractionBusy() || serverSelection || selectedImages.size > 0) return;
                    if (aiShowOverlays || aiFilterMode !== 'all' || (aiCompareRunId && aiCompareRunId !== 'latest')) updateGrid();
                }
                return;
            }
            const [imageResp, runResp] = await Promise.all([
                fetch(ccApiPath(`/api/images/${currentBatch}/${currentFolder}?sort=${currentSort}&order=${currentOrder}`)),
                fetch(ccApiPath(`/api/ai-curate/batches/${currentBatch}/runs`)),
            ]);
            if (!imageResp.ok || !runResp.ok) return;
            const [nextImages, runData] = await Promise.all([imageResp.json(), runResp.json()]);
            if (transitionToken !== viewTransitionToken || scopeKey !== getViewScopeKey() || isInteractionBusy() || serverSelection || selectedImages.size > 0) return;
            // Skip image-list updates when shuffle sort is active -- the server
            // shuffles randomly on each request, so polling would re-shuffle.
            const imageChanged = currentSort !== 'shuffle' && buildImageSignature(nextImages) !== buildImageSignature(images);
            const latestRunId = runData.runs && runData.runs.length > 0 ? runData.runs[runData.runs.length - 1] : null;
            const aiChanged = (aiLatestRun?.run_id || null) !== latestRunId;

            if (imageChanged) {
                images = nextImages;
                document.getElementById('img-count').textContent = images.length > 0 ? ` (${images.length})` : '';
                updateGrid();
            }
            if (aiChanged) {
                await aiRefreshRunData(runData.runs || []);
                if (transitionToken !== viewTransitionToken || scopeKey !== getViewScopeKey() || isInteractionBusy() || serverSelection || selectedImages.size > 0) return;
                // Only redraw the grid when the AI run change actually affects
                // the visible thumbs: overlays enabled, compare-mode active,
                // or AI filter on. Otherwise the new run data is captured in
                // aiLatestRun for later use but we avoid a no-op grid refresh.
                if (aiShowOverlays || aiFilterMode !== 'all' || (aiCompareRunId && aiCompareRunId !== 'latest')) {
                    updateGrid();
                }
                if (document.getElementById('lightbox').classList.contains('active')) showCurrentImage();
            }
        }
