/* Ordered classic script.
 * Defines: Prompt History modal state, selector, rendering, build/rebuild controls.
 */
        const PROMPTS_RENDER_CAP = 200;
        const PROMPTS_IMAGES_CAP = 20;
        const PROMPTS_TRUNCATE_LEN = 375;
        const PROMPT_COUNT_HOT_THRESHOLD = 5;
        const PROMPT_COUNT_WARM_THRESHOLD = 2;
        const PROMPTS_SORT_OPTIONS = ['count', 'alpha', 'length'];
        const PROMPTS_DEFAULT_SORT = 'count';

        let promptsData = null;
        let promptsCurrentBatch = '';
        let promptsBatchList = [];
        let promptsCollapseAll = (localStorage.getItem(PROMPTS_COLLAPSE_KEY) === 'true');
        let promptsSort = (function() {
            const stored = localStorage.getItem(PROMPTS_SORT_KEY);
            return PROMPTS_SORT_OPTIONS.includes(stored) ? stored : PROMPTS_DEFAULT_SORT;
        })();
        let promptsGroupByBatch = (localStorage.getItem(PROMPTS_GROUP_KEY) === 'true');
        let promptsRequestToken = 0;
        let promptsBuilding = false;
        let _promptPrevValue = '';
        let _promptBlurTimer = null;
        let _promptsRenderTimer = null;

        // --- Local storage helpers (scoped to prompts UI) ---

        function _promptsLocalSet(key, value) {
            try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
        }

        function _setPromptsCollapse(value) {
            promptsCollapseAll = !!value;
            _promptsLocalSet(PROMPTS_COLLAPSE_KEY, promptsCollapseAll ? 'true' : 'false');
        }

        function _setPromptsSort(value) {
            if (!PROMPTS_SORT_OPTIONS.includes(value)) return;
            promptsSort = value;
            _promptsLocalSet(PROMPTS_SORT_KEY, value);
        }

        function _setPromptsGroupByBatch(value) {
            promptsGroupByBatch = !!value;
            _promptsLocalSet(PROMPTS_GROUP_KEY, promptsGroupByBatch ? 'true' : 'false');
        }

        // --- Modal lifecycle ---

        async function showPromptsModal() {
            const modal = document.getElementById('prompts-modal');
            modal.classList.add('active');
            _trapFocus(modal);
            // Always refetch the batch list on open so newly created batches appear.
            try {
                const resp = await fetch(ccApiPath('/api/batches'));
                if (resp.ok) {
                    promptsBatchList = (await resp.json()).batches || [];
                }
            } catch { console.warn('prompt batch load failed'); }
            // Default to current batch if one is active (not null, not virtual).
            // If the previously selected promptsCurrentBatch was deleted between opens,
            // fall back to "All Batches" so the scope chip does not reference a dead batch.
            if (currentBatch && currentBatch !== '__favorites__' && currentBatch !== '__public__' && promptsBatchList.includes(currentBatch)) {
                promptsCurrentBatch = currentBatch;
            } else if (promptsCurrentBatch && !promptsBatchList.includes(promptsCurrentBatch)) {
                promptsCurrentBatch = '';
            }
            _syncPromptDisplay();
            updateAllBatchesBtn();
            updateScopeChip();
            updateBuildBtn();
            loadPromptsData();
            // Focus the search input so operators can refine without an extra click.
            const search = document.getElementById('prompts-search');
            if (search) {
                // Defer focus past the focus trap's first-focus to avoid a fight.
                setTimeout(() => { try { search.focus(); } catch { /* noop */ } }, 0);
            }
        }

        function hidePromptsModal() {
            // Cancel any in-flight search debounce so it cannot fire renderPromptsList
            // on a hidden modal and clobber state on the next open.
            if (_promptsRenderTimer) {
                clearTimeout(_promptsRenderTimer);
                _promptsRenderTimer = null;
            }
            _promptCloseDropdown();
            hideBuildAllConfirm();
            document.getElementById('prompts-modal').classList.remove('active');
            _releaseFocusTrap();
        }

        // --- Display sync ---

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
            updateScopeChip();
        }

        function updateAllBatchesBtn() {
            const btn = document.getElementById('prompts-all-batches-btn');
            if (!btn) return;
            const active = promptsCurrentBatch === '';
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        }

        function updateScopeChip() {
            const chip = document.getElementById('prompts-scope-chip');
            if (!chip) return;
            const label = promptsCurrentBatch ? `Scope: ${promptsCurrentBatch}` : 'Scope: All Batches';
            chip.textContent = label;
            chip.classList.toggle('is-all', promptsCurrentBatch === '');
            hideBuildAllConfirm();
        }

        function updateBuildBtn() {
            const btn = document.getElementById('prompts-build-btn');
            if (!btn) return;
            if (!promptsCurrentBatch) {
                btn.textContent = 'Build All Indexes';
                return;
            }
            const hasIndex = !!promptsData && !!promptsData.built_at;
            btn.textContent = hasIndex ? 'Rebuild Index' : 'Build Index';
        }

        // --- Custom combobox ---

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
            const activeValue = promptsCurrentBatch;
            matches.forEach(({ batch }, index) => {
                const li = document.createElement('li');
                li.className = 'prompts-batch-option';
                li.dataset.value = batch;
                li.id = `prompts-batch-option-${index}`;
                li.textContent = batch;
                li.setAttribute('role', 'option');
                li.setAttribute('aria-selected', batch === activeValue ? 'true' : 'false');
                if (batch === activeValue) li.classList.add('selected');
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
            updateBuildBtn();
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
                input.removeAttribute('aria-activedescendant');
            }
            clearTimeout(_promptBlurTimer);
            _promptBlurTimer = null;
        }

        function _promptVisibleOptions() {
            const dropdown = document.getElementById('prompts-batch-list');
            if (!dropdown) return [];
            return Array.from(dropdown.querySelectorAll('.prompts-batch-option'))
                .filter(el => el.style.display !== 'none' && el.offsetParent !== null);
        }

        function _promptSetActive(visible, index) {
            if (!visible || visible.length === 0) return;
            const target = visible[Math.max(0, Math.min(index, visible.length - 1))];
            // aria-selected reflects the *committed* value (set in _populatePromptDropdown);
            // arrow-key focus uses the visual .focus class plus aria-activedescendant
            // on the input, per the ARIA 1.2 combobox pattern.
            visible.forEach(el => el.classList.remove('focus'));
            target.classList.add('focus');
            target.scrollIntoView({block: 'nearest'});
            const input = document.getElementById('prompts-batch-filter');
            if (input) input.setAttribute('aria-activedescendant', target.id);
        }

        function _promptMoveFocus(delta) {
            const visible = _promptVisibleOptions();
            if (visible.length === 0) return;
            const current = visible.findIndex(el => el.classList.contains('focus'));
            const next = current < 0 ? 0 : (current + delta + visible.length) % visible.length;
            _promptSetActive(visible, next);
        }

        function _promptJumpFocus(target) {
            const visible = _promptVisibleOptions();
            if (visible.length === 0) return;
            _promptSetActive(visible, target);
        }

        // --- Data loading (with request-token stale-response guard) ---

        async function loadPromptsData() {
            const list = document.getElementById('prompts-list');
            if (list) list.textContent = 'Loading prompt history...';
            _setPromptsResultStatus('Loading index...');
            const token = ++promptsRequestToken;
            const url = promptsCurrentBatch
                ? ccApiPath(`/api/prompt-history/${encodeURIComponent(promptsCurrentBatch)}?check_stale=true`)
                : ccApiPath('/api/prompt-history');
            try {
                const resp = await fetch(url);
                if (token !== promptsRequestToken) return; // stale response, ignore
                if (resp.status === 404) {
                    promptsData = null;
                    if (list) list.textContent = '';
                    renderPromptsList();
                    updatePromptsFooter();
                    updateBuildBtn();
                    return;
                }
                if (!resp.ok) throw new Error('prompt history request failed');
                if (token !== promptsRequestToken) return;
                promptsData = await resp.json();
                renderPromptsList();
                updatePromptsFooter();
                updateBuildBtn();
            } catch {
                if (token !== promptsRequestToken) return;
                promptsData = null;
                if (list) list.textContent = 'Failed to load prompt history.';
                _setPromptsResultStatus('Load failed');
                updatePromptsFooter();
                updateBuildBtn();
            }
        }

        // --- Entry flattening / sort / group ---

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

        function _compareEntries(a, b, mode) {
            switch (mode) {
                case 'alpha':
                    return String(a.prompt || '').localeCompare(String(b.prompt || ''));
                case 'length':
                    return (b.prompt || '').length - (a.prompt || '').length;
                case 'count':
                default:
                    return (b.count || 0) - (a.count || 0);
            }
        }

        function _sortedEntries(entries) {
            const copy = entries.slice();
            copy.sort((a, b) => _compareEntries(a, b, promptsSort));
            return copy;
        }

        function _entriesByBatch(entries) {
            const groups = new Map();
            entries.forEach(entry => {
                const key = entry.batch || '';
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(entry);
            });
            return groups;
        }

        // --- Render ---

        function _highlightMatchNode(text, query) {
            if (!query) {
                const span = document.createElement('span');
                span.textContent = text;
                return span;
            }
            const safe = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const re = new RegExp(`(${safe})`, 'gi');
            const parts = String(text).split(re);
            const wrap = document.createElement('span');
            for (let i = 0; i < parts.length; i++) {
                if (!parts[i]) continue;
                if (i % 2 === 1) {
                    const m = document.createElement('mark');
                    m.className = 'prompts-match';
                    m.textContent = parts[i];
                    wrap.appendChild(m);
                } else {
                    wrap.appendChild(document.createTextNode(parts[i]));
                }
            }
            return wrap;
        }

        function _buildCountChip(count) {
            const chip = document.createElement('span');
            chip.className = 'prompts-count';
            const numeric = document.createElement('span');
            numeric.className = 'prompts-count-numeric';
            numeric.textContent = String(count || 0);
            chip.appendChild(numeric);
            const label = document.createElement('span');
            label.className = 'prompts-count-label';
            label.textContent = count === 1 ? 'use' : 'uses';
            chip.appendChild(label);
            if (count >= PROMPT_COUNT_HOT_THRESHOLD) {
                chip.classList.add('is-hot');
            } else if (count >= PROMPT_COUNT_WARM_THRESHOLD) {
                chip.classList.add('is-warm');
            } else {
                chip.classList.add('is-cold');
            }
            chip.setAttribute('aria-label', `${count} ${count === 1 ? 'use' : 'uses'}`);
            return chip;
        }

        function _buildBatchChip(batch) {
            if (!batch) return null;
            const chip = document.createElement('span');
            chip.className = 'prompts-batch-chip';
            chip.textContent = batch;
            return chip;
        }

        function _buildActionChip(label, className, onClick) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `prompts-action-chip ${className}`;
            btn.textContent = label;
            btn.addEventListener('click', onClick);
            return btn;
        }

        function _buildImageChipList(images) {
            if (!images || images.length === 0) return null;
            const wrap = document.createElement('div');
            wrap.className = 'prompts-image-groups hidden';
            const heading = createTextElement('div', 'prompts-image-references-label', 'Image references');
            wrap.appendChild(heading);
            const total = images.length;
            let remaining = PROMPTS_IMAGES_CAP;
            const byFolder = new Map();
            images.forEach(img => {
                if (!byFolder.has(img.folder)) byFolder.set(img.folder, []);
                byFolder.get(img.folder).push(img.filename);
            });
            byFolder.forEach((files, folder) => {
                if (remaining <= 0) return;
                const group = document.createElement('div');
                group.className = 'prompts-image-group';
                const label = document.createElement('span');
                label.className = 'prompts-image-folder';
                label.textContent = folder;
                group.appendChild(label);
                files.slice(0, remaining).forEach(name => {
                    const chip = document.createElement('span');
                    chip.className = 'prompts-image-chip';
                    chip.textContent = name;
                    chip.title = name;
                    group.appendChild(chip);
                });
                remaining -= Math.min(files.length, remaining);
                wrap.appendChild(group);
            });
            const over = total - PROMPTS_IMAGES_CAP;
            if (over > 0) {
                const more = document.createElement('span');
                more.className = 'prompts-image-chip prompts-image-chip-more';
                more.textContent = `+${over} more`;
                more.title = `${over} more images not shown`;
                wrap.appendChild(more);
            }
            return wrap;
        }

        function _buildNegativeDisclosure(negText) {
            if (!negText) return { el: null, btn: null };
            const el = createTextElement('div', 'prompts-negative hidden', '');
            el.hidden = true;
            el.appendChild(createTextElement('div', 'prompts-field-label', 'Negative prompt'));
            const text = createTextElement('div', 'prompts-negative-text', '');
            text.appendChild(_highlightMatchNode(negText, _currentSearchQuery()));
            el.appendChild(text);
            const btn = _buildActionChip('show negative', 'prompts-toggle-neg', () => {
                const hidden = el.classList.toggle('hidden');
                el.hidden = hidden;
                btn.textContent = hidden ? 'show negative' : 'hide negative';
                btn.setAttribute('aria-expanded', hidden ? 'false' : 'true');
            });
            btn.setAttribute('aria-expanded', 'false');
            return { el, btn };
        }

        function _buildImageDisclosure(images) {
            if (!images || images.length === 0) return { el: null, btn: null };
            const list = _buildImageChipList(images);
            if (!list) return { el: null, btn: null };
            const total = images.length;
            const shown = Math.min(total, PROMPTS_IMAGES_CAP);
            const truncated = total > shown;
            const label = truncated ? `show images (${shown} of ${total})` : `show images (${total})`;
            const btn = _buildActionChip(label, 'prompts-toggle-images', () => {
                const hidden = list.classList.toggle('hidden');
                list.hidden = hidden;
                if (hidden) {
                    btn.textContent = truncated ? `show images (${shown} of ${total})` : `show images (${total})`;
                } else {
                    btn.textContent = 'hide images';
                }
                btn.setAttribute('aria-expanded', hidden ? 'false' : 'true');
            });
            btn.setAttribute('aria-expanded', 'false');
            list.hidden = true;
            return { el: list, btn };
        }

        function _buildFullDisclosure(promptText) {
            if (promptText.length <= PROMPTS_TRUNCATE_LEN) return { el: null, btn: null };
            const truncated = `${promptText.slice(0, PROMPTS_TRUNCATE_LEN)}...`;
            const wrap = document.createElement('div');
            wrap.className = 'prompts-prompt-text';
            // Explicit per-entry state so the toggle cannot desync from the rendered
            // text (a previous endsWith('...') heuristic broke when prompts ended with
            // an actual ellipsis).
            let isExpanded = !promptsCollapseAll;
            const render = () => {
                wrap.textContent = '';
                wrap.appendChild(_highlightMatchNode(isExpanded ? promptText : truncated, _currentSearchQuery()));
            };
            render();
            const btn = _buildActionChip(isExpanded ? 'collapse' : 'show full', 'prompts-toggle-full', () => {
                isExpanded = !isExpanded;
                render();
                btn.textContent = isExpanded ? 'collapse' : 'show full';
                btn.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
            });
            btn.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
            return { el: wrap, btn };
        }

        function _buildEntry(entry, query) {
            const card = document.createElement('article');
            card.className = 'prompts-entry';
            card.dataset.batch = entry.batch || '';
            card.dataset.hash = entry.hash || '';

            const header = document.createElement('div');
            header.className = 'prompts-entry-header';
            header.appendChild(_buildCountChip(entry.count || 0));
            const batchChip = _buildBatchChip(entry.batch);
            if (batchChip) header.appendChild(batchChip);

            const textWrap = document.createElement('div');
            textWrap.className = 'prompts-entry-main';
            const promptText = String(entry.normalized || entry.prompt || '');
            const full = _buildFullDisclosure(promptText);
            const neg = _buildNegativeDisclosure(entry.negative_prompt || '');
            const imgs = _buildImageDisclosure(entry.images || []);

            const actions = document.createElement('div');
            actions.className = 'prompts-entry-actions';

            actions.appendChild(_buildActionChip('copy positive', 'prompts-copy-prompt', () => copyMetadataText(promptText, 'positive prompt')));
            if (neg.btn) actions.appendChild(neg.btn);
            const copyPairText = _formatCopyPair(promptText, entry.negative_prompt || '');
            actions.appendChild(_buildActionChip('copy pair', 'prompts-copy-pair', () => copyMetadataText(copyPairText, 'prompt pair')));
            if (full.btn) actions.appendChild(full.btn);
            if (imgs.btn) actions.appendChild(imgs.btn);
            if (entry.negative_prompt) {
                actions.appendChild(_buildActionChip('copy negative', 'prompts-copy-neg', () => copyMetadataText(entry.negative_prompt, 'negative prompt')));
            }

            textWrap.appendChild(createTextElement('div', 'prompts-field-label', 'Positive prompt'));
            if (full.el) {
                textWrap.appendChild(full.el);
            } else {
                const plain = document.createElement('div');
                plain.className = 'prompts-prompt-text';
                plain.appendChild(_highlightMatchNode(promptText, query));
                textWrap.appendChild(plain);
            }

            if (neg.el) textWrap.appendChild(neg.el);
            if (imgs.el) textWrap.appendChild(imgs.el);

            card.appendChild(header);
            card.appendChild(textWrap);
            card.appendChild(actions);
            return card;
        }

        function _formatCopyPair(prompt, negative) {
            if (!negative) return prompt;
            return `${prompt}\n\nNegative: ${negative}`;
        }

        function _currentSearchQuery() {
            const el = document.getElementById('prompts-search');
            return el ? el.value.trim().toLowerCase() : '';
        }

        function _schedulePromptsRender() {
            if (_promptsRenderTimer) clearTimeout(_promptsRenderTimer);
            _promptsRenderTimer = setTimeout(() => {
                _promptsRenderTimer = null;
                renderPromptsList();
            }, 180);
        }

        function _setPromptsResultStatus(text) {
            const status = document.getElementById('prompts-total');
            if (status) status.textContent = text;
        }

        function renderPromptsList() {
            const list = document.getElementById('prompts-list');
            if (!list) return;
            list.classList.toggle('is-building', promptsBuilding);
            // Clear any prior content.
            list.replaceChildren();

            // --- Empty / unbuilt states ---
            if (promptsBuilding) {
                _setPromptsResultStatus('Building index...');
                const status = createTextElement('div', 'prompts-building-status', '');
                const spinner = document.createElement('span');
                spinner.className = 'prompts-spinner';
                spinner.setAttribute('aria-hidden', 'true');
                status.appendChild(spinner);
                status.appendChild(document.createTextNode(`Building index for ${promptsCurrentBatch}...`));
                list.appendChild(status);
                return;
            }

            if (!promptsData) {
                _setPromptsResultStatus(promptsCurrentBatch ? 'Index not built' : 'No indexes found');
                if (promptsCurrentBatch) {
                    list.appendChild(_buildEmptyCta(promptsCurrentBatch, /* hasExisting */ false));
                } else {
                    list.appendChild(_buildAllEmptyState());
                }
                return;
            }

            const allEntries = getPromptEntries();
            const query = _currentSearchQuery();
            const filtered = allEntries.filter(entry => {
                if (!query) return true;
                const haystack = `${entry.prompt || ''} ${entry.negative_prompt || ''} ${entry.batch || ''}`.toLowerCase();
                return haystack.includes(query);
            });
            _setPromptsResultStatus(query
                ? `${filtered.length} of ${allEntries.length} prompts`
                : `${allEntries.length} prompt${allEntries.length === 1 ? '' : 's'}`);

            if (filtered.length === 0) {
                list.appendChild(_buildNoMatchesState(query, allEntries.length));
                return;
            }

            const sorted = _sortedEntries(filtered);
            const truncated = sorted.length > PROMPTS_RENDER_CAP;
            const visible = truncated ? sorted.slice(0, PROMPTS_RENDER_CAP) : sorted;

            if (truncated) {
                const cap = createTextElement('div', 'prompts-render-cap', `Showing first ${PROMPTS_RENDER_CAP} of ${sorted.length}. Refine your search to narrow results.`);
                list.appendChild(cap);
            }

            if (promptsGroupByBatch) {
                const groups = _entriesByBatch(visible);
                groups.forEach((entries, batch) => {
                    const header = document.createElement('div');
                    header.className = 'prompts-group-header';
                    header.textContent = batch || 'Unbatched';
                    list.appendChild(header);
                    const sortedEntries = _sortedEntries(entries);
                    sortedEntries.forEach(entry => list.appendChild(_buildEntry(entry, query)));
                });
            } else {
                visible.forEach(entry => list.appendChild(_buildEntry(entry, query)));
            }
        }

        function _buildEmptyCta(batch, hasExisting) {
            const wrap = document.createElement('div');
            wrap.className = 'prompts-empty-cta';
            const title = createTextElement('div', 'prompts-empty-title', `No prompt index for ${batch}`);
            const body = createTextElement('p', 'prompts-empty-body', 'Build the index to search every prompt text in this batch and see which prompts get reused the most.');
            const cta = document.createElement('button');
            cta.type = 'button';
            cta.className = 'prompts-empty-build-btn prompts-primary-action';
            cta.textContent = `Build Index for ${batch}`;
            cta.addEventListener('click', buildPromptIndex);
            wrap.append(title, body, cta);
            return wrap;
        }

        function _buildAllEmptyState() {
            const wrap = document.createElement('div');
            wrap.className = 'prompts-empty-cta';
            wrap.appendChild(createTextElement('div', 'prompts-empty-title', 'No prompt indexes found'));
            wrap.appendChild(createTextElement('p', 'prompts-empty-body', 'Open a single batch above to build its index. Aggregate view shows indexes already built.'));
            return wrap;
        }

        function _buildNoMatchesState(query, totalCount) {
            const wrap = document.createElement('div');
            wrap.className = 'prompts-empty-cta';
            const title = createTextElement('div', 'prompts-empty-title', `No prompts match "${query}"`);
            wrap.appendChild(title);
            const body = createTextElement('p', 'prompts-empty-body', `${totalCount} prompt${totalCount === 1 ? '' : 's'} available across the current scope.`);
            wrap.appendChild(body);
            return wrap;
        }

        // --- Footer ---

        function _formatRelativeTime(iso) {
            if (!iso) return '';
            const then = new Date(iso).getTime();
            if (Number.isNaN(then)) return '';
            const now = Date.now();
            const diffSec = Math.max(0, Math.round((now - then) / 1000));
            if (diffSec < 60) return 'just now';
            if (diffSec < 3600) {
                const m = Math.round(diffSec / 60);
                return `${m}m ago`;
            }
            if (diffSec < 86400) {
                const h = Math.round(diffSec / 3600);
                return `${h}h ago`;
            }
            if (diffSec < 86400 * 7) {
                const d = Math.round(diffSec / 86400);
                return `${d}d ago`;
            }
            // Older: stable YYYY-MM-DD HH:MM in UTC.
            const d = new Date(iso);
            const pad = (n) => String(n).padStart(2, '0');
            return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
        }

        function updatePromptsFooter() {
            const built = document.getElementById('prompts-built-at');
            const stale = document.getElementById('prompts-stale-warning');
            if (built) {
                const builtAt = promptsData?.built_at || (promptsCurrentBatch ? null : '');
                if (builtAt) {
                    const rel = _formatRelativeTime(builtAt);
                    built.textContent = rel ? `Built ${rel}` : '';
                    built.title = builtAt;
                } else {
                    built.textContent = '';
                    built.removeAttribute('title');
                }
            }
            if (stale) {
                const isStale = promptsData?.stale === true;
                stale.classList.toggle('hidden', !isStale);
                stale.setAttribute('aria-live', 'polite');
            }
        }

        // --- Build / rebuild ---

        async function buildPromptIndex() {
            if (!promptsCurrentBatch) {
                showBuildAllConfirm();
                return;
            }
            await buildSinglePromptIndex(promptsCurrentBatch);
        }

        function showBuildAllConfirm() {
            const confirm = document.getElementById('prompts-build-all-confirm');
            if (!confirm) return;
            confirm.classList.remove('hidden');
            confirm.hidden = false;
        }

        function hideBuildAllConfirm() {
            const confirm = document.getElementById('prompts-build-all-confirm');
            if (!confirm) return;
            confirm.classList.add('hidden');
            confirm.hidden = true;
        }

        async function buildAllPromptIndexes() {
            hideBuildAllConfirm();
            const batches = promptsBatchList.slice();
            if (batches.length === 0) {
                showToast('No batches available to build');
                return;
            }
            for (const batch of batches) {
                promptsCurrentBatch = batch;
                _syncPromptDisplay();
                updateBuildBtn();
                await buildSinglePromptIndex(batch, {quietSuccess: true});
            }
            promptsCurrentBatch = '';
            _syncPromptDisplay();
            showToast(`Built prompt indexes for ${batches.length} batches`);
            await loadPromptsData();
        }

        async function buildSinglePromptIndex(batch, options = {}) {
            const buildBtn = document.getElementById('prompts-build-btn');
            const rebuildBtn = document.getElementById('prompts-rebuild-btn');
            const buildLabel = buildBtn ? buildBtn.textContent : '';
            const rebuildLabel = rebuildBtn ? rebuildBtn.textContent : '';
            promptsBuilding = true;
            renderPromptsList();
            if (buildBtn) { buildBtn.disabled = true; buildBtn.textContent = 'Building...'; }
            if (rebuildBtn) { rebuildBtn.disabled = true; rebuildBtn.textContent = 'Building...'; }
            const token = ++promptsRequestToken;
            try {
                const resp = await fetch(ccApiPath(`/api/prompt-history/${encodeURIComponent(batch)}/build`), {method: 'POST'});
                if (token !== promptsRequestToken) return;
                if (!resp.ok) throw new Error('build failed');
                if (!options.quietSuccess) showToast('Prompt index built');
                // Clean up build state before reloading data so loadPromptsData's
                // token increment does not invalidate the token guarding this block.
                promptsBuilding = false;
                if (buildBtn) { buildBtn.disabled = false; buildBtn.textContent = buildLabel; }
                if (rebuildBtn) { rebuildBtn.disabled = false; rebuildBtn.textContent = rebuildLabel; }
                updateBuildBtn();
                renderPromptsList();
                if (!options.quietSuccess) await loadPromptsData();
            } catch {
                if (token !== promptsRequestToken) return;
                showToast('Prompt index build failed');
            } finally {
                // Only clear the building flag if this build is still the active one.
                // Otherwise a superseded build would clear the spinner while the
                // newer build is still in flight.
                if (token !== promptsRequestToken) return;
                promptsBuilding = false;
                if (buildBtn) {
                    buildBtn.disabled = false;
                    buildBtn.textContent = buildLabel;
                }
                if (rebuildBtn) {
                    rebuildBtn.disabled = false;
                    rebuildBtn.textContent = rebuildLabel;
                }
                updateBuildBtn();
                renderPromptsList();
            }
        }
