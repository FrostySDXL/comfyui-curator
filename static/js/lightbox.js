/* Ordered classic script.
 * Defines: lightbox viewer, zoom, navigation, scored navigation, lightbox favorite UI.
 * Later-file globals called at runtime: loadLightboxMetadata, renderLightboxMetadataPanel, toggleLightboxMetadata from metadata.js.
 */
let lightboxZoom = 1;
const _prefetchRegistry = new Map();
const _pendingCompareLoaders = [null, null];
let _pendingSingleImageLoader = null;
let _pendingLightboxOpen = null;
let lightboxOpenToken = 0;
let lightboxImageToken = 0;
let lightboxAiOpen = false;
let lightboxBaseWidth = 0;
let lightboxBaseHeight = 0;
let lightboxPanState = null;
let lightboxCompareMode = false;
let lightboxStickyCompareMode = false;
let lightboxComparePinnedIndex = -1;
let lightboxCompareCandidateIndex = -1;
let lightboxStickyPinnedPane = 0;
let lightboxStickyCandidatePane = 1;
let lightboxCompareItems = [];
let lightboxCompareActivePane = 0;
let lightboxCompareImageToken = 0;
let lightboxComparePanState = null;
let lightboxCompareSync = true;
let lightboxCompareSplitMode = false;
let lightboxCompareSplitPosition = 50;
let lightboxCompareSplitDragging = false;
let lightboxReturnFocusElement = null;
let lightboxCompareViewState = [
    {zoom: 1, baseWidth: 0, baseHeight: 0},
    {zoom: 1, baseWidth: 0, baseHeight: 0},
];

function isLightboxOpenPending() {
    return _pendingLightboxOpen !== null;
}

function rememberLightboxReturnFocus(element) {
    lightboxReturnFocusElement = element && typeof element.focus === 'function' ? element : null;
}

function stopLightboxMediaResources() {
            const video = document.getElementById('lightbox-video');
            const audio = document.getElementById('lightbox-audio-player');
            [video, audio].forEach(player => {
                if (!player) return;
                player.pause();
                player.removeAttribute('src');
                player.load();
            });
            const audioWrap = document.getElementById('lightbox-audio');
            const audioArt = document.getElementById('lightbox-audio-art');
            if (video) video.hidden = true;
            if (audioWrap) audioWrap.hidden = true;
            if (audioArt) audioArt.removeAttribute('src');
        }

function playLightboxVideo(video) {
            if (!video) return;
            const playResult = video.play();
            if (playResult && typeof playResult.catch === 'function') {
                playResult.catch(() => {});
            }
        }

function setLightboxVideoAutoplayLoopEnabled(enabled) {
            lightboxVideoAutoplayLoopEnabled = Boolean(enabled);
            localStorage.setItem(LIGHTBOX_VIDEO_AUTOPLAY_LOOP_KEY, lightboxVideoAutoplayLoopEnabled ? 'true' : 'false');
            const lightbox = document.getElementById('lightbox');
            const video = document.getElementById('lightbox-video');
            if (!video) return;
            video.autoplay = lightboxVideoAutoplayLoopEnabled;
            video.loop = lightboxVideoAutoplayLoopEnabled;
            if (
                lightboxVideoAutoplayLoopEnabled
                && lightbox
                && lightbox.classList.contains('active')
                && !video.hidden
            ) {
                playLightboxVideo(video);
            }
        }

function toggleLightboxVideoPlayback() {
            const lightbox = document.getElementById('lightbox');
            const video = document.getElementById('lightbox-video');
            if (!lightbox || !lightbox.classList.contains('active') || !video || video.hidden) return false;
            if (video.paused) playLightboxVideo(video);
            else video.pause();
            return true;
        }

function _showTypedLightboxMedia(img) {
            const lightbox = document.getElementById('lightbox');
            const image = document.getElementById('lightbox-img');
            const video = document.getElementById('lightbox-video');
            const audioWrap = document.getElementById('lightbox-audio');
            const audio = document.getElementById('lightbox-audio-player');
            const audioArt = document.getElementById('lightbox-audio-art');
            if (!lightbox || !image) return;
            _cancelPendingLightboxOpen();
            _cancelSingleImageLoader();
            _cleanupPrefetch();
            stopLightboxMediaResources();
            image.hidden = true;
            lightbox.classList.add('typed-media');
            const source = getImageBatchAndFolder(img);
            const original = ccImageUrl(source.batch, source.folder, img.name);
            if (img.media_kind === 'video' && video) {
                video.autoplay = lightboxVideoAutoplayLoopEnabled;
                video.loop = lightboxVideoAutoplayLoopEnabled;
                video.hidden = false;
                video.src = original;
                if (lightboxVideoAutoplayLoopEnabled) playLightboxVideo(video);
            } else if (img.media_kind === 'audio' && audioWrap && audio && audioArt) {
                audioWrap.hidden = false;
                audioArt.src = ccThumbUrl(source.batch, source.folder, img.name);
                audio.src = original;
            }
            currentLightboxDimensions = {w: null, h: null};
            currentLightboxMetadata = null;
            currentLightboxMetadataError = null;
            currentLightboxMetadataLoading = false;
            const metadataToken = ++lightboxMetadataRequestToken;
            resetLightboxPanelScroll();
            renderLightboxMetadataPanel();
            updateLightboxInfo(img, null, null);
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);
            const wasLightboxActive = lightbox.classList.contains('active');
            lightbox.inert = false;
            lightbox.classList.add('active');
            if (!wasLightboxActive && _getActiveFocusTrapModal() !== lightbox) {
                _trapFocus(lightbox, lightbox.querySelector('.lightbox-close'));
            }
            loadLightboxMetadata(img, metadataToken);
            renderLightboxAiPanel();
            if (typeof syncLightboxPublicActions === 'function') syncLightboxPublicActions();
        }

function openLightbox(index) {
            if (!lightboxReturnFocusElement) rememberLightboxReturnFocus(document.activeElement);
            lightboxCompareMode = false;
            lightboxStickyCompareMode = false;
            lightboxComparePinnedIndex = -1;
            lightboxCompareCandidateIndex = -1;
            lightboxStickyPinnedPane = 0;
            lightboxStickyCandidatePane = 1;
            lightboxCompareItems = [];
            currentIndex = index;
            syncLightboxModeUi();
            _prepareLightboxOpen();
        }

