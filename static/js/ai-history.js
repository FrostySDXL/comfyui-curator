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

async function aiFetchRun(runId, batch = currentBatch) {
            if (!runId) return null;
            if (aiRunDetails[runId]) return aiRunDetails[runId];
            const resp = await fetch(ccApiPath(`/api/ai-curate/batches/${batch}/runs/${runId}`));
            if (!resp.ok) return null;
            const run = await resp.json();
            if (currentBatch !== batch) return null;
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

function aiSetRunsState(message, kind = '') {
            const state = document.getElementById('ai-runs-state');
            if (!state) return;
            state.textContent = message;
            state.className = `ai-runs-state${kind ? ` ${kind}` : ''}`;
            state.classList.toggle('hidden', !message);
        }

function aiUpdateRunHistoryUi() {
            const historySection = document.getElementById('ai-history-section');
            const inspectControls = document.getElementById('ai-inspect-controls');
            if (!historySection && !inspectControls) return;

            if (aiRunIds.length === 0) {
                if (historySection) {
                    historySection.classList.remove('hidden');
                    const controls = historySection.querySelector('.ai-history-controls');
                    if (controls) controls.classList.add('hidden');
                    aiSetRunsState('No runs saved for this batch. Configure one in Score.');
                }
                if (inspectControls) {
                    inspectControls.classList.add('hidden');
                    inspectControls.querySelector('select').innerHTML = '';
                }
                aiSetPanelTab(aiActivePanelTab);
                return;
            }
            if (historySection) {
                historySection.classList.remove('hidden');
                const controls = historySection.querySelector('.ai-history-controls');
                if (controls) controls.classList.remove('hidden');
                aiSetRunsState('');
            }
            const runOptions = aiRunIds.map(id => ({
                value: id,
                label: formatAiRunLabel(aiRunDetails[id] || {run_id: id}),
            }));
            // Populate Runs tab selector
            aiPopulateRunSelect('ai-run-select', runOptions, aiActiveRun?.run_id || '', {
                value: '',
                label: '-- Active run --',
            });
            // Populate Inspect tab selector (no placeholder — always has a value)
            if (inspectControls) {
                inspectControls.classList.remove('hidden');
                aiPopulateRunSelect('ai-inspect-run-select', runOptions, aiActiveRun?.run_id || '', null);
            }
            aiSyncCompareSelect();
            aiSetPanelTab(aiActivePanelTab);
        }

async function aiRenderCurrentRunUi(requestToken = null, requestedBatch = currentBatch, requestedRunId = aiActiveRun?.run_id || null) {
            const isCurrent = () =>
                (requestToken === null || typeof aiRunDataRequestToken === 'undefined' || requestToken === aiRunDataRequestToken)
                && currentBatch === requestedBatch
                && (!requestedRunId || aiActiveRun?.run_id === requestedRunId);
            if (!isCurrent()) return false;
            const scopeKey = `${currentBatch || ''}:${aiActiveRun?.run_id || ''}`;
            if (aiThresholdScopeKey !== scopeKey) {
                aiThresholdScopeKey = scopeKey;
                aiThresholdValue = 70;
                aiAppliedThreshold = null;
                const thresholdInput = document.getElementById('ai-score-threshold');
                if (thresholdInput) thresholdInput.value = String(aiThresholdValue);
                if (aiFilterMode === 'threshold') {
                    aiFilterMode = 'all';
                    const filter = document.getElementById('ai-filter-mode');
                    if (filter) filter.value = 'all';
                }
            }
            if (aiActiveRun) {
                await aiShowRunDiff(aiActiveRun, isCurrent);
                if (!isCurrent()) return false;
                aiShowRunSummary(aiActiveRun);
                aiShowHeaderControls(true);
                aiUpdateRunHistoryUi();
            } else {
                document.getElementById('ai-run-summary').classList.add('hidden');
                document.getElementById('ai-run-diff').classList.add('hidden');
                aiShowHeaderControls(false);
            }
            aiRenderThresholdPreview(aiActiveRun);
            aiRenderImageInspector();
            return true;
        }

async function aiRefreshRunData(existingRuns = null) {
            if (!currentBatch) return;
            const requestedBatch = currentBatch;
            const requestToken = typeof aiRunDataRequestToken === 'undefined'
                ? 1 : ++aiRunDataRequestToken;
            const requestStillCurrent = () => typeof aiRunDataRequestToken === 'undefined'
                || requestToken === aiRunDataRequestToken;
            aiSetRunsState('Loading runs...');
            try {
                let runs = existingRuns;
                if (runs === null) {
                    const resp = await fetch(ccApiPath(`/api/ai-curate/batches/${currentBatch}/runs`));
                    if (!resp.ok) throw new Error(`Run list request failed: ${resp.status}`);
                    const data = await resp.json();
                    runs = data.runs || [];
                }
                if (!requestStillCurrent() || currentBatch !== requestedBatch) return;
                if (runs.length > 0) {
                    const runDetails = await Promise.all(runs.map(id => aiFetchRun(id, requestedBatch)));
                    if (!requestStillCurrent() || currentBatch !== requestedBatch) return;
                    if (runDetails.some(run => !run)) throw new Error('One or more run details could not be loaded');
                    aiRunIds = runs;
                    const latestId = runs[runs.length - 1];
                    aiLatestRun = aiRunDetails[latestId] || null;
                    if (!aiActiveRun || !runs.includes(aiActiveRun.run_id) || aiActiveRun.run_id === latestId) {
                        aiActiveRun = aiLatestRun;
                    }
                    if (!await aiRenderCurrentRunUi(requestToken, requestedBatch, aiActiveRun?.run_id || null)) return;
                } else {
                    const historySection = document.getElementById('ai-history-section');
                    if (historySection) historySection.classList.remove('hidden');
                    aiRunIds = [];
                    aiRunDetails = {};
                    aiLatestRun = null;
                    aiActiveRun = null;
                    aiCompareRunId = 'previous';
                    if (!await aiRenderCurrentRunUi(requestToken, requestedBatch, null)) return;
                    aiUpdateRunHistoryUi();
                }
            } catch {
                if (!requestStillCurrent() || currentBatch !== requestedBatch) return;
                console.warn('aiRefreshRunData failed');
                if (aiActiveRun) {
                    aiSetRunsState('Run history refresh failed. The last loaded run remains available.', 'error');
                } else {
                    const controls = document.querySelector('#ai-history-section .ai-history-controls');
                    if (controls) controls.classList.add('hidden');
                    aiSetRunsState('Run history could not be loaded. Switch batches and return, or reload the page to retry.', 'error');
                }
            }
        }

function resetAiBatchState(refreshGrid = true) {
            aiRunDataRequestToken += 1;
            aiCompareRequestToken += 1;
            aiCurrentJobId = null;
            aiStopPolling();
            aiActiveRun = null;
            aiLatestRun = null;
            aiRunIds = [];
            aiRunDetails = {};
            aiCompareRunId = 'previous';
            aiInspectedImageName = null;
            aiThresholdScopeKey = null;
            aiThresholdValue = 70;
            aiAppliedThreshold = null;
            aiShowHeaderControls(false);
            document.getElementById('ai-run-summary').classList.add('hidden');
            document.getElementById('ai-run-diff').classList.add('hidden');
            aiRenderImageInspector();
            const runSelect = document.getElementById('ai-run-select');
            if (runSelect) runSelect.value = '';
            const inspectSelect = document.getElementById('ai-inspect-run-select');
            if (inspectSelect) inspectSelect.value = '';
            const inspectControls = document.getElementById('ai-inspect-controls');
            if (inspectControls) inspectControls.classList.add('hidden');
            const compareSelect = document.getElementById('ai-compare-run-select');
            if (compareSelect) compareSelect.value = 'previous';
            const thresholdInput = document.getElementById('ai-score-threshold');
            if (thresholdInput) thresholdInput.value = String(aiThresholdValue);
            const thresholdPreview = document.getElementById('ai-threshold-preview');
            if (thresholdPreview) thresholdPreview.hidden = true;
            aiSetRunsState('Loading runs...');
            if (refreshGrid) updateGrid();
        }

function aiGetFailureDisplayData(results, limit = AI_FAILURE_DETAIL_LIMIT) {
            const failures = Array.isArray(results) ? results.filter(result => result && result.failed) : [];
            const max = Math.max(0, Number(limit) || 0);
            return {
                visible: failures.slice(0, max),
                hiddenCount: Math.max(0, failures.length - max),
            };
        }

function aiGetRunDisplayStatus(run, scored, failed) {
            if (run?.status === 'completed' && failed > 0) {
                return scored > 0 ? 'completed with failures' : 'failed';
            }
            return run?.status || 'completed';
        }

function aiShowRunSummary(run) {
            const summary = document.getElementById('ai-run-summary');
            const t = run.totals || {};
            const results = Array.isArray(run.results) ? run.results : [];
            const failureDisplay = aiGetFailureDisplayData(results);
            const failedResults = failureDisplay.visible;
            const hiddenFailures = failureDisplay.hiddenCount;
            const scoredFromResults = results.filter(result => result && !result.failed && aiGetNormalizedScore(result) !== null).length;
            const scored = Number.isFinite(Number(t.scored)) ? Number(t.scored) : scoredFromResults;
            const failed = Number.isFinite(Number(t.failed)) ? Number(t.failed) : failedResults.length;
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
            statusBadge.textContent = aiGetRunDisplayStatus(run, scored, failed);
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
            addStatCard('Images', Number.isFinite(Number(t.images)) ? Number(t.images) : results.length);
            addStatCard('Scored', scored);
            addStatCard('Failed', failed);
            addStatCard('Moved', t.moved || 0);

            const failureDetails = document.createElement('div');
            failureDetails.id = 'ai-run-failure-details';
            failureDetails.className = 'ai-run-failure-details';
            if (failed > 0) {
                const failureHeading = document.createElement('div');
                failureHeading.className = 'ai-run-failure-heading';
                failureHeading.textContent = `${scored} scored/succeeded · ${failed} failed`;
                failureDetails.appendChild(failureHeading);
                if (failedResults.length > 0) {
                    const failureList = document.createElement('ul');
                    failureList.className = 'ai-run-failure-list';
                    failedResults.forEach(result => {
                        const item = document.createElement('li');
                        item.className = 'ai-run-failure-item';
                        const name = document.createElement('strong');
                        name.textContent = result.filename || 'Unknown image';
                        const reason = document.createElement('span');
                        reason.textContent = result.error_message || result.error || 'No failure reason recorded';
                        item.append(name, reason);
                        failureList.appendChild(item);
                    });
                    failureDetails.appendChild(failureList);
                    if (hiddenFailures > 0) {
                        failureDetails.appendChild(createTextElement('div', 'ai-run-failure-more', `${hiddenFailures} more failures not shown`));
                    }
                } else {
                    failureDetails.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'Per-image failure details were not saved for this run.'));
                }
            } else {
                failureDetails.hidden = true;
            }

            summary.replaceChildren(brief, stats, failureDetails);
            summary.classList.remove('hidden');
            summary.style.display = 'block';
        }

