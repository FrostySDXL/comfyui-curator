/* Ordered classic script.
 * Defines: Prompt History modal state, batch selector, rendering, and build controls.
 */
let promptsData = null;
let promptsCurrentBatch = '';
let promptsBatchList = [];
let promptsCollapseAll = false;
let _promptPrevValue = '';
let _promptBlurTimer = null;

async function showPromptsModal() {
            const modal = document.getElementById('prompts-modal');
            modal.classList.add('active');
            _trapFocus(modal);
            if (promptsBatchList.length === 0) {
                try {
                    const resp = await fetch('/api/batches');
                    if (resp.ok) {
                        promptsBatchList = (await resp.json()).batches || [];
                    }
                } catch { console.warn('prompt batch load failed'); }
            }
            // Default to current batch if one is active (not null, not virtual)
            if (currentBatch && currentBatch !== '__favorites__' && promptsBatchList.includes(currentBatch)) {
                promptsCurrentBatch = currentBatch;
            }
            _syncPromptDisplay();
            updateAllBatchesBtn();
            loadPromptsData();
        }

function hidePromptsModal() {
            document.getElementById('prompts-modal').classList.remove('active');
            _releaseFocusTrap();
        }

function _syncPromptDisplay() {
            const wrapper = document.getElementById('prompts-batch-wrap');
            const input = document.getElementById('prompts-batch-filter');
            const dropdown = document.getElementById('prompts-batch-list');
            if (!input) return;
            const isOpen = wrapper && wrapper.classList.contains('open');
            if (!isOpen) {
                input.value = promptsCurrentBatch || '';
                input.placeholder = promptsCurrentBatch ? '' : 'All Batches';
            }
            updateAllBatchesBtn();
        }

function updateAllBatchesBtn() {
            const btn = document.getElementById('prompts-all-batches-btn');
            if (!btn) return;
            btn.classList.toggle('active', promptsCurrentBatch === '');
        }

function _populatePromptDropdown(filter = '') {
            const dropdown = document.getElementById('prompts-batch-list');
            if (!dropdown) return;
            const q = filter.toLowerCase();
            dropdown.replaceChildren();
            const matches = [];
            promptsBatchList.forEach(batch => {
                if (q && !batch.toLowerCase().includes(q)) return;
                matches.push({ batch, startsWith: batch.toLowerCase().startsWith(q) });
            });
            if (q) {
                matches.sort((a, b) => {
                    if (a.startsWith && !b.startsWith) return -1;
                    if (!a.startsWith && b.startsWith) return 1;
                    return 0;
                });
            }
            if (matches.length === 0) {
                const empty = document.createElement('li');
                empty.className = 'prompts-batch-empty';
                empty.textContent = 'No batches match';
                dropdown.appendChild(empty);
                return;
            }
            matches.forEach(({ batch }) => {
                const li = document.createElement('li');
                li.className = 'prompts-batch-option';
                li.dataset.value = batch;
                li.textContent = batch;
                li.setAttribute('role', 'option');
                li.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    clearTimeout(_promptBlurTimer);
                    _commitPromptSelection(batch);
                });
                dropdown.appendChild(li);
            });
        }

function _commitPromptSelection(batch) {
            const input = document.getElementById('prompts-batch-filter');
            promptsCurrentBatch = batch;
            if (input) {
                input.value = batch;
                input.blur();
            }
            _promptPrevValue = '';
            _promptCloseDropdown();
            _syncPromptDisplay();
            loadPromptsData();
        }

function _promptOpenDropdown() {
            const wrapper = document.getElementById('prompts-batch-wrap');
            const input = document.getElementById('prompts-batch-filter');
            if (!wrapper || !input || wrapper.classList.contains('open')) return;
            _promptPrevValue = input.value;
            input.value = '';
            input.setAttribute('aria-expanded', 'true');
            _populatePromptDropdown('');
            wrapper.classList.add('open');
        }