function _prepareLightboxOpen() {
            const openToken = ++lightboxOpenToken;
            const lightboxImages = getLightboxImages();
            const img = lightboxImages[currentIndex];
            const lightbox = document.getElementById('lightbox');
            const el = document.getElementById('lightbox-img');
            _cancelPendingLightboxOpen();
            _cancelSingleImageLoader();
            _cleanupPrefetch();
            ++lightboxImageToken;
            if (!img || !lightbox || !el) return;

            if (img.media_kind === 'video' || img.media_kind === 'audio') {
                _showTypedLightboxMedia(img);
                return;
            }

            stopLightboxMediaResources();
            lightbox.classList.remove('typed-media');
            el.hidden = false;
            lightbox.classList.remove('active');
            el.onload = null;
            el.onerror = null;
            el.src = '';
            el.draggable = false;
            el.classList.remove('loading');
            el.style.opacity = '';
            lightboxBaseWidth = 0;
            lightboxBaseHeight = 0;
            lightboxZoom = 1;
            currentLightboxDimensions = {w: null, h: null};
            currentLightboxMetadata = null;
            currentLightboxMetadataError = null;
            currentLightboxMetadataLoading = false;
            const metadataToken = ++lightboxMetadataRequestToken;
            resetLightboxPanelScroll();
            resetLightboxZoom();
            renderLightboxMetadataPanel();

            const source = getImageBatchAndFolder(img);
            const newSrc = ccImageUrl(source.batch, source.folder, img.name);
            const loaderEntry = _createLightboxImageLoader(newSrc);
            const pending = {entry: loaderEntry, token: openToken, visibleAssigned: false};
            _pendingLightboxOpen = pending;

            function isCurrentOpen() {
                return _pendingLightboxOpen === pending && openToken === lightboxOpenToken && !lightboxCompareMode;
            }
            function failOpen(error) {
                if (!isCurrentOpen()) return;
                _pendingLightboxOpen = null;
                el.onload = null;
                el.onerror = null;
                el.src = '';
                lightboxBaseWidth = 0;
                lightboxBaseHeight = 0;
                currentLightboxDimensions = {w: null, h: null};
                _disposeLightboxImageLoader(loaderEntry);
                console.warn(`Unable to open lightbox image ${img.name}:`, error);
                showToast('Unable to open image');
            }

            loaderEntry.ready.then(function() {
                if (_pendingLightboxOpen !== pending || openToken !== lightboxOpenToken || lightboxCompareMode) return;
                pending.visibleAssigned = true;
                el.onload = function() {
                    if (_pendingLightboxOpen !== pending || openToken !== lightboxOpenToken || lightboxCompareMode) return;
                    el.onload = null;
                    el.onerror = null;
                    currentLightboxDimensions = {
                        w: el.naturalWidth || loaderEntry.img.naturalWidth,
                        h: el.naturalHeight || loaderEntry.img.naturalHeight,
                    };
                    lightboxZoom = 1;
                    capturePreparedLightboxBaseSize();
                    if (lightboxBaseWidth <= 0 || lightboxBaseHeight <= 0) {
                        failOpen(new Error('image has no visible dimensions'));
                        return;
                    }
                    resetLightboxZoom();
                    _pendingLightboxOpen = null;
                    _disposeLightboxImageLoader(loaderEntry);
                    updateLightboxInfo(img, currentLightboxDimensions.w, currentLightboxDimensions.h);
                    if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);
                    lightbox.inert = false;
                    lightbox.classList.add('active');
                    if (_getActiveFocusTrapModal() !== lightbox) {
                        _trapFocus(lightbox, lightbox.querySelector('.lightbox-close'));
                    }
                    loadLightboxMetadata(img, metadataToken);
                    renderLightboxAiPanel();
                    if (typeof syncLightboxPublicActions === 'function') syncLightboxPublicActions();
                    _prefetchAdjacentImages(lightboxImageToken);
                };
                el.onerror = function(error) {
                    failOpen(error || new Error('visible image load failed'));
                };
                el.src = newSrc;
            }).catch(failOpen);
        }

function isLightboxCompareMode() {
            return lightboxCompareMode;
        }

function getSelectedImagesInDisplayOrder() {
            if (typeof syncCompareCandidateOrder === 'function') {
                return syncCompareCandidateOrder();
            }
            return getCurrentDisplayImages().filter(
                img => img && (!img.media_kind || img.media_kind === 'image') && selectedImages.has(img.name)
            );
        }

function openCompareLightbox() {
            const selected = getSelectedImagesInDisplayOrder();
            if (selected.length !== 2 || isVirtualCollectionView() || isPublicView()) {
                showToast('Select exactly two review images to compare');
                return;
            }
            rememberLightboxReturnFocus(document.activeElement);
            openCompareLightboxWithSelection(selected, null, true);
        }

function openCompareLightboxWithSelection(explicitSelection = null, focusElement = null, focusRemembered = false) {
            const selected = Array.isArray(explicitSelection)
                ? explicitSelection
                : getSelectedImagesInDisplayOrder();
            if (selected.length !== 2 || !selected.every(isStillLightboxImage) || isVirtualCollectionView() || isPublicView()) {
                showToast('Select exactly two review images to compare');
                return;
            }
            if (!focusRemembered) rememberLightboxReturnFocus(focusElement || document.activeElement);
            ++lightboxOpenToken;
            _cancelPendingLightboxOpen();
            _cancelSingleImageLoader();
            _cleanupPrefetch();
            lightboxCompareMode = true;
            lightboxStickyCompareMode = false;
            lightboxComparePinnedIndex = -1;
            lightboxCompareCandidateIndex = -1;
            lightboxStickyPinnedPane = 0;
            lightboxStickyCandidatePane = 1;
            lightboxCompareItems = selected;
            lightboxCompareActivePane = 0;
            lightboxCompareSplitMode = false;
            lightboxCompareViewState = [
                {zoom: 1, baseWidth: 0, baseHeight: 0},
                {zoom: 1, baseWidth: 0, baseHeight: 0},
            ];
            lightboxMetadataOpen = false;
            lightboxAiOpen = false;
            const lightbox = document.getElementById('lightbox');
            lightbox.inert = false;
            lightbox.classList.add('active');
            if (_getActiveFocusTrapModal() !== lightbox) {
                _trapFocus(lightbox, lightbox.querySelector('.lightbox-close'));
            }
            syncLightboxModeUi();
            showCompareImages();
            if (typeof syncLightboxPublicActions === 'function') syncLightboxPublicActions();
        }

function openStickyCompareLightbox() {
            const displayImages = getLightboxImages();
            const lightboxImages = getStillLightboxImages();
            const currentImage = displayImages[currentIndex];
            if (!isStillLightboxImage(currentImage)) {
                showToast('Still images only can be compared');
                return;
            }
            if (isVirtualCollectionView() || isPublicView() || lightboxImages.length < 2) {
                showToast('Open a review image with another still image available to pin compare');
                return;
            }
            ++lightboxOpenToken;
            _cancelPendingLightboxOpen();
            _cancelSingleImageLoader();
            _cleanupPrefetch();
            const pinnedIndex = getStillLightboxImageIndexByObject(currentImage);
            let candidateIndex = (pinnedIndex + 1) % lightboxImages.length;
            if (candidateIndex === pinnedIndex) candidateIndex = (candidateIndex + 1) % lightboxImages.length;
            lightboxCompareMode = true;
            lightboxStickyCompareMode = true;
            lightboxComparePinnedIndex = pinnedIndex;
            lightboxCompareCandidateIndex = candidateIndex;
            lightboxStickyPinnedPane = 0;
            lightboxStickyCandidatePane = 1;
            lightboxCompareActivePane = 1;
            lightboxCompareItems = [lightboxImages[pinnedIndex], lightboxImages[candidateIndex]];
            lightboxCompareSplitMode = false;
            lightboxCompareViewState = [
                {zoom: 1, baseWidth: 0, baseHeight: 0},
                {zoom: 1, baseWidth: 0, baseHeight: 0},
            ];
            lightboxMetadataOpen = false;
            lightboxAiOpen = false;
            syncLightboxModeUi();
            showCompareImages();
            if (typeof syncLightboxPublicActions === 'function') syncLightboxPublicActions();
        }

function getLightboxImages() {
            return getCurrentDisplayImages();
        }

function isStillLightboxImage(img) {
            return Boolean(img) && (!img.media_kind || img.media_kind === 'image');
        }

function getStillLightboxImages() {
            return getLightboxImages().filter(isStillLightboxImage);
        }

function getStillLightboxImageIndexByObject(target) {
            if (!isStillLightboxImage(target)) return -1;
            return getStillLightboxImages().findIndex(img => img.name === target.name);
        }

