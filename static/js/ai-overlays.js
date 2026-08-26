/* Ordered classic script.
 * Defines: AI grid overlays, filtering, sorting, score helpers, and batch run counts.
 */
function aiToggleOverlays() {
            aiShowOverlays = document.getElementById('ai-overlay-toggle').checked;
            if (CURATOR_NATIVE && currentBatch && currentFolder && !isVirtualCollectionView() && !isPublicView() && aiFilterMode !== 'all') {
                loadCurrentFolderImages({preserveScroll: true});
                return;
            }
            updateGrid();
        }

function aiApplyFilter() {
            const selectedMode = document.getElementById('ai-filter-mode').value;
            if (selectedMode === 'threshold') {
                aiApplyThresholdFilter();
                return;
            }
            aiFilterMode = selectedMode;
            aiAppliedThreshold = null;
            aiRefreshFilteredGrid();
        }

function aiRefreshFilteredGrid() {
            if (CURATOR_NATIVE && currentBatch && currentFolder && !isVirtualCollectionView() && !isPublicView()) {
                loadCurrentFolderImages({preserveScroll: true});
                return;
            }
            updateGrid();
        }

function aiShowHeaderControls(show) {
            const controls = document.getElementById('ai-display-controls');
            const scoreBtn = document.getElementById('sort-btn-score-desc');
            if (controls) controls.style.display = show ? 'flex' : 'none';
            if (scoreBtn) scoreBtn.style.display = show ? '' : 'none';
            // If hiding, also uncheck overlays and reset filter
            if (!show) {
                aiShowOverlays = false;
                aiFilterMode = 'all';
                aiAppliedThreshold = null;
                const toggle = document.getElementById('ai-overlay-toggle');
                if (toggle) toggle.checked = false;
                const filter = document.getElementById('ai-filter-mode');
                if (filter) filter.value = 'all';
            }
        }

function aiGetNormalizedScore(result) {
            if (!result || result.failed) return null;
            const normalized = Number(result.normalized_score);
            if (Number.isFinite(normalized) && normalized >= 0) return normalized;
            const score = Number(result.score);
            const total = Number(result.total);
            if (!Number.isFinite(score) || !Number.isFinite(total) || total <= 0 || score < 0) return null;
            return Math.round((score / total) * 100);
        }

function aiBuildThresholdPreview(results, cutoff) {
            const threshold = Math.max(0, Math.min(100, Number(cutoff) || 0));
            const counts = {atOrAbove: 0, below: 0, failed: 0, unscored: 0};
            const scores = [];
            for (const result of Array.isArray(results) ? results : []) {
                if (result?.failed) {
                    counts.failed += 1;
                    continue;
                }
                const score = aiGetNormalizedScore(result);
                if (score === null) {
                    counts.unscored += 1;
                    continue;
                }
                scores.push(score);
                if (score >= threshold) counts.atOrAbove += 1;
                else counts.below += 1;
            }
            return {
                cutoff: threshold,
                atOrAbove: counts.atOrAbove,
                below: counts.below,
                scored: counts.atOrAbove + counts.below,
                failed: counts.failed,
                unscored: counts.unscored,
                range: scores.length > 0 ? {min: Math.min(...scores), max: Math.max(...scores)} : null,
            };
        }

function aiApplyThresholdFilter() {
            if (!aiActiveRun) return;
            const input = document.getElementById('ai-score-threshold');
            const threshold = Math.max(0, Math.min(100, Number(input?.value) || 0));
            const preview = aiBuildThresholdPreview(aiActiveRun.results, threshold);
            if (preview.scored === 0) {
                aiRenderThresholdPreview(aiActiveRun);
                return;
            }
            aiThresholdValue = threshold;
            aiAppliedThreshold = threshold;
            aiFilterMode = 'threshold';
            aiShowOverlays = true;
            const overlayToggle = document.getElementById('ai-overlay-toggle');
            if (overlayToggle) overlayToggle.checked = true;
            const filter = document.getElementById('ai-filter-mode');
            if (filter && [...filter.options].some(option => option.value === 'threshold')) filter.value = 'threshold';
            aiRenderThresholdPreview(aiActiveRun);
            aiRefreshFilteredGrid();
        }

function aiClearThresholdFilter() {
            aiAppliedThreshold = null;
            aiFilterMode = 'all';
            const filter = document.getElementById('ai-filter-mode');
            if (filter) filter.value = 'all';
            aiRefreshFilteredGrid();
            aiRenderThresholdPreview(aiActiveRun);
        }

