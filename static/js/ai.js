/* Ordered classic script.
 * Defines: AI sidebar state, optional elements, jobs, run history, overlays, score helpers.
 */
        let aiPanelOpen = true;
        let aiSidebarOpen = true;
        let aiCurrentJobId = null;
        let aiPollTimer = null;
        let aiActiveRun = null;  // The run currently displayed (from history or active job)
        let aiLatestRun = null;  // The latest completed run for comparison
        let aiRunIds = [];
        let aiRunDetails = {};
        let aiCompareRunId = 'latest';
        let aiShowOverlays = false;
        let aiFilterMode = 'all';
        let aiBatchRunCounts = {};  // batch -> number of AI runs (for sidebar indicator)
        let aiBatchRunCountsLoaded = false;  // true after first successful load
        const AI_SIDEBAR_WIDTH_KEY = 'imageCurator.aiSidebarWidth';
        const AI_SIDEBAR_OPEN_KEY = 'imageCurator.aiSidebarOpen';
        const AI_PANEL_OPEN_KEY = 'imageCurator.aiPanelOpen';
        const AI_SIDEBAR_WIDTH_DEFAULT = 360;
        const AI_SIDEBAR_WIDTH_MIN = 280;
        const AI_SIDEBAR_WIDTH_MAX = 560;
        let aiSidebarWidth = AI_SIDEBAR_WIDTH_DEFAULT;
        let isAiSidebarResizing = false;
        let _aiSidebarResizePending = false;
        let _aiSidebarResizeLastEvent = null;

function clampAiSidebarWidth(value) {
            return Math.max(AI_SIDEBAR_WIDTH_MIN, Math.min(AI_SIDEBAR_WIDTH_MAX, value));
        }

function applyAiSidebarWidth(value, persist = true) {
            aiSidebarWidth = clampAiSidebarWidth(value);
            document.documentElement.style.setProperty('--ai-sidebar-width', `${aiSidebarWidth}px`);
            if (persist) localStorage.setItem(AI_SIDEBAR_WIDTH_KEY, String(aiSidebarWidth));
        }

function initializeAiSidebarState() {
            const widthRaw = localStorage.getItem(AI_SIDEBAR_WIDTH_KEY);
            const widthParsed = widthRaw ? parseInt(widthRaw, 10) : AI_SIDEBAR_WIDTH_DEFAULT;
            applyAiSidebarWidth(Number.isFinite(widthParsed) ? widthParsed : AI_SIDEBAR_WIDTH_DEFAULT, false);

            const sidebarOpenRaw = localStorage.getItem(AI_SIDEBAR_OPEN_KEY);
            aiSidebarOpen = sidebarOpenRaw === null ? true : sidebarOpenRaw === 'true';
            const panelOpenRaw = localStorage.getItem(AI_PANEL_OPEN_KEY);
            aiPanelOpen = panelOpenRaw === null ? true : panelOpenRaw === 'true';
            syncAiSidebarUi(false);
        }

function syncAiSidebarUi(persist = true) {
            const shell = document.getElementById('ai-sidebar-shell');
            const panel = document.getElementById('ai-curate-panel');
            const toggle = document.getElementById('ai-curate-toggle');
            const body = document.getElementById('ai-curate-body');
            const headerBtn = document.getElementById('ai-sidebar-toggle-btn');
            if (shell) {
                shell.classList.remove('hidden');
                shell.style.display = currentBatch ? 'flex' : 'none';
                shell.classList.toggle('collapsed', !aiSidebarOpen);
            }
            if (panel) panel.classList.toggle('collapsed', !aiPanelOpen);
            if (body) body.style.display = aiPanelOpen ? 'block' : 'none';
            if (toggle) toggle.textContent = aiPanelOpen ? '−' : '+';
            if (headerBtn) {
                if (currentBatch) {
                    headerBtn.classList.remove('hidden');
                    headerBtn.textContent = aiSidebarOpen ? 'Hide AI' : 'Show AI';
                } else {
                    headerBtn.classList.add('hidden');
                }
            }
            if (persist) {
                localStorage.setItem(AI_SIDEBAR_OPEN_KEY, String(aiSidebarOpen));
                localStorage.setItem(AI_PANEL_OPEN_KEY, String(aiPanelOpen));
            }
        }

