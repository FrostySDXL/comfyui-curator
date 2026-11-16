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

async function pollForChanges() {
            if (isInteractionBusy()) return;
            if (!currentBatch || isVirtualCollectionView() || isPublicView() || !currentFolder || serverSelection || selectedImages.size > 0) return;
            /* Native folders poll the immutable snapshot revision instead of
               refetching the whole listing. Unchanged revisions cost one small
               response; a changed revision reloads the current view in place. */
            if (!folderSnapshot) return;
            const transitionToken = viewTransitionToken;
            const scopeKey = getViewScopeKey();
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
        }
