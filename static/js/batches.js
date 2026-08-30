/* Ordered classic script.
 * Defines: batch list, active-batch combobox, batch/folder selection, imports, batch creation.
 * Later-file globals called at runtime: resetAiBatchState, showGridLoadingPlaceholders, loadCurrentFolderImages, loadUniversalFavorites, loadAllPublic, showAiCuratePanel.
 */
let _customSelectPrevValue = '';
let _customSelectBlurTimer = null;

let folderCountSnapshot = {};
let pendingActiveBatchSelection = null;
let _initialLoadDone = false;
let _lastBatchListKey = null;
let importInFlight = false;

function updatePendingImportUi(pendingCount, activeBatch) {
            const pendingInfo = document.getElementById('pending-info');
            const count = document.getElementById('pending-count');
            const importBtn = document.querySelector('.import-btn');
            const normalizedCount = Math.max(0, Number(pendingCount) || 0);
            if (count) count.textContent = normalizedCount;
            if (pendingInfo) pendingInfo.style.display = activeBatch ? 'flex' : 'none';
            if (importBtn) {
                importBtn.disabled = importInFlight || normalizedCount < 1;
                importBtn.textContent = importInFlight ? 'Importing…' : 'Import All';
            }
        }

async function pollImportAvailability() {
            const resp = await fetch(ccApiPath('/api/import-status')).catch(() => null);
            if (!resp || !resp.ok) return;
            const data = await resp.json();
            updatePendingImportUi(data.pending_count, data.active_batch);
        }

async function pollNativeBatchSummaries() {
            if (!CURATOR_NATIVE || isInteractionBusy()) return;
            await loadBatches();
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

async function loadBatches() {
            const resp = await fetch(ccApiPath('/api/batches')).catch(err => {
                console.warn('loadBatches fetch failed', err);
                return null;
            });
            if (!resp || !resp.ok) return;
            const data = await resp.json();
            const batches = data.batches;
            const activeBatch = data.active_batch;
            allCounts = data.counts;
            const batchMeta = data.batch_meta || {};

            updatePendingImportUi(data.pending_count, activeBatch);

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
            } else if (batchSort === 'ai') {
                sortByAiHistory(sortedBatches);
            }
            // 'alpha' keeps the default server-sorted order

            const filteredBatches = filterBatches(sortedBatches);
            const countLabel = document.getElementById('batch-count-label');
            if (countLabel) {
                countLabel.textContent = `Batches ${sortedBatches.length} (${filteredBatches.length} shown)`;
            }

            renderBatchList(filteredBatches);
            updateAllFavoritesCount();
            await updateAllPublicCount();

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
                    if (batchSort === 'ai') loadBatches();
                    else renderBatchList(filteredBatches);
                });
            }
        }

function sortByAiHistory(sortedBatches) {
            sortedBatches.sort((a, b) => {
                const aiA = aiBatchRunCounts[a] || 0;
                const aiB = aiBatchRunCounts[b] || 0;
                if (aiB !== aiA) return aiB - aiA;
                return a.localeCompare(b);
            });
        }

function formatBatchBreakdown(counts) {
            const safeCounts = counts || {};
            return [
                `${safeCounts.inbox || 0} inbox`,
                `${safeCounts.shortlisted || 0} shortlisted`,
                `${safeCounts.finals || 0} finals`,
                `${safeCounts.rejects || 0} rejects`,
            ].join(' · ');
        }