function closeLightbox() {
            const returnFocus = lightboxReturnFocusElement;
            lightboxReturnFocusElement = null;
            ++lightboxOpenToken;
            ++lightboxImageToken;
            ++lightboxMetadataRequestToken;
            _cleanupPrefetch();
            _cancelPendingLightboxOpen();
            _cancelSingleImageLoader();
            _cancelComparePaneLoader(0);
            _cancelComparePaneLoader(1);
            stopLightboxMediaResources();
            const el = document.getElementById('lightbox-img');
            if (el) {
                el.onload = null;
                el.onerror = null;
            }
            const lightbox = document.getElementById('lightbox');
            if (typeof _getActiveFocusTrapModal === 'function' && _getActiveFocusTrapModal() === lightbox) {
                _releaseFocusTrap();
            }
            lightbox.classList.remove('active');
            lightbox.classList.remove('typed-media');
            lightbox.inert = true;
            if (el) el.hidden = false;
            clearLightboxPanState();
            lightboxZoom = 1;
            resetCompareZoom();
            lightboxBaseWidth = 0;
            lightboxBaseHeight = 0;
            lightboxCompareMode = false;
            lightboxStickyCompareMode = false;
            lightboxComparePinnedIndex = -1;
            lightboxCompareCandidateIndex = -1;
            lightboxStickyPinnedPane = 0;
            lightboxStickyCandidatePane = 1;
            lightboxCompareItems = [];
            lightboxCompareSplitMode = false;
            lightboxMetadataOpen = false;
            lightboxAiOpen = false;
            syncLightboxModeUi();
            renderLightboxMetadataPanel();
            renderLightboxAiPanel();
            requestAnimationFrame(() => {
                const activeTrap = typeof _getActiveFocusTrapModal === 'function'
                    ? _getActiveFocusTrapModal()
                    : null;
                if (returnFocus && returnFocus.isConnected && !(activeTrap && activeTrap.classList.contains('modal'))) {
                    returnFocus.focus({preventScroll: true});
                }
            });
        }

function syncLightboxModeUi() {
            const lightbox = document.getElementById('lightbox');
            const singleWrap = document.getElementById('lightbox-image-wrap');
            const compare = document.getElementById('lightbox-compare');
            const singleIndicator = document.getElementById('lightbox-zoom-indicator');
            const pinCompareBtn = document.getElementById('lightbox-pin-compare-btn');
            if (lightbox) lightbox.classList.toggle('compare-mode', lightboxCompareMode);
            if (lightbox) lightbox.classList.toggle('compare-split-mode', lightboxCompareSplitMode);
            if (singleWrap) singleWrap.hidden = lightboxCompareMode;
            if (compare) compare.hidden = !lightboxCompareMode;
            if (compare) {
                compare.classList.toggle('split-mode', lightboxCompareSplitMode);
                if (compare.style && typeof compare.style.setProperty === 'function') {
                    compare.style.setProperty('--compare-split-position', `${lightboxCompareSplitPosition}%`);
                }
            }
            updateLightboxCompareSplitAria();
            if (singleIndicator) singleIndicator.hidden = false;
            if (pinCompareBtn) pinCompareBtn.closest('div').style.display = lightboxCompareMode ? '' : 'none';
            ['lightbox-compare-sync-btn', 'lightbox-compare-split-btn', 'lightbox-compare-pair-btn'].forEach(id => {
                const btn = document.getElementById(id);
                if (btn) btn.closest('div').style.display = lightboxCompareMode ? '' : 'none';
            });
            document.querySelectorAll('.lightbox-nav').forEach(nav => { nav.hidden = lightboxCompareMode; });
            ['metadata-toggle-btn', 'lightbox-ai-toggle-btn'].forEach(id => {
                const btn = document.getElementById(id);
                if (!btn) return;
                if (lightboxCompareMode && id === 'lightbox-ai-toggle-btn') btn.disabled = false;
                else if (id === 'lightbox-ai-toggle-btn') btn.disabled = false;
            });
            document.querySelectorAll('#lightbox-actions button').forEach(btn => {
                const label = btn.textContent.trim();
                const singleOnly = label === 'Prev scored' || label === 'Next scored';
                const wrapper = btn.closest('div');
                if (wrapper && singleOnly) wrapper.style.display = lightboxCompareMode ? 'none' : '';
            });
            if (lightboxCompareMode) {
                updateCompareZoomIndicator(lightboxCompareActivePane);
                positionCompareOverlayPanels();
            } else {
                resetCompareOverlayPanelPosition();
            }
            updateLightboxCompareControls();
        }

function resetLightboxPanelScroll() {
            ['lightbox-metadata-panel', 'lightbox-ai-panel'].forEach(id => {
                const panel = document.getElementById(id);
                if (panel) panel.scrollTop = 0;
            });
        }

function applyLightboxZoom() {
            if (lightboxCompareMode) {
                applyComparePaneZoom(lightboxCompareActivePane);
                return;
            }
            const wrap = document.getElementById('lightbox-image-wrap');
            const img = document.getElementById('lightbox-img');
            const indicator = document.getElementById('lightbox-zoom-indicator');
            if (img && lightboxBaseWidth > 0 && lightboxBaseHeight > 0) {
                img.style.width = `${Math.round(lightboxBaseWidth * lightboxZoom)}px`;
                img.style.height = `${Math.round(lightboxBaseHeight * lightboxZoom)}px`;
            } else if (img) {
                img.style.width = '';
                img.style.height = '';
            }
            if (indicator) indicator.textContent = `${Math.round(lightboxZoom * 100)}%`;
            if (wrap) {
                wrap.classList.toggle('zoomed', lightboxZoom > 1.001);
                wrap.classList.toggle('pannable', lightboxZoom > 1.001);
            }
        }

function captureLightboxBaseSize() {
            const img = document.getElementById('lightbox-img');
            if (!img) return;
            img.style.width = '';
            img.style.height = '';
            const rect = img.getBoundingClientRect();
            lightboxBaseWidth = rect.width || img.naturalWidth || 0;
            lightboxBaseHeight = rect.height || img.naturalHeight || 0;
            applyLightboxZoom();
        }

function capturePreparedLightboxBaseSize() {
            const img = document.getElementById('lightbox-img');
            if (!img) return;
            img.style.width = '';
            img.style.height = '';
            lightboxBaseWidth = img.offsetWidth || img.naturalWidth || 0;
            lightboxBaseHeight = img.offsetHeight || img.naturalHeight || 0;
            applyLightboxZoom();
        }

function zoomLightbox(delta, anchorEvent = null) {
            if (document.getElementById('lightbox').classList.contains('typed-media')) return;
            if (lightboxCompareMode) {
                zoomComparePane(lightboxCompareActivePane, delta, anchorEvent);
                return;
            }
            const wrap = document.getElementById('lightbox-image-wrap');
            const img = document.getElementById('lightbox-img');
            if (!wrap || !img) return;
            if (lightboxBaseWidth <= 0 || lightboxBaseHeight <= 0) captureLightboxBaseSize();
            const currentScale = lightboxZoom;
            const nextScale = Math.min(3, Math.max(0.6, +(currentScale + delta).toFixed(2)));
            if (nextScale === currentScale) return;
            const wrapRect = wrap.getBoundingClientRect();
            const imgRect = img.getBoundingClientRect();
            const anchorClientX = anchorEvent ? anchorEvent.clientX : wrapRect.left + (wrap.clientWidth / 2);
            const anchorClientY = anchorEvent ? anchorEvent.clientY : wrapRect.top + (wrap.clientHeight / 2);
            const ratioX = imgRect.width > 0 ? Math.min(1, Math.max(0, (anchorClientX - imgRect.left) / imgRect.width)) : 0.5;
            const ratioY = imgRect.height > 0 ? Math.min(1, Math.max(0, (anchorClientY - imgRect.top) / imgRect.height)) : 0.5;
            const viewportX = anchorClientX - wrapRect.left;
            const viewportY = anchorClientY - wrapRect.top;
            const zoomToken = lightboxImageToken;
            lightboxZoom = nextScale;
            applyLightboxZoom();
            requestAnimationFrame(() => {
                if (zoomToken !== lightboxImageToken || lightboxZoom !== nextScale) return;
                wrap.scrollLeft = Math.max(0, (ratioX * img.offsetWidth) - viewportX);
                wrap.scrollTop = Math.max(0, (ratioY * img.offsetHeight) - viewportY);
            });
        }

function clearLightboxPanState() {
            const wrap = document.getElementById('lightbox-image-wrap');
            if (wrap) wrap.classList.remove('panning');
            lightboxPanState = null;
        }