function toggleAiCuratePanel() {
            aiPanelOpen = !aiPanelOpen;
            syncAiSidebarUi();
        }

function toggleAiSidebar() {
            aiSidebarOpen = !aiSidebarOpen;
            syncAiSidebarUi();
        }

function onAiSidebarResizeMove(event) {
            if (!isAiSidebarResizing) return;
            _aiSidebarResizeLastEvent = event;
            if (!_aiSidebarResizePending) {
                _aiSidebarResizePending = true;
                requestAnimationFrame(() => {
                    _aiSidebarResizePending = false;
                    if (!isAiSidebarResizing || !_aiSidebarResizeLastEvent) return;
                    applyAiSidebarWidth(window.innerWidth - _aiSidebarResizeLastEvent.clientX);
                });
            }
        }

function stopAiSidebarResize() {
            if (!isAiSidebarResizing) return;
            isAiSidebarResizing = false;
            document.body.classList.remove('resizing-layout');
            const resizer = document.getElementById('ai-sidebar-resizer');
            if (resizer) resizer.classList.remove('active');
            document.removeEventListener('mousemove', onAiSidebarResizeMove);
            document.removeEventListener('mouseup', stopAiSidebarResize);
            document.removeEventListener('pointermove', onAiSidebarResizeMove);
            document.removeEventListener('pointerup', stopAiSidebarResize);
        }

function startAiSidebarResize(event) {
            if (event.type === 'mousedown' && window.PointerEvent) return;
            if (!aiSidebarOpen) return;
            event.preventDefault();
            isAiSidebarResizing = true;
            document.body.classList.add('resizing-layout');
            const resizer = document.getElementById('ai-sidebar-resizer');
            if (resizer) resizer.classList.add('active');
            if (event.type === 'pointerdown') {
                document.addEventListener('pointermove', onAiSidebarResizeMove);
                document.addEventListener('pointerup', stopAiSidebarResize);
            } else {
                document.addEventListener('mousemove', onAiSidebarResizeMove);
                document.addEventListener('mouseup', stopAiSidebarResize);
            }
        }

function showAiCuratePanel() {
            syncAiSidebarUi(false);
            if (!currentBatch) return;
            aiRefreshRunData().catch(() => {});
            aiLoadElementHistory();
            aiPopulateOptionalElements();
        }

function toggleAiOptionalSection() {
            const body = document.getElementById('ai-optional-body');
            const header = document.getElementById('ai-optional-header');
            if (!body || !header) return;
            const isOpen = !body.classList.contains('hidden');
            body.classList.toggle('hidden', isOpen);
            header.setAttribute('aria-expanded', String(!isOpen));
            const arrow = header.querySelector('.ai-optional-arrow');
            // After toggle: section is closed when it WAS open.
            // Arrow points right (collapsed) when now-closed.
            if (arrow) arrow.style.transform = isOpen ? 'rotate(-90deg)' : '';
        }

function aiCollectQualityFlags() {
            const flags = [];
            const body = document.getElementById('ai-optional-body');
            if (!body) return flags;
            body.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                if (cb.dataset.key) flags.push(cb.dataset.key);
            });
            return flags;
        }

function aiPopulateOptionalElements() {
            const body = document.getElementById('ai-optional-body');
            if (!body) return;
            // Fetch QUALITY_CHECKS from the server via the preview-elements route.
            // We cache the result in a module-scoped variable so this only
            // happens once per session.
            if (aiQualityChecksCache) {
                _renderOptionalCheckboxes(body, aiQualityChecksCache);
                return;
            }
            // Issue a minimal preview call to discover the full element set
            // that includes quality defaults.  We piggyback on preview-elements
            // with a single dummy element so the response has the quality
            // elements appended.  Then extract only the quality ones.
            fetch('/api/ai-curate/preview-elements', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({elements: ['x']}),
            }).then(r => r.json()).then(data => {
                if (data.elements) {
                    // Filter to just the quality elements (those that appear after 'x')
                    const xIdx = data.elements.indexOf('x');
                    if (xIdx >= 0) {
                        aiQualityChecksCache = data.elements.slice(xIdx + 1);
                    } else {
                        aiQualityChecksCache = data.elements.slice(1);
                    }
                } else {
                    aiQualityChecksCache = [];
                }
                _renderOptionalCheckboxes(body, aiQualityChecksCache);
            }).catch(() => {});
        }

