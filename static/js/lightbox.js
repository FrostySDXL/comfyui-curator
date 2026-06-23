/* Ordered classic script.
 * Defines: lightbox viewer, zoom, navigation, scored navigation, lightbox favorite UI.
 * Later-file globals called at runtime: loadLightboxMetadata, renderLightboxMetadataPanel, toggleLightboxMetadata from metadata.js.
 */
let lightboxZoom = 1;
let lightboxImageToken = 0;
let lightboxAiOpen = false;

function openLightbox(index) {
            currentIndex = index;
            document.getElementById('lightbox').classList.add('active');
            resetLightboxZoom();
            showCurrentImage();
        }

function closeLightbox() {
            document.getElementById('lightbox').classList.remove('active');
            resetLightboxZoom();
            lightboxMetadataOpen = false;
            lightboxAiOpen = false;
            renderLightboxMetadataPanel();
            renderLightboxAiPanel();
        }

function applyLightboxZoom() {
            const wrap = document.getElementById('lightbox-image-wrap');
            document.documentElement.style.setProperty('--lightbox-zoom', String(lightboxZoom));
            if (wrap) wrap.classList.toggle('zoomed', lightboxZoom > 1.001);
        }

function zoomLightbox(delta) {
            const currentScale = lightboxZoom;
            const nextScale = Math.min(3, Math.max(0.6, +(currentScale + delta).toFixed(2)));
            if (nextScale === currentScale) return;
            lightboxZoom = nextScale;
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
            if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);
            const imageToken = ++lightboxImageToken;
            const metadataToken = ++lightboxMetadataRequestToken;
            currentLightboxMetadata = null;
            currentLightboxMetadataError = null;
            currentLightboxMetadataLoading = false;
            currentLightboxDimensions = {w: null, h: null};
            renderLightboxMetadataPanel();
            resetLightboxZoom();
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
            lightboxAiOpen = !lightboxAiOpen;
            renderLightboxAiPanel();
        }

function renderLightboxAiPanel() {
            const panel = document.getElementById('lightbox-ai-panel');
            const btn = document.getElementById('lightbox-ai-toggle-btn');
            if (!panel) return;
            panel.classList.toggle('open', lightboxAiOpen);
            if (btn) btn.textContent = lightboxAiOpen ? 'Hide AI' : 'AI';
            panel.replaceChildren();
            if (!lightboxAiOpen) return;
            const img = images[currentIndex];
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

function updateLightboxInfo(img, w, h) {
            const infoEl = document.getElementById('lightbox-info');
            infoEl.replaceChildren();
            let line1 = `${currentIndex+1} / ${images.length}  -  ${img.name}`;
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
            const img = images[currentIndex];
            if (!img) return;
            await toggleFavorite(currentIndex);
        }

function updateLightboxFavorite(img) {
            const star = document.querySelector('.lightbox-favorite-star');
            if (!star || !img) return;
            star.textContent = img.favorite ? '\u2605' : '\u2606';
            star.style.color = img.favorite ? '#e8c84a' : '';
            star.title = img.favorite ? 'Remove favorite' : 'Add favorite';
        }

function navigate(delta) {
            if (images.length === 0) return;
            currentIndex = (currentIndex + delta + images.length) % images.length;
            showCurrentImage();
        }