function getComparePaneElements(paneIndex) {
            return {
                pane: document.querySelector(`.lightbox-compare-pane[data-compare-pane="${paneIndex}"]`),
                wrap: document.getElementById(`lightbox-compare-wrap-${paneIndex}`),
                img: document.getElementById(`lightbox-compare-img-${paneIndex}`),
                label: document.getElementById(`lightbox-compare-label-${paneIndex}`),
                indicator: document.getElementById(`lightbox-compare-zoom-${paneIndex}`),
            };
        }

function setLightboxCompareActivePane(paneIndex) {
            if (paneIndex < 0 || paneIndex > 1) return;
            lightboxCompareActivePane = paneIndex;
            document.querySelectorAll('.lightbox-compare-pane').forEach(pane => {
                const isActive = Number(pane.dataset.comparePane) === paneIndex;
                pane.classList.toggle('active', isActive);
                pane.setAttribute('aria-selected', String(isActive));
            });
            const img = getActiveLightboxImage();
            if (img && typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);
            updateCompareZoomIndicator(paneIndex);
            updateCompareInfo();
            refreshCompareActiveImagePanels();
        }

function updateLightboxCompareControls() {
            const syncBtn = document.getElementById('lightbox-compare-sync-btn');
            const splitBtn = document.getElementById('lightbox-compare-split-btn');
            const pinBtn = document.getElementById('lightbox-pin-compare-btn');
            if (syncBtn) {
                syncBtn.textContent = lightboxCompareSync ? 'Sync Pan/Zoom: On' : 'Sync Pan/Zoom: Off';
                if (typeof syncBtn.setAttribute === 'function') syncBtn.setAttribute('aria-pressed', String(lightboxCompareSync));
            }
            if (splitBtn) {
                splitBtn.textContent = lightboxCompareSplitMode ? 'Side-by-side' : 'A/B Split';
                if (typeof splitBtn.setAttribute === 'function') splitBtn.setAttribute('aria-pressed', String(lightboxCompareSplitMode));
            }
            if (pinBtn) {
                pinBtn.textContent = lightboxStickyCompareMode ? 'Clear Pin A' : 'Pin A';
                if (typeof pinBtn.setAttribute === 'function') pinBtn.setAttribute('aria-pressed', String(lightboxStickyCompareMode));
            }
        }

function setLightboxCompareSync(enabled) {
            lightboxCompareSync = Boolean(enabled);
            if (lightboxCompareMode && lightboxCompareSync) {
                const sourcePane = lightboxCompareActivePane;
                const state = lightboxCompareViewState[sourcePane];
                const otherPane = getInactiveComparePaneIndex();
                const otherState = lightboxCompareViewState[otherPane];
                if (state && otherState) {
                    otherState.zoom = state.zoom;
                    applyComparePaneZoom(otherPane);
                    syncComparePaneScroll(sourcePane);
                }
            }
            updateLightboxCompareControls();
        }

function canUseLightboxCompareSplit() {
            return lightboxCompareItems.length === 2
                && lightboxCompareItems.every(img => img && (!img.media_kind || img.media_kind === 'image'));
        }

function toggleLightboxCompareSplit() {
            if (!lightboxCompareMode) return false;
            if (!lightboxCompareSplitMode && !canUseLightboxCompareSplit()) {
                showToast('A/B Split is available for still images only');
                return false;
            }
            lightboxCompareSplitMode = !lightboxCompareSplitMode;
            const compare = document.getElementById('lightbox-compare');
            if (compare) {
                compare.classList.toggle('split-mode', lightboxCompareSplitMode);
                if (compare.style && typeof compare.style.setProperty === 'function') {
                    compare.style.setProperty('--compare-split-position', `${lightboxCompareSplitPosition}%`);
                }
            }
            updateLightboxCompareSplitAria();
            updateLightboxCompareControls();
            return true;
        }

function updateLightboxCompareSplitAria() {
            const divider = document.getElementById('lightbox-compare-divider');
            if (!divider || typeof divider.setAttribute !== 'function') return;
            divider.setAttribute('aria-valuenow', String(Math.round(lightboxCompareSplitPosition)));
        }

function setLightboxCompareSplitPercent(position) {
            lightboxCompareSplitPosition = Math.min(92, Math.max(8, Number(position) || 50));
            const compare = document.getElementById('lightbox-compare');
            if (compare && compare.style && typeof compare.style.setProperty === 'function') {
                compare.style.setProperty('--compare-split-position', `${lightboxCompareSplitPosition}%`);
            }
            updateLightboxCompareSplitAria();
        }

function setLightboxCompareSplitPosition(clientX) {
            const compare = document.getElementById('lightbox-compare');
            if (!compare || !lightboxCompareSplitMode) return;
            const rect = compare.getBoundingClientRect();
            if (!rect.width) return;
            setLightboxCompareSplitPercent(((clientX - rect.left) / rect.width) * 100);
        }

function handleLightboxCompareSplitKeydown(event) {
            if (!lightboxCompareSplitMode) return;
            let nextPosition = lightboxCompareSplitPosition;
            if (event.key === 'ArrowLeft') nextPosition -= 2;
            else if (event.key === 'ArrowRight') nextPosition += 2;
            else if (event.key === 'Home') nextPosition = 8;
            else if (event.key === 'End') nextPosition = 92;
            else return;
            event.preventDefault();
            setLightboxCompareSplitPercent(nextPosition);
        }

function startLightboxCompareSplitDrag(event) {
            const target = event.target;
            if (!lightboxCompareSplitMode || !target || typeof target.closest !== 'function'
                || !target.closest('#lightbox-compare-divider')) return;
            lightboxCompareSplitDragging = true;
            if (typeof event.currentTarget.setPointerCapture === 'function') {
                event.currentTarget.setPointerCapture(event.pointerId);
            }
            setLightboxCompareSplitPosition(event.clientX);
            event.preventDefault();
        }

function moveLightboxCompareSplitDrag(event) {
            if (!lightboxCompareSplitDragging) return;
            setLightboxCompareSplitPosition(event.clientX);
            event.preventDefault();
        }

function endLightboxCompareSplitDrag(event) {
            if (!lightboxCompareSplitDragging) return;
            if (typeof event.currentTarget.hasPointerCapture === 'function'
                && event.currentTarget.hasPointerCapture(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId);
            }
            lightboxCompareSplitDragging = false;
        }

function clearStickyComparePin() {
            if (!lightboxStickyCompareMode) return false;
            lightboxStickyCompareMode = false;
            lightboxComparePinnedIndex = -1;
            lightboxCompareCandidateIndex = -1;
            updateLightboxCompareControls();
            updateCompareInfo();
            return true;
        }

function toggleStickyComparePin() {
            if (lightboxStickyCompareMode) return clearStickyComparePin();
            enableStickyCompareFromCurrentPanes();
            return true;
        }

function syncComparePaneScroll(sourcePane) {
            if (!lightboxCompareSync) return;
            const {wrap: sourceWrap} = getComparePaneElements(sourcePane);
            const otherPane = sourcePane === 0 ? 1 : 0;
            const {wrap: targetWrap} = getComparePaneElements(otherPane);
            if (!sourceWrap || !targetWrap) return;
            const sourceMaxX = Math.max(0, (sourceWrap.scrollWidth || sourceWrap.clientWidth) - sourceWrap.clientWidth);
            const sourceMaxY = Math.max(0, (sourceWrap.scrollHeight || sourceWrap.clientHeight) - sourceWrap.clientHeight);
            const targetMaxX = Math.max(0, (targetWrap.scrollWidth || targetWrap.clientWidth) - targetWrap.clientWidth);
            const targetMaxY = Math.max(0, (targetWrap.scrollHeight || targetWrap.clientHeight) - targetWrap.clientHeight);
            targetWrap.scrollLeft = sourceMaxX > 0 ? (sourceWrap.scrollLeft / sourceMaxX) * targetMaxX : 0;
            targetWrap.scrollTop = sourceMaxY > 0 ? (sourceWrap.scrollTop / sourceMaxY) * targetMaxY : 0;
        }

