/* Ordered classic script.
 * Defines: thumbnail cache, image loading, sort controls, display filtering, grid rendering.
 * Later-file globals called at runtime: aiGetImageScore, aiShouldShowImage, aiSortImages, aiScoreGradient.
 */
        function getThumbnailCacheKey(imageSrc, img) {
            return `${imageSrc}|${img.size || 0}`;
        }

        function rememberThumbnailBlobUrl(cacheKey, blobUrl) {
            const existing = thumbnailBlobUrlCache.get(cacheKey);
            if (existing && existing !== blobUrl) URL.revokeObjectURL(existing);
            thumbnailBlobUrlCache.set(cacheKey, blobUrl);
            while (thumbnailBlobUrlCache.size > THUMBNAIL_BLOB_CACHE_MAX) {
                const oldestKey = thumbnailBlobUrlCache.keys().next().value;
                const oldestBlobUrl = thumbnailBlobUrlCache.get(oldestKey);
                if (oldestBlobUrl) URL.revokeObjectURL(oldestBlobUrl);
                thumbnailBlobUrlCache.delete(oldestKey);
            }
        }

        async function resolveThumbnailBlobUrl(imageSrc, cacheKey) {
            const cachedBlobUrl = thumbnailBlobUrlCache.get(cacheKey);
            if (cachedBlobUrl) return cachedBlobUrl;

            if (thumbnailBlobInflight.has(cacheKey)) return thumbnailBlobInflight.get(cacheKey);

            const request = fetch(imageSrc, {cache: 'force-cache'})
                .then(resp => {
                    if (!resp.ok) throw new Error(`thumbnail request failed (${resp.status})`);
                    return resp.blob();
                })
                .then(blob => {
                    const blobUrl = URL.createObjectURL(blob);
                    rememberThumbnailBlobUrl(cacheKey, blobUrl);
                    return blobUrl;
                })
                .catch(error => {
                    console.warn(`Thumbnail blob cache fallback for ${imageSrc}:`, error);
                    return imageSrc;
                })
                .finally(() => {
                    thumbnailBlobInflight.delete(cacheKey);
                });
            thumbnailBlobInflight.set(cacheKey, request);
            return request;
        }

        function setThumbnailImageSrc(imageEl, imageSrc, cacheKey) {
            imageEl.dataset.thumbnailCacheKey = cacheKey;
            resolveThumbnailBlobUrl(imageSrc, cacheKey).then(resolvedSrc => {
                if (imageEl.dataset.thumbnailCacheKey !== cacheKey) return;
                if (imageEl.getAttribute('src') !== resolvedSrc) {
                    imageEl.setAttribute('src', resolvedSrc);
                }
            });
        }

        window.addEventListener('beforeunload', () => {
            for (const blobUrl of thumbnailBlobUrlCache.values()) URL.revokeObjectURL(blobUrl);
            thumbnailBlobUrlCache.clear();
            thumbnailBlobInflight.clear();
        });

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
            updateImageCountLabel();
            updateGrid();
        }

function setSort(sort) {
            currentSort = sort;
            document.querySelectorAll('.sort-btn:not(.batch-sort-btn)').forEach(b => b.classList.toggle('active', b.dataset.sort === sort));
            document.getElementById('sort-dir-btn').classList.toggle('is-placeholder', sort === 'shuffle' || sort === 'score-desc');
            if (currentBatch === '__favorites__') { updateGrid(); return; }
            if (currentBatch && currentFolder) loadCurrentFolderImages();
        }

function toggleOrder() {
            currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
            document.getElementById('sort-dir-btn').classList.toggle('asc', currentOrder === 'asc');
            if (currentBatch === '__favorites__') { updateGrid(); return; }
            if (currentBatch && currentFolder) loadCurrentFolderImages();
        }

function normalizeGridDensity(density) {
            return ['compact', 'comfortable', 'large'].includes(density) ? density : 'comfortable';
        }

function setGridDensity(density) {
            gridDensity = normalizeGridDensity(density);
            const grid = document.getElementById('grid');
            if (grid) {
                grid.classList.remove('density-compact', 'density-comfortable', 'density-large');
                grid.classList.add(`density-${gridDensity}`);
            }
            document.querySelectorAll('.density-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.density === gridDensity);
            });
            localStorage.setItem(GRID_DENSITY_KEY, gridDensity);
        }