async function aiLoadRun(runId) {
            const requestedBatch = currentBatch;
            const requestToken = typeof aiRunDataRequestToken === 'undefined'
                ? 1 : ++aiRunDataRequestToken;
            const requestStillCurrent = () => typeof aiRunDataRequestToken === 'undefined'
                || requestToken === aiRunDataRequestToken;
            if (!runId) {
                aiActiveRun = aiLatestRun;
                if (aiActiveRun) {
                    if (!await aiRenderCurrentRunUi(requestToken, requestedBatch, aiActiveRun.run_id)) return;
                } else {
                document.getElementById('ai-run-summary').classList.add('hidden');
                document.getElementById('ai-run-diff').classList.add('hidden');
                    aiShowHeaderControls(false);
                }
                aiSyncRunSelects();
                updateGrid();
                return;
            }
            let run;
            try {
                run = await aiFetchRun(runId, requestedBatch);
            } catch {
                if (!requestStillCurrent() || currentBatch !== requestedBatch) return;
                showToast('Failed to load run');
                aiSyncRunSelects();
                return;
            }
            if (!requestStillCurrent() || currentBatch !== requestedBatch) return;
            if (!run) {
                showToast('Failed to load run');
                aiSyncRunSelects();
                return;
            }
            aiActiveRun = run;
            if (!await aiRenderCurrentRunUi(requestToken, requestedBatch, run.run_id)) return;
            if (!requestStillCurrent() || currentBatch !== requestedBatch || aiActiveRun?.run_id !== run.run_id) return;
            aiSyncRunSelects();
            updateGrid();
        }

