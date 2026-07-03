/* Ordered classic script.
 * Defines: lightbox viewer, zoom, navigation, scored navigation, lightbox favorite UI.
 * Later-file globals called at runtime: loadLightboxMetadata, renderLightboxMetadataPanel, toggleLightboxMetadata from metadata.js.
 */
let lightboxZoom = 1;
let lightboxImageToken = 0;
let lightboxAiOpen = false;
let lightboxBaseWidth = 0;
let lightboxBaseHeight = 0;
let lightboxPanState = null;
let lightboxCompareMode = false;
let lightboxCompareItems = [];
let lightboxCompareActivePane = 0;
let lightboxCompareImageToken = 0;
let lightboxComparePanState = null;
let lightboxCompareViewState = [
    {zoom: 1, baseWidth: 0, baseHeight: 0},
    {zoom: 1, baseWidth: 0, baseHeight: 0},
];

function openLightbox(index) {
            lightboxCompareMode = false;
            lightboxCompareItems = [];
            currentIndex = index;
            document.getElementById('lightbox').classList.add('active');
            syncLightboxModeUi();
            resetLightboxZoom();
            showCurrentImage();
        }

function isLightboxCompareMode() {
            return lightboxCompareMode;
        }

function getSelectedImagesInDisplayOrder() {
            return getCurrentDisplayImages().filter(img => selectedImages.has(img.name));
        }

function openCompareLightbox() {
            const selected = getSelectedImagesInDisplayOrder();
            if (selected.length !== 2 || isVirtualCollectionView() || isPublicView()) {
                showToast('Select exactly two review images to compare');
                return;
            }
            lightboxCompareMode = true;
            lightboxCompareItems = selected;
            lightboxCompareActivePane = 0;
            lightboxCompareViewState = [
                {zoom: 1, baseWidth: 0, baseHeight: 0},
                {zoom: 1, baseWidth: 0, baseHeight: 0},
            ];
            lightboxMetadataOpen = false;
            lightboxAiOpen = false;
            document.getElementById('lightbox').classList.add('active');
            syncLightboxModeUi();
            showCompareImages();
            if (typeof syncLightboxPublicActions === 'function') syncLightboxPublicActions();
        }

function getLightboxImages() {
            return getCurrentDisplayImages();
        }

function closeLightbox() {
            document.getElementById('lightbox').classList.remove('active');
            resetLightboxZoom();
            resetCompareZoom();
            lightboxCompareMode = false;
            lightboxCompareItems = [];
            lightboxMetadataOpen = false;
            lightboxAiOpen = false;
            syncLightboxModeUi();
            renderLightboxMetadataPanel();
            renderLightboxAiPanel();
        }

function syncLightboxModeUi() {
            const lightbox = document.getElementById('lightbox');
            const singleWrap = document.getElementById('lightbox-image-wrap');
            const compare = document.getElementById('lightbox-compare');
            const singleIndicator = document.getElementById('lightbox-zoom-indicator');
            if (lightbox) lightbox.classList.toggle('compare-mode', lightboxCompareMode);
            if (singleWrap) singleWrap.hidden = lightboxCompareMode;
            if (compare) compare.hidden = !lightboxCompareMode;
            if (singleIndicator) singleIndicator.hidden = false;
            document.querySelectorAll('.lightbox-nav').forEach(nav => { nav.hidden = lightboxCompareMode; });
            ['metadata-toggle-btn', 'lightbox-ai-toggle-btn'].forEach(id => {
                const btn = document.getElementById(id);
                if (!btn) return;
                if (lightboxCompareMode) btn.disabled = true;
                else if (id === 'lightbox-ai-toggle-btn') btn.disabled = false;
            });
            document.querySelectorAll('#lightbox-actions button').forEach(btn => {
                const label = btn.textContent.trim();
                const singleOnly = label === 'Prev scored' || label === 'Next scored' || btn.id === 'metadata-toggle-btn' || btn.id === 'lightbox-ai-toggle-btn';
                const wrapper = btn.closest('div');
                if (wrapper && singleOnly) wrapper.style.display = lightboxCompareMode ? 'none' : '';
            });
            if (lightboxCompareMode) updateCompareZoomIndicator(lightboxCompareActivePane);
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

function zoomLightbox(delta, anchorEvent = null) {
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
                pane.classList.toggle('active', Number(pane.dataset.comparePane) === paneIndex);
            });
            const img = getActiveLightboxImage();
            if (img && typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);
            updateCompareZoomIndicator(paneIndex);
            updateCompareInfo();
        }

