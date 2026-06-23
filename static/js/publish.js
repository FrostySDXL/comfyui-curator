/* Ordered classic script.
 * Defines: public derivative export modal, batch public view, All Public view, public-copy actions.
 */
function isVirtualCollectionView() {
            return currentBatch === '__favorites__' || currentBatch === '__public__';
        }

function isPublicView() {
            return currentBatch === '__public__' || currentFolder === 'public';
        }

function showPublishModal() {
            if (!currentBatch || isVirtualCollectionView() || isPublicView() || selectedImages.size === 0) {
                showToast('Select source images in a review folder first');
                return;
            }
            const modal = document.getElementById('publish-modal');
            const count = document.getElementById('publish-selected-count');
            if (count) count.textContent = String(selectedImages.size);
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

function buildPublishWatermarkOptions() {
            const enabled = document.getElementById('publish-watermark-enabled').checked;
            return {
                enabled,
                text: document.getElementById('publish-watermark-text').value || 'FrostySDXL',
                position: document.getElementById('publish-watermark-position').value,
                opacity: Number(document.getElementById('publish-watermark-opacity').value || 55) / 100,
                size_percent: Number(document.getElementById('publish-watermark-size').value || 4),
                margin: Number(document.getElementById('publish-watermark-margin').value || 32),
            };
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
                hidePublishModal();
                clearSelection();
                showToast(`Created ${data.exported || 0} public cop${data.exported === 1 ? 'y' : 'ies'}`);
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
            const destination = window.prompt('Copy public copies to destination under IMAGE_CURATOR_PUBLIC_EXPORTS:');
            if (!destination) return;
            const resp = await apiCopyPublic(destination, items);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                showToast(data.error || 'Copy public copies failed');
                return;
            }
            showToast(`Copied ${data.copied || 0} public cop${data.copied === 1 ? 'y' : 'ies'}`);
        }

async function moveSelectedPublicCopies() {
            const items = selectedPublicItems();
            if (!items.length) return;
            if (!window.confirm('Move selected public copies?\n\nThis only moves generated public copies. Original curated images will not be changed.')) return;
            const destination = window.prompt('Move public copies to destination under IMAGE_CURATOR_PUBLIC_EXPORTS:');
            if (!destination) return;
            const resp = await apiMovePublic(destination, items);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                showToast(data.error || 'Move public copies failed');
                return;
            }
            showToast(`Moved ${data.moved || 0} public cop${data.moved === 1 ? 'y' : 'ies'}`);
            await refreshPublicViewAfterAction();
        }

async function deleteSelectedPublicCopies() {
            const items = selectedPublicItems();
            if (!items.length) return;
            if (!window.confirm('Delete selected public copies?\n\nOriginal curated images will not be changed.')) return;
            const resp = await apiDeletePublic(items);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                showToast(data.error || 'Delete public copies failed');
                return;
            }
            showToast(`Deleted ${data.deleted || 0} public cop${data.deleted === 1 ? 'y' : 'ies'}`);
            await refreshPublicViewAfterAction();
        }

function syncLightboxPublicActions() {
            const activePublicView = isPublicView();
            document.querySelectorAll('#lightbox-actions .btn-shortlist, #lightbox-actions .btn-finals, #lightbox-actions .btn-reject').forEach(btn => {
                btn.closest('div').style.display = activePublicView ? 'none' : '';
            });
        }