function initializeGridDensity() {
            setGridDensity(gridDensity);
        }

function sortImagesForDisplay(imgList) {
            if (aiActiveRun && currentSort === 'score-desc') return aiSortImages(imgList);
            if (currentBatch !== '__favorites__') return imgList;
            if (currentSort === 'shuffle') return [...imgList].sort(() => Math.random() - 0.5);
            const direction = currentOrder === 'asc' ? 1 : -1;
            if (currentSort === 'date') {
                return [...imgList].sort((a, b) => {
                    const dateA = Number(a.modified_at || a.mtime || a.created_at || 0);
                    const dateB = Number(b.modified_at || b.mtime || b.created_at || 0);
                    if (dateA !== dateB) return (dateA - dateB) * direction;
                    return String(a.name || '').localeCompare(String(b.name || '')) * direction;
                });
            }
            return [...imgList].sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')) * direction);
        }

function getDisplayImages() {
            const filtered = favoritesFilterOn ? images.filter(img => img.favorite === true) : images;
            return sortImagesForDisplay(filtered);
        }

function getGridEmptyStateMessage() {
            if (favoritesFilterOn && images.length > 0) {
                return {
                    title: 'No favorite images in this view',
                    detail: 'Toggle favorites-only off or star images to build a focused review set.',
                };
            }
            if (aiActiveRun && aiShowOverlays && aiFilterMode !== 'all' && images.length > 0) {
                return {
                    title: 'No images match the active AI filter',
                    detail: 'Change the AI filter or turn AI badges off to return to the full folder.',
                };
            }
            return {
                title: 'No images in this folder',
                detail: currentBatch ? 'Move or import images into this folder to continue reviewing.' : 'Select a batch from the sidebar.',
            };
        }

function createGridEmptyState(message) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            const title = document.createElement('div');
            title.className = 'empty-title';
            title.textContent = message.title;
            const detail = document.createElement('div');
            detail.className = 'empty-detail';
            detail.textContent = message.detail;
            empty.append(title, detail);
            return empty;
        }

function updateImageCountLabel() {
            const countEl = document.getElementById('img-count');
            if (!countEl) return;
            const displayCount = getDisplayImages().length;
            if (images.length === 0) countEl.textContent = '';
            else if (favoritesFilterOn && displayCount !== images.length) countEl.textContent = ` (${displayCount} of ${images.length})`;
            else countEl.textContent = ` (${images.length})`;
        }

function getImageBatchAndFolder(img) {
            return currentBatch === '__favorites__'
                ? {batch: img.batch, folder: img.folder}
                : {batch: currentBatch, folder: currentFolder};
        }

function getImageIndexByName(name) {
            return images.findIndex(img => img.name === name);
        }

function createThumbElement() {
            const thumb = document.createElement('div');
            thumb.className = 'thumb';
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

            const favStar = document.createElement('span');
            favStar.className = 'favorite-star';
            favStar.setAttribute('role', 'button');
            favStar.tabIndex = 0;
            favStar.addEventListener('click', (event) => {
                event.stopPropagation();
                toggleFavorite(Number(thumb.dataset.index));
            });

            const img = document.createElement('img');
            img.draggable = false;
            img.addEventListener('load', () => requestAnimationFrame(() => img.classList.add('loaded')));
            img.addEventListener('error', () => requestAnimationFrame(() => img.classList.add('loaded')));

            const metaBatch = document.createElement('span');
            metaBatch.className = 'meta-batch hidden';

            const meta = document.createElement('div');
            meta.className = 'thumb-meta';
            meta.innerHTML = '<span class="meta-name"></span><span class="meta-detail"></span>';

            thumb.append(badge, select, favStar, img, metaBatch, meta);
            return thumb;
        }

