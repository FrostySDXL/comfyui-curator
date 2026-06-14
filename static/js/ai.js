/* Ordered classic script.
 * Defines: AI sidebar state, optional elements, jobs, run history, overlays, score helpers.
 */
        let aiSidebarOpen = true;
        let aiCurrentJobId = null;
        let aiPollTimer = null;
        let aiActiveRun = null;  // The run currently displayed (from history or active job)
        let aiLatestRun = null;  // The latest completed run for comparison
        let aiRunIds = [];
        let aiRunDetails = {};
        let aiCompareRunId = 'previous';
        let aiActivePanelTab = 'inspect';
        let aiShowOverlays = false;
        let aiFilterMode = 'all';
        let aiInspectedImageName = null;
        let aiBatchRunCounts = {};  // batch -> number of AI runs (for sidebar indicator)
        let aiBatchRunCountsLoaded = false;  // true after first successful load
        const AI_SIDEBAR_WIDTH_KEY = 'imageCurator.aiSidebarWidth';
        const AI_SIDEBAR_OPEN_KEY = 'imageCurator.aiSidebarOpen';
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
            syncAiSidebarUi(false);
            aiSetPanelTab(aiActivePanelTab);
        }

function syncAiSidebarUi(persist = true) {
            const shell = document.getElementById('ai-sidebar-shell');
            const headerBtn = document.getElementById('ai-sidebar-toggle-btn');
            if (shell) {
                shell.classList.remove('hidden');
                shell.style.display = currentBatch ? 'flex' : 'none';
                shell.classList.toggle('collapsed', !aiSidebarOpen);
            }
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
            }
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

function aiSetPanelTab(tabName) {
            aiActivePanelTab = ['inspect', 'score', 'runs'].includes(tabName) ? tabName : 'inspect';
            document.querySelectorAll('.ai-panel-tab').forEach(tab => {
                tab.classList.toggle('active', tab.dataset.aiTab === aiActivePanelTab);
            });
            document.querySelectorAll('.ai-panel-section').forEach(section => {
                section.style.display = section.dataset.aiPanelSection === aiActivePanelTab ? '' : 'none';
            });
            const reviewSection = document.getElementById('ai-review-section');
            if (reviewSection) reviewSection.style.display = aiActivePanelTab === 'inspect' ? '' : 'none';
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
            const previousId = aiGetPreviousRunId();
            const compareOptions = [
                {
                    value: 'previous',
                    label: previousId ? `Previous completed · ${formatAiRunLabel(aiRunDetails[previousId] || {run_id: previousId})}` : 'Need another run to compare',
                },
                ...aiRunIds
                    .filter(id => id !== aiActiveRun?.run_id)
                    .map(id => ({
                        value: id,
                        label: formatAiRunLabel(aiRunDetails[id] || {run_id: id}),
                    }))
            ];
            const desiredValue = aiCompareRunId === 'previous' || compareOptions.some(option => option.value === aiCompareRunId)
                ? aiCompareRunId
                : 'previous';
            aiCompareRunId = desiredValue;
            aiPopulateRunSelect('ai-compare-run-select', compareOptions, desiredValue, null);
        }

