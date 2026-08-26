/* Ordered classic script.
 * Defines: AI job submission, preview, status polling, cancellation, and move mode.
 */
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
            aiUpdateScoreSummary();
        }

function aiUpdateScoreSummary() {
            const elementsInput = document.getElementById('ai-elements');
            const capStatus = document.getElementById('ai-element-cap-status');
            const summary = document.getElementById('ai-score-summary');
            const submitBtn = document.getElementById('ai-submit-btn');
            if (!elementsInput || !capStatus || !summary || !submitBtn) return;

            const manualElements = elementsInput.value.split('\n').map(value => value.trim()).filter(Boolean);
            const qualityFlags = aiCollectQualityFlags();
            const totalChecks = manualElements.length + qualityFlags.length;
            capStatus.classList.toggle('limit-exceeded', totalChecks > AI_ELEMENT_CAP);
            if (manualElements.length === 0) {
                capStatus.textContent = `Add at least one element check. The total run limit is ${AI_ELEMENT_CAP}.`;
            } else if (totalChecks > AI_ELEMENT_CAP) {
                capStatus.textContent = `${totalChecks} checks configured. Only the first ${AI_ELEMENT_CAP} checks will be scored.`;
            } else if (totalChecks > 0) {
                capStatus.textContent = `${totalChecks} of ${AI_ELEMENT_CAP} checks configured.`;
            } else {
                capStatus.textContent = `Add checks to score. The run limit is ${AI_ELEMENT_CAP}.`;
            }

            const source = document.getElementById('ai-source-folder').value;
            const model = document.getElementById('ai-model').value.trim();
            const moveEnabled = document.getElementById('ai-move-toggle').checked;
            const topN = document.getElementById('ai-top-n').value || '15';
            const destination = document.getElementById('ai-dest-folder').value;
            const scopeLine = createTextElement('div', 'ai-score-summary-primary', `Score ${source} with ${model || 'a configured model'}.`);
            const checksLine = createTextElement('div', '', `${totalChecks} checks configured; ${Math.min(totalChecks, AI_ELEMENT_CAP)} will be scored.`);
            const outcomeLine = createTextElement('div', '', moveEnabled
                ? `After scoring, move the top ${topN} to ${destination}.`
                : 'Results will be saved. Files will not be moved.');
            summary.replaceChildren(scopeLine, checksLine, outcomeLine);
            submitBtn.disabled = !currentBatch || manualElements.length === 0 || !model;
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
                quality_flags: qualityFlags,
            };
            const resp = await fetch(ccApiPath('/api/ai-curate/preview-elements'), {
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
                quality_flags: qualityFlags,
                source_folder: document.getElementById('ai-source-folder').value,
                top_n: parseInt(document.getElementById('ai-top-n').value) || 15,
                model: document.getElementById('ai-model').value.trim(),
                move_enabled: moveEnabled,
                destination_folder: moveEnabled ? destFolder : null,
            };

            const resp = await fetch(ccApiPath('/api/ai-curate/jobs'), {
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
            const submittedJobId = data.run_id;
            activityRegister({
                id: `ai:${submittedJobId}`,
                kind: 'ai-score',
                title: 'AI scoring',
                scope: currentBatch,
                status: data.status || 'queued',
                detail: 'Waiting for the active run',
                cancel: () => aiCancelJob(submittedJobId),
                retry: () => aiSubmitJob(),
            });
            showToast(`AI curate job ${data.status}: ${data.run_id}`);
            aiShowJobStatus(data);
            aiStartPolling();
        }

function aiShowJobStatus(job) {
            const section = document.getElementById('ai-job-section');
            const statusRegion = document.querySelector('#ai-job-section .ai-job-status');
            const stateEl = document.getElementById('ai-job-state');
            const progressEl = document.getElementById('ai-job-progress');
            const cancelBtn = document.getElementById('ai-cancel-btn');
            const statusDot = document.getElementById('ai-status-dot');

            section.style.display = 'block';
            section.classList.remove('hidden');
            stateEl.className = 'ai-job-state ' + job.status;
            if (statusDot) statusDot.className = `ai-status-dot ${job.status}`;

            const isActive = job.status === 'running' || job.status === 'queued' || job.status === 'cancelling';
            const statusCopy = {
                queued: ['Queued', 'Waiting for the active run'],
                running: ['Running', 'Scoring images'],
                cancelling: ['Cancelling', 'Cancellation requested'],
                completed: ['Completed', 'Run saved'],
                cancelled: ['Cancelled', 'Run cancelled'],
                failed: ['Error', job.error || job.error_message || 'Run failed'],
            };
            const [stateLabel, detail] = statusCopy[job.status] || [job.status, 'Status updated'];
            stateEl.textContent = stateLabel;
            progressEl.textContent = detail;
            statusRegion.setAttribute('aria-busy', String(isActive));
            const totals = job.totals || {};
            const scored = Number(totals.scored) || 0;
            const failed = Number(totals.failed) || 0;
            const totalImages = Number(totals.images || job.total || 0) || null;
            const activityId = `ai:${job.run_id || aiCurrentJobId}`;
            activityUpdate(activityId, {
                status: job.status,
                scope: job.batch || currentBatch,
                completed: totalImages ? Math.min(totalImages, scored + failed) : null,
                total: totalImages,
                detail,
                error: job.error || job.error_message || '',
                cancel: () => aiCancelJob(job.run_id || aiCurrentJobId),
                retry: () => aiSubmitJob(),
            });
            if (job.status === 'completed' && failed > 0 && scored === 0) {
                activityComplete(activityId, 'failed', {error: 'AI scoring failed', detail: 'No images were scored'});
            } else if (job.status === 'completed' && failed > 0) {
                activityComplete(activityId, 'partial', {result: `${scored} scored · ${failed} failed`, detail: 'Run completed with failures'});
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
            aiSetPanelTab(aiActivePanelTab);
        }

function aiShowJobStatusError(message) {
            const section = document.getElementById('ai-job-section');
            const statusRegion = document.querySelector('#ai-job-section .ai-job-status');
            const stateEl = document.getElementById('ai-job-state');
            const progressEl = document.getElementById('ai-job-progress');
            const statusDot = document.getElementById('ai-status-dot');
            section.classList.remove('hidden');
            statusRegion.setAttribute('aria-busy', 'true');
            stateEl.textContent = 'Retrying';
            stateEl.className = 'ai-job-state queued';
            progressEl.textContent = message;
            if (statusDot) statusDot.className = 'ai-status-dot queued';
            activityUpdate(`ai:${aiCurrentJobId}`, {status: 'running', detail: message});
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
            try {
                const resp = await fetch(ccApiPath(`/api/ai-curate/jobs/${aiCurrentJobId}`));
                if (!resp.ok) throw new Error(`Job status request failed: ${resp.status}`);
                const job = await resp.json();
                aiShowJobStatus(job);
            } catch (error) {
                console.warn('aiPollJobStatus failed', error);
                aiShowJobStatusError('Status update failed. Retrying...');
            }
        }

async function aiCancelJob(jobId = aiCurrentJobId) {
            if (!jobId) return false;
            try {
                const resp = await fetch(ccApiPath(`/api/ai-curate/jobs/${jobId}/cancel`), {method: 'POST'});
                const data = await resp.json();
                if (data.success) {
                    showToast('Cancellation requested');
                    return true;
                }
                const message = data.error || 'Cannot cancel this job';
                activityUpdate(`ai:${jobId}`, {status: 'running', detail: `${message}; try again`});
                showToast(message);
                return false;
            } catch {
                activityUpdate(`ai:${jobId}`, {status: 'running', detail: 'Cancellation failed; try again'});
                showToast('Cancellation failed; try again');
                return false;
            }
        }