function updateThumbElement(thumb, img, index) {
            const scoreResult = aiGetImageScore ? aiGetImageScore(img.name) : null;
            const shouldShow = aiShouldShowImage ? aiShouldShowImage(img) : true;
            const badge = thumb.querySelector('.ai-score-badge');
            const selectBtn = thumb.querySelector('.thumb-select');
            const imageEl = thumb.querySelector('img');
            const metaName = thumb.querySelector('.meta-name');
            const metaSize = thumb.querySelector('.meta-detail');
            const favStar = thumb.querySelector('.favorite-star');
            const source = getImageBatchAndFolder(img);
            const imageSrc = `/thumb/${encodeURIComponent(source.batch)}/${encodeURIComponent(source.folder)}/${encodeURIComponent(img.name)}`;
            const thumbnailCacheKey = getThumbnailCacheKey(imageSrc, img);

            thumb.dataset.name = img.name;
            thumb.dataset.index = String(index);
            thumb.classList.toggle('selected', selectedImages.has(img.name));
            thumb.classList.toggle('inspected', typeof aiInspectedImageName !== 'undefined' && aiInspectedImageName === img.name);
            thumb.classList.toggle('ai-filtered-out', !shouldShow);
            thumb.classList.remove('removing');
            if (selectBtn) selectBtn.classList.toggle('selected', selectedImages.has(img.name));
            if (favStar) {
                const isFav = img.favorite === true;
                favStar.classList.toggle('active', isFav);
                favStar.title = isFav ? 'Remove favorite' : 'Add favorite';
                favStar.setAttribute('aria-label', favStar.title);
            }

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

            if (imageEl && imageEl.dataset.thumbnailCacheKey !== thumbnailCacheKey) {
                imageEl.classList.remove('loaded');
                setThumbnailImageSrc(imageEl, imageSrc, getThumbnailCacheKey(imageSrc, img));
            }
            if (metaName) metaName.textContent = img.name;
            if (metaSize) metaSize.textContent = currentBatch === '__favorites__'
                ? `${img.folder || 'folder'} · ${formatSize(img.size)}`
                : formatSize(img.size);
            const metaBatch = thumb.querySelector('.meta-batch');
            if (currentBatch === '__favorites__') {
                if (metaBatch) {
                    metaBatch.textContent = img.batch || '';
                    metaBatch.classList.remove('hidden');
                }
            } else if (metaBatch) {
                metaBatch.classList.add('hidden');
            }
        }

function showGridLoadingPlaceholders(batch, folder) {
            const grid = document.getElementById('grid');
            const expectedCount = allCounts[batch]?.[folder] || 0;
            gridThumbMap.clear();
            if (expectedCount <= 0) {
                grid.replaceChildren();
                return;
            }

            const fragment = document.createDocumentFragment();
            const placeholderCount = Math.min(expectedCount, MAX_GRID_LOADING_PLACEHOLDERS);
            for (let index = 0; index < placeholderCount; index++) {
                const thumb = document.createElement('div');
                thumb.className = 'thumb loading-placeholder';
                thumb.setAttribute('aria-hidden', 'true');
                fragment.appendChild(thumb);
            }
            grid.replaceChildren(fragment);
        }

function updateGrid() {
            const grid = document.getElementById('grid');
            const displayImages = getDisplayImages();

            if (images.length === 0 || displayImages.length === 0) {
                grid.classList.add('is-empty');
                grid.replaceChildren(createGridEmptyState(getGridEmptyStateMessage()));
                gridThumbMap.clear();
                return;
            }
            grid.classList.remove('is-empty');

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

            // Skip the replaceChildren() cycle when the live grid already
            // holds the desired children in the desired order. This avoids
            // a layout-thrashing detach/reattach on every poll tick, even
            // when the visible set is unchanged. The fragment appendChild
            // path above still guarantees correct ordering whenever the
            // display set actually changed.
            if (_gridChildrenMatchDesiredOrder(grid, displayImages)) {
                return;
            }
            // Replace all children atomically to prevent visible empty-grid flash
            grid.replaceChildren(fragment);
        }

function _gridChildrenMatchDesiredOrder(grid, displayImages) {
            const live = grid.children;
            if (live.length !== displayImages.length) return false;
            for (let i = 0; i < displayImages.length; i++) {
                if (live[i] !== gridThumbMap.get(displayImages[i].name)) return false;
            }
            return true;
        }