function aiGetPreviousRunId() {
            if (!aiActiveRun || aiRunIds.length < 2) return null;
            const activeIndex = aiRunIds.indexOf(aiActiveRun.run_id);
            if (activeIndex > 0) return aiRunIds[activeIndex - 1];
            return aiRunIds.find(id => id !== aiActiveRun.run_id) || null;
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
            aiRenderImageInspector();
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
                    aiCompareRunId = 'previous';
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
            aiCompareRunId = 'previous';
            aiInspectedImageName = null;
            aiShowHeaderControls(false);
            document.getElementById('ai-run-summary').style.display = 'none';
            document.getElementById('ai-run-diff').style.display = 'none';
            aiRenderImageInspector();
            const runSelect = document.getElementById('ai-run-select');
            if (runSelect) runSelect.value = '';
            const compareSelect = document.getElementById('ai-compare-run-select');
            if (compareSelect) compareSelect.value = 'previous';
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
            const statusDot = document.getElementById('ai-status-dot');

            section.style.display = 'block';
            section.classList.remove('hidden');
            stateEl.textContent = job.status;
            stateEl.className = 'ai-job-state ' + job.status;
            if (statusDot) statusDot.className = `ai-status-dot ${job.status}`;

            const isActive = job.status === 'running' || job.status === 'queued' || job.status === 'cancelling';
            progressEl.textContent = isActive ? 'Scoring in progress' : '';

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
            aiSetPanelTab(aiActivePanelTab);
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

function aiGetInspectedImage() {
            if (!aiInspectedImageName) return null;
            return images.find(img => img.name === aiInspectedImageName) || null;
        }

function aiSetInspectedImage(img) {
            aiInspectedImageName = img ? img.name : null;
            aiRenderImageInspector(img || null);
            if (typeof renderLightboxAiPanel === 'function') renderLightboxAiPanel();
            document.querySelectorAll('#grid .thumb').forEach(thumb => {
                thumb.classList.toggle('inspected', !!aiInspectedImageName && thumb.dataset.name === aiInspectedImageName);
            });
        }

function aiRenderImageInspector(img = null) {
            const inspector = document.getElementById('ai-image-inspector');
            if (!inspector) return;
            if (selectedImages.size > 1) {
                if (!document.getElementById('lightbox')?.classList.contains('active')) {
                    aiRenderSelectionInspector();
                    return;
                }
            }
            const target = img || aiGetInspectedImage();
            inspector.replaceChildren();
            inspector.className = 'ai-image-inspector';
            aiAppendImageInspectorContent(inspector, target);
        }

function aiRenderSelectionInspector() {
            const inspector = document.getElementById('ai-image-inspector');
            if (!inspector) return;
            inspector.replaceChildren();
            inspector.className = 'ai-image-inspector ai-selection-summary';

            const selected = images.filter(img => selectedImages.has(img.name));
            inspector.appendChild(createTextElement('div', 'ai-inspector-title', `${selected.length} selected`));

            if (!aiActiveRun) {
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No AI run selected for this batch.'));
                return;
            }

            const scored = [];
            let failed = 0;
            let unscored = 0;
            const missingCounts = new Map();
            selected.forEach(img => {
                const result = aiGetImageScore(img.name);
                if (!result) {
                    unscored += 1;
                    return;
                }
                if (result.failed) {
                    failed += 1;
                    return;
                }
                scored.push(result);
                if (aiActiveRun.elements && result.details) {
                    for (const [key, value] of Object.entries(result.details)) {
                        if (value === 'YES') continue;
                        const idx = parseInt(key, 10);
                        const element = aiActiveRun.elements[idx - 1] || `#${idx}`;
                        missingCounts.set(element, (missingCounts.get(element) || 0) + 1);
                    }
                }
            });

            const avg = scored.length > 0
                ? (scored.reduce((sum, result) => sum + result.score, 0) / scored.length).toFixed(1)
                : '—';
            const stats = document.createElement('div');
            stats.className = 'ai-selection-stats';
            [['Scored', scored.length], ['Failed', failed], ['Unscored', unscored], ['Avg', avg]].forEach(([label, value]) => {
                const stat = document.createElement('div');
                stat.className = 'ai-selection-stat';
                stat.append(createTextElement('div', 'ai-stat-label', label), createTextElement('div', 'ai-stat-value', String(value)));
                stats.appendChild(stat);
            });
            inspector.appendChild(stats);

            const common = [...missingCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
            inspector.appendChild(createTextElement('div', 'ai-inspector-empty-title', 'Common missing'));
            const details = document.createElement('div');
            details.className = 'ai-inspector-details';
            if (common.length === 0) {
                details.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No shared missing elements among scored selected images.'));
            } else {
                common.forEach(([element, count]) => {
                    const chip = document.createElement('div');
                    chip.className = 'ai-inspector-detail missing';
                    chip.textContent = `${count} × ${element}`;
                    details.appendChild(chip);
                });
            }
            inspector.appendChild(details);
        }

function aiAppendImageInspectorContent(inspector, target) {

            if (!currentBatch) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-title', 'Select a batch'));
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'AI inspection appears after a batch is open.'));
                return;
            }
            if (!target) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-title', 'Select an image'));
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'Click a thumbnail or navigate the lightbox to inspect AI details.'));
                return;
            }

            const header = document.createElement('div');
            header.className = 'ai-inspector-header';
            header.appendChild(createTextElement('div', 'ai-inspector-title', target.name));
            const source = getImageBatchAndFolder(target);
            header.appendChild(createTextElement('div', 'ai-inspector-subtitle', `${source.batch} / ${source.folder}`));
            inspector.appendChild(header);

            if (!aiActiveRun) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No AI run selected for this batch.'));
                return;
            }

            const result = aiGetImageScore(target.name);
            if (!result) {
                inspector.classList.add('ai-image-inspector-empty');
                inspector.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No AI score for this image in the active run.'));
                return;
            }

            const score = document.createElement('div');
            score.className = result.failed ? 'ai-inspector-score failed' : 'ai-inspector-score';
            score.textContent = result.failed ? 'FAIL' : `${result.score}/${result.total}`;
            inspector.appendChild(score);

            const details = document.createElement('div');
            details.className = 'ai-inspector-details';
            if (result.failed) {
                details.appendChild(createTextElement('div', 'ai-inspector-empty-detail', result.error || 'Scoring failed for this image.'));
            } else if (aiActiveRun.elements && result.details) {
                for (const [key, value] of Object.entries(result.details)) {
                    const idx = parseInt(key, 10);
                    const element = aiActiveRun.elements[idx - 1] || `#${idx}`;
                    const matched = value === 'YES';
                    const detailChip = document.createElement('div');
                    detailChip.className = `ai-inspector-detail ${matched ? 'matched' : 'missing'}`;
                    detailChip.textContent = `${matched ? 'YES' : 'NO'} · ${element}`;
                    details.appendChild(detailChip);
                }
            } else {
                details.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'No element details were saved for this score.'));
            }
            inspector.appendChild(details);
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
            aiCompareRunId = runId || 'previous';
            if (aiCompareRunId !== 'previous' && !aiRunDetails[aiCompareRunId]) {
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
            const previousId = aiGetPreviousRunId();
            const compareRun = aiCompareRunId === 'previous'
                ? (previousId ? aiRunDetails[previousId] || await aiFetchRun(previousId) : null)
                : aiRunDetails[aiCompareRunId] || await aiFetchRun(aiCompareRunId);
            if (!compareRun || run.run_id === compareRun.run_id) {
                diffEl.innerHTML = `<div class="ai-diff-empty">Need another run to compare.</div>`;
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
                    <div class="ai-diff-title">Delta from baseline</div>
                    <div class="ai-diff-subtitle">${_escapeHtml(formatAiRunTimestamp(run))} vs ${_escapeHtml(formatAiRunLabel(compareRun))}</div>
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
