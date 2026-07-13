/* Ordered classic script.
 * Defines: public derivative export modal, batch public view, All Public view, public-copy actions.
 */
let lastPublishedPublicBatch = null;
let pendingPublicDestinationAction = null;
let pendingPublicMoveConfirmDestination = null;
let publicDestinationBrowserPath = '';
let publishSubmitInflight = false;
let publishPreviewToken = 0;
const PUBLISH_PREVIEW_MIN_ZOOM = 1;
const PUBLISH_PREVIEW_MAX_ZOOM = 4;
const PUBLISH_PREVIEW_ZOOM_STEP = 0.25;
let publishPreviewSources = [];
let publishPreviewIndex = 0;
let publishPreviewActive = false;
let publishPreviewZoom = PUBLISH_PREVIEW_MIN_ZOOM;
let publishPreviewPanX = 0;
let publishPreviewPanY = 0;
let publishPreviewPanState = null;
const PUBLIC_DESTINATION_HISTORY_KEY = 'imageCurator.publicDestinationHistory';
const PUBLIC_DESTINATION_HISTORY_LIMIT = 10;
const PUBLISH_PRESETS_KEY = 'imageCurator.publishPresets';
const PUBLISH_PRESETS_VERSION = 1;
const PUBLISH_PRESET_LIMIT = 20;
const PUBLISH_WATERMARK_POSITIONS = new Set([
    'bottom-right', 'bottom-left', 'top-right', 'top-left', 'bottom-center', 'center',
]);

function syncPublishSubmitActivity(active) {
            const activity = document.getElementById('publish-submit-activity');
            if (!activity) return;
            const isActive = active === true;
            activity.classList.toggle('is-active', isActive);
            activity.setAttribute('aria-hidden', isActive ? 'false' : 'true');
        }

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
            syncPublishMetadataNote();
            const result = document.getElementById('publish-result');
            if (result) result.classList.add('hidden');
            syncPublishSubmitActivity(publishSubmitInflight);
             const submitBtn = document.getElementById('publish-submit-btn');
             if (submitBtn) submitBtn.disabled = publishSubmitInflight;
             renderPublishPresets();
             publishPreviewSources = getSelectedSourceImages();
             publishPreviewIndex = 0;
             resetPublishPreviewView(false);
             syncPublishPreviewNavigation();
             modal.classList.add('active');
             updatePublishPreview();
            const closeButton = modal.querySelector('.publish-workbench-footer .cancel');
            _trapFocus(modal, closeButton);
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
             publishPreviewToken += 1;
             resetPublishPreviewView(false);
             publishPreviewSources = [];
             publishPreviewIndex = 0;
            const img = document.getElementById('publish-preview-image');
            if (img) {
                img.onload = null;
                img.onerror = null;
                img.removeAttribute('src');
                img.style.display = 'none';
            }
            const overlay = document.getElementById('publish-preview-watermark');
            if (overlay) {
                overlay.textContent = '';
                overlay.style.display = 'none';
            }
            const wrap = document.getElementById('publish-preview-image-wrap');
            if (wrap) { wrap.style.width = ''; wrap.style.height = ''; }
            setPublishPreviewState('empty');
            document.getElementById('publish-modal').classList.remove('active');
            _releaseFocusTrap();
        }

function getSelectedSourceFilenames() {
             return images.filter(img => selectedImages.has(img.name)).map(img => img.name);
         }

