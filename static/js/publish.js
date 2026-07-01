/* Ordered classic script.
 * Defines: public derivative export modal, batch public view, All Public view, public-copy actions.
 */
let lastPublishedPublicBatch = null;
let pendingPublicDestinationAction = null;

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
                clearSelection();
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
            selectedImages.clear();
            lastSelectIndex = -1;
            lastAction = null;
            resetAiBatchState(false);
            closeLightbox();
            updateActionBar();
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
            selectedImages.clear();
            lastSelectIndex = -1;
            lastAction = null;
            resetAiBatchState(false);
            closeLightbox();
            updateActionBar();
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

function hidePublicDestinationModal() {
            const modal = document.getElementById('public-destination-modal');
            if (modal) modal.classList.remove('active');
            pendingPublicDestinationAction = null;
            _releaseFocusTrap();
        }

function showPublicDestinationModal(action) {
            const items = selectedPublicItems();
            if (!items.length) return;
            pendingPublicDestinationAction = action;
            const modal = document.getElementById('public-destination-modal');
            const title = document.getElementById('public-destination-modal-title');
            const detail = document.getElementById('public-destination-detail');
            const input = document.getElementById('public-destination-input');
            const submit = document.getElementById('public-destination-submit-btn');
            const label = action === 'move' ? 'Move Public Copies' : 'Copy Public Copies';
            if (title) title.textContent = label;
            if (detail) detail.textContent = `${label} for ${items.length} generated cop${items.length === 1 ? 'y' : 'ies'}. Only generated public copies are affected.`;
            if (submit) submit.textContent = label;
            if (input) input.value = '';
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
            if (action === 'move' && !window.confirm('Move selected public copies?\n\nThis only moves generated public copies. Original curated images will not be changed.')) return;
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
            selectedImages.clear();
            updateActionBar();
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
            const activePublicView = isPublicView();
            document.querySelectorAll('#lightbox-actions .btn-shortlist, #lightbox-actions .btn-finals, #lightbox-actions .btn-reject').forEach(btn => {
                btn.closest('div').style.display = activePublicView ? 'none' : '';
            });
        }