let aiQualityChecksCache = null;

function _renderOptionalCheckboxes(body, qualityElements) {
            body.replaceChildren();
            if (qualityElements.length === 0) {
                body.textContent = 'No optional elements available.';
                return;
            }
            // Map each quality element text to a stable key.
            // The keys match QUALITY_CHECKS in ai_curate/elements.py.
            const keyMap = {
                'Clean anatomy (no extra fingers, extra limbs, or broken body parts)': 'anatomy',
                'No visual artifacts, glitches, or garbled text': 'artifacts',
            };
            qualityElements.forEach(text => {
                const key = keyMap[text] || text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
                const label = document.createElement('label');
                label.className = 'ai-checkbox-label ai-optional-check';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.dataset.key = key;
                label.appendChild(cb);
                label.appendChild(document.createTextNode(' ' + text));
                body.appendChild(label);
            });
        }

async function aiLoadElementHistory() {
            const container = document.getElementById('ai-element-history');
            const select = document.getElementById('ai-history-select');
            if (!container || !select || !currentBatch) return;
            try {
                const resp = await fetch(`/api/ai-curate/batches/${currentBatch}/element-history?limit=10`);
                if (!resp.ok) return;
                const data = await resp.json();
                const items = data.history || [];
                select.innerHTML = '<option value="">-- Select a previous set --</option>';
                if (items.length === 0) {
                    container.classList.add('hidden');
                    return;
                }
                container.classList.remove('hidden');
                items.forEach(item => {
                    const option = document.createElement('option');
                    option.value = item.elements.join('\n');
                    const ts = item.timestamp ? new Date(item.timestamp) : null;
                    const label = ts && !Number.isNaN(ts.getTime())
                        ? new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}).format(ts)
                        : item.run_id;
                    const preview = item.elements.length > 3
                        ? item.elements.slice(0, 3).join(', ') + '...'
                        : item.elements.join(', ');
                    option.textContent = `${label} — ${preview}`;
                    select.appendChild(option);
                });
            } catch { console.warn('aiLoadElementHistory failed'); }
        }

function formatAiRunTimestamp(run) {
            if (run?.created_at) {
                const timestamp = new Date(run.created_at);
                if (!Number.isNaN(timestamp.getTime())) {
                    return new Intl.DateTimeFormat(undefined, {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                        hour: 'numeric',
                        minute: '2-digit',
                    }).format(timestamp);
                }
            }
            return run?.run_id || 'Unknown run';
        }

function formatAiRunLabel(run, includeStatus = false) {
            if (!run) return 'Unknown run';
            const pieces = [formatAiRunTimestamp(run)];
            if (run.model) pieces.push(run.model);
            if (includeStatus && run.status) pieces.push(run.status);
            return pieces.join(' · ');
        }

async function aiFetchRun(runId) {
            if (!runId) return null;
            if (aiRunDetails[runId]) return aiRunDetails[runId];
            const resp = await fetch(`/api/ai-curate/batches/${currentBatch}/runs/${runId}`);
            if (!resp.ok) return null;
            const run = await resp.json();
            aiRunDetails[runId] = run;
            return run;
        }

function aiPopulateRunSelect(selectId, options, selectedValue, placeholder) {
            const select = document.getElementById(selectId);
            if (!select) return;
            select.innerHTML = '';
            if (placeholder) {
                const option = document.createElement('option');
                option.value = placeholder.value;
                option.textContent = placeholder.label;
                select.appendChild(option);
            }
            options.forEach(({value, label}) => {
                const option = document.createElement('option');
                option.value = value;
                option.textContent = label;
                select.appendChild(option);
            });
            select.value = selectedValue;
        }

