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
        let promptsSelectedEntryKey = null;
        const promptsDetailModes = {
            positive: false,
            negative: false,
            images: false,
        };
        let promptsRequestToken = 0;
        let promptsBuilding = false;
        let _promptPrevValue = '';
        let _promptBlurTimer = null;
        let _promptsRenderTimer = null;
        let mediaSearchRequestToken = 0;
        let mediaSearchApplyToken = 0;
        let mediaSearchTimer = null;
        let mediaSearchResults = null;
        let mediaSearchBuilding = false;
        const mediaSearchIndexStates = new Map();
        let pendingMediaSearchBuildBatches = [];
        let librarySearchTab = (function() {
            const stored = localStorage.getItem(LIBRARY_SEARCH_TAB_KEY);
            return stored === 'images' ? 'images' : 'prompts';
        })();

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

        // --- Modal lifecycle ---

        async function showPromptsModal() {
            const modal = document.getElementById('prompts-modal');
            modal.classList.add('active');
            setLibrarySearchTab(librarySearchTab);
            const activePanel = document.getElementById(
                librarySearchTab === 'images' ? 'media-search-panel' : 'prompt-groups-panel'
            );
            const closeButton = activePanel?.querySelector('.prompts-workbench-footer .cancel');
            _trapFocus(modal, closeButton);
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
            updateBuildBtn();
            const mediaInput = document.getElementById('media-search-input');
            const mediaScope = document.getElementById('media-search-scope');
            if (mediaInput && !mediaInput.value) {
                mediaInput.value = localStorage.getItem(MEDIA_SEARCH_QUERY_KEY) || '';
            }
            if (mediaScope) {
                const storedScope = localStorage.getItem(MEDIA_SEARCH_SCOPE_KEY);
                mediaScope.value = ['folder', 'batch', 'all'].includes(storedScope) ? storedScope : 'folder';
            }
            setLibrarySearchTab(librarySearchTab, {load: true});
        }

        function hidePromptsModal() {
            // Cancel any in-flight search debounce so it cannot fire renderPromptsList
            // on a hidden modal and clobber state on the next open.
            if (_promptsRenderTimer) {
                clearTimeout(_promptsRenderTimer);
                _promptsRenderTimer = null;
            }
            if (mediaSearchTimer) {
                clearTimeout(mediaSearchTimer);
                mediaSearchTimer = null;
            }
            mediaSearchRequestToken += 1;
            _invalidateMediaSearchApply();
            _promptCloseDropdown();
            hideMediaSearchBuildConfirm();
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
            updateScopeChip();
        }

        function updateScopeChip() {
            const chip = document.getElementById('prompts-scope-chip');
            if (!chip) return;
            if (librarySearchTab === 'images') {
                const options = _mediaSearchOptions();
                let label = 'Scope: All Batches';
                if (options.scope === 'batch') {
                    label = `Scope: ${options.batch}`;
                } else if (options.scope === 'folder') {
                    label = `Scope: ${options.batch} / ${options.folder}`;
                }
                chip.textContent = label;
                chip.classList.toggle('is-all', label === 'Scope: All Batches');
                return;
            }
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
            [{batch: '', label: 'All Batches'}, ...promptsBatchList.map(batch => ({batch, label: batch}))].forEach(option => {
                const normalized = option.label.toLowerCase();
                if (q && !normalized.includes(q)) return;
                matches.push({...option, startsWith: normalized.startsWith(q)});
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
            matches.forEach(({ batch, label }, index) => {
                const li = document.createElement('li');
                li.className = 'prompts-batch-option';
                li.dataset.value = batch;
                li.id = `prompts-batch-option-${index}`;
                li.textContent = label;
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
            promptsSelectedEntryKey = null;
            if (input) {
                input.value = batch;
                input.blur();
            }
            _promptPrevValue = '';
            _promptCloseDropdown();
            _syncPromptDisplay();
            updateBuildBtn();
            _syncPromptSelectionControls();
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

        // --- Library search tabs and media metadata search ---

        function setLibrarySearchTab(tab, options = {}) {
            _invalidateMediaSearchApply();
            librarySearchTab = tab === 'images' ? 'images' : 'prompts';
            _promptsLocalSet(LIBRARY_SEARCH_TAB_KEY, librarySearchTab);
            const mediaTab = document.getElementById('media-search-tab');
            const promptTab = document.getElementById('prompt-groups-tab');
            const mediaPanel = document.getElementById('media-search-panel');
            const promptPanel = document.getElementById('prompt-groups-panel');
            const mediaActive = librarySearchTab === 'images';
            if (mediaTab) {
                mediaTab.setAttribute('aria-selected', mediaActive ? 'true' : 'false');
                mediaTab.tabIndex = mediaActive ? 0 : -1;
            }
            if (promptTab) {
                promptTab.setAttribute('aria-selected', mediaActive ? 'false' : 'true');
                promptTab.tabIndex = mediaActive ? -1 : 0;
            }
            if (mediaPanel) mediaPanel.hidden = !mediaActive;
            if (promptPanel) promptPanel.hidden = mediaActive;
            updateScopeChip();
            if (!options.load) return;
            if (mediaActive) runMediaSearch();
            else loadPromptsData();
        }

        function _mediaSearchContext() {
            if (!isWorkspaceSearchView()) return {batch: currentBatch, folder: currentFolder};
            const returnBatch = workspaceSearchReturnContext?.batch;
            if (returnBatch && !String(returnBatch).startsWith('__')) {
                return {
                    batch: returnBatch,
                    folder: workspaceSearchReturnContext?.folder || null,
                };
            }
            return {
                batch: workspaceSearchFilter?.batch || null,
                folder: workspaceSearchFilter?.folder || null,
            };
        }

        function _mediaSearchOptions() {
            const scope = document.getElementById('media-search-scope')?.value || 'folder';
            const context = _mediaSearchContext();
            const contextBatch = context.batch;
            const contextFolder = context.folder;
            if (scope === 'all' || !contextBatch || (isVirtualCollectionView() && !isWorkspaceSearchView())) return {scope: 'all'};
            if (scope === 'batch' || !contextFolder || contextFolder === 'public') {
                return {scope: 'batch', batch: contextBatch};
            }
            return {scope: 'folder', batch: contextBatch, folder: contextFolder};
        }

        function scheduleMediaSearch() {
            _invalidateMediaSearchApply();
            if (mediaSearchTimer) clearTimeout(mediaSearchTimer);
            mediaSearchTimer = setTimeout(() => {
                mediaSearchTimer = null;
                runMediaSearch();
            }, 240);
        }

        async function runMediaSearch() {
            _invalidateMediaSearchApply();
            const input = document.getElementById('media-search-input');
            const list = document.getElementById('media-search-results');
            const total = document.getElementById('media-search-total');
            if (!input || !list || librarySearchTab !== 'images') return;
            const query = input.value.trim();
            const options = _mediaSearchOptions();
            _promptsLocalSet(MEDIA_SEARCH_QUERY_KEY, query);
            _promptsLocalSet(MEDIA_SEARCH_SCOPE_KEY, options.scope);
            updateScopeChip();
            const token = ++mediaSearchRequestToken;
            if (total) total.textContent = 'Searching...';
            list.replaceChildren(createTextElement('div', 'prompts-building-status', 'Searching indexes...'));
            try {
                const resp = await apiSearchMedia(query, options);
                if (token !== mediaSearchRequestToken) return;
                if (!resp.ok) throw new Error('media search failed');
                const data = await resp.json();
                if (token !== mediaSearchRequestToken) return;
                mediaSearchResults = data;
                renderMediaSearchResults(mediaSearchResults);
            } catch {
                if (token !== mediaSearchRequestToken) return;
                mediaSearchResults = null;
                if (total) total.textContent = 'Search failed';
                list.replaceChildren(createTextElement('div', 'prompts-empty-state', 'Media search failed. Try rebuilding the current index.'));
            }
        }

        function _mediaSearchSnippet(result) {
            if (result.prompt) return result.prompt;
            const sidecar = result.sidecar_summary || {};
            if (sidecar.tags) return String(sidecar.tags);
            const values = Object.values(sidecar).filter(value => value !== null && typeof value !== 'object');
            return values.length ? values.join(' · ') : 'Filename match';
        }

        function renderMediaSearchResults(data) {
            const list = document.getElementById('media-search-results');
            const total = document.getElementById('media-search-total');
            if (!list) return;
            list.replaceChildren();
            const items = data?.items || [];
            const missing = data?.missing_batches || [];
            const stale = data?.stale_batches || [];
            const unavailable = [...new Set([...missing, ...stale])];
            (data?.index_statuses || []).forEach(detail => {
                const transient = mediaSearchIndexStates.get(detail.batch);
                if (!mediaSearchBuilding || transient?.status !== 'building') {
                    mediaSearchIndexStates.set(detail.batch, {...detail});
                }
            });
            if (total) {
                total.textContent = `${data?.total || 0} result${data?.total === 1 ? '' : 's'}${data?.truncated ? ` · first ${data.limit}` : ''}`;
            }
            renderMediaSearchIndexStatus(data, unavailable);
            if (items.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'prompts-empty-state';
                empty.appendChild(createTextElement('div', 'prompts-empty-title', unavailable.length ? 'No current indexed matches yet' : 'No media match this search'));
                empty.appendChild(createTextElement('p', 'prompts-empty-body', unavailable.length
                    ? 'Build missing or stale search indexes, or change scope to a batch that is already indexed.'
                    : 'Try fewer words, a filename fragment, seed, model, LoRA, tag, or sidecar value.'));
                list.appendChild(empty);
                return;
            }
            items.forEach(result => {
                const row = document.createElement('article');
                row.className = 'media-search-result';
                const thumb = document.createElement('img');
                thumb.className = 'media-search-thumb';
                thumb.loading = 'lazy';
                thumb.alt = '';
                thumb.src = ccThumbUrl(result.batch, result.folder, result.name);
                const main = document.createElement('div');
                main.className = 'media-search-result-main';
                main.appendChild(createTextElement('div', 'media-search-result-name', result.name));
                main.appendChild(createTextElement('div', 'media-search-result-location', `${result.batch} / ${result.folder}`));
                main.appendChild(createTextElement('p', 'media-search-result-snippet', _mediaSearchSnippet(result)));
                const chips = document.createElement('div');
                chips.className = 'media-search-result-chips';
                (result.metadata_sources || []).forEach(source => chips.appendChild(createTextElement('span', 'media-search-chip', source === 'sidecar' ? 'JSON sidecar' : 'PNG metadata')));
                (result.matched_fields || []).forEach(field => chips.appendChild(createTextElement('span', 'media-search-chip is-match', field.replace('_', ' '))));
                main.appendChild(chips);
                const open = document.createElement('button');
                open.type = 'button';
                open.className = 'prompts-primary-action media-search-open';
                open.textContent = 'Open';
                open.addEventListener('click', () => openMediaSearchResult(result));
                row.append(thumb, main, open);
                list.appendChild(row);
            });
        }

        function _mediaSearchIndexStatus(batch, data = mediaSearchResults) {
            const persisted = (data?.index_statuses || []).find(item => item.batch === batch)
                || mediaSearchIndexStates.get(batch)
                || {batch, status: 'not_built', built_at: null, item_count: 0};
            const transient = mediaSearchIndexStates.get(batch);
            const status = transient && !['ready', 'stale', 'not_built'].includes(transient.status)
                ? transient.status
                : persisted.status;
            const labels = {
                not_built: 'Not built',
                building: 'Building',
                ready: 'Ready',
                stale: 'Stale',
                partially_failed: 'Partially failed',
                failed: 'Failed',
                cancelled: 'Cancelled',
            };
            const active = status === transient?.status ? transient : persisted;
            const builtAt = active.built_at || persisted.built_at;
            const age = builtAt ? _formatMediaSearchIndexAge(builtAt) : '';
            const count = Number.isFinite(Number(active.item_count)) ? Number(active.item_count) : 0;
            const details = status === 'not_built' ? 'No snapshot yet' : `${count} items${age ? ` · ${age}` : ''}`;
            return {batch, status, label: labels[status] || 'Not built', details};
        }

        function _formatMediaSearchIndexAge(builtAt) {
            const timestamp = Date.parse(builtAt);
            if (!Number.isFinite(timestamp)) return '';
            const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
            if (seconds < 60) return 'built just now';
            if (seconds < 3600) return `built ${Math.floor(seconds / 60)}m ago`;
            if (seconds < 86400) return `built ${Math.floor(seconds / 3600)}h ago`;
            return `built ${Math.floor(seconds / 86400)}d ago`;
        }

        function renderMediaSearchIndexStatus(data = mediaSearchResults, unavailable = []) {
            const container = document.getElementById('media-search-index-status');
            if (!container) return;
            container.replaceChildren();
            let statuses = Array.isArray(data?.index_statuses) ? data.index_statuses : [];
            if (statuses.length === 0) statuses = Array.from(mediaSearchIndexStates.values());
            if (statuses.length === 0) statuses = unavailable.map(batch => ({batch}));
            if (statuses.length === 0) {
                container.appendChild(createTextElement('span', 'media-search-index-note', 'Search index status unavailable.'));
            }
            statuses.forEach(detail => {
                const status = _mediaSearchIndexStatus(detail.batch, data);
                const row = document.createElement('span');
                row.className = `media-search-index-row is-${status.status.replace('_', '-')}`;
                row.appendChild(createTextElement('strong', 'media-search-index-badge', status.label));
                row.appendChild(createTextElement('span', 'media-search-index-batch', detail.batch));
                row.appendChild(createTextElement('span', 'media-search-index-detail', status.details));
                container.appendChild(row);
            });
            container.appendChild(createTextElement('span', 'media-search-index-note', 'Filesystem remains authoritative; indexes are rebuildable snapshots.'));
        }

        async function openMediaSearchResult(result) {
            hidePromptsModal();
            await selectFolder(result.batch, result.folder);
            let index = getImageDisplayIndexByName(result.name);
            if (index < 0 && pagedFolderMode && folderSnapshot) {
                const resp = await apiGetFolderItemIndex(
                    result.batch,
                    result.folder,
                    _folderTransportSort(),
                    currentOrder,
                    folderSnapshot.revision,
                    result.name,
                    folderShuffleSeed,
                );
                if (resp.ok) {
                    const payload = await resp.json();
                    index = payload.index;
                    await ensureFolderPageForIndex(index);
                }
            }
            if (index < 0) {
                showToast('The search result moved or the index is stale');
                return;
            }
            const content = document.querySelector('.content');
            const grid = document.getElementById('grid');
            if (content && grid) {
                const {track, gap} = getGridDensityConfig();
                const columns = _calculateFittedGridColumns(getCurrentDisplayImages().length);
                content.scrollTop = Math.max(0, getGridScrollOrigin(grid) + Math.floor(index / columns) * (track + gap));
                updateGrid();
            }
            openLightbox(index);
        }

        async function buildCurrentMediaSearchIndex() {
            const options = _mediaSearchOptions();
            const batch = options.batch || (isWorkspaceSearchView() ? workspaceSearchReturnContext?.batch : currentBatch);
            if (!batch || batch.startsWith('__')) {
                showToast('Select a real batch before building its search index');
                return;
            }
            await _buildMediaSearchIndexes([batch]);
        }

        function buildMissingMediaSearchIndexes() {
            const missing = [...new Set([
                ...(mediaSearchResults?.missing_batches || []),
                ...(mediaSearchResults?.stale_batches || []),
            ])];
            if (!mediaSearchResults && missing.length === 0) missing.push(...promptsBatchList);
            if (missing.length === 0) {
                showToast('All batches in this scope are indexed');
                return;
            }
            pendingMediaSearchBuildBatches = missing;
            const confirm = document.getElementById('media-search-build-confirm');
            const copy = document.getElementById('media-search-build-confirm-copy');
            const footerCopy = document.getElementById('media-search-footer-copy');
            if (copy) copy.textContent = `Build search indexes for ${missing.length} batch${missing.length === 1 ? '' : 'es'}?`;
            if (footerCopy) footerCopy.classList.add('hidden');
            if (confirm) {
                confirm.classList.remove('hidden');
                confirm.hidden = false;
                document.getElementById('media-search-build-confirm-btn')?.focus();
            }
        }

        function hideMediaSearchBuildConfirm() {
            pendingMediaSearchBuildBatches = [];
            const confirm = document.getElementById('media-search-build-confirm');
            const footerCopy = document.getElementById('media-search-footer-copy');
            if (footerCopy) footerCopy.classList.remove('hidden');
            if (confirm) {
                confirm.classList.add('hidden');
                confirm.hidden = true;
            }
        }

        async function confirmMissingMediaSearchIndexes() {
            const batches = pendingMediaSearchBuildBatches.slice();
            hideMediaSearchBuildConfirm();
            await _buildMediaSearchIndexes(batches);
        }

        async function _buildMediaSearchIndexes(batches) {
            if (mediaSearchBuilding || batches.length === 0) return;
            const activityId = `media-index:${batches.join('|')}`;
            activityRegister({
                id: activityId,
                kind: 'search-index',
                title: 'Build media search indexes',
                scope: batches.length === 1 ? batches[0] : `${batches.length} batches`,
                status: 'running',
                completed: 0,
                total: batches.length,
                detail: `Building ${batches[0]}…`,
                retry: () => _buildMediaSearchIndexes(batches),
            });
            mediaSearchBuilding = true;
            const buttons = ['media-search-build-btn', 'media-search-build-all-btn']
                .map(id => document.getElementById(id)).filter(Boolean);
            buttons.forEach(button => { button.disabled = true; });
            let activeBatch = null;
            try {
                for (let index = 0; index < batches.length; index++) {
                    activeBatch = batches[index];
                    mediaSearchIndexStates.set(activeBatch, {
                        batch: activeBatch,
                        status: 'building',
                        built_at: null,
                        item_count: 0,
                    });
                    renderMediaSearchIndexStatus(mediaSearchResults);
                    activityUpdate(activityId, {
                        status: 'running',
                        completed: index,
                        total: batches.length,
                        detail: `Building ${batches[index]} (${index + 1} of ${batches.length})…`,
                    });
                    const resp = await apiBuildMediaSearchIndex(batches[index]);
                    if (!resp.ok) throw new Error('search index build failed');
                    const summary = await resp.json();
                    mediaSearchIndexStates.set(activeBatch, {
                        batch: activeBatch,
                        status: 'ready',
                        built_at: summary.built_at || null,
                        item_count: summary.item_count || 0,
                    });
                    activityUpdate(activityId, {completed: index + 1, total: batches.length});
                }
                activityComplete(activityId, 'completed', {
                    completed: batches.length,
                    total: batches.length,
                    result: `Built ${batches.length} media search index${batches.length === 1 ? '' : 'es'}`,
                    detail: 'Search indexes ready',
                });
                showToast(`Built ${batches.length} media search index${batches.length === 1 ? '' : 'es'}`);
                await runMediaSearch();
            } catch {
                const completed = Number(activityGet(activityId)?.completed) || 0;
                if (activeBatch) {
                    const activityStatus = activityGet(activityId)?.status;
                    mediaSearchIndexStates.set(activeBatch, {
                        batch: activeBatch,
                        status: activityStatus === 'cancelled' ? 'cancelled' : 'failed',
                        built_at: mediaSearchIndexStates.get(activeBatch)?.built_at || null,
                        item_count: mediaSearchIndexStates.get(activeBatch)?.item_count || 0,
                    });
                    renderMediaSearchIndexStatus(mediaSearchResults);
                }
                activityComplete(activityId, completed > 0 ? 'partial' : 'failed', {
                    completed,
                    total: batches.length,
                    error: 'Media search index build failed',
                    detail: completed > 0 ? `${completed} of ${batches.length} indexes ready` : 'Try rebuilding the indexes',
                });
                showToast('Media search index build failed');
            } finally {
                mediaSearchBuilding = false;
                buttons.forEach(button => { button.disabled = false; });
            }
        }

        function _workspaceSearchScopeText(filter) {
            if (filter.scope === 'folder') return `Current folder · ${filter.batch} / ${filter.folder}`;
            if (filter.scope === 'batch') return `Batch · ${filter.batch}`;
            return 'All batches';
        }

        function _workspaceSearchSourceText(filter) {
            if (filter.scope === 'folder') return `${filter.batch} / ${filter.folder}`;
            if (filter.scope === 'batch') return filter.batch || 'Current batch';
            return 'All batches';
        }

        function _workspaceSearchChip(label, value, key) {
            const chip = document.createElement('span');
            chip.className = 'workspace-search-filter-chip';
            chip.setAttribute('role', 'listitem');
            chip.appendChild(createTextElement('span', 'workspace-search-filter-chip-label', `${label}:`));
            chip.appendChild(createTextElement('span', 'workspace-search-filter-chip-value', value));
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'workspace-search-filter-chip-remove';
            remove.textContent = '×';
            remove.setAttribute('aria-label', 'Clear active workspace search');
            remove.title = 'Clear active workspace search';
            remove.addEventListener('click', () => removeWorkspaceSearchChip(key));
            chip.appendChild(remove);
            return chip;
        }

        function renderWorkspaceSearchFilterChips(filter) {
            const chips = document.getElementById('workspace-search-filter-chips');
            if (!chips) return;
            chips.replaceChildren(
                _workspaceSearchChip('Query', `“${filter.query}”`, 'query'),
                _workspaceSearchChip('Scope', filter.scope === 'folder' ? 'Current folder' : filter.scope === 'batch' ? 'This batch' : 'All batches', 'scope'),
                _workspaceSearchChip('Source', _workspaceSearchSourceText(filter), 'source'),
            );
        }

        function removeWorkspaceSearchChip(key) {
            if (!workspaceSearchFilter || !['query', 'scope', 'source'].includes(key)) return;
            void clearWorkspaceSearchFilter();
        }

        function syncWorkspaceSearchFilterBar() {
            const bar = document.getElementById('workspace-search-filter-bar');
            const summary = document.getElementById('workspace-search-filter-summary');
            const count = document.getElementById('workspace-search-filter-count');
            const active = isWorkspaceSearchView() && !!workspaceSearchFilter;
            if (bar) bar.hidden = !active;
            document.body.classList.toggle('workspace-search-active', active);
            if (!active) return;
            if (summary) summary.textContent = `“${workspaceSearchFilter.query}” · ${_workspaceSearchScopeText(workspaceSearchFilter)}`;
            renderWorkspaceSearchFilterChips(workspaceSearchFilter);
            if (count) {
                count.textContent = workspaceSearchFilter.hasMore
                    ? `${workspaceSearchFilter.shown} of ${workspaceSearchFilter.total} loaded${workspaceSearchFilter.loading ? '…' : ''}`
                    : `${workspaceSearchFilter.total} match${workspaceSearchFilter.total === 1 ? '' : 'es'}`;
            }
        }

        function deactivateWorkspaceSearchFilter() {
            workspaceSearchFilter = null;
            syncWorkspaceSearchFilterBar();
        }

        function _invalidateMediaSearchApply() {
            mediaSearchApplyToken += 1;
            const applyButton = document.getElementById('media-search-apply-btn');
            if (applyButton) applyButton.disabled = false;
        }

        function _mediaSearchApplyStillOwned(operation) {
            if (!operation || operation.token !== mediaSearchApplyToken) return false;
            if (operation.transitionToken !== viewTransitionToken || operation.scopeKey !== getViewScopeKey()) return false;
            const input = document.getElementById('media-search-input');
            const scope = document.getElementById('media-search-scope');
            if ((input?.value.trim() || '') !== operation.query) return false;
            if ((scope?.value || 'folder') !== operation.scopeControl) return false;
            return true;
        }

        async function applyMediaSearchToWorkspace() {
            const input = document.getElementById('media-search-input');
            const query = input?.value.trim() || '';
            if (!query) {
                showToast('Enter search terms before filtering the workspace');
                input?.focus();
                return;
            }
            const options = {..._mediaSearchOptions(), limit: 500, offset: 0};
            const applyButton = document.getElementById('media-search-apply-btn');
            if (mediaSearchTimer) {
                clearTimeout(mediaSearchTimer);
                mediaSearchTimer = null;
            }
            mediaSearchRequestToken += 1;
            const operation = {
                token: ++mediaSearchApplyToken,
                transitionToken: viewTransitionToken,
                scopeKey: getViewScopeKey(),
                query,
                scopeControl: document.getElementById('media-search-scope')?.value || 'folder',
            };
            if (applyButton) applyButton.disabled = true;
            try {
                const resp = await apiSearchMedia(query, options);
                if (!_mediaSearchApplyStillOwned(operation)) return;
                if (!resp.ok) throw new Error('workspace search failed');
                const data = await resp.json();
                if (!_mediaSearchApplyStillOwned(operation)) return;
                mediaSearchResults = data;
                renderMediaSearchResults(data);
                const unavailable = [...(data.missing_batches || []), ...(data.stale_batches || [])];
                if (unavailable.length > 0) {
                    showToast('Build missing or stale indexes before filtering the workspace');
                    return;
                }
                let favoriteKeys = new Set();
                try {
                    const favoriteResp = await fetch(ccApiPath('/api/favorites'));
                    if (favoriteResp.ok) {
                        const favoriteData = await favoriteResp.json();
                        favoriteKeys = new Set((favoriteData.favorites || []).map(item => `${item.batch}\u001f${item.folder}\u001f${item.filename}`));
                    }
                } catch { console.warn('workspace search favorite status load failed'); }

                if (!_mediaSearchApplyStillOwned(operation)) return;

                if (!isWorkspaceSearchView()) {
                    workspaceSearchReturnContext = {
                        batch: currentBatch,
                        folder: currentFolder,
                        anchor: typeof _captureGridIdentityAnchor === 'function'
                            ? _captureGridIdentityAnchor()
                            : null,
                    };
                }
                workspaceSearchFilter = {
                    key: `${Date.now()}-${query}`,
                    query,
                    scope: options.scope,
                    batch: options.batch || null,
                    folder: options.folder || null,
                    total: data.total || 0,
                    shown: (data.items || []).length,
                    hasMore: data.has_more === true,
                    nextOffset: data.next_offset,
                    snapshot: data.snapshot || null,
                    pageSize: data.limit || 500,
                    loading: false,
                    favoriteKeys,
                };
                beginViewTransition({clearImages: true, closeLightbox: true});
                folderRequestToken += 1;
                resetPagedFolderState();
                currentBatch = '__search__';
                currentFolder = null;
                images = (data.items || []).map(item => ({
                    ...item,
                    modified_at: item.mtime || 0,
                    favorite: favoriteKeys.has(`${item.batch}\u001f${item.folder}\u001f${item.name}`),
                }));
                resetAiBatchState(false);
                document.querySelectorAll('.batch-name').forEach(el => el.classList.remove('selected'));
                document.getElementById('folder-tabs')?.classList.remove('visible');
                const sortControls = document.getElementById('sort-controls');
                if (sortControls) sortControls.style.display = 'flex';
                const pathEl = document.getElementById('current-path');
                if (pathEl) pathEl.replaceChildren(createTextElement('span', 'path', 'Filtered workspace'));
                const content = document.querySelector('.content');
                if (content) content.scrollTop = 0;
                syncWorkspaceSearchFilterBar();
                updateImageCountLabel();
                updateGrid();
                hidePromptsModal();
                showToast(workspaceSearchFilter.hasMore
                    ? `Loaded ${images.length} of ${workspaceSearchFilter.total} matching media items`
                    : `Workspace filtered to ${images.length} matching item${images.length === 1 ? '' : 's'}`);
            } catch {
                if (!_mediaSearchApplyStillOwned(operation)) return;
                showToast('Could not filter the workspace');
            } finally {
                if (applyButton && operation.token === mediaSearchApplyToken) applyButton.disabled = false;
            }
        }

        async function loadMoreWorkspaceSearchResults() {
            const filter = workspaceSearchFilter;
            if (!isWorkspaceSearchView() || !filter?.hasMore || filter.loading) return false;
            filter.loading = true;
            syncWorkspaceSearchFilterBar();
            try {
                const options = {
                    scope: filter.scope,
                    batch: filter.batch,
                    folder: filter.folder,
                    limit: filter.pageSize,
                    offset: filter.nextOffset,
                    snapshot: filter.snapshot,
                };
                const resp = await apiSearchMedia(filter.query, options);
                if (resp.status === 409) {
                    filter.hasMore = false;
                    showToast('This search index changed. Edit and reapply the filter to refresh it.');
                    return false;
                }
                if (!resp.ok) throw new Error('workspace search page failed');
                const data = await resp.json();
                if (!isWorkspaceSearchView() || workspaceSearchFilter !== filter) return false;
                const existing = new Set(images.map(item => getImageRenderKey(item)));
                const nextImages = (data.items || []).map(item => ({
                    ...item,
                    modified_at: item.mtime || 0,
                    favorite: filter.favoriteKeys.has(`${item.batch}\u001f${item.folder}\u001f${item.name}`),
                })).filter(item => !existing.has(getImageRenderKey(item)));
                const gridAnchor = typeof _captureGridIdentityAnchor === 'function'
                    ? _captureGridIdentityAnchor()
                    : null;
                images.push(...nextImages);
                filter.shown = images.length;
                filter.hasMore = data.has_more === true;
                filter.nextOffset = data.next_offset;
                filter.snapshot = data.snapshot || filter.snapshot;
                updateImageCountLabel();
                updateGrid();
                if (typeof _restoreGridIdentityAnchor === 'function' && _restoreGridIdentityAnchor(gridAnchor)) {
                    updateGrid();
                }
                return nextImages.length > 0;
            } catch {
                showToast('Could not load more filtered results');
                return false;
            } finally {
                if (workspaceSearchFilter === filter) {
                    filter.loading = false;
                    syncWorkspaceSearchFilterBar();
                }
            }
        }

        function maybeLoadMoreWorkspaceSearchResults(visibleEndIndex) {
            if (!isWorkspaceSearchView() || !workspaceSearchFilter?.hasMore) return;
            if (visibleEndIndex < images.length - 64) return;
            void loadMoreWorkspaceSearchResults();
        }

        function _restoreWorkspaceSearchReturnAnchor(context) {
            const anchor = context?.anchor;
            if (!anchor?.key) return;
            if (typeof pagedFolderMode !== 'undefined' && pagedFolderMode && folderSnapshot
                && typeof apiGetFolderItemIndex === 'function'
                && typeof ensureFolderPageForIndex === 'function'
                && typeof _folderTransportSort === 'function'
                && typeof _restoreGridIdentityAnchor === 'function') {
                void (async () => {
                    try {
                        const lookupResp = await apiGetFolderItemIndex(
                            context.batch, context.folder || 'inbox', _folderTransportSort(), currentOrder,
                            folderSnapshot.revision, anchor.key, folderShuffleSeed,
                        );
                        if (!lookupResp || !lookupResp.ok || isWorkspaceSearchView()) return;
                        const lookup = await lookupResp.json();
                        if (typeof lookup.index !== 'number' || lookup.index < 0) return;
                        await ensureFolderPageForIndex(lookup.index);
                        _restoreGridIdentityAnchor(anchor);
                    } catch { /* anchor restore is best-effort; the view stays at the top */ }
                })();
                return;
            }
            if (typeof _restoreGridIdentityAnchor === 'function') {
                _restoreGridIdentityAnchor(anchor);
            }
        }

        async function clearWorkspaceSearchFilter() {
            const context = workspaceSearchReturnContext;
            deactivateWorkspaceSearchFilter();
            workspaceSearchReturnContext = null;
            if (!context?.batch) {
                currentBatch = null;
                currentFolder = null;
                images = [];
                updateImageCountLabel();
                updateGrid();
                return;
            }
            if (context.batch === '__favorites__') {
                await loadUniversalFavorites();
            } else if (context.batch === '__public__') {
                await loadAllPublic();
            } else {
                await selectFolder(context.batch, context.folder || 'inbox');
                document.querySelectorAll('.batch-name').forEach(el =>
                    el.classList.toggle('selected', el.dataset.batch === context.batch));
            }
            if (typeof _restoreWorkspaceSearchReturnAnchor === 'function') {
                _restoreWorkspaceSearchReturnAnchor(context);
            }
        }

        async function editWorkspaceSearchFilter() {
            if (!workspaceSearchFilter) return;
            const input = document.getElementById('media-search-input');
            const scope = document.getElementById('media-search-scope');
            if (input) input.value = workspaceSearchFilter.query;
            if (scope) scope.value = workspaceSearchFilter.scope;
            setLibrarySearchTab('images');
            await showPromptsModal();
            input?.focus();
            input?.select();
        }

        function updateWorkspaceSearchAfterMove(img, destination) {
            if (!isWorkspaceSearchView() || !workspaceSearchFilter || !img) return null;
            const priorIndex = images.indexOf(img);
            const snapshot = {...img};
            const oldKey = getImageRenderKey(img);
            if (workspaceSearchFilter.scope === 'folder') {
                images = images.filter(candidate => candidate !== img);
            } else {
                img.folder = destination;
            }
            gridThumbMap.delete(oldKey);
            workspaceSearchFilter.shown = images.length;
            workspaceSearchFilter.total = Math.max(0, workspaceSearchFilter.total - (workspaceSearchFilter.scope === 'folder' ? 1 : 0));
            syncWorkspaceSearchFilterBar();
            updateImageCountLabel();
            updateGrid();
            return {
                item: snapshot,
                index: priorIndex,
                destination,
                removed: workspaceSearchFilter.scope === 'folder',
            };
        }

        function restoreWorkspaceSearchAfterUndo(moveState) {
            if (!isWorkspaceSearchView() || !workspaceSearchFilter || !moveState?.item) return;
            if (moveState.removed) {
                const index = Math.max(0, Math.min(moveState.index, images.length));
                images.splice(index, 0, moveState.item);
                workspaceSearchFilter.total += 1;
            } else {
                const current = images.find(item =>
                    item.batch === moveState.item.batch
                    && item.name === moveState.item.name
                    && item.folder === moveState.destination);
                if (current) current.folder = moveState.item.folder;
            }
            workspaceSearchFilter.shown = images.length;
            syncWorkspaceSearchFilterBar();
            updateImageCountLabel();
            updateGrid();
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

        function _promptEntryKey(entry) {
            const identity = entry.hash || entry.normalized || entry.prompt || '';
            return JSON.stringify([entry.batch || '', identity]);
        }

        function _selectedPromptEntry() {
            if (!promptsSelectedEntryKey) return null;
            return getPromptEntries().find(entry => _promptEntryKey(entry) === promptsSelectedEntryKey) || null;
        }

        function _syncPromptSelectionControls() {
            const selected = _selectedPromptEntry();
            const globalPositiveExpanded = !promptsCollapseAll;
            const status = document.getElementById('prompts-selection-status');
            if (status) {
                if (!selected) {
                    status.textContent = 'Select a prompt row to inspect its full text and image references.';
                } else if (globalPositiveExpanded) {
                    status.textContent = `Selected prompt from ${selected.batch || 'current scope'}. All positive prompts are expanded; collapse them to use the selected-only override.`;
                } else {
                    status.textContent = `Selected prompt from ${selected.batch || 'current scope'}. View options transfer to the next selected row.`;
                }
            }
            const controls = {
                positive: document.getElementById('prompts-view-positive'),
                negative: document.getElementById('prompts-view-negative'),
                images: document.getElementById('prompts-view-images'),
            };
            Object.entries(controls).forEach(([mode, button]) => {
                if (!button) return;
                const available = !!selected && (
                    mode === 'positive'
                    || (mode === 'negative' && !!selected.negative_prompt)
                    || (mode === 'images' && (selected.images || []).length > 0)
                );
                const pressed = mode === 'positive' && selected
                    ? globalPositiveExpanded || promptsDetailModes.positive
                    : promptsDetailModes[mode];
                button.disabled = !available || (mode === 'positive' && globalPositiveExpanded);
                button.setAttribute('aria-pressed', pressed ? 'true' : 'false');
            });
        }

        function _selectPromptEntry(key, restoreFocus = false) {
            promptsSelectedEntryKey = key;
            renderPromptsList();
            if (!restoreFocus) return;
            const selectedButton = document.querySelector('#prompts-list .prompts-entry.selected .prompts-select-entry');
            if (selectedButton) selectedButton.focus();
        }

        function _setPromptDetailMode(mode, value) {
            if (!(mode in promptsDetailModes)) return;
            promptsDetailModes[mode] = !!value;
            renderPromptsList();
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

        function _buildActionChip(label, className, onClick) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `prompts-action-chip ${className}`;
            btn.textContent = label;
            btn.addEventListener('click', onClick);
            return btn;
        }

        function searchImagesForPrompt(entry) {
            const input = document.getElementById('media-search-input');
            const scope = document.getElementById('media-search-scope');
            if (input) input.value = String(entry.prompt || entry.normalized || '').trim();
            if (scope) {
                scope.value = entry.batch && entry.batch === currentBatch && !isVirtualCollectionView()
                    ? 'batch'
                    : 'all';
            }
            setLibrarySearchTab('images');
            runMediaSearch();
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

        function _buildNegativeDisclosure(negText, visible) {
            if (!negText || !visible) return null;
            const el = createTextElement('div', 'prompts-negative', '');
            el.appendChild(createTextElement('div', 'prompts-field-label', 'Negative prompt'));
            const text = createTextElement('div', 'prompts-negative-text', '');
            text.appendChild(_highlightMatchNode(negText, _currentSearchQuery()));
            el.appendChild(text);
            return el;
        }

        function _buildImageDisclosure(images, visible) {
            if (!visible || !images || images.length === 0) return null;
            const list = _buildImageChipList(images);
            if (!list) return null;
            list.classList.remove('hidden');
            return list;
        }

        function _buildFullDisclosure(promptText, expanded) {
            const truncated = `${promptText.slice(0, PROMPTS_TRUNCATE_LEN)}...`;
            const wrap = document.createElement('div');
            wrap.className = 'prompts-prompt-text';
            const text = promptText.length > PROMPTS_TRUNCATE_LEN && !expanded ? truncated : promptText;
            wrap.appendChild(_highlightMatchNode(text, _currentSearchQuery()));
            return wrap;
        }

        function _buildEntry(entry, query) {
            const card = document.createElement('article');
            card.className = 'prompts-entry';
            card.dataset.batch = entry.batch || '';
            card.dataset.hash = entry.hash || '';
            const entryKey = _promptEntryKey(entry);
            const isSelected = entryKey === promptsSelectedEntryKey;
            card.dataset.entryKey = entryKey;
            if (isSelected) card.classList.add('selected');
            card.addEventListener('click', event => {
                if (!event.target.closest('button')) _selectPromptEntry(entryKey);
            });

            const header = document.createElement('div');
            header.className = 'prompts-entry-header';
            header.appendChild(_buildCountChip(entry.count || 0));
            const selectButton = _buildActionChip(isSelected ? 'Selected' : 'Select', 'prompts-select-entry', event => {
                event.stopPropagation();
                _selectPromptEntry(entryKey, true);
            });
            selectButton.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
            selectButton.setAttribute('aria-label', `${isSelected ? 'Selected' : 'Select'} prompt from ${entry.batch || 'current batch'}`);
            header.appendChild(selectButton);
            const findButton = _buildActionChip('Find images', 'prompts-find-images', event => {
                event.stopPropagation();
                searchImagesForPrompt(entry);
            });
            findButton.setAttribute('aria-label', `Find images using this prompt from ${entry.batch || 'current batch'}`);
            header.appendChild(findButton);

            const textWrap = document.createElement('div');
            textWrap.className = 'prompts-entry-main';
            const promptText = String(entry.normalized || entry.prompt || '');
            const positiveExpanded = (isSelected && promptsDetailModes.positive) || !promptsCollapseAll;
            const full = _buildFullDisclosure(promptText, positiveExpanded);
            const neg = _buildNegativeDisclosure(entry.negative_prompt || '', isSelected && promptsDetailModes.negative);
            const imgs = _buildImageDisclosure(entry.images || [], isSelected && promptsDetailModes.images);

            const heading = document.createElement('div');
            heading.className = 'prompts-entry-heading';
            heading.appendChild(createTextElement('div', 'prompts-field-label', 'Positive prompt'));
            const copyActions = document.createElement('div');
            copyActions.className = 'prompts-copy-actions';
            copyActions.appendChild(_buildActionChip('copy positive', 'prompts-copy-prompt', () => copyMetadataText(promptText, 'positive prompt')));
            if (entry.negative_prompt) {
                copyActions.appendChild(_buildActionChip('copy negative', 'prompts-copy-neg', () => copyMetadataText(entry.negative_prompt, 'negative prompt')));
            } else {
                copyActions.appendChild(createTextElement('span', 'prompts-copy-placeholder', ''));
            }
            const copyPairText = _formatCopyPair(promptText, entry.negative_prompt || '');
            copyActions.appendChild(_buildActionChip('copy pair', 'prompts-copy-pair', () => copyMetadataText(copyPairText, 'prompt pair')));
            heading.appendChild(copyActions);

            textWrap.appendChild(heading);
            textWrap.appendChild(full);

            if (neg) textWrap.appendChild(neg);
            if (imgs) textWrap.appendChild(imgs);

            card.appendChild(header);
            card.appendChild(textWrap);
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
                promptsSelectedEntryKey = null;
                _syncPromptSelectionControls();
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
                promptsSelectedEntryKey = null;
                _syncPromptSelectionControls();
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
                promptsSelectedEntryKey = null;
                _syncPromptSelectionControls();
                list.appendChild(_buildNoMatchesState(query, allEntries.length));
                return;
            }

            const sorted = _sortedEntries(filtered);
            const truncated = sorted.length > PROMPTS_RENDER_CAP;
            const visible = truncated ? sorted.slice(0, PROMPTS_RENDER_CAP) : sorted;
            if (promptsSelectedEntryKey && !visible.some(entry => _promptEntryKey(entry) === promptsSelectedEntryKey)) {
                promptsSelectedEntryKey = null;
            }
            _syncPromptSelectionControls();

            if (truncated) {
                const cap = createTextElement('div', 'prompts-render-cap', `Showing first ${PROMPTS_RENDER_CAP} of ${sorted.length}. Refine your search to narrow results.`);
                list.appendChild(cap);
            }

            if (!promptsCurrentBatch) {
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
            wrap.className = 'prompts-empty-state';
            const title = createTextElement('div', 'prompts-empty-title', 'Index not built');
            const body = createTextElement('p', 'prompts-empty-body', `Build an index for ${batch} to search prompt metadata.`);
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
            wrap.className = 'prompts-empty-state';
            wrap.appendChild(createTextElement('div', 'prompts-empty-title', 'No prompt indexes'));
            wrap.appendChild(createTextElement('p', 'prompts-empty-body', 'Choose a batch to build its index, or use Build All Indexes below.'));
            return wrap;
        }

        function _buildNoMatchesState(query, totalCount) {
            const wrap = document.createElement('div');
            wrap.className = 'prompts-empty-state';
            if (!query) {
                wrap.appendChild(createTextElement('div', 'prompts-empty-title', 'No prompts found'));
                const emptyCopy = promptsCurrentBatch
                    ? 'This index contains no prompt metadata.'
                    : 'No indexed prompts are available across the current scope.';
                wrap.appendChild(createTextElement('p', 'prompts-empty-body', emptyCopy));
                return wrap;
            }
            const title = createTextElement('div', 'prompts-empty-title', `No prompts match "${query}"`);
            wrap.appendChild(title);
            const body = createTextElement('p', 'prompts-empty-body', `${totalCount} prompt${totalCount === 1 ? '' : 's'} available. Try a different search.`);
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
                if (isStale) _updatePromptsStaleLabel(stale, _promptsStaleCopy());
            }
        }

        function _promptsStaleCopy() {
            const promptCount = promptsData?.prompt_count;
            const age = promptsData?.built_at ? _formatRelativeTime(promptsData.built_at) : '';
            const parts = ['Index may be stale'];
            if (promptCount !== null && promptCount !== undefined) parts.push(`${promptCount} prompts`);
            if (age) parts.push(`built ${age}`);
            return parts.join(' · ');
        }

        function _updatePromptsStaleLabel(stale, text) {
            const btn = document.getElementById('prompts-rebuild-btn');
            if (!btn || btn.parentNode !== stale) return;
            let node = stale.firstChild;
            while (node && node !== btn) {
                const next = node.nextSibling;
                stale.removeChild(node);
                node = next;
            }
            if (text) stale.insertBefore(document.createTextNode(`${text} `), btn);
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
            const token = ++promptsRequestToken;
            const activityGroup = `prompt-index:${batch}`;
            const activityId = activityAttemptId(activityGroup, token);
            activityRegister({
                id: activityId,
                group: activityGroup,
                kind: 'prompt-index',
                title: 'Build prompt index',
                scope: batch,
                status: 'running',
                total: 1,
                detail: 'Reading PNG prompts…',
                retry: () => buildSinglePromptIndex(batch, options),
            });
            promptsBuilding = true;
            renderPromptsList();
            if (buildBtn) { buildBtn.disabled = true; buildBtn.textContent = 'Building...'; }
            if (rebuildBtn) { rebuildBtn.disabled = true; rebuildBtn.textContent = 'Building...'; }
            activityUpdate(activityId, {status: 'running', detail: 'Reading PNG prompts…'});
            try {
                const resp = await fetch(ccApiPath(`/api/prompt-history/${encodeURIComponent(batch)}/build`), {method: 'POST'});
                if (token !== promptsRequestToken) {
                    activityCancel(activityId);
                    return;
                }
                if (!resp.ok) throw new Error('build failed');
                activityComplete(activityId, 'completed', {
                    completed: 1,
                    total: 1,
                    result: 'Prompt index ready',
                    detail: 'Prompt history refreshed',
                });
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
                if (token !== promptsRequestToken) {
                    activityCancel(activityId);
                    return;
                }
                activityComplete(activityId, 'failed', {
                    error: 'Prompt index build failed',
                    detail: 'Try rebuilding the prompt index',
                });
                showToast('Prompt index build failed');
            } finally {
                // Only clear the building flag if this build is still the active one.
                // Otherwise a superseded build would clear the spinner while the
                // newer build is still in flight.
                if (token !== promptsRequestToken) {
                    activityCancel(activityId);
                    return;
                }
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