function getSelectedSourceImages() {
             return getCurrentDisplayImages().filter(img => selectedImages.has(img.name));
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

function syncPublishMetadataNote() {
            const note = document.getElementById('publish-preview-metadata-note');
            if (!note) return;
            const strip = document.getElementById('publish-strip-metadata')?.checked === true;
            note.textContent = strip
                ? 'Metadata will be stripped from generated copies.'
                : 'Metadata stripping is off for generated copies.';
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

function syncPublishPreviewNavigation() {
             const controls = document.getElementById('publish-preview-navigation');
             const previous = document.getElementById('publish-preview-prev-btn');
             const next = document.getElementById('publish-preview-next-btn');
             const position = document.getElementById('publish-preview-position');
             const total = publishPreviewSources.length;
             if (controls) controls.hidden = total <= 1;
             if (previous) previous.disabled = publishPreviewIndex <= 0;
             if (next) next.disabled = publishPreviewIndex >= total - 1;
             if (position) position.textContent = total ? `${publishPreviewIndex + 1} of ${total}` : '0 of 0';
         }

function navigatePublishPreview(delta) {
             if (publishPreviewSources.length <= 1) return;
             const nextIndex = Math.min(
                 publishPreviewSources.length - 1,
                 Math.max(0, publishPreviewIndex + delta),
             );
             if (nextIndex === publishPreviewIndex) return;
             publishPreviewIndex = nextIndex;
             syncPublishPreviewNavigation();
             updatePublishPreview();
         }

function clearPublishPreviewPan() {
             const frame = document.getElementById('publish-preview-frame');
             const pointerId = publishPreviewPanState?.pointerId;
             if (frame && pointerId !== undefined && frame.hasPointerCapture(pointerId)) {
                 frame.releasePointerCapture(pointerId);
             }
             if (frame) frame.classList.remove('is-panning');
             publishPreviewPanState = null;
         }

function applyPublishPreviewView() {
             const frame = document.getElementById('publish-preview-frame');
             const wrap = document.getElementById('publish-preview-image-wrap');
             const activation = document.getElementById('publish-preview-activation');
             const level = document.getElementById('publish-preview-zoom-level');
             if (!frame || !wrap) return;
             const maxX = Math.max(0, ((wrap.offsetWidth * publishPreviewZoom) - frame.clientWidth) / 2);
             const maxY = Math.max(0, ((wrap.offsetHeight * publishPreviewZoom) - frame.clientHeight) / 2);
             publishPreviewPanX = Math.min(maxX, Math.max(-maxX, publishPreviewPanX));
             publishPreviewPanY = Math.min(maxY, Math.max(-maxY, publishPreviewPanY));
             wrap.style.transform = `translate(${publishPreviewPanX}px, ${publishPreviewPanY}px) scale(${publishPreviewZoom})`;
             frame.classList.toggle('is-active', publishPreviewActive);
             frame.classList.toggle('is-zoomed', publishPreviewZoom > PUBLISH_PREVIEW_MIN_ZOOM);
             if (activation) {
                 activation.textContent = publishPreviewActive ? 'Zoom and pan on' : 'Enable zoom and pan';
                 activation.setAttribute('aria-pressed', publishPreviewActive ? 'true' : 'false');
             }
             if (level) level.textContent = `${Math.round(publishPreviewZoom * 100)}%`;
         }

function setPublishPreviewActive(active) {
             publishPreviewActive = active === true;
             if (!publishPreviewActive) {
                 clearPublishPreviewPan();
                 publishPreviewZoom = PUBLISH_PREVIEW_MIN_ZOOM;
                 publishPreviewPanX = 0;
                 publishPreviewPanY = 0;
             }
             applyPublishPreviewView();
         }

function resetPublishPreviewView(active = publishPreviewActive) {
             clearPublishPreviewPan();
             publishPreviewActive = active === true;
             publishPreviewZoom = PUBLISH_PREVIEW_MIN_ZOOM;
             publishPreviewPanX = 0;
             publishPreviewPanY = 0;
             applyPublishPreviewView();
         }

function zoomPublishPreview(delta, anchorEvent = null) {
             if (!publishPreviewActive) setPublishPreviewActive(true);
             const currentZoom = publishPreviewZoom;
             const nextZoom = Math.min(
                 PUBLISH_PREVIEW_MAX_ZOOM,
                 Math.max(PUBLISH_PREVIEW_MIN_ZOOM, +(currentZoom + delta).toFixed(2)),
             );
             if (nextZoom === currentZoom) return;
             if (anchorEvent) {
                 const frame = document.getElementById('publish-preview-frame');
                 const rect = frame?.getBoundingClientRect();
                 if (rect) {
                     const ratio = nextZoom / currentZoom;
                     publishPreviewPanX -= (anchorEvent.clientX - (rect.left + rect.width / 2)) * (ratio - 1);
                     publishPreviewPanY -= (anchorEvent.clientY - (rect.top + rect.height / 2)) * (ratio - 1);
                 }
             }
             publishPreviewZoom = nextZoom;
             applyPublishPreviewView();
         }

function handlePublishPreviewWheel(event) {
             if (!publishPreviewActive) return;
             event.preventDefault();
             zoomPublishPreview(event.deltaY < 0 ? PUBLISH_PREVIEW_ZOOM_STEP : -PUBLISH_PREVIEW_ZOOM_STEP, event);
         }

function handlePublishPreviewKeydown(event) {
             if (event.key === 'Enter' || event.key === ' ') {
                 event.preventDefault();
                 setPublishPreviewActive(!publishPreviewActive);
             }
         }

function startPublishPreviewPan(event) {
             if (!publishPreviewActive || publishPreviewZoom <= PUBLISH_PREVIEW_MIN_ZOOM || event.button !== 0) return;
             const frame = document.getElementById('publish-preview-frame');
             if (!frame) return;
             publishPreviewPanState = {
                 pointerId: event.pointerId,
                 startX: event.clientX,
                 startY: event.clientY,
                 panX: publishPreviewPanX,
                 panY: publishPreviewPanY,
             };
             frame.classList.add('is-panning');
             frame.setPointerCapture(event.pointerId);
             event.preventDefault();
         }

function movePublishPreviewPan(event) {
             if (!publishPreviewPanState || event.pointerId !== publishPreviewPanState.pointerId) return;
             publishPreviewPanX = publishPreviewPanState.panX + event.clientX - publishPreviewPanState.startX;
             publishPreviewPanY = publishPreviewPanState.panY + event.clientY - publishPreviewPanState.startY;
             applyPublishPreviewView();
             event.preventDefault();
         }

function endPublishPreviewPan(event) {
             if (!publishPreviewPanState || event.pointerId !== publishPreviewPanState.pointerId) return;
             const frame = document.getElementById('publish-preview-frame');
             if (frame?.hasPointerCapture(event.pointerId)) frame.releasePointerCapture(event.pointerId);
             clearPublishPreviewPan();
         }

function setPublishPreviewState(state) {
            const frame = document.getElementById('publish-preview-frame');
            if (!frame) return;
            frame.classList.toggle('is-loading', state === 'loading');
            frame.classList.toggle('is-error', state === 'error');
            frame.classList.toggle('is-empty', state === 'empty');
            const empty = document.getElementById('publish-preview-empty');
            const error = document.getElementById('publish-preview-error');
            if (empty) empty.classList.toggle('hidden', state !== 'empty');
            if (error) error.classList.toggle('hidden', state !== 'error');
        }

function updatePublishWatermarkOverlay() {
            const overlay = document.getElementById('publish-preview-watermark');
            const img = document.getElementById('publish-preview-image');
            if (!overlay || !img) return;
            const enabled = document.getElementById('publish-watermark-enabled')?.checked === true;
            const text = document.getElementById('publish-watermark-text')?.value.trim() || '';
            if (!enabled || !text) {
                overlay.textContent = '';
                overlay.style.display = 'none';
                return;
            }
            overlay.textContent = text;
            overlay.style.display = '';
            const position = document.getElementById('publish-watermark-position')?.value || 'bottom-right';
            overlay.dataset.position = position;
            const opacity = Math.max(0, Math.min(100, Number(document.getElementById('publish-watermark-opacity')?.value || 55))) / 100;
            overlay.style.opacity = String(opacity);
            const sizePercent = Math.max(1, Math.min(20, Number(document.getElementById('publish-watermark-size')?.value || 4)));
            const rawMargin = Math.max(0, Number(document.getElementById('publish-watermark-margin')?.value || 32));
            const displayedWidth = img.clientWidth || img.naturalWidth || 320;
            const naturalWidth = img.naturalWidth || displayedWidth;
            const scale = naturalWidth > 0 ? displayedWidth / naturalWidth : 1;
            const margin = rawMargin * scale;
            overlay.style.fontSize = `${(displayedWidth * sizePercent) / 100}px`;
            overlay.style.margin = `${margin}px`;
            overlay.style.color = document.getElementById('publish-watermark-black')?.checked ? '#000' : '#fff';
        }

        function syncPublishPreviewGeometry() {
            const img = document.getElementById('publish-preview-image');
            const wrap = document.getElementById('publish-preview-image-wrap');
            if (!img || !wrap) return;
            wrap.style.width = '';
            wrap.style.height = '';
            const w = img.clientWidth;
            const h = img.clientHeight;
            if (w <= 0 || h <= 0) return;
             wrap.style.width = w + 'px';
             wrap.style.height = h + 'px';
             updatePublishWatermarkOverlay();
             applyPublishPreviewView();
         }

        function updatePublishPreview() {
            const img = document.getElementById('publish-preview-image');
            const overlay = document.getElementById('publish-preview-watermark');
             const wrap = document.getElementById('publish-preview-image-wrap');
             if (!img || !overlay) return;
             resetPublishPreviewView(false);
             if (wrap) { wrap.style.width = ''; wrap.style.height = ''; }
            publishPreviewToken += 1;
            const token = publishPreviewToken;
             const source = publishPreviewSources[publishPreviewIndex];
            if (!source || !currentBatch || !currentFolder) {
                img.removeAttribute('src');
                img.style.display = 'none';
                overlay.style.display = 'none';
                setPublishPreviewState('empty');
                return;
            }
            setPublishPreviewState('loading');
            img.style.display = '';
            img.onload = () => {
                if (token !== publishPreviewToken) return;
                setPublishPreviewState('loaded');
                syncPublishPreviewGeometry();
            };
            img.onerror = () => {
                if (token !== publishPreviewToken) return;
                img.style.display = 'none';
                overlay.style.display = 'none';
                setPublishPreviewState('error');
            };
            img.src = ccImageUrl(currentBatch, currentFolder, source.name);
        }

function _clampPublishWatermarkNumber(value, fallback, min, max) {
            const num = Number(value);
            if (!Number.isFinite(num)) return fallback;
            if (min !== undefined && num < min) return min;
            if (max !== undefined && num > max) return max;
            return num;
        }

        function normalizePublishPresets(raw) {
            const safeName = (value) => (typeof value === 'string' ? value.trim().slice(0, 60) : '');
            const safeBool = (value) => value === true;
            const safeColor = (value) => (value === 'black' ? 'black' : 'white');
            const safePosition = (value) =>
                (typeof value === 'string' && PUBLISH_WATERMARK_POSITIONS.has(value)) ? value : 'bottom-right';
            const normalizePreset = (entry) => {
                if (!entry || typeof entry !== 'object') return null;
                const name = safeName(entry.name);
                if (!name) return null;
                const watermark = entry.watermark && typeof entry.watermark === 'object' ? entry.watermark : {};
                return {
                    name,
                    strip_metadata: safeBool(entry.strip_metadata),
                    watermark: {
                        enabled: safeBool(watermark.enabled),
                        text: (typeof watermark.text === 'string' ? watermark.text.slice(0, 120) : 'FrostySDXL') || 'FrostySDXL',
                        position: safePosition(watermark.position),
                        opacity: _clampPublishWatermarkNumber(watermark.opacity, 0.55, 0, 1),
                        size_percent: _clampPublishWatermarkNumber(watermark.size_percent, 4, 1, 20),
                        margin: _clampPublishWatermarkNumber(watermark.margin, 32, 0, 500),
                        color: safeColor(watermark.color),
                    },
                };
            };
            let presets = [];
            if (raw && typeof raw === 'object' && raw.version === PUBLISH_PRESETS_VERSION && Array.isArray(raw.presets)) {
                presets = raw.presets.map(normalizePreset).filter(Boolean);
            }
            return {
                version: PUBLISH_PRESETS_VERSION,
                presets: presets.slice(0, PUBLISH_PRESET_LIMIT),
            };
        }

function getPublishPresets() {
            try {
                const raw = localStorage.getItem(PUBLISH_PRESETS_KEY);
                const parsed = raw ? JSON.parse(raw) : null;
                return normalizePublishPresets(parsed);
            } catch {
                return { version: PUBLISH_PRESETS_VERSION, presets: [] };
            }
        }

function savePublishPreset(name) {
            const trimmed = (typeof name === 'string' ? name.trim() : '').slice(0, 60);
            if (!trimmed) {
                showToast('Enter a preset name');
                return false;
            }
            const stored = getPublishPresets();
            const presets = stored.presets.filter(p => p.name !== trimmed);
            presets.unshift({
                name: trimmed,
                strip_metadata: document.getElementById('publish-strip-metadata')?.checked === true,
                watermark: buildPublishWatermarkOptions(),
            });
            try {
                localStorage.setItem(
                    PUBLISH_PRESETS_KEY,
                    JSON.stringify({ version: PUBLISH_PRESETS_VERSION, presets: presets.slice(0, PUBLISH_PRESET_LIMIT) }),
                );
                renderPublishPresets();
                showToast(`Saved preset \u201c${trimmed}\u201d`);
                return true;
            } catch {
                showToast('Could not save preset \u2014 storage unavailable');
                return false;
            }
        }

function applyPublishPreset(preset) {
            if (!preset || !preset.watermark) return;
            const set = (id, value) => { const el = document.getElementById(id); if (el) el.value = value; };
            const check = (id, value) => { const el = document.getElementById(id); if (el) el.checked = value; };
            check('publish-strip-metadata', !!preset.strip_metadata);
            check('publish-watermark-enabled', !!preset.watermark.enabled);
            set('publish-watermark-text', preset.watermark.text || 'FrostySDXL');
            set('publish-watermark-position', preset.watermark.position || 'bottom-right');
            set('publish-watermark-opacity', String(Math.round((preset.watermark.opacity ?? 0.55) * 100)));
            set('publish-watermark-size', String(preset.watermark.size_percent ?? 4));
            set('publish-watermark-margin', String(preset.watermark.margin ?? 32));
            check('publish-watermark-black', preset.watermark.color === 'black');
            syncPublishWatermarkFields();
            updatePublishWatermarkOverlay();
            syncPublishMetadataNote();
        }

function deletePublishPreset(name) {
            const stored = getPublishPresets();
            const presets = stored.presets.filter(p => p.name !== name);
            try {
                localStorage.setItem(
                    PUBLISH_PRESETS_KEY,
                    JSON.stringify({ version: PUBLISH_PRESETS_VERSION, presets }),
                );
                renderPublishPresets();
            } catch {
                showToast('Could not delete preset \u2014 storage unavailable');
            }
        }

function renderPublishPresets() {
            const container = document.getElementById('publish-preset-list');
            if (!container) return;
            const stored = getPublishPresets();
            container.replaceChildren();
            if (!stored.presets.length) {
                const empty = document.createElement('div');
                empty.className = 'publish-preset-empty';
                empty.textContent = 'No saved presets. Current settings stay usable without one.';
                container.append(empty);
                return;
            }
            stored.presets.forEach(preset => {
                const row = document.createElement('div');
                row.className = 'publish-preset-row';
                const applyBtn = document.createElement('button');
                applyBtn.type = 'button';
                applyBtn.className = 'publish-preset-apply';
                applyBtn.textContent = preset.name;
                applyBtn.title = 'Apply preset';
                applyBtn.addEventListener('click', () => applyPublishPreset(preset));
                const deleteBtn = document.createElement('button');
                deleteBtn.type = 'button';
                deleteBtn.className = 'publish-preset-delete';
                deleteBtn.textContent = 'Delete';
                deleteBtn.title = `Delete preset “${preset.name}”`;
                deleteBtn.setAttribute('aria-label', `Delete preset ${preset.name}`);
                deleteBtn.addEventListener('click', () => deletePublishPreset(preset.name));
                row.append(applyBtn, deleteBtn);
                container.append(row);
            });
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
            if (publishSubmitInflight) return;
            const filenames = getSelectedSourceFilenames();
            if (!filenames.length) {
                showToast('Select images first');
                return;
            }
            publishSubmitInflight = true;
            const submitBtn = document.getElementById('publish-submit-btn');
            if (submitBtn) submitBtn.disabled = true;
            syncPublishSubmitActivity(true);
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
                showToast(`Created ${data.exported || 0} public cop${data.exported === 1 ? 'y' : 'ies'}`);
                showPublishResult(data);
                await loadBatches();
            } catch {
                showToast('Public export failed');
            } finally {
                publishSubmitInflight = false;
                if (submitBtn) submitBtn.disabled = false;
                syncPublishSubmitActivity(false);
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