function getInactiveComparePaneIndex() {
            return lightboxCompareActivePane === 0 ? 1 : 0;
        }

function resetCompareOverlayPanelPosition() {
            const lightbox = document.getElementById('lightbox');
            if (lightbox) {
                lightbox.classList.remove('compare-panel-overlay-left', 'compare-panel-overlay-right');
            }
            ['lightbox-metadata-panel', 'lightbox-ai-panel'].forEach(id => {
                const panel = document.getElementById(id);
                if (!panel) return;
                panel.style.left = '';
                panel.style.right = '';
                panel.style.top = '';
                panel.style.width = '';
                panel.style.maxHeight = '';
            });
        }

function positionCompareOverlayPanels() {
            if (!lightboxCompareMode) {
                resetCompareOverlayPanelPosition();
                return;
            }
            const inactiveIndex = getInactiveComparePaneIndex();
            const {pane} = getComparePaneElements(inactiveIndex);
            const lightbox = document.getElementById('lightbox');
            if (!pane || !lightbox) return;
            const rect = pane.getBoundingClientRect();
            lightbox.classList.toggle('compare-panel-overlay-left', inactiveIndex === 0);
            lightbox.classList.toggle('compare-panel-overlay-right', inactiveIndex === 1);
            const panelWidth = Math.max(280, Math.min(rect.width - 28, 520));
            const panelLeft = rect.left + Math.max(14, (rect.width - panelWidth) / 2);
            const panelTop = rect.top + 42;
            const panelMaxHeight = Math.max(220, rect.height - 64);
            const bothPanelsOpen = lightboxMetadataOpen && lightboxAiOpen;
            ['lightbox-metadata-panel', 'lightbox-ai-panel'].forEach((id, index) => {
                const panel = document.getElementById(id);
                if (!panel) return;
                const splitHeight = Math.max(160, Math.floor((panelMaxHeight - 10) / 2));
                const top = bothPanelsOpen && index === 1 ? panelTop + splitHeight + 10 : panelTop;
                const maxHeight = bothPanelsOpen ? splitHeight : panelMaxHeight;
                panel.style.left = `${Math.round(panelLeft)}px`;
                panel.style.right = 'auto';
                panel.style.top = `${Math.round(top)}px`;
                panel.style.width = `${Math.round(panelWidth)}px`;
                panel.style.maxHeight = `${Math.round(maxHeight)}px`;
            });
        }

function refreshCompareActiveImagePanels() {
            if (!lightboxCompareMode) return;
            const img = getActiveLightboxImage();
            if (!img) return;
            const metadataToken = ++lightboxMetadataRequestToken;
            currentLightboxMetadata = null;
            currentLightboxMetadataError = null;
            currentLightboxMetadataLoading = false;
            currentLightboxDimensions = {w: null, h: null};
            resetLightboxPanelScroll();
            currentLightboxMetadataLoading = true;
            syncMetadataToggleButton();
            renderLightboxMetadataPanel();
            renderLightboxAiPanel();
            positionCompareOverlayPanels();
            loadLightboxMetadata(img, metadataToken).finally(() => {
                if (metadataToken !== lightboxMetadataRequestToken) return;
                renderLightboxMetadataPanel();
                renderLightboxAiPanel();
                positionCompareOverlayPanels();
            });
        }

function getImageDisplayIndexByObject(target) {
            if (!target) return -1;
            return getLightboxImages().findIndex(img => img.name === target.name);
        }

function getCompareSplitPaneIndex(clientX) {
            const compare = document.getElementById('lightbox-compare');
            if (!compare || !lightboxCompareSplitMode || !Number.isFinite(clientX)) return -1;
            const rect = compare.getBoundingClientRect();
            if (!rect.width) return -1;
            const splitX = rect.left + (rect.width * lightboxCompareSplitPosition / 100);
            return clientX < splitX ? 0 : 1;
        }

function getActiveComparePaneIndexFromEvent(event) {
            const target = event && event.target;
            const divider = target && typeof target.closest === 'function'
                ? target.closest('#lightbox-compare-divider')
                : null;
            if (lightboxCompareSplitMode && !divider) {
                const splitPane = getCompareSplitPaneIndex(event && event.clientX);
                if (splitPane >= 0) return splitPane;
            }
            const pane = target && typeof target.closest === 'function'
                ? target.closest('.lightbox-compare-pane')
                : null;
            if (!pane) return lightboxCompareActivePane;
            return Number(pane.dataset.comparePane || lightboxCompareActivePane);
        }

function getActiveCompareImage() {
            return lightboxCompareItems[lightboxCompareActivePane] || null;
        }

function getActiveLightboxImage() {
            if (lightboxCompareMode) return getActiveCompareImage();
            return getLightboxImages()[currentIndex] || null;
        }

function applyComparePaneZoom(paneIndex) {
            const state = lightboxCompareViewState[paneIndex];
            const {wrap, img, indicator} = getComparePaneElements(paneIndex);
            if (!state || !wrap || !img) return;
            if (state.baseWidth > 0 && state.baseHeight > 0) {
                img.style.width = `${Math.round(state.baseWidth * state.zoom)}px`;
                img.style.height = `${Math.round(state.baseHeight * state.zoom)}px`;
            } else {
                img.style.width = '';
                img.style.height = '';
            }
            if (indicator) indicator.textContent = `${Math.round(state.zoom * 100)}%`;
            updateCompareZoomIndicator(paneIndex);
            positionCompareOverlayPanels();
            wrap.classList.toggle('zoomed', state.zoom > 1.001);
            wrap.classList.toggle('pannable', state.zoom > 1.001);
        }

function updateCompareZoomIndicator(paneIndex) {
            const state = lightboxCompareViewState[paneIndex];
            const indicator = document.getElementById('lightbox-zoom-indicator');
            if (!state || !indicator) return;
            indicator.textContent = `Pane ${paneIndex + 1} · ${Math.round(state.zoom * 100)}%`;
        }

function captureComparePaneBaseSize(paneIndex) {
            const state = lightboxCompareViewState[paneIndex];
            const {img} = getComparePaneElements(paneIndex);
            if (!state || !img) return;
            img.style.width = '';
            img.style.height = '';
            const rect = img.getBoundingClientRect();
            state.baseWidth = rect.width || img.naturalWidth || 0;
            state.baseHeight = rect.height || img.naturalHeight || 0;
            applyComparePaneZoom(paneIndex);
        }

function zoomComparePane(paneIndex, delta, anchorEvent = null) {
            const state = lightboxCompareViewState[paneIndex];
            const {wrap, img} = getComparePaneElements(paneIndex);
            if (!state || !wrap || !img) return;
            setLightboxCompareActivePane(paneIndex);
            if (state.baseWidth <= 0 || state.baseHeight <= 0) captureComparePaneBaseSize(paneIndex);
            const currentScale = state.zoom;
            const nextScale = Math.min(3, Math.max(0.6, +(currentScale + delta).toFixed(2)));
            if (nextScale === currentScale) return;
            const wrapRect = wrap.getBoundingClientRect();
            const imgRect = img.getBoundingClientRect();
            const anchorClientX = anchorEvent ? anchorEvent.clientX : wrapRect.left + (wrap.clientWidth / 2);
            const anchorClientY = anchorEvent ? anchorEvent.clientY : wrapRect.top + (wrap.clientHeight / 2);
            const ratioX = imgRect.width > 0 ? Math.min(1, Math.max(0, (anchorClientX - imgRect.left) / imgRect.width)) : 0.5;
            const ratioY = imgRect.height > 0 ? Math.min(1, Math.max(0, (anchorClientY - imgRect.top) / imgRect.height)) : 0.5;
            const viewportX = anchorClientX - wrapRect.left;
            const viewportY = anchorClientY - wrapRect.top;
            const zoomToken = lightboxCompareImageToken;
            state.zoom = nextScale;
            applyComparePaneZoom(paneIndex);
            if (lightboxCompareSync) {
                const otherPane = paneIndex === 0 ? 1 : 0;
                const otherState = lightboxCompareViewState[otherPane];
                if (otherState) {
                    otherState.zoom = nextScale;
                    applyComparePaneZoom(otherPane);
                }
            }
            requestAnimationFrame(() => {
                if (zoomToken !== lightboxCompareImageToken || state.zoom !== nextScale) return;
                wrap.scrollLeft = Math.max(0, (ratioX * img.offsetWidth) - viewportX);
                wrap.scrollTop = Math.max(0, (ratioY * img.offsetHeight) - viewportY);
                syncComparePaneScroll(paneIndex);
            });
        }

