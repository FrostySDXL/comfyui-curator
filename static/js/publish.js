/* Ordered classic script.
 * Defines: public derivative export modal, batch public view, All Public view, public-copy actions.
 */
let lastPublishedPublicBatch = null;
let pendingPublicDestinationAction = null;
let pendingPublicMoveConfirmDestination = null;
let publicDestinationBrowserPath = '';
const PUBLIC_DESTINATION_HISTORY_KEY = 'imageCurator.publicDestinationHistory';
const PUBLIC_DESTINATION_HISTORY_LIMIT = 10;

function showPublishModal() {
            if (!currentBatch || isVirtualCollectionView() || isPublicView() || selectedImages.size === 0) {
                showToast('Select source images in a review folder first');
                return;
            }
            const modal = document.getElementById('publish-modal');
            const count = document.getElementById('publish-selected-count');
            if (count) count.textContent = String(selectedImages.size);
            updatePublishSourceSummary();
            syncPublishWatermarkFields();
            const result = document.getElementById('publish-result');
            if (result) result.classList.add('hidden');
            modal.classList.add('active');
            _trapFocus(modal);
            const textInput = document.getElementById('publish-watermark-text');
            if (textInput) textInput.focus();
        }

function showLightboxPublishModal() {
            const compareWasActive = typeof isLightboxCompareMode === 'function' && isLightboxCompareMode();
            const img = typeof getActiveLightboxImage === 'function'
                ? getActiveLightboxImage()
                : getLightboxImages()[currentIndex];
            if (!img || isVirtualCollectionView() || isPublicView()) {
                showToast('Select a source image in a review folder first');
                return;
            }
            selectedImages = new Set([img.name]);
            lastSelectIndex = getImageDisplayIndexByName(img.name);
            updateSelectionVisuals();
            updateActionBar();
            if (compareWasActive) closeLightbox();
            showPublishModal();
        }

function hidePublishModal() {
            document.getElementById('publish-modal').classList.remove('active');
            _releaseFocusTrap();
        }

function getSelectedSourceFilenames() {
            return images.filter(img => selectedImages.has(img.name)).map(img => img.name);
        }

function updatePublishSourceSummary() {
            const summary = document.getElementById('publish-source-summary');
            if (!summary) return;
            const selectedCount = selectedImages.size;
            const folder = currentFolder || 'review folder';
            const batch = currentBatch || 'current batch';
            summary.textContent = `${selectedCount} selected from ${batch} / ${folder}. Output: ${batch} / public. Originals are not changed.`;
        }

function syncPublishWatermarkFields() {
            const enabled = document.getElementById('publish-watermark-enabled')?.checked === true;
            const options = document.getElementById('publish-watermark-options');
            const warning = document.getElementById('publish-watermark-warning');
            if (options) options.classList.toggle('disabled', !enabled);
            ['publish-watermark-text', 'publish-watermark-position', 'publish-watermark-opacity', 'publish-watermark-size', 'publish-watermark-margin', 'publish-watermark-black'].forEach(id => {
                const input = document.getElementById(id);
                if (input) input.disabled = !enabled;
            });
            const text = document.getElementById('publish-watermark-text')?.value.trim() || '';
            if (warning) warning.classList.toggle('hidden', !enabled || text.length > 0);
        }

function resetPublishWatermarkDefaults() {
            const values = {
                'publish-watermark-text': 'FrostySDXL',
                'publish-watermark-position': 'bottom-right',
                'publish-watermark-opacity': '55',
                'publish-watermark-size': '4',
                'publish-watermark-margin': '32',
            };
            Object.entries(values).forEach(([id, value]) => {
                const input = document.getElementById(id);
                if (input) input.value = value;
            });
            const blackText = document.getElementById('publish-watermark-black');
            if (blackText) blackText.checked = false;
            syncPublishWatermarkFields();
        }