function renderBatchList(filteredBatches) {
            const list = document.getElementById('batch-list');
            if (!list) return;
            const fragment = document.createDocumentFragment();
            const favLi = document.createElement('li');
            favLi.className = 'batch-item batch-item-favorites';
            const favDiv = document.createElement('div');
            favDiv.className = 'batch-name' + (currentBatch === '__favorites__' ? ' selected' : '');
            favDiv.dataset.batch = '__favorites__';
            favDiv.setAttribute('role', 'button');
            favDiv.tabIndex = 0;
            const favLabel = document.createElement('span');
            favLabel.className = 'batch-label';
            const favTitle = document.createElement('span');
            favTitle.className = 'batch-title batch-favorites-title';
            favTitle.textContent = '★ All Favorites';
            const favSubtitle = document.createElement('span');
            favSubtitle.className = 'batch-breakdown batch-favorites-subtitle';
            favSubtitle.textContent = 'Universal review set';
            favLabel.appendChild(favTitle);
            favLabel.appendChild(favSubtitle);
            favDiv.appendChild(favLabel);
            const favMeta = document.createElement('span');
            favMeta.className = 'batch-meta';
            const favCount = document.createElement('span');
            favCount.className = 'batch-count batch-count-pill';
            favCount.id = 'all-favorites-count';
            favCount.textContent = String(universalFavoritesCount);
            favMeta.appendChild(favCount);
            favDiv.appendChild(favMeta);
            favLi.appendChild(favDiv);
            fragment.appendChild(favLi);
            const publicLi = document.createElement('li');
            publicLi.className = 'batch-item batch-item-public';
            const publicDiv = document.createElement('div');
            publicDiv.className = 'batch-name' + (currentBatch === '__public__' ? ' selected' : '');
            publicDiv.dataset.batch = '__public__';
            publicDiv.setAttribute('role', 'button');
            publicDiv.tabIndex = 0;
            const publicLabel = document.createElement('span');
            publicLabel.className = 'batch-label';
            const publicTitle = document.createElement('span');
            publicTitle.className = 'batch-title batch-public-title';
            publicTitle.textContent = 'All Public';
            const publicSubtitle = document.createElement('span');
            publicSubtitle.className = 'batch-breakdown batch-public-subtitle';
            publicSubtitle.textContent = 'Generated posting copies';
            publicLabel.appendChild(publicTitle);
            publicLabel.appendChild(publicSubtitle);
            publicDiv.appendChild(publicLabel);
            const publicMeta = document.createElement('span');
            publicMeta.className = 'batch-meta';
            const publicCount = document.createElement('span');
            publicCount.className = 'batch-count batch-count-pill';
            publicCount.id = 'all-public-count';
            publicCount.textContent = String(universalPublicCount);
            publicMeta.appendChild(publicCount);
            publicDiv.appendChild(publicMeta);
            publicLi.appendChild(publicDiv);
            fragment.appendChild(publicLi);
            if (filteredBatches.length === 0) {
                const empty = document.createElement('li');
                empty.className = 'batch-empty';
                empty.setAttribute('aria-label', 'no batches found');
                empty.textContent = 'No batches match';
                fragment.appendChild(empty);
                list.replaceChildren(fragment);
                return;
            }
            filteredBatches.forEach(batch => {
                const c = allCounts[batch] || {};
                const total = (c.inbox||0) + (c.shortlisted||0) + (c.finals||0);

                const li = document.createElement('li');
                li.className = 'batch-item';

                const div = document.createElement('div');
                div.className = 'batch-name' + (batch === currentBatch ? ' selected' : '');
                div.dataset.batch = batch;
                div.setAttribute('role', 'button');
                div.tabIndex = 0;

                const label = document.createElement('span');
                label.className = 'batch-label';
                const batchTitle = document.createElement('span');
                batchTitle.className = 'batch-title';
                batchTitle.textContent = batch;
                const breakdown = document.createElement('span');
                breakdown.className = 'batch-breakdown';
                breakdown.textContent = formatBatchBreakdown(c);
                label.appendChild(batchTitle);
                label.appendChild(breakdown);
                div.appendChild(label);

                // Right-aligned group: optional AI dot + image count badge
                const metaDiv = document.createElement('span');
                metaDiv.className = 'batch-meta';

                if (aiBatchRunCounts[batch] > 0) {
                    const dot = document.createElement('span');
                    dot.className = 'batch-ai-dot';
                    dot.title = 'Has AI run history';
                    metaDiv.appendChild(dot);
                }

                const countSpan = document.createElement('span');
                countSpan.className = 'batch-count batch-count-pill';
                countSpan.textContent = String(total);
                countSpan.title = `${total} active images`;
                metaDiv.appendChild(countSpan);

                div.appendChild(metaDiv);

                li.appendChild(div);
                fragment.appendChild(li);
            });
            list.replaceChildren(fragment);
        }

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

