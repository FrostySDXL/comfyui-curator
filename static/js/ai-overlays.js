/* Ordered classic script.
 * Defines: AI grid overlays, filtering, sorting, score helpers, and batch run counts.
 */
function aiToggleOverlays() {
            aiShowOverlays = document.getElementById('ai-overlay-toggle').checked;
            updateGrid();
        }

function aiApplyFilter() {
            aiFilterMode = document.getElementById('ai-filter-mode').value;
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
                const toggle = document.getElementById('ai-overlay-toggle');
                if (toggle) toggle.checked = false;
                const filter = document.getElementById('ai-filter-mode');
                if (filter) filter.value = 'all';
            }
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
                    const resp = await fetch(`/api/ai-curate/batches/${batch}/runs`);
                    const data = await resp.json();
                    aiBatchRunCounts[batch] = data.runs ? data.runs.length : 0;
                } catch { console.warn(`aiLoadBatchRunCounts failed for ${batch}`); aiBatchRunCounts[batch] = 0; }
            });
            await Promise.all(promises);
            aiBatchRunCountsLoaded = true;
        }