function buildPublishWatermarkOptions() {
            syncPublishWatermarkFields();
            const enabled = document.getElementById('publish-watermark-enabled').checked;
            return {
                enabled,
                text: document.getElementById('publish-watermark-text').value || 'FrostySDXL',
                position: document.getElementById('publish-watermark-position').value,
                opacity: Number(document.getElementById('publish-watermark-opacity').value || 55) / 100,
                size_percent: Number(document.getElementById('publish-watermark-size').value || 4),
                margin: Number(document.getElementById('publish-watermark-margin').value || 32),
                color: document.getElementById('publish-watermark-black').checked ? 'black' : 'white',
            };
        }

function showPublishResult(data) {
            const result = document.getElementById('publish-result');
            const text = document.getElementById('publish-result-text');
            if (!result || !text) return;
            const exported = data.exported || 0;
            const failed = data.failed || 0;
            text.textContent = failed > 0
                ? `Created ${exported}; ${failed} failed.`
                : `Created ${exported} public cop${exported === 1 ? 'y' : 'ies'}.`;
            result.classList.remove('hidden');
        }

async function viewCreatedPublicCopies() {
            hidePublishModal();
            if (lastPublishedPublicBatch) await loadBatchPublic(lastPublishedPublicBatch);
        }

async function submitPublicExport() {
            const filenames = getSelectedSourceFilenames();
            if (!filenames.length) {
                showToast('Select images first');
                return;
            }
            const submitBtn = document.getElementById('publish-submit-btn');
            if (submitBtn) submitBtn.disabled = true;
            try {
                const resp = await apiPublishExport({
                    batch: currentBatch,
                    folder: currentFolder,
                    filenames,
                    strip_metadata: document.getElementById('publish-strip-metadata').checked,
                    watermark: buildPublishWatermarkOptions(),
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok && !data.exported) {
                    showToast(data.error || 'Public export failed');
                    return;
                }
                lastPublishedPublicBatch = currentBatch;
                resetSelectionState();
                showToast(`Created ${data.exported || 0} public cop${data.exported === 1 ? 'y' : 'ies'}`);
                showPublishResult(data);
                await loadBatches();
            } catch {
                showToast('Public export failed');
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        }

async function updateAllPublicCount() {
            try {
                const data = await apiGetAllPublic();
                const publicItems = data.public || [];
                universalPublicCount = publicItems.length;
                Object.keys(allCounts || {}).forEach(batch => {
                    if (allCounts[batch]) allCounts[batch].public = 0;
                });
                publicItems.forEach(item => {
                    if (!item.batch) return;
                    if (!allCounts[item.batch]) allCounts[item.batch] = {};
                    allCounts[item.batch].public = (allCounts[item.batch].public || 0) + 1;
                });
                const countEl = document.getElementById('all-public-count');
                if (countEl) countEl.textContent = String(universalPublicCount);
                if (currentBatch && !isVirtualCollectionView()) updateFolderTabs();
            } catch { console.warn('updateAllPublicCount failed'); }
        }

function normalizePublicItems(items) {
            return (items || []).map(item => ({
                name: item.name || item.filename,
                size: item.size || 0,
                batch: item.batch,
                folder: item.folder || 'public',
                modified_at: item.modified_at || 0,
                favorite: false,
                public: true,
            })).filter(item => item.name && item.batch);
        }

async function loadBatchPublic(batch) {
            currentBatch = batch;
            currentFolder = 'public';
            saveBatchState();
            resetSelectionState();
            lastAction = null;
            resetAiBatchState(false);
            closeLightbox();
            document.querySelectorAll('.batch-name').forEach(el =>
                el.classList.toggle('selected', el.dataset.batch === batch));
            document.querySelectorAll('.folder-tab').forEach(t =>
                t.classList.toggle('active', t.dataset.folder === 'public'));
            document.getElementById('sort-controls').style.display = 'flex';
            const pathEl = document.getElementById('current-path');
            pathEl.replaceChildren(createTextElement('span', 'path', batch), document.createTextNode(' / public'));
            const publicData = await apiGetBatchPublic(batch);
            images = normalizePublicItems(publicData);
            updateImageCountLabel();
            updateGrid();
            updateFolderTabs();
        }

async function loadAllPublic() {
            currentBatch = '__public__';
            currentFolder = null;
            saveBatchState();
            resetSelectionState();
            lastAction = null;
            resetAiBatchState(false);
            closeLightbox();
            document.querySelectorAll('.batch-name').forEach(el =>
                el.classList.toggle('selected', el.dataset.batch === '__public__'));
            const tabs = document.getElementById('folder-tabs');
            if (tabs) tabs.classList.remove('visible');
            document.getElementById('sort-controls').style.display = 'flex';
            const pathEl = document.getElementById('current-path');
            pathEl.replaceChildren(createTextElement('span', 'path', 'All Public'));
            updateAutoImportQuickAction(document.getElementById('active-batch-select').value || null);
            try {
                const data = await apiGetAllPublic();
                images = normalizePublicItems(data.public || []);
                universalPublicCount = images.length;
                updateImageCountLabel();
                updateGrid();
                await updateAllPublicCount();
            } catch {
                showToast('Failed to load public copies');
            }
        }

function selectedPublicItems() {
            return images
                .filter(img => selectedImages.has(img.name))
                .map(img => ({batch: img.batch || currentBatch, filename: img.name}));
        }

function normalizePublicDestinationPath(value) {
            return String(value || '').trim().replace(/\\+/g, '/').replace(/^\/+|\/+$/g, '');
        }

function getPublicDestinationHistory() {
            try {
                const raw = localStorage.getItem(PUBLIC_DESTINATION_HISTORY_KEY);
                const parsed = raw ? JSON.parse(raw) : [];
                return Array.isArray(parsed)
                    ? parsed.map(normalizePublicDestinationPath).filter(Boolean).slice(0, PUBLIC_DESTINATION_HISTORY_LIMIT)
                    : [];
            } catch {
                return [];
            }
        }

function savePublicDestinationHistory(destination) {
            const normalized = normalizePublicDestinationPath(destination);
            if (!normalized) return;
            const next = [
                normalized,
                ...getPublicDestinationHistory().filter(item => item !== normalized),
            ].slice(0, PUBLIC_DESTINATION_HISTORY_LIMIT);
            try {
                localStorage.setItem(PUBLIC_DESTINATION_HISTORY_KEY, JSON.stringify(next));
            } catch { /* localStorage may be unavailable */ }
            renderPublicDestinationHistory();
        }

function resetPublicMoveConfirmation() {
            if (!pendingPublicDestinationAction) return;
            pendingPublicMoveConfirmDestination = null;
            setPublicDestinationModalState(
                pendingPublicDestinationAction,
                selectedPublicItems().length,
                false,
            );
        }

function setPublicDestinationInput(destination) {
            const input = document.getElementById('public-destination-input');
            if (!input) return;
            input.value = normalizePublicDestinationPath(destination);
            resetPublicMoveConfirmation();
            input.focus();
        }

function renderPublicDestinationHistory() {
            const container = document.getElementById('public-destination-history');
            if (!container) return;
            const history = getPublicDestinationHistory();
            container.replaceChildren();
            container.classList.toggle('hidden', history.length === 0);
            if (!history.length) return;
            const label = document.createElement('div');
            label.className = 'public-destination-section-label';
            label.textContent = 'Recent destinations';
            container.append(label);
            const list = document.createElement('div');
            list.className = 'public-destination-history-list';
            history.forEach(destination => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.textContent = destination;
                btn.addEventListener('click', () => setPublicDestinationInput(destination));
                list.append(btn);
            });
            container.append(list);
        }

function renderPublicDestinationBrowser(data) {
            const currentPath = normalizePublicDestinationPath(data?.path || '');
            const currentEl = document.getElementById('public-destination-current-path');
            const list = document.getElementById('public-destination-browser-list');
            const upBtn = document.getElementById('public-destination-up-btn');
            if (currentEl) currentEl.textContent = currentPath ? `/${currentPath}` : '/';
            if (upBtn) {
                upBtn.disabled = !currentPath;
                upBtn.dataset.path = normalizePublicDestinationPath(data?.parent || '');
            }
            if (!list) return;
            list.replaceChildren();
            const directories = Array.isArray(data?.directories) ? data.directories : [];
            if (!directories.length) {
                const empty = document.createElement('div');
                empty.className = 'public-destination-empty';
                empty.textContent = 'No subfolders found here.';
                list.append(empty);
                return;
            }
            directories.forEach(directory => {
                const path = normalizePublicDestinationPath(directory.path);
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'public-destination-folder-btn';
                btn.dataset.path = path;
                btn.textContent = `${directory.name}/`;
                btn.addEventListener('click', () => {
                    setPublicDestinationInput(path);
                    loadPublicDestinationBrowser(path);
                });
                list.append(btn);
            });
        }

async function loadPublicDestinationBrowser(path = '') {
            publicDestinationBrowserPath = normalizePublicDestinationPath(path);
            const list = document.getElementById('public-destination-browser-list');
            if (list) list.textContent = 'Loading folders...';
            try {
                const data = await apiGetPublicDestinations(publicDestinationBrowserPath);
                publicDestinationBrowserPath = normalizePublicDestinationPath(data.path || '');
                renderPublicDestinationBrowser(data);
            } catch {
                const currentEl = document.getElementById('public-destination-current-path');
                if (currentEl) currentEl.textContent = publicDestinationBrowserPath ? `/${publicDestinationBrowserPath}` : '/';
                if (list) list.textContent = 'Folder browser unavailable. You can still type a destination.';
            }
        }

function browsePublicDestinationUp() {
            const upBtn = document.getElementById('public-destination-up-btn');
            loadPublicDestinationBrowser(upBtn?.dataset.path || '');
        }

function refreshPublicDestinationBrowser() {
            loadPublicDestinationBrowser(publicDestinationBrowserPath);
        }

function handlePublicDestinationInputChanged() {
            resetPublicMoveConfirmation();
        }

function hidePublicDestinationModal() {
            const modal = document.getElementById('public-destination-modal');
            if (modal) modal.classList.remove('active');
            pendingPublicDestinationAction = null;
            pendingPublicMoveConfirmDestination = null;
            _releaseFocusTrap();
        }

function setPublicDestinationModalState(action, itemCount, confirmMove) {
            const detail = document.getElementById('public-destination-detail');
            const submit = document.getElementById('public-destination-submit-btn');
            const label = action === 'move' ? 'Move Public Copies' : 'Copy Public Copies';
            const copiesLabel = `generated cop${itemCount === 1 ? 'y' : 'ies'}`;
            const detailText = action === 'move'
                ? `${label} for ${itemCount} ${copiesLabel}. Moved public copies leave this batch's public folder. Original curated images are not changed.`
                : `${label} for ${itemCount} ${copiesLabel}. Only generated public copies are affected.`;
            if (detail) {
                detail.textContent = confirmMove
                    ? `Confirm move to this destination. ${detailText}`
                    : detailText;
            }
            if (submit) submit.textContent = confirmMove ? 'Confirm Move' : label;
        }

function showPublicDestinationModal(action) {
            const items = selectedPublicItems();
            if (!items.length) return;
            pendingPublicDestinationAction = action;
            pendingPublicMoveConfirmDestination = null;
            const modal = document.getElementById('public-destination-modal');
            const title = document.getElementById('public-destination-modal-title');
            const input = document.getElementById('public-destination-input');
            const label = action === 'move' ? 'Move Public Copies' : 'Copy Public Copies';
            if (title) title.textContent = label;
            setPublicDestinationModalState(action, items.length, false);
            if (input) input.value = '';
            renderPublicDestinationHistory();
            loadPublicDestinationBrowser('');
            modal.classList.add('active');
            _trapFocus(modal);
            if (input) input.focus();
        }

function showPublicDeleteModal() {
            const items = selectedPublicItems();
            if (!items.length) return;
            const modal = document.getElementById('public-delete-modal');
            const count = document.getElementById('public-delete-count');
            if (count) count.textContent = String(items.length);
            modal.classList.add('active');
            _trapFocus(modal);
            const confirmBtn = document.getElementById('public-delete-confirm-btn');
            if (confirmBtn) confirmBtn.focus();
        }

function hidePublicDeleteModal() {
            const modal = document.getElementById('public-delete-modal');
            if (modal) modal.classList.remove('active');
            _releaseFocusTrap();
        }

async function submitPublicDestinationAction() {
            const action = pendingPublicDestinationAction;
            const items = selectedPublicItems();
            const destination = document.getElementById('public-destination-input')?.value.trim() || '';
            if (!action || !items.length) return;
            if (!destination) {
                showToast('Enter a destination under IMAGE_CURATOR_PUBLIC_EXPORTS');
                return;
            }
            if (action === 'move' && pendingPublicMoveConfirmDestination !== destination) {
                pendingPublicMoveConfirmDestination = destination;
                setPublicDestinationModalState(action, items.length, true);
                return;
            }
            const submit = document.getElementById('public-destination-submit-btn');
            if (submit) submit.disabled = true;
            try {
                const resp = action === 'move'
                    ? await apiMovePublic(destination, items)
                    : await apiCopyPublic(destination, items);
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    showToast(data.error || `${action === 'move' ? 'Move' : 'Copy'} public copies failed`);
                    return;
                }
                const completed = action === 'move' ? (data.moved || 0) : (data.copied || 0);
                if (completed > 0) savePublicDestinationHistory(destination);
                hidePublicDestinationModal();
                if (action === 'move') {
                    showToast(`Moved ${data.moved || 0} public cop${data.moved === 1 ? 'y' : 'ies'}`);
                    await refreshPublicViewAfterAction();
                } else {
                    showToast(`Copied ${data.copied || 0} public cop${data.copied === 1 ? 'y' : 'ies'}`);
                    await updateAllPublicCount();
                }
            } finally {
                if (submit) submit.disabled = false;
            }
        }