function aiSyncCompareSelect() {
            const compareSelect = document.getElementById('ai-compare-run-select');
            if (!compareSelect || aiRunIds.length === 0) return;
            const compareOptions = [
                {
                    value: 'latest',
                    label: aiLatestRun ? `Latest completed · ${formatAiRunLabel(aiLatestRun)}` : 'Latest completed run',
                },
                ...aiRunIds
                    .filter(id => id !== aiActiveRun?.run_id)
                    .map(id => ({
                        value: id,
                        label: formatAiRunLabel(aiRunDetails[id] || {run_id: id}),
                    }))
            ];
            const desiredValue = aiCompareRunId === 'latest' || compareOptions.some(option => option.value === aiCompareRunId)
                ? aiCompareRunId
                : 'latest';
            aiCompareRunId = desiredValue;
            aiPopulateRunSelect('ai-compare-run-select', compareOptions, desiredValue, null);
        }

function aiUpdateRunHistoryUi() {
            const historySection = document.getElementById('ai-history-section');
            if (!historySection) return;
            if (aiRunIds.length === 0) {
                historySection.style.display = 'none';
                return;
            }
            historySection.style.display = 'block';
            const runOptions = aiRunIds.map(id => ({
                value: id,
                label: formatAiRunLabel(aiRunDetails[id] || {run_id: id}),
            }));
            aiPopulateRunSelect('ai-run-select', runOptions, aiActiveRun?.run_id || '', {
                value: '',
                label: '-- Active run --',
            });
            aiSyncCompareSelect();
        }

async function aiRenderCurrentRunUi() {
            if (aiActiveRun) {
                aiShowRunSummary(aiActiveRun);
                await aiShowRunDiff(aiActiveRun);
                aiShowHeaderControls(true);
                aiUpdateRunHistoryUi();
            } else {
                document.getElementById('ai-run-summary').style.display = 'none';
                document.getElementById('ai-run-diff').style.display = 'none';
                aiShowHeaderControls(false);
            }
        }

async function aiRefreshRunData(existingRuns = null) {
            if (!currentBatch) return;
            try {
                const runs = existingRuns || (await fetch(`/api/ai-curate/batches/${currentBatch}/runs`).then(resp => resp.json()).then(data => data.runs || []));
                aiRunIds = runs;
                if (runs.length > 0) {
                    await Promise.all(runs.map(aiFetchRun));
                    const latestId = runs[runs.length - 1];
                    aiLatestRun = aiRunDetails[latestId] || null;
                    if (!aiActiveRun || !runs.includes(aiActiveRun.run_id) || aiActiveRun.run_id === latestId) {
                        aiActiveRun = aiLatestRun;
                    }
                    await aiRenderCurrentRunUi();
                } else {
                    const historySection = document.getElementById('ai-history-section');
                    if (historySection) historySection.style.display = 'none';
                    aiRunIds = [];
                    aiRunDetails = {};
                    aiLatestRun = null;
                    aiActiveRun = null;
                    aiCompareRunId = 'latest';
                    await aiRenderCurrentRunUi();
                }
            } catch { console.warn('aiRefreshRunData failed'); }
        }

function resetAiBatchState(refreshGrid = true) {
            aiCurrentJobId = null;
            aiStopPolling();
            aiActiveRun = null;
            aiLatestRun = null;
            aiRunIds = [];
            aiRunDetails = {};
            aiCompareRunId = 'latest';
            aiShowHeaderControls(false);
            document.getElementById('ai-run-summary').style.display = 'none';
            document.getElementById('ai-run-diff').style.display = 'none';
            const runSelect = document.getElementById('ai-run-select');
            if (runSelect) runSelect.value = '';
            const compareSelect = document.getElementById('ai-compare-run-select');
            if (compareSelect) compareSelect.value = 'latest';
            if (refreshGrid) updateGrid();
        }

function aiToggleMoveMode() {
            const moveToggle = document.getElementById('ai-move-toggle');
            const destField = document.getElementById('ai-dest-field');
            const submitBtn = document.getElementById('ai-submit-btn');
            if (moveToggle.checked) {
                destField.style.display = 'block';
                submitBtn.textContent = 'Score and move top-N';
            } else {
                destField.style.display = 'none';
                submitBtn.textContent = 'Score only';
            }
        }