function _promptCloseDropdown(restoreInput = false) {
            const wrapper = document.getElementById('prompts-batch-wrap');
            const input = document.getElementById('prompts-batch-filter');
            if (!wrapper) return;
            wrapper.classList.remove('open');
            if (input) {
                if (restoreInput && _promptPrevValue) {
                    input.value = _promptPrevValue;
                }
                input.setAttribute('aria-expanded', 'false');
            }
            clearTimeout(_promptBlurTimer);
            _promptBlurTimer = null;
        }

function _promptMoveFocus(delta) {
            const dropdown = document.getElementById('prompts-batch-list');
            if (!dropdown) return;
            const visible = Array.from(dropdown.querySelectorAll('.prompts-batch-option'))
                .filter(el => el.style.display !== 'none' && el.offsetParent !== null);
            if (visible.length === 0) return;
            const current = visible.findIndex(el => el.classList.contains('focus'));
            const next = current < 0 ? 0 : (current + delta + visible.length) % visible.length;
            visible.forEach(el => el.classList.remove('focus'));
            visible[next].classList.add('focus');
            visible[next].scrollIntoView({block: 'nearest'});
        }

async function loadPromptsData() {
            const list = document.getElementById('prompts-list');
            if (list) list.textContent = 'Loading prompt history...';
            const url = promptsCurrentBatch
                ? `/api/prompt-history/${encodeURIComponent(promptsCurrentBatch)}?check_stale=true`
                : '/api/prompt-history';
            try {
                const resp = await fetch(url);
                if (resp.status === 404) {
                    promptsData = null;
                    if (list) list.textContent = 'Prompt index not built for this batch.';
                    updatePromptsFooter();
                    return;
                }
                if (!resp.ok) throw new Error('prompt history request failed');
                promptsData = await resp.json();
                renderPromptsList();
                updatePromptsFooter();
            } catch {
                promptsData = null;
                if (list) list.textContent = 'Failed to load prompt history.';
            }
        }

function getPromptEntries() {
            if (!promptsData) return [];
            if (promptsCurrentBatch) {
                return (promptsData.prompts || []).map(prompt => ({...prompt, batch: promptsData.batch}));
            }
            const entries = [];
            Object.entries(promptsData.batches || {}).forEach(([batch, index]) => {
                (index.prompts || []).forEach(prompt => entries.push({...prompt, batch}));
            });
            return entries;
        }