function getActiveComparePaneIndexFromEvent(event) {
            const pane = event.target.closest('.lightbox-compare-pane');
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
            requestAnimationFrame(() => {
                if (zoomToken !== lightboxCompareImageToken || state.zoom !== nextScale) return;
                wrap.scrollLeft = Math.max(0, (ratioX * img.offsetWidth) - viewportX);
                wrap.scrollTop = Math.max(0, (ratioY * img.offsetHeight) - viewportY);
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

function startLightboxPan(event) {
            if (lightboxCompareMode) {
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
                if (!lightboxComparePanState || event.pointerId !== lightboxComparePanState.pointerId) return;
                const {wrap} = getComparePaneElements(lightboxComparePanState.paneIndex);
                if (!wrap) return;
                wrap.scrollLeft = lightboxComparePanState.scrollLeft - (event.clientX - lightboxComparePanState.startX);
                wrap.scrollTop = lightboxComparePanState.scrollTop - (event.clientY - lightboxComparePanState.startY);
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
                .map((img, index) => ({img, index, score: aiGetImageScore(img.name)}))
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
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);
            const imageToken = ++lightboxImageToken;
            const metadataToken = ++lightboxMetadataRequestToken;
            currentLightboxMetadata = null;
            currentLightboxMetadataError = null;
            currentLightboxMetadataLoading = false;
            currentLightboxDimensions = {w: null, h: null};
            lightboxBaseWidth = 0;
            lightboxBaseHeight = 0;
            renderLightboxMetadataPanel();
            resetLightboxZoom();
            const el = document.getElementById('lightbox-img');
            el.draggable = false;
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
                captureLightboxBaseSize();
                updateLightboxInfo(img, this.naturalWidth, this.naturalHeight);
            };
            el.onerror = function() {
                el.classList.remove('loading');
                el.style.opacity = '';
            };
            // Use decode() when available to avoid flash of partially-decoded image
            const source = getImageBatchAndFolder(img);
            const newSrc = `/image/${encodeURIComponent(source.batch)}/${encodeURIComponent(source.folder)}/${encodeURIComponent(img.name)}`;
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
            renderLightboxAiPanel();
            if (typeof syncLightboxPublicActions === 'function') syncLightboxPublicActions();
        }

function toggleLightboxAiPanel() {
            if (lightboxCompareMode) return;
            lightboxAiOpen = !lightboxAiOpen;
            renderLightboxAiPanel();
        }

function renderLightboxAiPanel() {
            const panel = document.getElementById('lightbox-ai-panel');
            const btn = document.getElementById('lightbox-ai-toggle-btn');
            if (!panel) return;
            if (lightboxCompareMode) lightboxAiOpen = false;
            panel.classList.toggle('open', lightboxAiOpen);
            if (btn) btn.textContent = lightboxAiOpen ? 'Hide AI' : 'AI';
            panel.replaceChildren();
            if (!lightboxAiOpen) return;
            const img = getLightboxImages()[currentIndex];
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
            const token = ++lightboxCompareImageToken;
            syncLightboxModeUi();
            lightboxCompareItems.forEach((img, paneIndex) => {
                const {pane, wrap, img: imgEl, label} = getComparePaneElements(paneIndex);
                if (!imgEl || !img) return;
                if (pane) pane.classList.toggle('active', paneIndex === lightboxCompareActivePane);
                if (label) label.textContent = `${paneIndex === 0 ? 'Left' : 'Right'} · ${img.name}`;
                if (wrap) {
                    wrap.scrollTop = 0;
                    wrap.scrollLeft = 0;
                }
                lightboxCompareViewState[paneIndex] = {zoom: 1, baseWidth: 0, baseHeight: 0};
                imgEl.draggable = false;
                imgEl.style.opacity = '0';
                imgEl.classList.add('loading');
                imgEl.onload = function() {
                    if (token !== lightboxCompareImageToken) return;
                    imgEl.classList.remove('loading');
                    imgEl.style.opacity = '';
                    captureComparePaneBaseSize(paneIndex);
                    updateCompareInfo();
                };
                imgEl.onerror = function() {
                    imgEl.classList.remove('loading');
                    imgEl.style.opacity = '';
                };
                const source = getImageBatchAndFolder(img);
                imgEl.src = `/image/${encodeURIComponent(source.batch)}/${encodeURIComponent(source.folder)}/${encodeURIComponent(img.name)}`;
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
            let line1 = `${currentIndex+1} / ${getLightboxImages().length}  -  ${img.name}`;
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
            const index = getImageDisplayIndexByName(img.name);
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

function navigate(delta) {
            if (lightboxCompareMode) return;
            const lightboxImages = getLightboxImages();
            if (lightboxImages.length === 0) return;
            currentIndex = (currentIndex + delta + lightboxImages.length) % lightboxImages.length;
            showCurrentImage();
        }
