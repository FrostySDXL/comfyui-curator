        const SIDEBAR_WIDTH_KEY = 'imageCurator.sidebarWidth';
        const SIDEBAR_OPEN_KEY = 'imageCurator.sidebarOpen';
        const BATCH_STATE_KEY = 'imageCurator.lastBatch';
        const FOLDER_STATE_KEY = 'imageCurator.lastFolder';
        const BATCH_SORT_KEY = 'imageCurator.batchSort';
        let currentBatch = null;
        let currentFolder = null;
        let images = [];
        let currentIndex = 0;
        let allCounts = {};
        let currentSort = 'date';
        let currentOrder = 'desc';
        let selectedImages = new Set();
        let lastSelectIndex = -1;
        let lastAction = null;
        let draggedFiles = [];
        let toastTimeout = null;
        let batchSort = (localStorage.getItem(BATCH_SORT_KEY) || 'alpha');
        let batchFilterQuery = '';
        let batchFilterTimer = null;
        let isDraggingImages = false;
        let folderRequestToken = 0;
        let gridThumbMap = new Map();
        let folderCountSnapshot = {};
        let pendingActiveBatchSelection = null;
        let _initialLoadDone = false;
        let _lastBatchListKey = null;
        const SIDEBAR_WIDTH_DEFAULT = 240;
        const SIDEBAR_WIDTH_MIN = 220;
        const SIDEBAR_WIDTH_MAX = 520;
        let sidebarWidth = SIDEBAR_WIDTH_DEFAULT;
        let sidebarOpen = true;
        let isSidebarResizing = false;
        let _sidebarResizePending = false;
        let _sidebarResizeLastEvent = null;

        // --- Global fetch error handling ---

        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled fetch/promise error:', event.reason);
            showToast('Network error — check connection and try again');
        });

        async function safeFetch(url, options = {}) {
            try {
                return await fetch(url, options);
            } catch (err) {
                console.error(`Fetch failed for ${url}:`, err);
                showToast('Network request failed');
                throw err;
            }
        }

        function clampSidebarWidth(value) {
            return Math.max(SIDEBAR_WIDTH_MIN, Math.min(SIDEBAR_WIDTH_MAX, value));
        }

        function applySidebarWidth(value, persist = true) {
            sidebarWidth = clampSidebarWidth(value);
            document.documentElement.style.setProperty('--sidebar-width', `${sidebarWidth}px`);
            document.documentElement.style.setProperty('--sidebar-effective-width', sidebarOpen ? `${sidebarWidth}px` : '0px');
            if (persist) localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
        }

        function initializeSidebarState() {
            const raw = localStorage.getItem(SIDEBAR_WIDTH_KEY);
            const parsed = raw ? parseInt(raw, 10) : SIDEBAR_WIDTH_DEFAULT;
            applySidebarWidth(Number.isFinite(parsed) ? parsed : SIDEBAR_WIDTH_DEFAULT, false);
            const openRaw = localStorage.getItem(SIDEBAR_OPEN_KEY);
            sidebarOpen = openRaw === null ? true : openRaw === 'true';
            syncBatchSidebarUi(false);
        }

        function saveBatchState() {
            if (currentBatch) localStorage.setItem(BATCH_STATE_KEY, currentBatch);
            else localStorage.removeItem(BATCH_STATE_KEY);
            if (currentFolder) localStorage.setItem(FOLDER_STATE_KEY, currentFolder);
            else localStorage.removeItem(FOLDER_STATE_KEY);
        }

        function restoreBatchState(batches) {
            const savedBatch = localStorage.getItem(BATCH_STATE_KEY);
            const savedFolder = localStorage.getItem(FOLDER_STATE_KEY);
            if (savedBatch && batches.includes(savedBatch)) {
                selectBatch(savedBatch);
                if (savedFolder) selectFolder(savedBatch, savedFolder);
                return true;
            }
            return false;
        }

        function syncBatchSidebarUi(persist = true) {
            const sidebar = document.getElementById('batch-sidebar');
            const resizer = document.getElementById('sidebar-resizer');
            const toggleBtn = document.getElementById('batch-sidebar-toggle-btn');
            document.documentElement.style.setProperty('--sidebar-effective-width', sidebarOpen ? `${sidebarWidth}px` : '0px');
            if (sidebar) sidebar.classList.toggle('collapsed', !sidebarOpen);
            if (resizer) resizer.classList.toggle('collapsed', !sidebarOpen);
            if (toggleBtn) toggleBtn.textContent = sidebarOpen ? 'Hide Batches' : 'Show Batches';
            if (persist) localStorage.setItem(SIDEBAR_OPEN_KEY, String(sidebarOpen));
        }

        function toggleBatchSidebar() {
            sidebarOpen = !sidebarOpen;
            syncBatchSidebarUi();
        }

        function ensureBatchSidebarOpen() {
            if (sidebarOpen) return;
            sidebarOpen = true;
            syncBatchSidebarUi();
        }

        function updateSidebarResizeVisualState(active) {
            const resizer = document.getElementById('sidebar-resizer');
            if (!resizer) return;
            resizer.classList.toggle('active', active);
        }

        function onSidebarResizeMove(event) {
            if (!isSidebarResizing) return;
            _sidebarResizeLastEvent = event;
            if (!_sidebarResizePending) {
                _sidebarResizePending = true;
                requestAnimationFrame(() => {
                    _sidebarResizePending = false;
                    if (!isSidebarResizing || !_sidebarResizeLastEvent) return;
                    applySidebarWidth(_sidebarResizeLastEvent.clientX);
                });
            }
        }

        function stopSidebarResize() {
            if (!isSidebarResizing) return;
            isSidebarResizing = false;
            updateSidebarResizeVisualState(false);
            document.removeEventListener('mousemove', onSidebarResizeMove);
            document.removeEventListener('mouseup', stopSidebarResize);
            document.removeEventListener('pointermove', onSidebarResizeMove);
            document.removeEventListener('pointerup', stopSidebarResize);
        }

        function startSidebarResize(event) {
            if (event.type === 'mousedown' && window.PointerEvent) return;
            event.preventDefault();
            isSidebarResizing = true;
            updateSidebarResizeVisualState(true);
            if (event.type === 'pointerdown') {
                document.addEventListener('pointermove', onSidebarResizeMove);
                document.addEventListener('pointerup', stopSidebarResize);
            } else {
                document.addEventListener('mousemove', onSidebarResizeMove);
                document.addEventListener('mouseup', stopSidebarResize);
            }
        }

        function updateAutoImportQuickAction(activeBatch) {
            const quickBtn = document.getElementById('set-auto-import-btn');
            if (!quickBtn) return;
            if (!currentBatch) {
                quickBtn.style.display = 'none';
                quickBtn.disabled = true;
                return;
            }
            quickBtn.style.display = 'inline-block';
            if (activeBatch === currentBatch) {
                quickBtn.textContent = 'Auto-import active';
                quickBtn.disabled = true;
            } else {
                quickBtn.textContent = 'Set as Auto-import';
                quickBtn.disabled = false;
            }
        }

        async function setCurrentBatchAsAutoImport() {
            if (!currentBatch) return;
            await setActiveBatch(currentBatch);
        }

        function normalizeBatchFilterQuery(value) {
            return (value || '').trim().toLowerCase();
        }

        function filterBatches(sortedBatches) {
            if (!batchFilterQuery) return sortedBatches;
            return sortedBatches.filter(batch => batch.toLowerCase().includes(batchFilterQuery));
        }

        function updateBatchSearchClearButton() {
            const clearBtn = document.getElementById('batch-search-clear');
            if (!clearBtn) return;
            clearBtn.classList.toggle('hidden', batchFilterQuery.length === 0);
        }

        function setBatchFilter(value) {
            batchFilterQuery = normalizeBatchFilterQuery(value);
            updateBatchSearchClearButton();
            if (batchFilterTimer) clearTimeout(batchFilterTimer);
            batchFilterTimer = setTimeout(loadBatches, 160);
        }

        function clearBatchSearch() {
            const input = document.getElementById('batch-search');
            if (!input) return;
            input.value = '';
            setBatchFilter('');
            input.focus();
        }

        // --- Data loading ---

        async function loadBatches() {
            const resp = await fetch('/api/batches').catch(err => {
                console.warn('loadBatches fetch failed', err);
                return null;
            });
            if (!resp || !resp.ok) return;
            const data = await resp.json();
            const batches = data.batches;
            const activeBatch = data.active_batch;
            allCounts = data.counts;
            const batchMeta = data.batch_meta || {};

            const pendingInfo = document.getElementById('pending-info');
            document.getElementById('pending-count').textContent = data.pending_count;
            pendingInfo.style.display = (data.pending_count > 0 && activeBatch) ? 'flex' : 'none';

            const select = document.getElementById('active-batch-select');
            const selectedAutoImportBatch = pendingActiveBatchSelection !== null ? pendingActiveBatchSelection : activeBatch;

            // Skip rebuilding the select when the batch list hasn't changed
            // (e.g. during background polling).  Rebuilding while the dropdown is
            // open causes the browser to render a partially-populated list.
            const batchListKey = batches.join(',');
            if (batchListKey !== _lastBatchListKey) {
                _lastBatchListKey = batchListKey;

                // Detach from DOM so Chrome discards the old dropdown widget
                // and creates a fresh one when re-attached.  Without this,
                // long option lists show blank rows until scrolled.
                const selectParent = select.parentNode;
                const selectPlaceholder = document.createComment('batch-select');
                selectParent.replaceChild(selectPlaceholder, select);

                // Build options in a fragment
                const selectFragment = document.createDocumentFragment();
                const defaultOpt = document.createElement('option');
                defaultOpt.value = '';
                defaultOpt.textContent = '-- Select batch --';
                selectFragment.appendChild(defaultOpt);
                batches.forEach(b => {
                    const opt = document.createElement('option');
                    opt.value = b;
                    opt.textContent = b;
                    opt.selected = b === selectedAutoImportBatch;
                    selectFragment.appendChild(opt);
                });
                // Clear any stale options before appending new ones
                select.options.length = 0;
                select.appendChild(selectFragment);

                // Re-attach to DOM (creates a fresh dropdown widget)
                selectPlaceholder.parentNode.replaceChild(select, selectPlaceholder);
            }
            select.value = selectedAutoImportBatch || '';
            _syncCustomSelectDisplay();
            if (pendingActiveBatchSelection === activeBatch) pendingActiveBatchSelection = null;
            updateAutoImportQuickAction(selectedAutoImportBatch);

            // Sort batches based on current batch sort
            const sortedBatches = [...batches];
            if (batchSort === 'count') {
                sortedBatches.sort((a, b) => {
                    const ca = allCounts[a] || {}, cb = allCounts[b] || {};
                    const ta = (ca.inbox||0)+(ca.shortlisted||0)+(ca.finals||0);
                    const tb = (cb.inbox||0)+(cb.shortlisted||0)+(cb.finals||0);
                    return tb - ta;
                });
            } else if (batchSort === 'recent') {
                sortedBatches.sort((a, b) => {
                    const ma = batchMeta[a]?.modified_at || 0;
                    const mb = batchMeta[b]?.modified_at || 0;
                    if (mb !== ma) return mb - ma;
                    return a.localeCompare(b);
                });
            }
            // 'alpha' keeps the default server-sorted order

            const filteredBatches = filterBatches(sortedBatches);
            const countLabel = document.getElementById('batch-count-label');
            if (countLabel) {
                countLabel.textContent = `Batches ${sortedBatches.length} (${filteredBatches.length} shown)`;
            }

            renderBatchList(filteredBatches);

            updateBatchSearchClearButton();

            if (currentBatch) updateFolderTabs();

            // Restore previously opened batch on first successful load
            if (!_initialLoadDone) {
                _initialLoadDone = true;
                if (!currentBatch) restoreBatchState(batches);
            }

            // Load AI run counts only if we have uncached batches
            const uncachedBatches = filteredBatches.filter(b => !(b in aiBatchRunCounts));
            if (uncachedBatches.length > 0) {
                aiLoadBatchRunCounts(uncachedBatches).then(() => {
                    renderBatchList(filteredBatches);
                });
            }
        }

        function renderBatchList(filteredBatches) {
            const list = document.getElementById('batch-list');
            if (!list) return;
            if (filteredBatches.length === 0) {
                list.innerHTML = '<li class="batch-empty" aria-label="no batches found">No batches match</li>';
                return;
            }
            const fragment = document.createDocumentFragment();
            filteredBatches.forEach(batch => {
                const c = allCounts[batch] || {};
                const total = (c.inbox||0) + (c.shortlisted||0) + (c.finals||0);

                const li = document.createElement('li');
                li.className = 'batch-item';

                const div = document.createElement('div');
                div.className = 'batch-name' + (batch === currentBatch ? ' selected' : '');
                div.dataset.batch = batch;

                const nameSpan = document.createElement('span');
                nameSpan.textContent = batch;
                div.appendChild(nameSpan);

                if (aiBatchRunCounts[batch] > 0) {
                    const dot = document.createElement('span');
                    dot.className = 'batch-ai-dot';
                    dot.title = 'Has AI run history';
                    div.appendChild(dot);
                }

                const countSpan = document.createElement('span');
                countSpan.className = 'batch-count';
                countSpan.textContent = String(total);
                div.appendChild(countSpan);

                li.appendChild(div);
                fragment.appendChild(li);
            });
            list.replaceChildren(fragment);
        }

        // --- Custom batch dropdown (combobox: live-filter input + dropdown list) ---

        let _customSelectPrevValue = '';
        let _customSelectBlurTimer = null;

        function _populateCustomDropdown(filter = '') {
            const select = document.getElementById('active-batch-select');
            const dropdown = document.getElementById('active-batch-dropdown');
            if (!select || !dropdown) return;
            const q = filter.toLowerCase();
            dropdown.replaceChildren();
            // Collect matching options first, then sort:
            // startsWith matches appear before includes-only matches
            const matches = [];
            for (let i = 0; i < select.options.length; i++) {
                const opt = select.options[i];
                if (!opt.value) continue; // skip "-- Select batch --" placeholder
                const text = opt.textContent;
                if (q && !text.toLowerCase().includes(q)) continue;
                matches.push({ opt, text, startsWith: text.toLowerCase().startsWith(q) });
            }
            if (q) {
                matches.sort((a, b) => {
                    if (a.startsWith && !b.startsWith) return -1;
                    if (!a.startsWith && b.startsWith) return 1;
                    return 0; // preserve original order within each group
                });
            }
            for (const { opt, text } of matches) {
                const li = document.createElement('li');
                li.className = 'custom-select-option' + (opt.selected ? ' selected' : '');
                li.dataset.value = opt.value;
                li.textContent = text;
                li.setAttribute('role', 'option');
                li.addEventListener('mousedown', (e) => {
                    e.preventDefault();  // keep focus on input
                    clearTimeout(_customSelectBlurTimer);
                    _commitCustomSelectSelection(opt.value);
                });
                dropdown.appendChild(li);
            }
        }

        function _syncCustomSelectDisplay() {
            const select = document.getElementById('active-batch-select');
            const input = document.getElementById('active-batch-input');
            const arrow = document.getElementById('active-batch-arrow');
            const dropdown = document.getElementById('active-batch-dropdown');
            if (!select || !input) return;
            const selectedOpt = select.options[select.selectedIndex];
            const name = selectedOpt ? selectedOpt.textContent : '';
            // Don't overwrite input while dropdown is open (user is typing/searching)
            const wrapper = document.getElementById('active-batch-custom');
            const isOpen = wrapper && wrapper.classList.contains('open');
            if (!isOpen) {
                input.value = name;
                input.placeholder = name ? '' : 'Select batch...';
                if (arrow) arrow.style.display = '';
            }
            if (dropdown) {
                const value = select.value;
                dropdown.querySelectorAll('.custom-select-option').forEach(el => {
                    el.classList.toggle('selected', el.dataset.value === value);
                });
            }
        }

        function _commitCustomSelectSelection(value) {
            const select = document.getElementById('active-batch-select');
            const input = document.getElementById('active-batch-input');
            select.value = value || '';
            // Update input display directly (syncCustomSelectDisplay skips while open)
            const selectedOpt = select.options[select.selectedIndex];
            if (input) {
                input.value = selectedOpt ? selectedOpt.textContent : '';
                input.placeholder = selectedOpt ? '' : 'Select batch...';
                input.blur(); // release focus after selection
            }
            _customSelectPrevValue = ''; // selection committed, no restore needed
            _closeCustomDropdown();
            setActiveBatch(value || null);
        }

        function _openCustomDropdown() {
            const wrapper = document.getElementById('active-batch-custom');
            const input = document.getElementById('active-batch-input');
            const arrow = document.getElementById('active-batch-arrow');
            if (!wrapper || !input || wrapper.classList.contains('open')) return;
            _customSelectPrevValue = input.value;
            input.value = '';
            if (arrow) arrow.style.display = 'none';
            _populateCustomDropdown('');
            wrapper.classList.add('open');
            input.setAttribute('aria-expanded', 'true');
        }

        function _closeCustomDropdown(restoreInput = false) {
            const wrapper = document.getElementById('active-batch-custom');
            const input = document.getElementById('active-batch-input');
            const arrow = document.getElementById('active-batch-arrow');
            if (!wrapper) return;
            wrapper.classList.remove('open');
            if (input) {
                if (restoreInput && _customSelectPrevValue) {
                    input.value = _customSelectPrevValue;
                }
                input.setAttribute('aria-expanded', 'false');
            }
            if (arrow) arrow.style.display = '';
            clearTimeout(_customSelectBlurTimer);
            _customSelectBlurTimer = null;
        }

        function _customSelectMoveFocus(delta) {
            // Move .focus class among visible (non-display:none) options
            const dropdown = document.getElementById('active-batch-dropdown');
            if (!dropdown) return;
            const visible = Array.from(dropdown.querySelectorAll('.custom-select-option'))
                .filter(el => el.style.display !== 'none' && el.offsetParent !== null);
            if (visible.length === 0) return;
            const current = visible.findIndex(el => el.classList.contains('focus'));
            const next = current < 0 ? 0 : (current + delta + visible.length) % visible.length;
            visible.forEach(el => el.classList.remove('focus'));
            visible[next].classList.add('focus');
            visible[next].scrollIntoView({block: 'nearest'});
        }

        // Keyboard navigation + live-filter (input-based, no stopPropagation needed
        // because the document keyboard handler already skips INPUT elements)
        (function _bindCustomSelectKeys() {
            const input = document.getElementById('active-batch-input');
            if (!input) return;

            input.addEventListener('focus', () => {
                _openCustomDropdown();
            });

            input.addEventListener('blur', () => {
                _customSelectBlurTimer = setTimeout(() => {
                    const wrapper = document.getElementById('active-batch-custom');
                    if (!wrapper || !wrapper.classList.contains('open')) return;
                    const query = (input.value || '').trim();
                    // Case-insensitive exact match against option text
                    const options = document.querySelectorAll('#active-batch-dropdown .custom-select-option');
                    for (const opt of options) {
                        if (opt.textContent.trim().toLowerCase() === query.toLowerCase() && opt.dataset.value) {
                            _commitCustomSelectSelection(opt.dataset.value);
                            return;
                        }
                    }
                    // No match found — close dropdown but leave input as-is
                    // so the user can return and correct their search
                    _closeCustomDropdown(false);
                }, 150);
            });

            input.addEventListener('input', () => {
                if (!document.getElementById('active-batch-custom').classList.contains('open')) {
                    _openCustomDropdown();
                }
                _populateCustomDropdown(input.value);
            });

            input.addEventListener('keydown', (e) => {
                const wrapper = document.getElementById('active-batch-custom');
                if (!wrapper || !wrapper.classList.contains('open')) return;
                switch (e.key) {
                    case 'ArrowDown':
                        e.preventDefault();
                        _customSelectMoveFocus(1);
                        break;
                    case 'ArrowUp':
                        e.preventDefault();
                        _customSelectMoveFocus(-1);
                        break;
                    case 'Enter':
                        e.preventDefault();
                        const focused = document.querySelector('#active-batch-dropdown .custom-select-option.focus');
                        if (focused) {
                            clearTimeout(_customSelectBlurTimer);
                            _commitCustomSelectSelection(focused.dataset.value);
                        }
                        break;
                    case 'Escape':
                        _closeCustomDropdown(true);
                        break;
                }
            });
        })();

        // Close custom dropdown when clicking outside
        document.addEventListener('mousedown', (e) => {
            const wrapper = document.getElementById('active-batch-custom');
            if (wrapper && wrapper.classList.contains('open') && !wrapper.contains(e.target)) {
                _closeCustomDropdown(true);
            }
        });

        // Delegated click handler for batch items (XSS-safe, no inline onclick)
        document.addEventListener('DOMContentLoaded', () => {
            const batchList = document.getElementById('batch-list');
            if (batchList) {
                batchList.addEventListener('click', (e) => {
                    const batchNameEl = e.target.closest('.batch-name');
                    if (batchNameEl && batchNameEl.dataset.batch) {
                        selectBatch(batchNameEl.dataset.batch);
                    }
                });
            }
        });

        function updateFolderTabs() {
            if (!currentBatch) return;
            const c = allCounts[currentBatch] || {};
            ['inbox','shortlisted','finals','rejects'].forEach(f => {
                const el = document.getElementById('tc-' + f);
                if (!el) return;
                const nextValue = c[f] || 0;
                if (folderCountSnapshot[f] !== undefined && folderCountSnapshot[f] !== nextValue) {
                    el.classList.remove('changed');
                    void el.offsetWidth;
                    el.classList.add('changed');
                }
                el.textContent = nextValue;
                folderCountSnapshot[f] = nextValue;
            });
            const delBtn = document.getElementById('delete-rejects-btn');
            delBtn.style.display = (currentFolder === 'rejects' && (c.rejects||0) > 0) ? 'inline-block' : 'none';
        }

        // --- Batch & folder selection ---

        function selectBatch(batch) {
            const batchChanged = currentBatch !== batch;
            currentBatch = batch;
            saveBatchState();
            selectedImages.clear();
            lastSelectIndex = -1;
            lastAction = null;  // Clear undo state on batch switch
            updateActionBar();
            updateAutoImportQuickAction(document.getElementById('active-batch-select').value || null);
            document.querySelectorAll('.batch-name').forEach(el =>
                el.classList.toggle('selected', el.dataset.batch === batch));
            document.getElementById('folder-tabs').classList.add('visible');
            if (batchChanged) {
                resetAiBatchState();
                // Immediately clear grid and images to prevent flickering old thumbnails
                images = [];
                closeLightbox();
                clearGrid();
            }
            showAiCuratePanel();
            selectFolder(batch, 'inbox');
        }

        async function selectFolder(batch, folder) {
            currentBatch = batch;
            currentFolder = folder;
            saveBatchState();
            selectedImages.clear();
            lastSelectIndex = -1;
            updateActionBar();

            document.querySelectorAll('.folder-tab').forEach(t =>
                t.classList.toggle('active', t.dataset.folder === folder));
            document.getElementById('sort-controls').style.display = 'flex';
            const pathEl = document.getElementById('current-path');
            pathEl.replaceChildren();
            const pathSpan = document.createElement('span');
            pathSpan.className = 'path';
            pathSpan.textContent = batch;
            pathEl.appendChild(pathSpan);
            pathEl.appendChild(document.createTextNode(' / ' + folder));
            updateAutoImportQuickAction(document.getElementById('active-batch-select').value || null);
            updateFolderTabs();

            await loadCurrentFolderImages();
        }

        async function loadCurrentFolderImages() {
            if (!currentBatch || !currentFolder) return;
            const requestToken = ++folderRequestToken;
            const batch = currentBatch;
            const folder = currentFolder;
            const resp = await fetch(`/api/images/${batch}/${folder}?sort=${currentSort}&order=${currentOrder}`);
            if (!resp.ok) return;
            const nextImages = await resp.json();
            if (requestToken !== folderRequestToken) return;
            images = nextImages;
            document.getElementById('img-count').textContent =
                images.length > 0 ? ` (${images.length})` : '';
            updateGrid();
        }

        // --- Sort ---

        function setBatchSort(sort) {
            batchSort = sort;
            localStorage.setItem(BATCH_SORT_KEY, sort);
            document.querySelectorAll('.batch-sort-btn').forEach(b =>
                b.classList.toggle('active', b.dataset.bsort === sort));
            loadBatches();
        }

        function setSort(sort) {
            currentSort = sort;
            document.querySelectorAll('.sort-btn:not(.batch-sort-btn)').forEach(b => b.classList.toggle('active', b.dataset.sort === sort));
            document.getElementById('sort-dir-btn').style.display = sort === 'shuffle' || sort === 'score-desc' ? 'none' : 'flex';
            if (currentBatch && currentFolder) loadCurrentFolderImages();
        }

        function toggleOrder() {
            currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
            document.getElementById('sort-dir-btn').classList.toggle('asc', currentOrder === 'asc');
            if (currentBatch && currentFolder) loadCurrentFolderImages();
        }

        // --- Grid rendering ---

        function getDisplayImages() {
            return (aiActiveRun && currentSort === 'score-desc') ? aiSortImages(images) : images;
        }

        function getImageIndexByName(name) {
            return images.findIndex(img => img.name === name);
        }

        function createThumbElement() {
            const thumb = document.createElement('div');
            thumb.className = 'thumb loading';
            thumb.draggable = true;
            thumb.addEventListener('dragstart', (event) => onDragStart(event, Number(thumb.dataset.index)));
            thumb.addEventListener('click', (event) => onThumbClick(Number(thumb.dataset.index), event));

            const badge = document.createElement('span');
            badge.className = 'ai-score-badge';

            const select = document.createElement('div');
            select.className = 'thumb-select';
            select.innerHTML = `
                <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            `;
            select.addEventListener('click', (event) => {
                event.stopPropagation();
                toggleSelect(Number(thumb.dataset.index), event);
            });

            const img = document.createElement('img');
            img.loading = 'lazy';
            img.draggable = false;
            img.addEventListener('load', () => thumb.classList.remove('loading'));
            img.addEventListener('error', () => thumb.classList.remove('loading'));

            const meta = document.createElement('div');
            meta.className = 'thumb-meta';
            meta.innerHTML = '<span class="meta-name"></span><span class="meta-size"></span>';

            thumb.append(badge, select, img, meta);
            return thumb;
        }

        function updateThumbElement(thumb, img, index) {
            const scoreResult = aiGetImageScore ? aiGetImageScore(img.name) : null;
            const shouldShow = aiShouldShowImage ? aiShouldShowImage(img) : true;
            const badge = thumb.querySelector('.ai-score-badge');
            const selectBtn = thumb.querySelector('.thumb-select');
            const imageEl = thumb.querySelector('img');
            const metaName = thumb.querySelector('.meta-name');
            const metaSize = thumb.querySelector('.meta-size');
            const imageSrc = `/thumb/${currentBatch}/${currentFolder}/${encodeURIComponent(img.name)}`;

            thumb.dataset.name = img.name;
            thumb.dataset.index = String(index);
            thumb.classList.toggle('selected', selectedImages.has(img.name));
            thumb.classList.toggle('ai-filtered-out', !shouldShow);
            thumb.classList.remove('removing');
            if (selectBtn) selectBtn.classList.toggle('selected', selectedImages.has(img.name));

            if (badge) {
                if (aiShowOverlays && scoreResult) {
                    badge.className = `ai-score-badge visible${scoreResult.failed ? ' failed-badge' : ''}`;
                    badge.style.cssText = scoreResult.failed ? '' : aiScoreGradient(scoreResult.score, scoreResult.total);
                    badge.textContent = scoreResult.failed ? 'FAIL' : `${scoreResult.score}/${scoreResult.total}`;
                } else {
                    badge.className = 'ai-score-badge';
                    badge.style.cssText = '';
                    badge.textContent = '';
                }
            }

            if (imageEl && imageEl.getAttribute('src') !== imageSrc) {
                thumb.classList.add('loading');
                imageEl.src = imageSrc;
            }
            if (metaName) metaName.textContent = img.name;
            if (metaSize) metaSize.textContent = formatSize(img.size);
        }

        function clearGrid() {
            const grid = document.getElementById('grid');
            grid.replaceChildren();
            gridThumbMap.clear();
        }

        function updateGrid() {
            const grid = document.getElementById('grid');

            if (images.length === 0) {
                grid.replaceChildren(Object.assign(document.createElement('div'), {
                    className: 'empty',
                    textContent: 'No images in this folder',
                }));
                gridThumbMap.clear();
                return;
            }

            const displayImages = getDisplayImages();
            const activeNames = new Set(displayImages.map(img => img.name));
            for (const [name, element] of gridThumbMap.entries()) {
                if (!activeNames.has(name)) {
                    element.remove();
                    gridThumbMap.delete(name);
                }
            }

            const fragment = document.createDocumentFragment();
            displayImages.forEach((img) => {
                const originalIndex = getImageIndexByName(img.name);
                let thumb = gridThumbMap.get(img.name);
                if (!thumb) {
                    thumb = createThumbElement();
                    gridThumbMap.set(img.name, thumb);
                }
                updateThumbElement(thumb, img, originalIndex);
                fragment.appendChild(thumb);
            });

            // Replace all children atomically to prevent visible empty-grid flash
            grid.replaceChildren(fragment);
        }

        function formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
            return (bytes/1048576).toFixed(1) + ' MB';
        }

        // --- Selection ---

        function onThumbClick(index, event) {
            if (!images[index]) return;
            if (selectedImages.size > 0) {
                toggleSelect(index, event);
            } else {
                openLightbox(index);
            }
        }

        function toggleSelect(index, event) {
            if (!images[index]) return;
            const name = images[index].name;
            if (event.shiftKey && lastSelectIndex >= 0) {
                const lo = Math.min(lastSelectIndex, index);
                const hi = Math.max(lastSelectIndex, index);
                for (let i = lo; i <= hi; i++) selectedImages.add(images[i].name);
            } else {
                if (selectedImages.has(name)) selectedImages.delete(name);
                else selectedImages.add(name);
            }
            lastSelectIndex = index;
            updateSelectionVisuals();
            updateActionBar();
        }

        function clearSelection() {
            selectedImages.clear();
            lastSelectIndex = -1;
            updateSelectionVisuals();
            updateActionBar();
        }

        function updateSelectionVisuals() {
            const thumbs = document.querySelectorAll('#grid .thumb');
            thumbs.forEach(thumb => {
                const fname = thumb.dataset.name;
                if (!fname) return;
                const isSelected = selectedImages.has(fname);
                thumb.classList.toggle('selected', isSelected);
                const selectBtn = thumb.querySelector('.thumb-select');
                if (selectBtn) selectBtn.classList.toggle('selected', isSelected);
            });
        }

        function updateActionBar() {
            const bar = document.getElementById('action-bar');
            const grid = document.getElementById('grid');
            if (selectedImages.size > 0) {
                bar.classList.add('visible');
                grid.classList.add('selecting');
                document.getElementById('action-count').textContent = selectedImages.size + ' selected';
                bar.querySelectorAll('.action-btn[data-dest]').forEach(b =>
                    b.style.display = b.dataset.dest === currentFolder ? 'none' : '');
            } else {
                bar.classList.remove('visible');
                grid.classList.remove('selecting');
            }
        }

        // --- Drag and drop ---

        function onDragStart(event, index) {
            const img = images[index];
            if (!img) return;
            isDraggingImages = true;
            if (selectedImages.has(img.name) && selectedImages.size > 0) {
                draggedFiles = [...selectedImages];
            } else {
                draggedFiles = [img.name];
            }
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', '');
            event.target.addEventListener('dragend', () => {
                isDraggingImages = false;
                draggedFiles = [];
            }, {once: true});
            // Safety net: reset on document-level dragend in case the
            // element-level event doesn't fire (e.g. element removed mid-drag).
            document.addEventListener('dragend', function resetDragState() {
                isDraggingImages = false;
                draggedFiles = [];
                document.removeEventListener('dragend', resetDragState);
            }, {once: true});
        }

        function onDragOver(event) {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            event.currentTarget.classList.add('drag-over');
        }

        function onDragLeave(event) {
            event.currentTarget.classList.remove('drag-over');
        }

        function onDrop(event, folder) {
            event.preventDefault();
            event.currentTarget.classList.remove('drag-over');
            if (draggedFiles.length > 0 && folder !== currentFolder) {
                moveBatch(draggedFiles, folder);
            }
            draggedFiles = [];
        }

        // --- Move operations ---

        function recordLastAction(filenames, source, destination) {
            lastAction = {
                batch: currentBatch,
                filenames: [...filenames],
                source,
                destination,
                expiresAt: Date.now() + 8000,
            };
        }

        function getThumbByName(name) {
            return gridThumbMap.get(name) || document.querySelector(`#grid .thumb[data-name="${CSS.escape(name)}"]`);
        }

        async function animateThumbRemoval(names) {
            const targets = names
                .map(getThumbByName)
                .filter(Boolean);
            if (targets.length === 0) return;
            targets.forEach(target => target.classList.add('removing'));
            await new Promise(resolve => setTimeout(resolve, 180));
        }

        function removeImagesFromCurrentView(names) {
            const removeSet = new Set(names);
            images = images.filter(img => !removeSet.has(img.name));
            names.forEach(name => gridThumbMap.delete(name));
            document.getElementById('img-count').textContent = images.length > 0 ? ` (${images.length})` : '';
        }

        async function moveBatch(filenames, destination) {
            const resp = await fetch('/api/move-batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch: currentBatch, filenames: filenames,
                    source: currentFolder, destination: destination
                })
            });
            if (resp.ok) {
                const data = await resp.json();
                await animateThumbRemoval(filenames);
                recordLastAction(filenames, currentFolder, destination);
                showToast(`Moved ${data.moved} image${data.moved!==1?'s':''} to ${destination}`, true);
                removeImagesFromCurrentView(filenames);
                selectedImages.clear();
                updateGrid();
                updateActionBar();
                loadBatches();
            } else {
                const data = await resp.json().catch(() => ({}));
                showToast(data.error || 'Move failed');
            }
        }

        async function moveSelected(destination) {
            if (selectedImages.size === 0) return;
            await moveBatch([...selectedImages], destination);
        }

        async function moveImage(destination) {
            const img = images[currentIndex];
            if (!img) return;
            const resp = await fetch('/api/move', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch: currentBatch, filename: img.name,
                    source: currentFolder, destination: destination
                })
            });
            if (resp.ok) {
                await animateThumbRemoval([img.name]);
                recordLastAction([img.name], currentFolder, destination);
                showToast(`Moved to ${destination}`, true);
                removeImagesFromCurrentView([img.name]);
                loadBatches();
                if (images.length === 0) {
                    closeLightbox();
                    updateGrid();
                } else {
                    currentIndex = Math.min(currentIndex, images.length - 1);
                    updateGrid();
                    showCurrentImage();
                }
            } else {
                showToast('Error moving file');
            }
        }

        // --- Undo ---

        async function undoLastMove() {
            if (!lastAction) return;
            if (lastAction.expiresAt && Date.now() > lastAction.expiresAt) {
                lastAction = null;
                hideToast();
                return;
            }
            const {batch, filenames, source, destination} = lastAction;
            const resp = await fetch('/api/move-batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    batch, filenames, source: destination, destination: source
                })
            });
            if (resp.ok) {
                lastAction = null;
                hideToast();
                showToast(`Restored ${filenames.length} image${filenames.length!==1?'s':''}`);
                loadBatches();
                if (currentBatch === batch) loadCurrentFolderImages();
            }
        }

        // --- Delete rejects ---

        function showDeleteModal() {
            const modal = document.getElementById('delete-modal');
            document.getElementById('delete-count').textContent =
                (allCounts[currentBatch]?.rejects) || 0;
            modal.classList.add('active');
            _trapFocus(modal);
        }

        function hideDeleteModal() {
            document.getElementById('delete-modal').classList.remove('active');
            _releaseFocusTrap();
        }

        async function confirmDeleteRejects() {
            const resp = await fetch(`/api/delete-rejects/${currentBatch}`, {method:'POST'});
            if (resp.ok) {
                const data = await resp.json();
                hideDeleteModal();
                showToast(`Deleted ${data.count} rejected images`);
                loadBatches();
                if (currentFolder === 'rejects') { images = []; updateGrid(); }
                document.getElementById('img-count').textContent = '';
            } else {
                const data = await resp.json().catch(() => ({}));
                showToast(data.error || 'Delete failed');
            }
        }

        // --- Lightbox ---

        let lightboxZoom = 1;
        let lightboxMetadataOpen = false;
        let lightboxMetadataRequestToken = 0;
        let lightboxImageToken = 0;
        let currentLightboxMetadata = null;
        let currentLightboxMetadataLoading = false;
        let currentLightboxMetadataError = null;
        let currentLightboxDimensions = {w: null, h: null};
        const lightboxMetadataCache = new Map();
        const LIGHTBOX_METADATA_CACHE_MAX = 200;

        function openLightbox(index) {
            currentIndex = index;
            resetLightboxZoom();
            showCurrentImage();
            document.getElementById('lightbox').classList.add('active');
        }

        function closeLightbox() {
            document.getElementById('lightbox').classList.remove('active');
            resetLightboxZoom();
            lightboxMetadataOpen = false;
            renderLightboxMetadataPanel();
        }

        function applyLightboxZoom() {
            const wrap = document.getElementById('lightbox-image-wrap');
            document.documentElement.style.setProperty('--lightbox-zoom', String(lightboxZoom));
            if (wrap) wrap.classList.toggle('zoomed', lightboxZoom > 1.001);
        }

        function zoomLightbox(delta) {
            lightboxZoom = Math.min(3, Math.max(0.6, +(lightboxZoom + delta).toFixed(2)));
            applyLightboxZoom();
        }

        function resetLightboxZoom() {
            lightboxZoom = 1;
            applyLightboxZoom();
            const wrap = document.getElementById('lightbox-image-wrap');
            if (wrap) {
                wrap.scrollTop = 0;
                wrap.scrollLeft = 0;
            }
        }

        function getScoredImageIndices() {
            if (!aiActiveRun || !aiActiveRun.results) return [];
            return images
                .map((img, index) => ({img, index, score: aiGetImageScore(img.name)}))
                .filter(entry => entry.score && !entry.score.failed)
                .sort((a, b) => {
                    if (currentSort === 'score-desc') return b.score.score - a.score.score;
                    return a.index - b.index;
                })
                .map(entry => entry.index);
        }

        function navigateScored(delta) {
            const scoredIndices = getScoredImageIndices();
            if (scoredIndices.length === 0) {
                showToast('No scored images in this folder');
                return;
            }
            const currentScoredIndex = scoredIndices.indexOf(currentIndex);
            const nextPosition = currentScoredIndex >= 0
                ? (currentScoredIndex + delta + scoredIndices.length) % scoredIndices.length
                : (delta > 0 ? 0 : scoredIndices.length - 1);
            currentIndex = scoredIndices[nextPosition];
            showCurrentImage();
        }

        function showCurrentImage() {
            const img = images[currentIndex];
            if (!img) return;
            const imageToken = ++lightboxImageToken;
            const metadataToken = ++lightboxMetadataRequestToken;
            currentLightboxMetadata = null;
            currentLightboxMetadataError = null;
            currentLightboxMetadataLoading = false;
            currentLightboxDimensions = {w: null, h: null};
            renderLightboxMetadataPanel();
            const wrap = document.getElementById('lightbox-image-wrap');
            if (wrap && lightboxZoom <= 1.001) {
                wrap.scrollTop = 0;
                wrap.scrollLeft = 0;
            }
            const el = document.getElementById('lightbox-img');
            // Immediately hide (no transition) to prevent flash of previous image.
            // Do NOT removeAttribute('src') -- it collapses the <img> layout to 0x0
            // and causes a visual jump.  Inline opacity:0 already hides the old image.
            el.style.opacity = '0';
            el.classList.add('loading');
            el.onload = function() {
                if (imageToken !== lightboxImageToken) return;
                el.classList.remove('loading');
                el.style.opacity = '';
                currentLightboxDimensions = {w: this.naturalWidth, h: this.naturalHeight};
                updateLightboxInfo(img, this.naturalWidth, this.naturalHeight);
            };
            el.onerror = function() {
                el.classList.remove('loading');
                el.style.opacity = '';
            };
            // Use decode() when available to avoid flash of partially-decoded image
            const newSrc = `/image/${currentBatch}/${currentFolder}/${encodeURIComponent(img.name)}`;
            if (el.decode) {
                el.src = newSrc;
                el.decode().then(() => {
                    if (imageToken === lightboxImageToken) {
                        el.classList.remove('loading');
                        el.style.opacity = '';
                    }
                }).catch(() => {
                    el.classList.remove('loading');
                    el.style.opacity = '';
                });
            } else {
                el.src = newSrc;
            }
            loadLightboxMetadata(img, metadataToken);
        }

        function updateLightboxInfo(img, w, h) {
            const infoEl = document.getElementById('lightbox-info');
            infoEl.replaceChildren();
            let line1 = `${currentIndex+1} / ${images.length}  -  ${img.name}`;
            if (w && h) line1 += `  (${w}x${h})`;
            const lineEl = document.createElement('div');
            lineEl.className = 'lightbox-info-line';
            lineEl.textContent = line1;
            infoEl.appendChild(lineEl);

            // Add AI score breakdown if available
            const scoreResult = aiGetImageScore ? aiGetImageScore(img.name) : null;
            const scoreEl = document.createElement('div');
            if (scoreResult && scoreResult.failed) {
                scoreEl.className = 'lightbox-score-line failed';
                scoreEl.textContent = 'FAIL';
                infoEl.appendChild(scoreEl);
            } else if (scoreResult && !scoreResult.failed && aiActiveRun && aiActiveRun.elements && scoreResult.details) {
                const scoredIndices = getScoredImageIndices();
                const scoredPosition = scoredIndices.indexOf(currentIndex);
                const yes = [], no = [];
                for (const [k, v] of Object.entries(scoreResult.details)) {
                    const idx = parseInt(k);
                    const elem = aiActiveRun.elements[idx - 1] || `#${idx}`;
                    if (v === 'YES') yes.push(elem);
                    else no.push(elem);
                }
                scoreEl.className = 'lightbox-score-line';
                scoreEl.appendChild(document.createTextNode(`AI ${scoreResult.score}/${scoreResult.total}`));
                if (scoredPosition >= 0) {
                    const scoredEl = document.createElement('span');
                    scoredEl.className = 'scored-position';
                    scoredEl.textContent = `scored ${scoredPosition + 1} of ${scoredIndices.length}`;
                    scoreEl.appendChild(scoredEl);
                }
                if (no.length > 0) {
                    const missingEl = document.createElement('span');
                    missingEl.className = 'missing-elements';
                    missingEl.textContent = `missing: ${no.join(', ')}`;
                    scoreEl.appendChild(missingEl);
                }
                infoEl.appendChild(scoreEl);
            }
        }

        function getLightboxMetadataCacheKey(img) {
            return `${currentBatch}/${currentFolder}/${img.name}`;
        }

        async function loadLightboxMetadata(img, token) {
            const cacheKey = getLightboxMetadataCacheKey(img);
            if (lightboxMetadataCache.has(cacheKey)) {
                currentLightboxMetadata = lightboxMetadataCache.get(cacheKey);
                currentLightboxMetadataLoading = false;
                syncMetadataToggleButton();
                renderLightboxMetadataPanel();
                return;
            }
            currentLightboxMetadataLoading = true;
            syncMetadataToggleButton();
            try {
                const resp = await fetch(`/api/image-metadata/${encodeURIComponent(currentBatch)}/${encodeURIComponent(currentFolder)}/${encodeURIComponent(img.name)}`);
                if (!resp.ok) throw new Error(`metadata request failed (${resp.status})`);
                const data = await resp.json();
                if (token !== lightboxMetadataRequestToken) return;
                lightboxMetadataCache.set(cacheKey, data);
                // Evict oldest entries if cache exceeds limit
                while (lightboxMetadataCache.size > LIGHTBOX_METADATA_CACHE_MAX) {
                    const firstKey = lightboxMetadataCache.keys().next().value;
                    lightboxMetadataCache.delete(firstKey);
                }
                currentLightboxMetadata = data;
                currentLightboxMetadataError = null;
            } catch (error) {
                if (token !== lightboxMetadataRequestToken) return;
                currentLightboxMetadataError = error.message || 'metadata request failed';
                currentLightboxMetadata = null;
            } finally {
                if (token === lightboxMetadataRequestToken) {
                    currentLightboxMetadataLoading = false;
                    syncMetadataToggleButton();
                    renderLightboxMetadataPanel();
                }
            }
        }

        function syncMetadataToggleButton() {
            const btn = document.getElementById('metadata-toggle-btn');
            if (!btn) return;
            const hasMetadata = currentLightboxMetadata && currentLightboxMetadata.has_metadata;
            btn.disabled = !lightboxMetadataOpen && !currentLightboxMetadataLoading && !hasMetadata && !currentLightboxMetadataError;
            if (currentLightboxMetadataLoading) btn.textContent = 'Metadata...';
            else if (hasMetadata) btn.textContent = lightboxMetadataOpen ? 'Hide metadata' : 'Metadata';
            else if (currentLightboxMetadataError) btn.textContent = lightboxMetadataOpen ? 'Hide metadata' : 'Metadata error';
            else btn.textContent = lightboxMetadataOpen ? 'Hide metadata' : 'No metadata';
        }

        function toggleLightboxMetadata() {
            if (!lightboxMetadataOpen && !currentLightboxMetadataLoading && !currentLightboxMetadataError && !(currentLightboxMetadata && currentLightboxMetadata.has_metadata)) return;
            lightboxMetadataOpen = !lightboxMetadataOpen;
            syncMetadataToggleButton();
            renderLightboxMetadataPanel();
        }

        function createTextElement(tag, className, text) {
            const el = document.createElement(tag);
            if (className) el.className = className;
            el.textContent = text;
            return el;
        }

        // Strip <lora:name:weight> tokens from a prompt string for display only.
        // Mirrors the LORA_RE regex in image_curator/png_metadata.py so display
        // stays consistent with the dedicated LoRAs section. Cleans up orphan
        // commas and whitespace left behind by the removal.
        function stripLoraTags(text) {
            if (text === null || text === undefined) return text;
            const raw = String(text);
            if (!raw) return raw;
            const cleaned = raw.replace(/<lora:[^>]+>/g, '');
            const hadComma = cleaned.includes(',');
            const parts = cleaned.split(',').map(part => part.trim()).filter(part => part.length > 0);
            if (hadComma) {
                return parts.join(', ');
            }
            return parts.join(' ').replace(/\s+/g, ' ').trim();
        }

        function addMetadataField(grid, label, value) {
            if (value === null || value === undefined || value === '') return;
            const field = document.createElement('div');
            field.className = 'metadata-field';
            field.append(
                createTextElement('div', 'metadata-label', label),
                createTextElement('div', 'metadata-value', String(value))
            );
            grid.appendChild(field);
        }

        function addMetadataTextSection(panel, title, value, copyLabel) {
            if (!value) return;
            const section = document.createElement('section');
            section.className = 'metadata-section';
            section.appendChild(createTextElement('div', 'metadata-section-title', title));
            section.appendChild(createTextElement('pre', 'metadata-text', value));
            const actions = document.createElement('div');
            actions.className = 'metadata-actions';
            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'metadata-copy-btn';
            copyBtn.textContent = `Copy ${copyLabel}`;
            copyBtn.addEventListener('click', () => copyMetadataText(value, copyLabel));
            actions.appendChild(copyBtn);
            section.appendChild(actions);
            panel.appendChild(section);
        }

        function copyTextWithTextareaFallback(value) {
            const textarea = document.createElement('textarea');
            textarea.value = value;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.top = '-9999px';
            textarea.style.left = '-9999px';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            let copied = false;
            try {
                copied = document.execCommand('copy');
            } finally {
                document.body.removeChild(textarea);
            }
            return copied;
        }

        async function copyMetadataText(value, label) {
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(value);
                    showToast(`Copied ${label}`);
                    return;
                }
            } catch {
                // Fall through to the textarea copy path for local HTTP or denied clipboard access.
            }

            if (copyTextWithTextareaFallback(value)) {
                showToast(`Copied ${label}`);
            } else {
                showToast(`Could not copy ${label}`);
            }
        }

        function renderLightboxMetadataPanel() {
            const panel = document.getElementById('lightbox-metadata-panel');
            if (!panel) return;
            panel.classList.toggle('open', lightboxMetadataOpen);
            panel.replaceChildren();
            if (!lightboxMetadataOpen) return;

            if (currentLightboxMetadataLoading) {
                panel.appendChild(createTextElement('div', 'metadata-loading', 'Loading PNG generation metadata...'));
                return;
            }
            if (currentLightboxMetadataError) {
                panel.appendChild(createTextElement('div', 'metadata-error', currentLightboxMetadataError));
                return;
            }
            if (!currentLightboxMetadata || !currentLightboxMetadata.has_metadata) {
                panel.appendChild(createTextElement('div', 'metadata-empty', 'No PNG generation metadata found for this image.'));
                return;
            }

            const metadata = currentLightboxMetadata;
            const params = metadata.parameters || {};
            const header = document.createElement('div');
            header.className = 'metadata-header';
            const titleWrap = document.createElement('div');
            titleWrap.append(
                createTextElement('div', 'metadata-title', 'Generation metadata'),
                createTextElement('div', 'metadata-subtitle', `Raw chunks: ${(metadata.raw_keys || []).join(', ') || 'none'}`)
            );
            header.appendChild(titleWrap);
            panel.appendChild(header);

            const summary = document.createElement('section');
            summary.className = 'metadata-section';
            summary.appendChild(createTextElement('div', 'metadata-section-title', 'Summary'));
            const grid = document.createElement('div');
            grid.className = 'metadata-grid';
            addMetadataField(grid, 'Model', params.model);
            addMetadataField(grid, 'Model hash', params.model_hash);
            addMetadataField(grid, 'Seed', params.seed);
            addMetadataField(grid, 'Size', params.width && params.height ? `${params.width}x${params.height}` : null);
            addMetadataField(grid, 'Steps', params.steps);
            addMetadataField(grid, 'Sampler', params.sampler);
            addMetadataField(grid, 'CFG', params.cfg_scale);
            addMetadataField(grid, 'Clip skip', params.clip_skip);
            addMetadataField(grid, 'Version', params.version);
            addMetadataField(grid, 'Workflow JSON', metadata.workflow_available ? `${metadata.workflow_size} bytes available` : 'not present');
            summary.appendChild(grid);
            panel.appendChild(summary);

            addMetadataTextSection(panel, 'Positive prompt', stripLoraTags(params.prompt), 'positive prompt');
            addMetadataTextSection(panel, 'Negative prompt', stripLoraTags(params.negative_prompt), 'negative prompt');

            if (metadata.loras && metadata.loras.length > 0) {
                const section = document.createElement('section');
                section.className = 'metadata-section';
                section.appendChild(createTextElement('div', 'metadata-section-title', 'LoRAs'));
                const loras = document.createElement('div');
                loras.className = 'metadata-loras';
                metadata.loras.forEach(lora => {
                    const weight = lora.weight === null || lora.weight === undefined ? '?' : lora.weight;
                    loras.appendChild(createTextElement('span', 'metadata-lora-chip', `${lora.name} · ${weight}`));
                });
                section.appendChild(loras);
                panel.appendChild(section);
            }

            addMetadataTextSection(panel, 'Raw parameters', metadata.raw_parameters, 'parameters');
        }

        function navigate(delta) {
            if (images.length === 0) return;
            currentIndex = (currentIndex + delta + images.length) % images.length;
            showCurrentImage();
        }

        // --- Batch management ---

        async function setActiveBatch(batch) {
            pendingActiveBatchSelection = batch || null;
            const select = document.getElementById('active-batch-select');
            if (select) { select.value = batch || ''; _syncCustomSelectDisplay(); }
            const resp = await fetch('/api/active-batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({batch: batch})
            });
            if (resp.ok) {
                showToast(batch ? `Auto-importing to: ${batch}` : 'Auto-import disabled');
            } else {
                const data = await resp.json().catch(() => ({}));
                showToast(data.error || 'Failed to set active batch');
                pendingActiveBatchSelection = null;
            }
            await loadBatches();
        }

        async function importAll() {
            const batch = document.getElementById('active-batch-select').value;
            if (!batch) { showToast('Select a batch first'); return; }
            const resp = await fetch('/api/import-all', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({batch: batch})
            });
            if (resp.ok) {
                const data = await resp.json();
                showToast(`Imported ${data.count} images`);
                loadBatches();
                if (currentBatch === batch && currentFolder === 'inbox')
                    selectFolder(batch, 'inbox');
            } else { showToast('Import failed'); }
        }

        // --- Modal focus trap ---

        let _modalFocusRestore = null;
        let _activeModal = null;

        function _trapFocus(modal) {
            _activeModal = modal;
            _modalFocusRestore = document.activeElement;
            const focusable = modal.querySelectorAll(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            modal.addEventListener('keydown', function _modalKey(e) {
                if (e.key !== 'Tab') return;
                if (e.shiftKey) {
                    if (document.activeElement === first) {
                        e.preventDefault();
                        last.focus();
                    }
                } else {
                    if (document.activeElement === last) {
                        e.preventDefault();
                        first.focus();
                    }
                }
            });
            if (first) first.focus();
        }

        function _releaseFocusTrap() {
            _activeModal = null;
            if (_modalFocusRestore) {
                _modalFocusRestore.focus();
                _modalFocusRestore = null;
            }
        }

        function showNewBatchModal() {
            const modal = document.getElementById('new-batch-modal');
            modal.classList.add('active');
            _trapFocus(modal);
            document.getElementById('new-batch-name').focus();
        }
        function hideNewBatchModal() {
            document.getElementById('new-batch-modal').classList.remove('active');
            document.getElementById('new-batch-name').value = '';
            _releaseFocusTrap();
        }

        function showHelpModal() {
            const modal = document.getElementById('help-modal');
            modal.classList.add('active');
            _trapFocus(modal);
        }

        function hideHelpModal() {
            document.getElementById('help-modal').classList.remove('active');
            _releaseFocusTrap();
        }

        async function createBatch() {
            const name = document.getElementById('new-batch-name').value.trim();
            if (!name) return;
            const safeName = name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-_]/g, '');
            const resp = await fetch('/api/batches', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: safeName})
            });
            if (resp.ok) {
                hideNewBatchModal();
                await loadBatches();
                showToast(`Created batch: ${safeName}`);
                await setActiveBatch(safeName);
                document.getElementById('active-batch-select').value = safeName;
                _syncCustomSelectDisplay();
                selectBatch(safeName);
            } else { showToast('Failed to create batch'); }
        }

        // --- Toast ---

        function showToast(message, undoable = false) {
            const toast = document.getElementById('toast');
            document.getElementById('toast-text').textContent = message;
            const undoBtn = document.getElementById('toast-undo');
            undoBtn.style.display = (undoable && lastAction) ? 'inline-block' : 'none';
            toast.classList.add('show');
            if (toastTimeout) clearTimeout(toastTimeout);
            toastTimeout = setTimeout(() => {
                if (undoable) lastAction = null;
                toast.classList.remove('show');
            }, undoable ? 8000 : 3000);
        }

        function hideToast() {
            document.getElementById('toast').classList.remove('show');
            if (toastTimeout) clearTimeout(toastTimeout);
        }

        // --- Keyboard shortcuts ---

        document.addEventListener('keydown', (e) => {
            const activeEl = document.activeElement;
            const searchInput = document.getElementById('batch-search');
            const isTypingTarget = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable;
            const lightboxActive = document.getElementById('lightbox').classList.contains('active');

            if (e.key === "/" && !isTypingTarget) {
                e.preventDefault();
                ensureBatchSidebarOpen();
                if (searchInput) searchInput.focus();
                return;
            }

            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                ensureBatchSidebarOpen();
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
                return;
            }

            if (e.key === 'Escape' && searchInput && activeEl === searchInput) {
                e.preventDefault();
                clearBatchSearch();
                return;
            }

            if (e.key === 'Escape' && document.getElementById('help-modal').classList.contains('active')) {
                e.preventDefault();
                hideHelpModal();
                return;
            }

            if (isTypingTarget) return;

            if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
                e.preventDefault();
                undoLastMove();
                return;
            }

            if (!lightboxActive && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a' && currentBatch && currentFolder && images.length > 0) {
                e.preventDefault();
                selectedImages = new Set(images.map(img => img.name));
                lastSelectIndex = images.length - 1;
                updateSelectionVisuals();
                updateActionBar();
                return;
            }

            if (!lightboxActive) {
                switch (e.key.toLowerCase()) {
                    case 'b':
                        if (aiActiveRun) {
                            e.preventDefault();
                            const toggle = document.getElementById('ai-overlay-toggle');
                            if (toggle) {
                                toggle.checked = !toggle.checked;
                                aiToggleOverlays();
                            }
                        }
                        return;
                    case 'v':
                        if (aiActiveRun) {
                            e.preventDefault();
                            setSort(currentSort === 'score-desc' ? 'date' : 'score-desc');
                        }
                        return;
                    case 'i':
                        if (currentBatch) {
                            e.preventDefault();
                            toggleAiSidebar();
                        }
                        return;
                    case 'u':
                        e.preventDefault();
                        toggleBatchSidebar();
                        return;
                }
                return;
            }

            switch(e.key.toLowerCase()) {
                case 's': e.preventDefault(); moveImage('shortlisted'); break;
                case 'f': e.preventDefault(); moveImage('finals'); break;
                case 'r': e.preventDefault(); moveImage('rejects'); break;
                case 'arrowleft': e.preventDefault(); navigate(-1); break;
                case 'arrowright': e.preventDefault(); navigate(1); break;
                case '[': e.preventDefault(); navigateScored(-1); break;
                case ']': e.preventDefault(); navigateScored(1); break;
                case 'm': e.preventDefault(); toggleLightboxMetadata(); break;
                case '+':
                case '=': e.preventDefault(); zoomLightbox(0.2); break;
                case '-': e.preventDefault(); zoomLightbox(-0.2); break;
                case '0': e.preventDefault(); resetLightboxZoom(); break;
                case 'escape': e.preventDefault(); closeLightbox(); break;
            }
        });

        document.getElementById('lightbox-image-wrap').addEventListener('wheel', (event) => {
            if (!document.getElementById('lightbox').classList.contains('active')) return;
            if (!event.ctrlKey) return;
            event.preventDefault();
            zoomLightbox(event.deltaY < 0 ? 0.2 : -0.2);
        }, {passive: false});

        // --- Polling ---

        function isInteractionBusy() {
            return document.getElementById('lightbox').classList.contains('active')
                || isDraggingImages
                || isSidebarResizing
                || isAiSidebarResizing;
        }

        function buildImageSignature(list) {
            return list.map(img => `${img.name}:${img.size}`).join('|');
        }

        async function pollForChanges() {
            if (isInteractionBusy()) return;
            await loadBatches();
            if (!currentBatch || !currentFolder || selectedImages.size > 0 || isInteractionBusy()) return;
            const [imageResp, runResp] = await Promise.all([
                fetch(`/api/images/${currentBatch}/${currentFolder}?sort=${currentSort}&order=${currentOrder}`),
                fetch(`/api/ai-curate/batches/${currentBatch}/runs`),
            ]);
            if (!imageResp.ok || !runResp.ok) return;
            const [nextImages, runData] = await Promise.all([imageResp.json(), runResp.json()]);
            const imageChanged = buildImageSignature(nextImages) !== buildImageSignature(images);
            const latestRunId = runData.runs && runData.runs.length > 0 ? runData.runs[runData.runs.length - 1] : null;
            const aiChanged = (aiLatestRun?.run_id || null) !== latestRunId;

            if (imageChanged) {
                images = nextImages;
                document.getElementById('img-count').textContent = images.length > 0 ? ` (${images.length})` : '';
                updateGrid();
            }
            if (aiChanged) {
                await aiRefreshRunData(runData.runs || []);
                updateGrid();
                if (document.getElementById('lightbox').classList.contains('active')) showCurrentImage();
            }
        }

        setInterval(() => {
            pollForChanges().catch(() => { console.warn('pollForChanges failed'); });
        }, 5000);

        // --- AI Curation ---

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
            if (shell) shell.classList.toggle('collapsed', !aiSidebarOpen);
            if (panel) panel.classList.toggle('collapsed', !aiPanelOpen);
            if (body) body.style.display = aiPanelOpen ? 'block' : 'none';
            if (toggle) toggle.textContent = aiPanelOpen ? '−' : '+';
            if (headerBtn) headerBtn.textContent = aiSidebarOpen ? 'Hide AI' : 'Show AI';
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
            const shell = document.getElementById('ai-sidebar-shell');
            const headerBtn = document.getElementById('ai-sidebar-toggle-btn');
            if (shell) shell.style.display = currentBatch ? 'flex' : 'none';
            if (headerBtn) headerBtn.style.display = currentBatch ? 'inline-block' : 'none';
            aiRefreshRunData().catch(() => {});
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

        function _escapeHtml(text) {
            if (!text && text !== 0) return '';
            const div = document.createElement('div');
            div.appendChild(document.createTextNode(String(text)));
            return div.innerHTML;
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

        function resetAiBatchState() {
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
            updateGrid();
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
            const prompt = document.getElementById('ai-prompt').value.trim();
            const elementsText = document.getElementById('ai-elements').value.trim();
            if (!prompt && !elementsText) {
                showToast('Enter a prompt or elements first');
                return;
            }
            const body = { prompt: prompt || 'placeholder' };
            if (elementsText) {
                body.elements = elementsText.split('\n').map(e => e.trim()).filter(e => e.length > 0);
            }
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
            const prompt = document.getElementById('ai-prompt').value.trim();
            if (!prompt) {
                showToast('Enter a prompt first');
                return;
            }
            const elementsText = document.getElementById('ai-elements').value.trim();
            const moveEnabled = document.getElementById('ai-move-toggle').checked;
            const destFolder = document.getElementById('ai-dest-folder').value;

            const body = {
                batch: currentBatch,
                prompt: prompt,
                source_folder: document.getElementById('ai-source-folder').value,
                top_n: parseInt(document.getElementById('ai-top-n').value) || 15,
                model: document.getElementById('ai-model').value.trim(),
                move_enabled: moveEnabled,
                destination_folder: moveEnabled ? destFolder : null,
            };
            if (elementsText) {
                body.elements = elementsText.split('\n').map(e => e.trim()).filter(e => e.length > 0);
            }

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

        // --- Event delegation (replaces inline handlers for CSP compatibility) ---

        function _bindDelegatedEvents() {

            const importBtn = document.querySelector('.import-btn');
            if (importBtn) importBtn.addEventListener('click', importAll);

            // Batch sort buttons
            document.querySelectorAll('.batch-sort-btn').forEach(btn => {
                btn.addEventListener('click', function() { setBatchSort(this.dataset.bsort); });
            });

            // Batch search
            const batchSearch = document.getElementById('batch-search');
            if (batchSearch) batchSearch.addEventListener('input', function() {
                setBatchFilter(this.value);
            });

            const batchSearchClear = document.getElementById('batch-search-clear');
            if (batchSearchClear) batchSearchClear.addEventListener('click', clearBatchSearch);

            // New batch button
            const newBatchBtn = document.querySelector('.new-batch-btn');
            if (newBatchBtn) newBatchBtn.addEventListener('click', showNewBatchModal);

            // Sidebar resizer
            const resizer = document.getElementById('sidebar-resizer');
            if (resizer) {
                resizer.addEventListener('mousedown', startSidebarResize);
                resizer.addEventListener('pointerdown', startSidebarResize);
            }

            // Header buttons
            const batchToggleBtn = document.getElementById('batch-sidebar-toggle-btn');
            if (batchToggleBtn) batchToggleBtn.addEventListener('click', toggleBatchSidebar);

            const aiToggleBtn = document.getElementById('ai-sidebar-toggle-btn');
            if (aiToggleBtn) aiToggleBtn.addEventListener('click', toggleAiSidebar);

            const helpBtn = document.getElementById('help-btn');
            if (helpBtn) helpBtn.addEventListener('click', showHelpModal);

            const autoImportBtn = document.getElementById('set-auto-import-btn');
            if (autoImportBtn) autoImportBtn.addEventListener('click', setCurrentBatchAsAutoImport);

            // Sort controls
            document.querySelectorAll('.sort-btn:not(.batch-sort-btn)').forEach(btn => {
                btn.addEventListener('click', function() { setSort(this.dataset.sort); });
            });

            const sortDirBtn = document.getElementById('sort-dir-btn');
            if (sortDirBtn) sortDirBtn.addEventListener('click', toggleOrder);

            // Folder tabs (delegated)
            const folderTabs = document.getElementById('folder-tabs');
            if (folderTabs) {
                folderTabs.addEventListener('click', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab && tab.dataset.folder) {
                        selectFolder(currentBatch, tab.dataset.folder);
                    }
                });
                folderTabs.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        const tab = e.target.closest('.folder-tab');
                        if (tab && tab.dataset.folder) {
                            e.preventDefault();
                            selectFolder(currentBatch, tab.dataset.folder);
                        }
                    }
                });
                folderTabs.addEventListener('dragover', onDragOver);
                folderTabs.addEventListener('dragleave', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab) onDragLeave(e);
                });
                folderTabs.addEventListener('drop', function(e) {
                    const tab = e.target.closest('.folder-tab');
                    if (tab && tab.dataset.folder) {
                        e.preventDefault();
                        onDrop(e, tab.dataset.folder);
                    }
                });
            }

            // Lightbox buttons
            const lightboxBtns = {
                'lightbox-prev': function() { navigateLightbox(-1); },
                'lightbox-next': function() { navigateLightbox(1); },
                'lightbox-prev-scored': function() { navigateLightboxToScored(-1); },
                'lightbox-next-scored': function() { navigateLightboxToScored(1); },
                'lightbox-close': closeLightbox,
                'metadata-toggle-btn': toggleLightboxMetadata,
            };
            Object.entries(lightboxBtns).forEach(([id, handler]) => {
                const el = document.getElementById(id);
                if (el) el.addEventListener('click', handler);
            });

            // Move buttons in lightbox
            document.querySelectorAll('#lightbox-actions .btn-shortlist').forEach(btn => {
                btn.addEventListener('click', function() { moveImage('shortlisted'); });
            });
            document.querySelectorAll('#lightbox-actions .btn-finals').forEach(btn => {
                btn.addEventListener('click', function() { moveImage('finals'); });
            });
            document.querySelectorAll('#lightbox-actions .btn-reject').forEach(btn => {
                btn.addEventListener('click', function() { moveImage('rejects'); });
            });

            // Modal buttons
            document.querySelectorAll('#new-batch-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hideNewBatchModal);
            });
            document.querySelectorAll('#new-batch-modal .create').forEach(btn => {
                btn.addEventListener('click', createBatch);
            });
            const newBatchName = document.getElementById('new-batch-name');
            if (newBatchName) newBatchName.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') createBatch();
            });

            document.querySelectorAll('#delete-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hideDeleteModal);
            });
            document.querySelectorAll('#delete-modal .delete-confirm').forEach(btn => {
                btn.addEventListener('click', confirmDeleteRejects);
            });

            document.querySelectorAll('#help-modal .cancel').forEach(btn => {
                btn.addEventListener('click', hideHelpModal);
            });

            // Toast undo
            const toastUndo = document.getElementById('toast-undo');
            if (toastUndo) toastUndo.addEventListener('click', undoLastMove);

            // AI sidebar resizer
            const aiResizer = document.getElementById('ai-sidebar-resizer');
            if (aiResizer) {
                aiResizer.addEventListener('mousedown', startAiSidebarResize);
                aiResizer.addEventListener('pointerdown', startAiSidebarResize);
            }

            // AI curate header collapse toggle
            const aiCurateHeader = document.querySelector('.ai-curate-header');
            if (aiCurateHeader) {
                aiCurateHeader.addEventListener('click', toggleAiCuratePanel);
                aiCurateHeader.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') toggleAiCuratePanel();
                });
            }

            // AI overlay toggle
            const aiOverlayToggle = document.getElementById('ai-overlay-toggle');
            if (aiOverlayToggle) aiOverlayToggle.addEventListener('change', aiToggleOverlays);

            // AI filter mode
            const aiFilterMode = document.getElementById('ai-filter-mode');
            if (aiFilterMode) aiFilterMode.addEventListener('change', aiApplyFilter);

            // AI preview elements button
            const aiPreviewBtn = document.querySelector('.ai-btn-secondary');
            if (aiPreviewBtn) aiPreviewBtn.addEventListener('click', aiPreviewElements);

            // AI move toggle
            const aiMoveToggle = document.getElementById('ai-move-toggle');
            if (aiMoveToggle) aiMoveToggle.addEventListener('change', aiToggleMoveMode);

            // AI submit button
            const aiSubmitBtn = document.getElementById('ai-submit-btn');
            if (aiSubmitBtn) aiSubmitBtn.addEventListener('click', aiSubmitJob);

            // AI cancel button
            const aiCancelBtn = document.getElementById('ai-cancel-btn');
            if (aiCancelBtn) aiCancelBtn.addEventListener('click', aiCancelJob);

            // AI run history selectors
            const aiRunSelect = document.getElementById('ai-run-select');
            if (aiRunSelect) aiRunSelect.addEventListener('change', function() {
                aiLoadRun(this.value || null);
            });

            const aiDiffSelect = document.getElementById('ai-diff-select');
            if (aiDiffSelect) aiDiffSelect.addEventListener('change', function() {
                aiToggleRunDiff(this.value || null);
            });

            // AI compare run selector
            const aiCompareRunSelect = document.getElementById('ai-compare-run-select');
            if (aiCompareRunSelect) aiCompareRunSelect.addEventListener('change', function() {
                aiSetCompareRun(this.value);
            });

            // Delete rejects button
            const deleteRejectsBtn = document.getElementById('delete-rejects-btn');
            if (deleteRejectsBtn) deleteRejectsBtn.addEventListener('click', showDeleteModal);

            // Action bar (multi-select) buttons - delegated
            const actionBar = document.querySelector('.action-bar');
            if (actionBar) {
                actionBar.addEventListener('click', function(e) {
                    const btn = e.target.closest('.action-btn');
                    if (!btn) return;
                    if (btn.classList.contains('action-clear')) {
                        clearSelection();
                    } else if (btn.dataset.dest) {
                        moveSelected(btn.dataset.dest);
                    }
                });
            }

            // Lightbox close button
            const lightboxClose = document.querySelector('.lightbox-close');
            if (lightboxClose) {
                lightboxClose.addEventListener('click', closeLightbox);
                lightboxClose.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') closeLightbox();
                });
            }

            // Lightbox nav buttons
            document.querySelectorAll('.lightbox-nav.prev').forEach(el => {
                el.addEventListener('click', function() { navigateLightbox(-1); });
                el.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') navigateLightbox(-1);
                });
            });
            document.querySelectorAll('.lightbox-nav.next').forEach(el => {
                el.addEventListener('click', function() { navigateLightbox(1); });
                el.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') navigateLightbox(1);
                });
            });

            // Lightbox toolbar buttons - delegate on #lightbox-actions
            const lightboxActions = document.getElementById('lightbox-actions');
            if (lightboxActions) {
                lightboxActions.addEventListener('click', function(e) {
                    const btn = e.target.closest('button');
                    if (!btn) return;
                    if (btn.classList.contains('btn-shortlist')) moveImage('shortlisted');
                    else if (btn.classList.contains('btn-finals')) moveImage('finals');
                    else if (btn.classList.contains('btn-reject')) moveImage('rejects');
                    else if (btn.id === 'metadata-toggle-btn') toggleLightboxMetadata();
                });
                // Map button text to handlers for generic buttons
                lightboxActions.querySelectorAll('button').forEach(btn => {
                    const text = btn.textContent.trim();
                    if (text === 'Prev scored') btn.addEventListener('click', function() { navigateLightboxToScored(-1); });
                    else if (text === 'Next scored') btn.addEventListener('click', function() { navigateLightboxToScored(1); });
                    else if (text === 'Zoom \u2212') btn.addEventListener('click', function() { zoomLightbox(-0.2); });
                    else if (text === 'Reset zoom') btn.addEventListener('click', resetLightboxZoom);
                    else if (text === 'Zoom +') btn.addEventListener('click', function() { zoomLightbox(0.2); });
                });
            }
        }

        initializeSidebarState();
        initializeAiSidebarState();
        _bindDelegatedEvents();
        // Sync batch sort button highlights with stored preference
        document.querySelectorAll('.batch-sort-btn').forEach(b => b.classList.toggle('active', b.dataset.bsort === batchSort));
        loadBatches();