function resetComparePaneZoom(paneIndex) {
            const state = lightboxCompareViewState[paneIndex];
            const {wrap} = getComparePaneElements(paneIndex);
            if (!state) return;
            state.zoom = 1;
            applyComparePaneZoom(paneIndex);
            if (wrap) {
                wrap.scrollTop = 0;
                wrap.scrollLeft = 0;
            }
        }

function resetCompareZoom() {
            lightboxComparePanState = null;
            resetComparePaneZoom(0);
            resetComparePaneZoom(1);
        }

function updateComparePaneImage(paneIndex, img, preserveZoom = false) {
            ++lightboxCompareImageToken;
            const {pane, wrap, img: imgEl, label} = getComparePaneElements(paneIndex);
            if (!imgEl || !img) return;
            _cancelComparePaneLoader(paneIndex);
            if (pane) pane.classList.toggle('active', paneIndex === lightboxCompareActivePane);
            if (wrap) {
                wrap.scrollTop = 0;
                wrap.scrollLeft = 0;
            }
            if (!preserveZoom) {
                const linkedZoom = lightboxCompareSync
                    ? lightboxCompareViewState[paneIndex === 0 ? 1 : 0].zoom
                    : 1;
                lightboxCompareViewState[paneIndex] = {zoom: linkedZoom, baseWidth: 0, baseHeight: 0};
            }
            imgEl.draggable = false;
            imgEl.onload = null;
            imgEl.onerror = null;
            const source = getImageBatchAndFolder(img);
            const newSrc = ccImageUrl(source.batch, source.folder, img.name);
            const loader = new Image();
            const entry = {img: loader};
            _pendingCompareLoaders[paneIndex] = entry;
            function commitSwap() {
                if (_pendingCompareLoaders[paneIndex] !== entry) return;
                imgEl.onload = function() {
                    imgEl.onload = null;
                    imgEl.onerror = null;
                    captureComparePaneBaseSize(paneIndex);
                    updateCompareInfo();
                };
                imgEl.onerror = function() {
                    imgEl.onload = null;
                    imgEl.onerror = null;
                };
                if (label) {
                    const side = lightboxStickyCompareMode && paneIndex === lightboxStickyPinnedPane
                        ? 'Pinned'
                        : (paneIndex === 0 ? 'Left' : 'Right');
                    label.textContent = `${side} \u00B7 ${img.name}`;
                }
                imgEl.src = newSrc;
                _pendingCompareLoaders[paneIndex] = null;
            }
            function failLoad() {
                if (_pendingCompareLoaders[paneIndex] !== entry) return;
                _pendingCompareLoaders[paneIndex] = null;
            }
            loader.onload = function() {
                if (_pendingCompareLoaders[paneIndex] !== entry) return;
                if (loader.decode) {
                    loader.decode().then(function() {
                        commitSwap();
                    }).catch(function() {
                        failLoad();
                    });
                } else {
                    commitSwap();
                }
            };
            loader.onerror = function() {
                failLoad();
            };
            loader.src = newSrc;
        }

function _cancelComparePaneLoader(paneIndex) {
            const entry = _pendingCompareLoaders[paneIndex];
            if (!entry) return;
            entry.img.onload = null;
            entry.img.onerror = null;
            entry.img.src = '';
            _pendingCompareLoaders[paneIndex] = null;
        }

function enableStickyCompareFromCurrentPanes() {
            if (!lightboxCompareMode) {
                openStickyCompareLightbox();
                return;
            }
            const pinnedImage = getActiveLightboxImage();
            const candidatePane = getInactiveComparePaneIndex();
            const candidateImage = lightboxCompareItems[candidatePane];
            const pinnedIndex = getStillLightboxImageIndexByObject(pinnedImage);
            const candidateIndex = getStillLightboxImageIndexByObject(candidateImage);
            if (pinnedIndex < 0 || candidateIndex < 0) {
                showToast('Still images only can be compared');
                return;
            }
            lightboxStickyCompareMode = true;
            lightboxStickyPinnedPane = lightboxCompareActivePane;
            lightboxStickyCandidatePane = getInactiveComparePaneIndex();
            lightboxComparePinnedIndex = pinnedIndex;
            lightboxCompareCandidateIndex = candidateIndex;
            updateComparePaneImage(lightboxStickyPinnedPane, lightboxCompareItems[lightboxStickyPinnedPane], true);
            updateComparePaneImage(lightboxStickyCandidatePane, lightboxCompareItems[lightboxStickyCandidatePane], true);
            setLightboxCompareActivePane(lightboxStickyPinnedPane);
            updateLightboxCompareControls();
            showToast('Pinned active image for compare');
        }

function navigateStickyCompare(delta) {
            if (!lightboxCompareMode || !lightboxStickyCompareMode) return;
            const lightboxImages = getStillLightboxImages();
            if (lightboxImages.length < 2 || lightboxComparePinnedIndex < 0) return;
            let nextIndex = lightboxCompareCandidateIndex;
            do {
                nextIndex = (nextIndex + delta + lightboxImages.length) % lightboxImages.length;
            } while (nextIndex === lightboxComparePinnedIndex && lightboxImages.length > 1);
            lightboxCompareCandidateIndex = nextIndex;
            lightboxCompareItems[lightboxStickyCandidatePane] = lightboxImages[nextIndex];
            lightboxCompareActivePane = lightboxStickyCandidatePane;
            updateComparePaneImage(lightboxStickyCandidatePane, lightboxCompareItems[lightboxStickyCandidatePane]);
            setLightboxCompareActivePane(lightboxStickyCandidatePane);
        }

function advanceComparePair(delta) {
            if (!lightboxCompareMode || lightboxCompareItems.length !== 2) return false;
            const lightboxImages = getStillLightboxImages();
            if (lightboxImages.length < 2) return false;
            const firstIndex = getStillLightboxImageIndexByObject(lightboxCompareItems[0]);
            const secondIndex = getStillLightboxImageIndexByObject(lightboxCompareItems[1]);
            if (firstIndex < 0 || secondIndex < 0) return false;
            const nextFirst = (firstIndex + delta + lightboxImages.length) % lightboxImages.length;
            let nextSecond = (secondIndex + delta + lightboxImages.length) % lightboxImages.length;
            if (nextSecond === nextFirst) {
                nextSecond = (nextSecond + (delta >= 0 ? 1 : -1) + lightboxImages.length) % lightboxImages.length;
            }
            lightboxCompareItems[0] = lightboxImages[nextFirst];
            lightboxCompareItems[1] = lightboxImages[nextSecond];
            if (lightboxStickyCompareMode) {
                lightboxComparePinnedIndex = lightboxStickyPinnedPane === 0 ? nextFirst : nextSecond;
                lightboxCompareCandidateIndex = lightboxStickyCandidatePane === 0 ? nextFirst : nextSecond;
            }
            updateComparePaneImage(0, lightboxCompareItems[0]);
            updateComparePaneImage(1, lightboxCompareItems[1]);
            setLightboxCompareActivePane(lightboxCompareActivePane);
            updateLightboxCompareControls();
            return true;
        }

