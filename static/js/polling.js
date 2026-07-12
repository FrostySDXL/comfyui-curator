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
            return list.map(img => `${img.name}:${img.size}`).join('|');
        }

async function pollForChanges() {
            if (isInteractionBusy()) return;
            await loadBatches();
            if (!currentBatch || isVirtualCollectionView() || isPublicView() || !currentFolder || selectedImages.size > 0 || isInteractionBusy()) return;
            const [imageResp, runResp] = await Promise.all([
                fetch(ccApiPath(`/api/images/${currentBatch}/${currentFolder}?sort=${currentSort}&order=${currentOrder}`)),
                fetch(ccApiPath(`/api/ai-curate/batches/${currentBatch}/runs`)),
            ]);
            if (!imageResp.ok || !runResp.ok) return;
            const [nextImages, runData] = await Promise.all([imageResp.json(), runResp.json()]);
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