async function refreshPublicViewAfterAction() {
            resetSelectionState();
            if (currentBatch === '__public__') {
                await loadAllPublic();
            } else if (currentFolder === 'public') {
                await loadBatchPublic(currentBatch);
                await updateAllPublicCount();
            }
        }

async function copySelectedPublicCopies() {
            const items = selectedPublicItems();
            if (!items.length) return;
            showPublicDestinationModal('copy');
        }

async function moveSelectedPublicCopies() {
            const items = selectedPublicItems();
            if (!items.length) return;
            showPublicDestinationModal('move');
        }

async function deleteSelectedPublicCopies() {
            const items = selectedPublicItems();
            if (!items.length) return;
            showPublicDeleteModal();
        }

async function confirmPublicDelete() {
            const items = selectedPublicItems();
            if (!items.length) {
                hidePublicDeleteModal();
                return;
            }
            const confirmBtn = document.getElementById('public-delete-confirm-btn');
            if (confirmBtn) confirmBtn.disabled = true;
            try {
            const resp = await apiDeletePublic(items);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                showToast(data.error || 'Delete public copies failed');
                return;
            }
            hidePublicDeleteModal();
            showToast(`Deleted ${data.deleted || 0} public cop${data.deleted === 1 ? 'y' : 'ies'}`);
            await refreshPublicViewAfterAction();
            } finally {
                if (confirmBtn) confirmBtn.disabled = false;
            }
        }

function syncLightboxPublicActions() {
            const activePublicView = isVirtualCollectionView() || isPublicView();
            const compareActive = typeof isLightboxCompareMode === 'function' && isLightboxCompareMode();
            document.querySelectorAll('#lightbox-actions .btn-shortlist, #lightbox-actions .btn-finals, #lightbox-actions .btn-reject, #lightbox-publish-btn').forEach(btn => {
                btn.closest('div').style.display = activePublicView ? 'none' : '';
            });
            document.querySelectorAll('#lightbox-actions .btn-secondary').forEach(btn => {
                const label = btn.textContent.trim();
                const singleOnly = label === 'Prev scored' || label === 'Next scored';
                if (singleOnly) btn.closest('div').style.display = compareActive ? 'none' : '';
            });
        }