function startLightboxPan(event) {
            if (lightboxCompareMode) {
                const target = event && event.target;
                const divider = target && typeof target.closest === 'function'
                    ? target.closest('#lightbox-compare-divider')
                    : null;
                if (lightboxCompareSplitDragging || divider) return;
                const paneIndex = getActiveComparePaneIndexFromEvent(event);
                const state = lightboxCompareViewState[paneIndex];
                const {wrap} = getComparePaneElements(paneIndex);
                if (!state || state.zoom <= 1.001 || event.button !== 0 || !wrap) return;
                setLightboxCompareActivePane(paneIndex);
                lightboxComparePanState = {
                    paneIndex,
                    pointerId: event.pointerId,
                    startX: event.clientX,
                    startY: event.clientY,
                    scrollLeft: wrap.scrollLeft,
                    scrollTop: wrap.scrollTop,
                };
                wrap.classList.add('panning');
                wrap.setPointerCapture(event.pointerId);
                event.preventDefault();
                return;
            }
            if (lightboxZoom <= 1.001 || event.button !== 0) return;
            const wrap = document.getElementById('lightbox-image-wrap');
            if (!wrap) return;
            lightboxPanState = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                scrollLeft: wrap.scrollLeft,
                scrollTop: wrap.scrollTop,
            };
            wrap.classList.add('panning');
            wrap.setPointerCapture(event.pointerId);
            event.preventDefault();
        }

function moveLightboxPan(event) {
            if (lightboxCompareMode) {
                if (lightboxCompareSplitDragging || !lightboxComparePanState
                    || event.pointerId !== lightboxComparePanState.pointerId) return;
                const {wrap} = getComparePaneElements(lightboxComparePanState.paneIndex);
                if (!wrap) return;
                wrap.scrollLeft = lightboxComparePanState.scrollLeft - (event.clientX - lightboxComparePanState.startX);
                wrap.scrollTop = lightboxComparePanState.scrollTop - (event.clientY - lightboxComparePanState.startY);
                syncComparePaneScroll(lightboxComparePanState.paneIndex);
                event.preventDefault();
                return;
            }
            if (!lightboxPanState || event.pointerId !== lightboxPanState.pointerId) return;
            const wrap = document.getElementById('lightbox-image-wrap');
            if (!wrap) return;
            wrap.scrollLeft = lightboxPanState.scrollLeft - (event.clientX - lightboxPanState.startX);
            wrap.scrollTop = lightboxPanState.scrollTop - (event.clientY - lightboxPanState.startY);
            event.preventDefault();
        }

function endLightboxPan(event) {
            if (lightboxCompareMode) {
                if (!lightboxComparePanState || event.pointerId !== lightboxComparePanState.pointerId) return;
                const {wrap} = getComparePaneElements(lightboxComparePanState.paneIndex);
                if (wrap && wrap.hasPointerCapture(event.pointerId)) wrap.releasePointerCapture(event.pointerId);
                if (wrap) wrap.classList.remove('panning');
                lightboxComparePanState = null;
                return;
            }
            if (!lightboxPanState || event.pointerId !== lightboxPanState.pointerId) return;
            const wrap = document.getElementById('lightbox-image-wrap');
            if (wrap && wrap.hasPointerCapture(event.pointerId)) wrap.releasePointerCapture(event.pointerId);
            clearLightboxPanState();
        }

function resetLightboxZoom() {
            if (lightboxCompareMode) {
                resetComparePaneZoom(lightboxCompareActivePane);
                if (lightboxCompareSync) resetComparePaneZoom(getInactiveComparePaneIndex());
                return;
            }
            clearLightboxPanState();
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
            return getLightboxImages()
                .map((img, index) => ({img, index, score: img ? aiGetImageScore(img.name) : -1}))
                .filter(entry => entry.score && !entry.score.failed)
                .sort((a, b) => {
                    if (currentSort === 'score-desc') return b.score.score - a.score.score;
                    return a.index - b.index;
                })
                .map(entry => entry.index);
        }

function navigateScored(delta) {
            if (lightboxCompareMode) return;
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
            if (lightboxCompareMode) {
                showCompareImages();
                return;
            }
            const lightboxImages = getLightboxImages();
            const img = lightboxImages[currentIndex];
            if (!img) return;
            if (img.media_kind === 'video' || img.media_kind === 'audio') {
                ++lightboxImageToken;
                ++lightboxMetadataRequestToken;
                _showTypedLightboxMedia(img);
                return;
            }
            stopLightboxMediaResources();
            document.getElementById('lightbox').classList.remove('typed-media');
            document.getElementById('lightbox-img').hidden = false;
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);
            const imageToken = ++lightboxImageToken;
            const metadataToken = ++lightboxMetadataRequestToken;
            currentLightboxMetadata = null;
            currentLightboxMetadataError = null;
            currentLightboxMetadataLoading = false;
            currentLightboxDimensions = {w: null, h: null};
            lightboxBaseWidth = 0;
            lightboxBaseHeight = 0;
            resetLightboxPanelScroll();
            renderLightboxMetadataPanel();
            resetLightboxZoom();
            const el = document.getElementById('lightbox-img');
            el.draggable = false;
            el.onload = null;
            el.onerror = null;
            el.classList.remove('loading');
            el.style.opacity = '';
            _cancelSingleImageLoader();
            const source = getImageBatchAndFolder(img);
            const newSrc = ccImageUrl(source.batch, source.folder, img.name);
            const loaderEntry = _prefetchRegistry.get(newSrc) || _createLightboxImageLoader(newSrc);
            _prefetchRegistry.delete(newSrc);
            const pending = {entry: loaderEntry, token: imageToken};
            _pendingSingleImageLoader = pending;
            loaderEntry.ready.then(function() {
                const lightbox = document.getElementById('lightbox');
                if (_pendingSingleImageLoader !== pending || imageToken !== lightboxImageToken ||
                    !lightbox || !lightbox.classList.contains('active') || lightboxCompareMode) return;
                _pendingSingleImageLoader = null;
                loaderEntry.img.onload = null;
                loaderEntry.img.onerror = null;
                el.onload = function() {
                    if (imageToken !== lightboxImageToken) return;
                    el.onload = null;
                    el.onerror = null;
                    captureLightboxBaseSize();
                };
                el.onerror = function() {
                    if (imageToken !== lightboxImageToken) return;
                    el.onload = null;
                    el.onerror = null;
                };
                el.src = newSrc;
                currentLightboxDimensions = {
                    w: loaderEntry.img.naturalWidth,
                    h: loaderEntry.img.naturalHeight,
                };
                updateLightboxInfo(img, currentLightboxDimensions.w, currentLightboxDimensions.h);
                _prefetchAdjacentImages(imageToken);
            }).catch(function() {
                if (_pendingSingleImageLoader === pending) _pendingSingleImageLoader = null;
            });
            loadLightboxMetadata(img, metadataToken);
            renderLightboxAiPanel();
            if (typeof syncLightboxPublicActions === 'function') syncLightboxPublicActions();
        }

function toggleLightboxAiPanel() {
            lightboxAiOpen = !lightboxAiOpen;
            renderLightboxAiPanel();
            positionCompareOverlayPanels();
        }

function renderLightboxAiPanel() {
            const panel = document.getElementById('lightbox-ai-panel');
            const btn = document.getElementById('lightbox-ai-toggle-btn');
            if (!panel) return;
            panel.classList.toggle('open', lightboxAiOpen);
            if (btn) btn.textContent = lightboxAiOpen ? 'Hide AI' : 'AI';
            panel.replaceChildren();
            if (!lightboxAiOpen) return;
            const img = getActiveLightboxImage();
            const header = document.createElement('div');
            header.className = 'metadata-header';
            const titleWrap = document.createElement('div');
            titleWrap.appendChild(createTextElement('div', 'metadata-title', 'AI Review'));
            titleWrap.appendChild(createTextElement('div', 'metadata-subtitle', 'Lightbox image score details'));
            header.appendChild(titleWrap);
            panel.appendChild(header);
            const body = document.createElement('div');
            body.className = 'ai-image-inspector';
            if (typeof aiAppendImageInspectorContent === 'function') {
                aiAppendImageInspectorContent(body, img || null);
            } else {
                body.appendChild(createTextElement('div', 'ai-inspector-empty-detail', 'AI inspector is unavailable.'));
            }
            panel.appendChild(body);
        }