function aiRenderThresholdPreview(run = aiActiveRun) {
            const panel = document.getElementById('ai-threshold-preview');
            const status = document.getElementById('ai-threshold-preview-status');
            const input = document.getElementById('ai-score-threshold');
            const applyButton = document.getElementById('ai-threshold-apply');
            if (!panel || !status || !input) return;
            if (!run || !Array.isArray(run.results)) {
                panel.hidden = true;
                if (applyButton) applyButton.disabled = true;
                return;
            }
            const threshold = Math.max(0, Math.min(100, Number(input.value) || 0));
            aiThresholdValue = threshold;
            const preview = aiBuildThresholdPreview(run.results, threshold);
            if (applyButton) applyButton.disabled = preview.scored === 0;
            if (preview.scored === 0) {
                status.textContent = `No scored images in this run. Failed: ${preview.failed} · Unscored/unknown: ${preview.unscored}.`;
            } else {
                const range = preview.range ? ` · scored range ${preview.range.min}%–${preview.range.max}%` : '';
                status.textContent = `At or above ${preview.cutoff}%: ${preview.atOrAbove} · Below: ${preview.below} · Failed: ${preview.failed} · Unscored/unknown: ${preview.unscored}${range}`;
            }
            panel.hidden = false;
            panel.classList.toggle('is-applied', aiAppliedThreshold !== null && aiAppliedThreshold === threshold);
        }

function aiGetImageScore(filename) {
            if (!aiActiveRun || !aiActiveRun.results) return null;
            if (!aiActiveRun.resultMap) {
                aiActiveRun.resultMap = new Map(aiActiveRun.results.map(r => [r.filename, r]));
            }
            return aiActiveRun.resultMap.get(filename) || null;
        }

function aiShouldShowImage(img) {
            if (!aiActiveRun || !aiShowOverlays) return true;
            const result = aiGetImageScore(img.name);
            if (aiFilterMode === 'scored') return result && !result.failed;
            if (aiFilterMode === 'failed') return result && result.failed;
            if (aiFilterMode === 'threshold') {
                const score = aiGetNormalizedScore(result);
                return score !== null && score >= (aiAppliedThreshold ?? 0);
            }
            if (aiFilterMode === 'top-n') {
                if (!result || result.failed) return false;
                // Check if this image is in the top-N
                if (!aiActiveRun.topNSet) {
                    const scored = aiActiveRun.results
                        .filter(r => !r.failed)
                        .sort((a, b) => b.score - a.score);
                    aiActiveRun.topNSet = new Set(scored.slice(0, aiActiveRun.top_n).map(r => r.filename));
                }
                return aiActiveRun.topNSet.has(img.name);
            }
            return true;
        }

function aiSortImages(imgList) {
            if (!aiActiveRun || currentSort !== 'score-desc') return imgList;
            return [...imgList].sort((a, b) => {
                const sa = aiGetImageScore(a.name);
                const sb = aiGetImageScore(b.name);
                const scoreA = sa && !sa.failed ? sa.score : -999;
                const scoreB = sb && !sb.failed ? sb.score : -999;
                return scoreB - scoreA;
            });
        }

function aiScoreGradient(score, total) {
            // Dark red (0%) -> Dark yellow (50%) -> Green (100%)
            // Kept dark enough for white text readability on dark thumbnails
            if (total <= 0) return '';
            const pct = score / total;
            let r, g;
            if (pct < 0.5) {
                r = Math.round(160 + 40 * (pct * 2));
                g = Math.round(30 + 90 * (pct * 2));
            } else {
                r = Math.round(200 - 170 * ((pct - 0.5) * 2));
                g = Math.round(120 + 40 * ((pct - 0.5) * 2));
            }
            return `background:rgba(${r},${g},35,0.88)`;
        }

async function aiLoadBatchRunCounts(batches) {
            // Fetch run counts for specified batches (or all if not specified)
            const targetBatches = batches || (allCounts ? Object.keys(allCounts) : []);
            if (targetBatches.length === 0) return;
            const promises = targetBatches.map(async batch => {
                try {
                    const resp = await fetch(ccApiPath(`/api/ai-curate/batches/${batch}/runs`));
                    const data = await resp.json();
                    aiBatchRunCounts[batch] = data.runs ? data.runs.length : 0;
                } catch { console.warn(`aiLoadBatchRunCounts failed for ${batch}`); aiBatchRunCounts[batch] = 0; }
            });
            await Promise.all(promises);
            aiBatchRunCountsLoaded = true;
        }
