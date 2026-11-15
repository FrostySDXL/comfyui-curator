/* Ordered classic script.
 * Defines: interaction-aware polling helpers.
 */
function isInteractionBusy() {
            return document.getElementById('lightbox').classList.contains('active')
                || isDraggingImages
                || isSidebarResizing
                || isAiSidebarResizing
                || (typeof isBatchSidebarPeeking === 'function' && isBatchSidebarPeeking());
        }

function buildImageSignature(list) {
            return list.map(img => `${img.name}:${img.size}:${img.mtime || img.modified_at || 0}`).join('|');
        }

async function pollForChanges() {
            if (isInteractionBusy()) return;
            if (!CURATOR_NATIVE) await loadBatches({background: true});
            if (!currentBatch || isVirtualCollectionView() || isPublicView() || !currentFolder || serverSelection || selectedImages.size > 0 || isInteractionBusy()) return;
            const transitionToken = viewTransitionToken;
            const scopeKey = getViewScopeKey();
            const importRefresh = typeof pendingImportRefresh !== 'undefined'
                && pendingImportRefresh?.batch === currentBatch && currentFolder === 'inbox'
                ? pendingImportRefresh : null;
            const folderCountHint = allCounts[currentBatch]?.[currentFolder];
            const usesPagedFolderTransport = Boolean(folderSnapshot)
                || CURATOR_NATIVE
                || (typeof folderCountHint === 'number' && folderCountHint >= PAGED_FOLDER_THRESHOLD);
            if (usesPagedFolderTransport) {
                // A large standalone folder may still be waiting for its first
                // snapshot (or be between view transitions). Do not fall back
                // to the expensive legacy full listing while that load owns the
                // folder state; the next poll will use the revisioned endpoint
                // once the snapshot is published.
                if (!folderSnapshot) {
                    // An explicit import can push a small standalone folder over
                    // the paging threshold. Keep the legacy view until a guarded
                    // snapshot load commits, and retry if interaction intervenes.
                    if (importRefresh && typeof importSnapshotLoad !== 'undefined' && !importSnapshotLoad) {
                        const sort = currentSort, order = currentOrder;
                        const owned = () => transitionToken === viewTransitionToken
                            && scopeKey === getViewScopeKey() && currentSort === sort && currentOrder === order
                            && pendingImportRefresh === importRefresh && !isInteractionBusy()
                            && !serverSelection && selectedImages.size === 0;
                        const load = loadCurrentFolderImages({preserveScroll: true, mayCommit: owned});
                        importSnapshotLoad = load;
                        try {
                            const loaded = await load;
                            if (loaded && owned() && folderSnapshot && pendingImportRefresh === importRefresh) pendingImportRefresh = null;
                        } finally {
                            if (importSnapshotLoad === load) importSnapshotLoad = null;
                        }
                    }
                    return;
                }
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
                    const loaded = await loadCurrentFolderImages({preserveScroll: true});
                    if (loaded && importRefresh && pendingImportRefresh === importRefresh
                        && transitionToken === viewTransitionToken && scopeKey === getViewScopeKey()
                        && !isInteractionBusy() && !serverSelection && selectedImages.size === 0) pendingImportRefresh = null;
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
            if (currentSort === 'shuffle' && importRefresh) {
                // Preserve the existing random order and append newly imported members.
                const byName = new Map(nextImages.map(image => [image.name, image]));
                const ordered = [];
                for (const image of images) {
                    if (byName.has(image.name)) {
                        ordered.push(byName.get(image.name));
                        byName.delete(image.name);
                    }
                }
                ordered.push(...byName.values());
                nextImages.splice(0, nextImages.length, ...ordered);
            }
            const imageChanged = (currentSort !== 'shuffle' || importRefresh) && buildImageSignature(nextImages) !== buildImageSignature(images);
            const latestRunId = runData.runs && runData.runs.length > 0 ? runData.runs[runData.runs.length - 1] : null;
            const aiChanged = (aiLatestRun?.run_id || null) !== latestRunId;

            if (imageChanged) {
                images = nextImages;
                document.getElementById('img-count').textContent = images.length > 0 ? ` (${images.length})` : '';
                updateGrid();
            }
            if (importRefresh && pendingImportRefresh === importRefresh) pendingImportRefresh = null;
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