function showCompareImages() {
            syncLightboxModeUi();
            lightboxCompareItems.forEach((img, paneIndex) => {
                updateComparePaneImage(paneIndex, img);
            });
            setLightboxCompareActivePane(lightboxCompareActivePane);
        }

function updateCompareInfo() {
            const infoEl = document.getElementById('lightbox-info');
            const img = getActiveLightboxImage();
            if (!infoEl || !img) return;
            infoEl.replaceChildren();
            const lineEl = document.createElement('div');
            lineEl.className = 'lightbox-info-line';
            lineEl.appendChild(document.createTextNode(`Compare active ${lightboxCompareActivePane + 1} / 2  -  ${img.name}`));
            const fav = document.createElement('span');
            fav.className = 'lightbox-favorite-star';
            fav.textContent = img.favorite ? '\u2605' : '\u2606';
            fav.title = img.favorite ? 'Remove favorite' : 'Add favorite';
            fav.addEventListener('click', toggleLightboxFavorite);
            lineEl.appendChild(fav);
            infoEl.appendChild(lineEl);
        }

function updateLightboxInfo(img, w, h) {
            const infoEl = document.getElementById('lightbox-info');
            infoEl.replaceChildren();
            const workspaceSearchActive = typeof isWorkspaceSearchView === 'function'
                && isWorkspaceSearchView()
                && typeof workspaceSearchFilter !== 'undefined'
                && workspaceSearchFilter;
            let line1 = `${currentIndex+1} / ${getLightboxImages().length}  -  ${img.name}`;
            if (workspaceSearchActive) {
                line1 = `${currentIndex+1} / ${workspaceSearchFilter.total}  -  ${img.name}`;
            }
            if (w && h) line1 += `  (${w}x${h})`;
            const lineEl = document.createElement('div');
            lineEl.className = 'lightbox-info-line';
            lineEl.appendChild(document.createTextNode(line1));
            const fav = document.createElement('span');
            fav.className = 'lightbox-favorite-star';
            fav.textContent = img.favorite ? '\u2605' : '\u2606';
            fav.title = img.favorite ? 'Remove favorite' : 'Add favorite';
            fav.addEventListener('click', toggleLightboxFavorite);
            lineEl.appendChild(fav);
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

async function toggleLightboxFavorite() {
            const img = getActiveLightboxImage();
            if (!img) return;
            const index = getImageDisplayIndex(img);
            if (index < 0) return;
            await toggleFavorite(index);
            if (lightboxCompareMode) updateCompareInfo();
        }

function updateLightboxFavorite(img) {
            const star = document.querySelector('.lightbox-favorite-star');
            if (!star || !img) return;
            star.textContent = img.favorite ? '\u2605' : '\u2606';
            star.style.color = img.favorite ? '#e8c84a' : '';
            star.title = img.favorite ? 'Remove favorite' : 'Add favorite';
        }

async function navigate(delta) {
            if (lightboxCompareMode) return;
            const lightboxImages = getLightboxImages();
            if (lightboxImages.length === 0) return;
            const activeImageKey = typeof getImageRenderKey === 'function'
                ? getImageRenderKey(lightboxImages[currentIndex])
                : null;
            let navigationImages = lightboxImages;
            const workspaceSearchActive = typeof isWorkspaceSearchView === 'function'
                && isWorkspaceSearchView()
                && typeof workspaceSearchFilter !== 'undefined'
                && workspaceSearchFilter?.hasMore;
            if (workspaceSearchActive) {
                if (delta > 0 && currentIndex === lightboxImages.length - 1) {
                    await loadMoreWorkspaceSearchResults();
                    navigationImages = getLightboxImages();
                    const reanchoredIndex = activeImageKey === null
                        ? -1
                        : navigationImages.findIndex(image => getImageRenderKey(image) === activeImageKey);
                    if (reanchoredIndex >= 0) currentIndex = reanchoredIndex;
                } else if (delta < 0 && currentIndex === 0) {
                    return;
                }
            }
            if (workspaceSearchActive) {
                currentIndex = (currentIndex + delta + navigationImages.length) % navigationImages.length;
            } else {
                currentIndex = (currentIndex + delta + lightboxImages.length) % lightboxImages.length;
            }
            if (typeof pagedFolderMode !== 'undefined' && pagedFolderMode && !navigationImages[currentIndex]) {
                await ensureFolderPageForIndex(currentIndex);
            }
            showCurrentImage();
        }

function _createLightboxImageLoader(url) {
            const loader = new Image();
            const entry = {img: loader, ready: null};
            entry.ready = new Promise(function(resolve, reject) {
                const settleReady = function() {
                    loader.onload = null;
                    loader.onerror = null;
                    resolve(entry);
                };
                const failLoad = function(error) {
                    loader.onload = null;
                    loader.onerror = null;
                    reject(error);
                };
                loader.onload = function() {
                    if (loader.decode) {
                        loader.decode().then(settleReady).catch(settleReady);
                    } else {
                        settleReady();
                    }
                };
                loader.onerror = failLoad;
            });
            // Every caller installs its own lifecycle handler; this prevents a
            // cancelled loader rejection from becoming an unhandled promise.
            entry.ready.catch(function() {});
            loader.src = url;
            return entry;
        }

function _disposeLightboxImageLoader(entry) {
            if (!entry) return;
            entry.img.onload = null;
            entry.img.onerror = null;
            entry.img.src = '';
        }

function _cancelSingleImageLoader() {
            const pending = _pendingSingleImageLoader;
            if (!pending) return;
            _pendingSingleImageLoader = null;
            _disposeLightboxImageLoader(pending.entry);
        }

function _cancelPendingLightboxOpen() {
            const pending = _pendingLightboxOpen;
            if (!pending) return;
            _pendingLightboxOpen = null;
            const el = document.getElementById('lightbox-img');
            if (el) {
                el.onload = null;
                el.onerror = null;
                if (pending.visibleAssigned) el.src = '';
            }
            _disposeLightboxImageLoader(pending.entry);
        }

function _prefetchAdjacentImages(imageToken) {
            if (imageToken !== lightboxImageToken) return;
            const lb = document.getElementById('lightbox');
            if (!lb || !lb.classList.contains('active')) { _cleanupPrefetch(); return; }
            if (lightboxCompareMode) { _cleanupPrefetch(); return; }
            const lightboxImages = getLightboxImages();
            if (lightboxImages.length <= 1) { _cleanupPrefetch(); return; }
            const prevIdx = (currentIndex - 1 + lightboxImages.length) % lightboxImages.length;
            const nextIdx = (currentIndex + 1) % lightboxImages.length;
            const desired = new Set();
            const addDesired = function(idx) {
                const cand = lightboxImages[idx];
                if (!cand) return;
                if (cand.media_kind === 'video' || cand.media_kind === 'audio') return;
                const source = getImageBatchAndFolder(cand);
                desired.add(ccImageUrl(source.batch, source.folder, cand.name));
            };
            addDesired(prevIdx);
            if (nextIdx !== prevIdx) addDesired(nextIdx);
            for (const [url, entry] of _prefetchRegistry) {
                if (!desired.has(url)) {
                    _disposeLightboxImageLoader(entry);
                    _prefetchRegistry.delete(url);
                }
            }
            for (const url of desired) {
                if (_prefetchRegistry.has(url)) continue;
                const entry = _createLightboxImageLoader(url);
                _prefetchRegistry.set(url, entry);
                entry.ready.catch(function() {
                    if (_prefetchRegistry.get(url) === entry) {
                        _disposeLightboxImageLoader(entry);
                        _prefetchRegistry.delete(url);
                    }
                });
            }
        }

function _cleanupPrefetch() {
            for (const [, entry] of _prefetchRegistry) {
                _disposeLightboxImageLoader(entry);
            }
            _prefetchRegistry.clear();
        }