async function aiPreviewElements() {
            const elementsText = document.getElementById('ai-elements').value.trim();
            if (!elementsText) {
                showToast('Enter elements first (one per line)');
                return;
            }
            const elements = elementsText.split('\n').map(e => e.trim()).filter(e => e.length > 0);
            if (elements.length === 0) {
                showToast('Enter at least one element');
                return;
            }
            const qualityFlags = aiCollectQualityFlags();
            const body = {
                elements: elements,
                quality_flags: qualityFlags.length > 0 ? qualityFlags : null,
            };
            const resp = await fetch('/api/ai-curate/preview-elements', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            const data = await resp.json();
            if (data.error) {
                showToast(data.error);
                return;
            }
            const preview = document.getElementById('ai-elements-preview');
            preview.replaceChildren();
            const qualityStart = data.elements.findIndex(e =>
                e.includes('Clean anatomy') || e.includes('No visual artifacts')
            );
            data.elements.forEach((e, i) => {
                const isQuality = i >= qualityStart && qualityStart >= 0;
                const item = document.createElement('div');
                item.className = 'element-item';
                const numSpan = document.createElement('span');
                numSpan.className = 'element-num';
                numSpan.textContent = `${i + 1}.`;
                const textSpan = document.createElement('span');
                if (isQuality) textSpan.className = 'element-quality';
                textSpan.textContent = e;
                item.appendChild(numSpan);
                item.appendChild(textSpan);
                preview.appendChild(item);
            });
            preview.style.display = 'block';
        }

async function aiSubmitJob() {
            const elementsText = document.getElementById('ai-elements').value.trim();
            if (!elementsText) {
                showToast('Enter elements first (one per line)');
                return;
            }
            const elements = elementsText.split('\n').map(e => e.trim()).filter(e => e.length > 0);
            if (elements.length === 0) {
                showToast('Enter at least one element');
                return;
            }
            const moveEnabled = document.getElementById('ai-move-toggle').checked;
            const destFolder = document.getElementById('ai-dest-folder').value;
            const qualityFlags = aiCollectQualityFlags();

            const body = {
                batch: currentBatch,
                elements: elements,
                quality_flags: qualityFlags.length > 0 ? qualityFlags : null,
                source_folder: document.getElementById('ai-source-folder').value,
                top_n: parseInt(document.getElementById('ai-top-n').value) || 15,
                model: document.getElementById('ai-model').value.trim(),
                move_enabled: moveEnabled,
                destination_folder: moveEnabled ? destFolder : null,
            };

            const resp = await fetch('/api/ai-curate/jobs', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                showToast(errData.error || 'AI job submission failed');
                return;
            }
            const data = await resp.json();
            if (data.error) {
                showToast(data.error);
                return;
            }

            aiCurrentJobId = data.run_id;
            showToast(`AI curate job ${data.status}: ${data.run_id}`);
            aiShowJobStatus(data);
            aiStartPolling();
        }

function aiShowJobStatus(job) {
            const section = document.getElementById('ai-job-section');
            const stateEl = document.getElementById('ai-job-state');
            const progressEl = document.getElementById('ai-job-progress');
            const cancelBtn = document.getElementById('ai-cancel-btn');

            section.style.display = 'block';
            stateEl.textContent = job.status;
            stateEl.className = 'ai-job-state ' + job.status;

            // Show progress bar for running jobs
            if (job.status === 'running' && job.results) {
                const scored = job.results.filter(r => !r.failed).length;
                const failed = job.results.filter(r => r.failed).length;
                const total = job.totals?.images || 0;
                const done = scored + failed;
                const pct = total > 0 ? Math.round((done / total) * 100) : 0;
                progressEl.innerHTML = `<div class="ai-progress-bar"><div class="ai-progress-fill" style="width:${pct}%"></div></div><span class="ai-progress-text">${done}/${total}</span>`;
            } else {
                progressEl.innerHTML = '';
            }

            // Show cancel button for queued or running jobs
            cancelBtn.style.display = (job.status === 'queued' || job.status === 'running') ? 'inline-block' : 'none';

            // If completed, show run summary and history
            if (job.status === 'completed') {
                aiStopPolling();
                aiShowRunSummary(job);
                aiRefreshRunData().catch(() => { console.warn('aiRefreshRunData failed'); });
                aiActiveRun = job;
                aiLatestRun = job;
                aiShowHeaderControls(true);
                loadBatches();  // Refresh sidebar AI dots
                updateGrid();
            }
            if (job.status === 'cancelled' || job.status === 'failed') {
                aiStopPolling();
                aiRefreshRunData().catch(() => { console.warn('aiRefreshRunData failed'); });
            }
        }

function aiStartPolling() {
            aiStopPolling();
            aiPollTimer = setInterval(aiPollJobStatus, 2000);
        }

function aiStopPolling() {
            if (aiPollTimer) {
                clearInterval(aiPollTimer);
                aiPollTimer = null;
            }
        }

async function aiPollJobStatus() {
            if (!aiCurrentJobId) {
                aiStopPolling();
                return;
            }
            const resp = await fetch(`/api/ai-curate/jobs/${aiCurrentJobId}`);
            if (!resp.ok) {
                aiStopPolling();
                return;
            }
            const job = await resp.json();
            aiShowJobStatus(job);
        }

async function aiCancelJob() {
            if (!aiCurrentJobId) return;
            const resp = await fetch(`/api/ai-curate/jobs/${aiCurrentJobId}/cancel`, {method: 'POST'});
            const data = await resp.json();
            if (data.success) {
                showToast('Cancellation requested');
            } else {
                showToast(data.error || 'Cannot cancel this job');
            }
        }

function aiShowRunSummary(run) {
            const summary = document.getElementById('ai-run-summary');
            const t = run.totals || {};
            const modeLabel = run.move_enabled ? `Move top-${run.top_n} to ${run.destination_folder}` : 'Score only';

            // Build DOM tree instead of innerHTML to avoid XSS regression risk
            const header = document.createElement('div');
            header.className = 'ai-run-summary-header';
            const headerLeft = document.createElement('div');
            const titleEl = document.createElement('div');
            titleEl.className = 'ai-run-summary-title';
            titleEl.textContent = formatAiRunLabel(run);
            const subtitleEl = document.createElement('div');
            subtitleEl.className = 'ai-run-summary-subtitle';
            subtitleEl.textContent = `Run ID: ${run.run_id}`;
            headerLeft.append(titleEl, subtitleEl);
            const badges = document.createElement('div');
            badges.className = 'ai-run-summary-badges';
            const statusBadge = document.createElement('span');
            statusBadge.className = 'ai-run-badge';
            statusBadge.textContent = run.status || 'completed';
            const topBadge = document.createElement('span');
            topBadge.className = 'ai-run-badge';
            topBadge.textContent = `Top-N ${run.top_n}`;
            badges.append(statusBadge, topBadge);
            header.append(headerLeft, badges);

            const stats = document.createElement('div');
            stats.className = 'ai-run-summary-stats';
            function addStatCard(label, value) {
                const card = document.createElement('div');
                card.className = 'ai-stat-card';
                const lbl = document.createElement('div');
                lbl.className = 'ai-stat-label';
                lbl.textContent = label;
                const val = document.createElement('div');
                val.className = 'ai-stat-value';
                val.textContent = String(value);
                card.append(lbl, val);
                stats.appendChild(card);
            }
            addStatCard('Images', t.images || 0);
            addStatCard('Scored', t.scored || 0);
            addStatCard('Failed', t.failed || 0);
            addStatCard('Moved', t.moved || 0);

            const meta = document.createElement('div');
            meta.className = 'ai-run-summary-meta';
            function addMetaRow(label, value) {
                const row = document.createElement('div');
                row.className = 'ai-meta-row';
                const lbl = document.createElement('div');
                lbl.className = 'ai-meta-label';
                lbl.textContent = label;
                const val = document.createElement('div');
                val.className = 'ai-meta-value';
                val.textContent = value || '\u2014';
                row.append(lbl, val);
                meta.appendChild(row);
            }
            addMetaRow('Model', run.model);
            addMetaRow('Mode', modeLabel);

            summary.replaceChildren(header, stats, meta);
            summary.style.display = 'block';
        }

async function aiLoadRun(runId) {
            if (!runId) {
                aiActiveRun = aiLatestRun;
                if (aiActiveRun) {
                    await aiRenderCurrentRunUi();
                } else {
                    document.getElementById('ai-run-summary').style.display = 'none';
                    document.getElementById('ai-run-diff').style.display = 'none';
                    aiShowHeaderControls(false);
                }
                updateGrid();
                return;
            }
            const run = await aiFetchRun(runId);
            if (!run) {
                showToast('Failed to load run');
                return;
            }
            aiActiveRun = run;
            await aiRenderCurrentRunUi();
            updateGrid();
        }

async function aiSetCompareRun(runId) {
            aiCompareRunId = runId || 'latest';
            if (aiCompareRunId !== 'latest' && !aiRunDetails[aiCompareRunId]) {
                await aiFetchRun(aiCompareRunId);
            }
            await aiShowRunDiff(aiActiveRun);
        }

async function aiShowRunDiff(run) {
            const diffEl = document.getElementById('ai-run-diff');
            if (!diffEl) return;
            if (!run) {
                diffEl.style.display = 'none';
                return;
            }
            const compareRun = aiCompareRunId === 'latest' ? aiLatestRun : aiRunDetails[aiCompareRunId] || await aiFetchRun(aiCompareRunId);
            if (!compareRun || run.run_id === compareRun.run_id) {
                diffEl.innerHTML = `<div class="ai-diff-empty">Select a different run to compare against.</div>`;
                diffEl.style.display = 'block';
                aiSyncCompareSelect();
                return;
            }
            const currentResults = {};
            for (const r of run.results) currentResults[r.filename] = r;
            const compareResults = {};
            for (const r of compareRun.results) compareResults[r.filename] = r;

            let scoreChanged = 0, newImages = 0, removedImages = 0, failedStateChanged = 0, identicalScores = 0;
            for (const [name, r] of Object.entries(currentResults)) {
                if (!compareResults[name]) newImages++;
                else {
                    if (r.score !== compareResults[name].score) scoreChanged++;
                    else identicalScores++;
                    if (!!r.failed !== !!compareResults[name].failed) failedStateChanged++;
                }
            }
            for (const name of Object.keys(compareResults)) {
                if (!currentResults[name]) removedImages++;
            }
            const totalCompared = Object.keys(currentResults).filter(name => compareResults[name]).length;
            const notes = [];
            if ((run.model || '') !== (compareRun.model || '')) notes.push(`Model changed: ${_escapeHtml(compareRun.model) || '—'} → ${_escapeHtml(run.model) || '—'}`);
            if ((run.top_n || 0) !== (compareRun.top_n || 0)) notes.push(`Top-N changed: ${compareRun.top_n || 0} → ${run.top_n || 0}`);
            if (!!run.move_enabled !== !!compareRun.move_enabled || (run.destination_folder || '') !== (compareRun.destination_folder || '')) {
                const fromMode = compareRun.move_enabled ? `Move to ${_escapeHtml(compareRun.destination_folder)}` : 'Score only';
                const toMode = run.move_enabled ? `Move to ${_escapeHtml(run.destination_folder)}` : 'Score only';
                notes.push(`Mode changed: ${fromMode} → ${toMode}`);
            }

            diffEl.innerHTML = `
                <div class="ai-diff-header">
                    <div class="ai-diff-title">Comparing ${_escapeHtml(formatAiRunTimestamp(run))}</div>
                    <div class="ai-diff-subtitle">against ${_escapeHtml(formatAiRunLabel(compareRun))}</div>
                </div>
                <div class="ai-diff-grid">
                    <div class="ai-diff-card"><div class="ai-stat-label">Scores changed</div><div class="ai-stat-value">${scoreChanged}</div></div>
                    <div class="ai-diff-card"><div class="ai-stat-label">Failure flips</div><div class="ai-stat-value">${failedStateChanged}</div></div>
                    <div class="ai-diff-card"><div class="ai-stat-label">Only in current</div><div class="ai-stat-value">${newImages}</div></div>
                    <div class="ai-diff-card"><div class="ai-stat-label">Only in compare</div><div class="ai-stat-value">${removedImages}</div></div>
                </div>
                ${scoreChanged === 0 && failedStateChanged === 0 && newImages === 0 && removedImages === 0
                    ? '<div class="ai-diff-empty">These runs produced identical per-image results.</div>'
                    : `<div class="ai-diff-notes">
                        <span class="ai-diff-note">Shared images compared: ${totalCompared}</span>
                        <span class="ai-diff-note">Unchanged scores: ${identicalScores}</span>
                        ${notes.map(note => `<span class="ai-diff-note">${_escapeHtml(note)}</span>`).join('')}
                    </div>`}
            `;
            diffEl.style.display = 'block';
            aiSyncCompareSelect();
        }

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
