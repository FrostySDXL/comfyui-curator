/* Ordered classic script.
 * Defines: AI run history, run selection, summary, diff, and batch reset helpers.
 */
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
                historySection.classList.add('hidden');
                return;
            }
            historySection.classList.remove('hidden');
            const runOptions = aiRunIds.map(id => ({
                value: id,
                label: formatAiRunLabel(aiRunDetails[id] || {run_id: id}),
            }));
            aiPopulateRunSelect('ai-run-select', runOptions, aiActiveRun?.run_id || '', {
                value: '',
                label: '-- Active run --',
            });
            aiSyncCompareSelect();
            aiSetPanelTab(aiActivePanelTab);
        }

async function aiRenderCurrentRunUi() {
            if (aiActiveRun) {
                aiShowRunSummary(aiActiveRun);
                await aiShowRunDiff(aiActiveRun);
                aiShowHeaderControls(true);
                aiUpdateRunHistoryUi();
            } else {
                document.getElementById('ai-run-summary').classList.add('hidden');
                document.getElementById('ai-run-diff').classList.add('hidden');
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
                    if (historySection) historySection.classList.add('hidden');
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
            document.getElementById('ai-run-summary').classList.add('hidden');
            document.getElementById('ai-run-diff').classList.add('hidden');
            aiRenderImageInspector();
            const runSelect = document.getElementById('ai-run-select');
            if (runSelect) runSelect.value = '';
            const compareSelect = document.getElementById('ai-compare-run-select');
            if (compareSelect) compareSelect.value = 'previous';
            if (refreshGrid) updateGrid();
        }

function aiShowRunSummary(run) {
            const summary = document.getElementById('ai-run-summary');
            const t = run.totals || {};
            const modeLabel = run.move_enabled ? `Move top-${run.top_n} to ${run.destination_folder}` : 'Score only';

            const brief = document.createElement('div');
            brief.className = 'ai-run-brief';
            const headerLeft = document.createElement('div');
            const titleEl = document.createElement('div');
            titleEl.className = 'ai-run-summary-title';
            titleEl.textContent = formatAiRunLabel(run);
            const subtitleEl = document.createElement('div');
            subtitleEl.className = 'ai-run-summary-subtitle';
            subtitleEl.textContent = modeLabel;
            headerLeft.append(titleEl, subtitleEl);
            const statusBadge = document.createElement('span');
            statusBadge.className = 'ai-run-badge';
            statusBadge.textContent = run.status || 'completed';
            brief.append(headerLeft, statusBadge);

            const stats = document.createElement('div');
            stats.className = 'ai-run-kpis';
            function addStatCard(label, value) {
                const card = document.createElement('div');
                card.className = 'ai-run-kpi';
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

            summary.replaceChildren(brief, stats);
            summary.classList.remove('hidden');
            summary.style.display = 'block';
        }

async function aiLoadRun(runId) {
            if (!runId) {
                aiActiveRun = aiLatestRun;
                if (aiActiveRun) {
                    await aiRenderCurrentRunUi();
                } else {
                document.getElementById('ai-run-summary').classList.add('hidden');
                document.getElementById('ai-run-diff').classList.add('hidden');
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
                diffEl.classList.add('hidden');
                return;
            }
            const previousId = aiGetPreviousRunId();
            const compareRun = aiCompareRunId === 'previous'
                ? (previousId ? aiRunDetails[previousId] || await aiFetchRun(previousId) : null)
                : aiRunDetails[aiCompareRunId] || await aiFetchRun(aiCompareRunId);
            if (!compareRun || run.run_id === compareRun.run_id) {
                diffEl.innerHTML = `<div class="ai-diff-empty">Need another run to compare.</div>`;
                diffEl.classList.remove('hidden');
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
                <div class="ai-diff-list">
                    <div><strong>${scoreChanged}</strong> scores changed</div>
                    <div><strong>${failedStateChanged}</strong> failure flips</div>
                    <div><strong>${newImages}</strong> only in current</div>
                    <div><strong>${removedImages}</strong> only in baseline</div>
                </div>
                ${scoreChanged === 0 && failedStateChanged === 0 && newImages === 0 && removedImages === 0
                    ? '<div class="ai-diff-empty">These runs produced identical per-image results.</div>'
                    : `<div class="ai-diff-notes">
                        <span class="ai-diff-note">Shared images compared: ${totalCompared}</span>
                        <span class="ai-diff-note">Unchanged scores: ${identicalScores}</span>
                        ${notes.map(note => `<span class="ai-diff-note">${_escapeHtml(note)}</span>`).join('')}
                    </div>`}
            `;
            diffEl.classList.remove('hidden');
            diffEl.style.display = 'block';
            aiSyncCompareSelect();
        }