function renderPromptsList() {
            const list = document.getElementById('prompts-list');
            if (!list) return;
            const query = (document.getElementById('prompts-search')?.value || '').trim().toLowerCase();
            const entries = getPromptEntries().filter(entry => {
                const haystack = `${entry.prompt || ''} ${entry.negative_prompt || ''} ${entry.batch || ''}`.toLowerCase();
                return !query || haystack.includes(query);
            });
            list.replaceChildren();
            if (entries.length === 0) {
                list.textContent = promptsData ? 'No prompts match.' : 'No prompt indexes found.';
                return;
            }
            entries.forEach(entry => {
                const card = document.createElement('div');
                card.className = 'prompts-entry';
                const main = document.createElement('div');
                main.className = 'prompts-entry-main';
                main.appendChild(createTextElement('span', 'prompts-count', String(entry.count || 0)));
                const textWrap = document.createElement('div');
                const promptText = String(entry.normalized || entry.prompt || '');
                const truncated = promptsCollapseAll;
                textWrap.appendChild(createTextElement('div', 'prompts-prompt-text', truncated ? promptText.slice(0, 375) + (promptText.length > 375 ? '...' : '') : promptText));
                if (!promptsCurrentBatch) textWrap.appendChild(createTextElement('span', 'prompts-batch-label', entry.batch || ''));
                main.appendChild(textWrap);
                const actions = document.createElement('div');
                actions.className = 'prompts-entry-actions';
                const copyBtn = document.createElement('button');
                copyBtn.type = 'button';
                copyBtn.className = 'prompts-copy-btn';
                copyBtn.textContent = 'copy prompt';
                copyBtn.addEventListener('click', () => copyMetadataText(promptText, 'prompt'));
                actions.appendChild(copyBtn);

                if (promptText.length > 375) {
                    const showBtn = document.createElement('button');
                    showBtn.type = 'button';
                    showBtn.className = 'prompts-show-more';
                    showBtn.textContent = promptsCollapseAll ? 'show positive' : 'hide positive';
                    showBtn.addEventListener('click', () => {
                        const el = card.querySelector('.prompts-prompt-text');
                        const expanded = showBtn.textContent === 'hide positive';
                        el.textContent = expanded ? `${promptText.slice(0, 375)}...` : promptText;
                        showBtn.textContent = expanded ? 'show positive' : 'hide positive';
                    });
                    actions.appendChild(showBtn);
                }

                let negBtn = null, neg = null;
                const negText = entry.negative_prompt || '';
                if (negText) {
                    negBtn = document.createElement('button');
                    negBtn.type = 'button';
                    negBtn.className = 'prompts-toggle-neg';
                    negBtn.textContent = 'show negative';
                    neg = createTextElement('div', 'prompts-negative hidden', negText);
                    negBtn.addEventListener('click', () => {
                        const hidden = neg.classList.toggle('hidden');
                        negBtn.textContent = hidden ? 'show negative' : 'hide negative';
                    });
                    actions.appendChild(negBtn);
                }

                let imgBtn = null, imgDiv = null;
                const imagesList = (entry.images || []).map(img => img.filename).slice(0, 20).join(', ');
                if (imagesList) {
                    imgBtn = document.createElement('button');
                    imgBtn.type = 'button';
                    imgBtn.className = 'prompts-toggle-images';
                    imgBtn.textContent = 'show images';
                    imgDiv = createTextElement('div', 'prompts-images-list hidden', imagesList);
                    imgBtn.addEventListener('click', () => {
                        const hidden = imgDiv.classList.toggle('hidden');
                        imgBtn.textContent = hidden ? 'show images' : 'hide images';
                    });
                    actions.appendChild(imgBtn);
                }

                main.appendChild(actions);
                card.appendChild(main);

                if (neg) card.appendChild(neg);
                if (imgDiv) card.appendChild(imgDiv);
                list.appendChild(card);
            });
        }

function updatePromptsFooter() {
            const total = document.getElementById('prompts-total');
            const built = document.getElementById('prompts-built-at');
            const stale = document.getElementById('prompts-stale-warning');
            if (total) {
                if (!promptsCurrentBatch && promptsData) {
                    const batchCount = Object.keys(promptsData.batches || {}).length;
                    total.textContent = `${promptsData.total_prompts || 0} prompts across ${batchCount} batch${batchCount !== 1 ? 'es' : ''}`;
                } else {
                    total.textContent = '';
                }
            }
            if (built) {
                const builtAt = promptsData?.built_at || (promptsCurrentBatch ? null : '');
                built.textContent = builtAt ? `Built ${new Date(builtAt).toLocaleString()}` : '';
            }
            if (stale) stale.classList.toggle('hidden', promptsData?.stale !== true);
        }

async function buildPromptIndex() {
            if (!promptsCurrentBatch) {
                showToast('Select a batch before building a prompt index');
                return;
            }
            const buildBtn = document.getElementById('prompts-build-btn');
            const rebuildBtn = document.getElementById('prompts-rebuild-btn');
            const buildLabel = buildBtn ? buildBtn.textContent : '';
            const rebuildLabel = rebuildBtn ? rebuildBtn.textContent : '';
            if (buildBtn) { buildBtn.disabled = true; buildBtn.textContent = 'Building...'; }
            if (rebuildBtn) { rebuildBtn.disabled = true; rebuildBtn.textContent = 'Building...'; }
            try {
                const resp = await fetch(`/api/prompt-history/${encodeURIComponent(promptsCurrentBatch)}/build`, {method: 'POST'});
                if (!resp.ok) throw new Error('build failed');
                showToast('Prompt index built');
                await loadPromptsData();
            } catch {
                showToast('Prompt index build failed');
            } finally {
                if (buildBtn) { buildBtn.disabled = false; buildBtn.textContent = buildLabel; }
                if (rebuildBtn) { rebuildBtn.disabled = false; rebuildBtn.textContent = rebuildLabel; }
            }
        }