async function aiSetCompareRun(runId) {
            aiCompareRunId = runId || 'previous';
            const compareToken = ++aiCompareRequestToken;
            const requestedBatch = currentBatch;
            const requestedRunId = aiActiveRun?.run_id || null;
            const isCurrent = () => compareToken === aiCompareRequestToken
                && currentBatch === requestedBatch
                && (!requestedRunId || aiActiveRun?.run_id === requestedRunId);
            if (aiCompareRunId !== 'previous' && !aiRunDetails[aiCompareRunId]) {
                try {
                    await aiFetchRun(aiCompareRunId, requestedBatch);
                } catch {
                    if (isCurrent()) console.warn('aiSetCompareRun failed');
                    return;
                }
            }
            if (!isCurrent()) return;
            await aiShowRunDiff(aiActiveRun, isCurrent);
        }

async function aiShowRunDiff(run, isCurrent = () => true) {
            const diffEl = document.getElementById('ai-run-diff');
            if (!diffEl) return;
            if (!isCurrent()) return;
            if (!run) {
                diffEl.classList.add('hidden');
                return;
            }
            const previousId = aiGetPreviousRunId();
            const compareRun = aiCompareRunId === 'previous'
                ? (previousId ? aiRunDetails[previousId] || await aiFetchRun(previousId) : null)
                : aiRunDetails[aiCompareRunId] || await aiFetchRun(aiCompareRunId);
            if (!isCurrent()) return;
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

function aiSyncRunSelects() {
            const runSelect = document.getElementById('ai-run-select');
            const inspectSelect = document.getElementById('ai-inspect-run-select');
            const activeId = aiActiveRun?.run_id || '';
            if (runSelect && runSelect.value !== activeId) {
                runSelect.value = activeId;
            }
            if (inspectSelect && inspectSelect.value !== activeId) {
                inspectSelect.value = activeId;
            }
        }