function updateFolderTabs() {
            if (!currentBatch) return;
            const c = allCounts[currentBatch] || {};
            ['inbox','shortlisted','finals','rejects','public'].forEach(f => {
                const el = document.getElementById('tc-' + f);
                if (!el) return;
                const nextValue = f === 'public' && currentFolder === 'public' ? images.length : (c[f] || 0);
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

function selectBatch(batch) {
            const searchModal = document.getElementById('prompts-modal');
            if (searchModal?.classList.contains('active') && typeof hidePromptsModal === 'function') {
                hidePromptsModal();
            }
            if (isWorkspaceSearchView()) {
                deactivateWorkspaceSearchFilter();
                workspaceSearchReturnContext = null;
            }
            if (batch === '__favorites__') {
                loadUniversalFavorites();
                return;
            }
            if (batch === '__public__') {
                loadAllPublic();
                return;
            }
            /* Stage 2: track real batch transitions for cache scope awareness.
               Must run before batchChanged check so the first real batch
               is registered. */
            if (typeof _updateRealBatchTracking === 'function') {
                _updateRealBatchTracking(batch);
            }
            const batchChanged = currentBatch !== batch;
            currentBatch = batch;
            saveBatchState();
            updateAutoImportQuickAction(document.getElementById('active-batch-select').value || null);
            document.querySelectorAll('.batch-name').forEach(el =>
                el.classList.toggle('selected', el.dataset.batch === batch));
            document.getElementById('folder-tabs').classList.add('visible');
            if (batchChanged) {
                // Immediately replace old thumbnails with thumb-shaped placeholders
                // while the new batch's image list loads.
                beginViewTransition({clearImages: true, closeLightbox: true});
                resetAiBatchState(false);
                showGridLoadingPlaceholders(batch, 'inbox');
                _focusSelectedWorkspaceControl('inbox');
            }
            showAiCuratePanel();
            selectFolder(batch, 'inbox');
            // Reset content scroll position when switching batches
            const content = document.querySelector('.content');
            if (content) content.scrollTop = 0;
        }

async function selectFolder(batch, folder) {
            if (isWorkspaceSearchView()) {
                deactivateWorkspaceSearchFilter();
                workspaceSearchReturnContext = null;
            }
            document.getElementById('folder-tabs').classList.add('visible');
            if (folder === 'public') {
                await loadBatchPublic(batch);
                return;
            }
            const priorScope = getViewScopeKey();
            currentBatch = batch;
            currentFolder = folder;
            saveBatchState();
            if (priorScope !== getViewScopeKey()) {
                beginViewTransition({clearImages: true, closeLightbox: true});
            }

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

            showGridLoadingPlaceholders(batch, folder);
            updateFolderTabs();
            await loadCurrentFolderImages();
        }

function _focusSelectedWorkspaceControl(folder) {
            const target = [...document.querySelectorAll('.folder-tab')]
                .find(tab => tab.dataset.folder === folder);
            if (target && typeof target.focus === 'function') target.focus({preventScroll: true});
        }

function setBatchSort(sort) {
            batchSort = sort;
            localStorage.setItem(BATCH_SORT_KEY, sort);
            document.querySelectorAll('.batch-sort-btn').forEach(b =>
                b.classList.toggle('active', b.dataset.bsort === sort));
            loadBatches();
        }

async function setActiveBatch(batch) {
            pendingActiveBatchSelection = batch || null;
            const select = document.getElementById('active-batch-select');
            if (select) { select.value = batch || ''; _syncCustomSelectDisplay(); }
            const resp = await fetch(ccApiPath('/api/active-batch'), {
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
            if (importInFlight) return;
            const batch = document.getElementById('active-batch-select').value;
            if (!batch) { showToast('Select a batch first'); return; }
            const activityId = `import:${batch}`;
            const pendingTotal = Math.max(0, Number(document.getElementById('pending-count')?.textContent) || 0);
            activityRegister({
                id: activityId,
                kind: 'import',
                title: 'Import media',
                scope: batch,
                status: 'running',
                total: pendingTotal,
                detail: 'Importing ComfyUI output…',
                retry: () => importAll(),
            });
            activityUpdate(activityId, {detail: 'Import request submitted…'});
            importInFlight = true;
            updatePendingImportUi(document.getElementById('pending-count')?.textContent, batch);
            try {
                const resp = await fetch(ccApiPath('/api/import-all'), {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({batch: batch})
                });
                if (resp.ok) {
                    const data = await resp.json();
                    activityComplete(activityId, 'completed', {
                        completed: data.count || 0,
                        total: pendingTotal || data.count || 0,
                        result: `Imported ${data.count || 0} media files`,
                        detail: 'Import finished',
                    });
                    showToast(`Imported ${data.count} media files`);
                    updatePendingImportUi(0, batch);
                    await loadBatches();
                    if (currentBatch === batch && currentFolder === 'inbox')
                        await selectFolder(batch, 'inbox');
                } else {
                    activityComplete(activityId, 'failed', {error: 'Import failed', detail: 'The import request was rejected'});
                    showToast('Import failed');
                }
            } catch (error) {
                activityComplete(activityId, 'failed', {error: 'Import failed', detail: 'Status could not be confirmed'});
                throw error;
            } finally {
                importInFlight = false;
                await pollImportAvailability();
            }
        }

async function createBatch() {
            const name = document.getElementById('new-batch-name').value.trim();
            if (!name) return;
            const safeName = name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-_]/g, '');
            const resp = await fetch(ccApiPath('/api/batches'), {
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
