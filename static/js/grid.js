/* Ordered classic script.
 * Defines: metadata-aware LRU thumbnail cache with scope/priority eviction,
 *          image loading, sort controls, display filtering, grid rendering.
 * Later-file globals called at runtime: aiGetImageScore, aiShouldShowImage, aiSortImages, aiScoreGradient.
 */

        /* ── Stage 2 cache metadata ──────────────────────────────────────
         * _thumbnailMetadata: Map<cacheKey, {priority, scopeBatch, _lruTouch}>
         *   - priority: strongest observed request priority (0=visible, 1=near, 2=deferred)
         *   - scopeBatch: real source batch for scope-aware eviction
         *   - _lruTouch: monotonic recency counter; higher = more recently used
         * _lruTouchNext: monotonic counter incremented on every touch
         * _inflightMetadataPriority: Map<cacheKey, meta> for metadata aggregation
         *   during inflight fetch dedup; taken when fetch completes
         * _realBatchCurrent / _realBatchPrev: tracked by _updateRealBatchTracking()
         */
        const _thumbnailMetadata = new Map();
        const _inflightMetadataPriority = new Map();
        let _lruTouchNext = 0;
        let _realBatchCurrent = null;
        let _realBatchPrev = null;

        function _touchCacheEntry(cacheKey) {
            const meta = _thumbnailMetadata.get(cacheKey);
            if (meta) {
                meta._lruTouch = ++_lruTouchNext;
            }
        }

        function _updateCacheMetadata(cacheKey, meta) {
            /* Creates or promotes metadata (priority, scope).
               Bumps LRU recency only when the entry is first created.
               _touchCacheEntry is the sole LRU touch point for cache reuse. */
            if (!meta) return;
            let existing = _thumbnailMetadata.get(cacheKey);
            if (!existing) {
                _thumbnailMetadata.set(cacheKey, { priority: 2, scopeBatch: null, _lruTouch: ++_lruTouchNext });
                existing = _thumbnailMetadata.get(cacheKey);
            }
            /* Monotonic priority promotion: visible(0) > near(1) > deferred(2).
               Lower numeric value is stronger. Only promote, never demote. */
            if (typeof meta.priority === 'number' && meta.priority < existing.priority) {
                existing.priority = meta.priority;
            }
            /* Scope batch: always overwrite with the latest (real source batch or
               the newly resolved scope). Virtual views resolve the real batch
               from the image record before calling this. */
            if (meta.scopeBatch !== undefined && meta.scopeBatch !== null) {
                existing.scopeBatch = meta.scopeBatch;
            }
        }

        function _getScopeClass(scopeBatch) {
            if (!scopeBatch) return 0; /* unknown scope = weakest */
            if (_realBatchCurrent === scopeBatch) return 2;
            if (_realBatchPrev === scopeBatch) return 1;
            return 0; /* other batch */
        }

        function _getPriorityClass(priority) {
            /* Lower numeric priority = stronger. Invert for protection score:
               visible(0)->2, near(1)->1, deferred(2)->0 */
            if (typeof priority !== 'number') return 0;
            if (priority <= 0) return 2;
            if (priority === 1) return 1;
            return 0;
        }

        function _evictIfNeeded() {
            while (thumbnailBlobUrlCache.size > THUMBNAIL_BLOB_CACHE_MAX) {
                let weakestKey = null;
                let weakestScopeProtection = Infinity;
                let weakestPriorityProtection = Infinity;
                let weakestLruTouch = Infinity;

                for (const [key, blobUrl] of thumbnailBlobUrlCache) {
                    const meta = _thumbnailMetadata.get(key);
                    const scopeClass = _getScopeClass(meta ? meta.scopeBatch : null);
                    const priorityClass = _getPriorityClass(meta ? meta.priority : undefined);
                    const lruTouch = meta ? meta._lruTouch : 0;

                    /* Eviction ranking (lower = evict first):
                       1. scopeClass (0=other, 1=previous, 2=current)
                       2. priorityClass (0=deferred, 1=near, 2=visible)
                       3. lruTouch (lower = older = evict first)
                    */
                    if (scopeClass < weakestScopeProtection ||
                        (scopeClass === weakestScopeProtection && priorityClass < weakestPriorityProtection) ||
                        (scopeClass === weakestScopeProtection && priorityClass === weakestPriorityProtection && lruTouch < weakestLruTouch)) {
                        weakestKey = key;
                        weakestScopeProtection = scopeClass;
                        weakestPriorityProtection = priorityClass;
                        weakestLruTouch = lruTouch;
                    }
                }

                if (weakestKey) {
                    const evictedUrl = thumbnailBlobUrlCache.get(weakestKey);
                    if (evictedUrl) URL.revokeObjectURL(evictedUrl);
                    thumbnailBlobUrlCache.delete(weakestKey);
                    _thumbnailMetadata.delete(weakestKey);
                } else {
                    /* Safety: fallback FIFO if no metadata */
                    const oldestKey = thumbnailBlobUrlCache.keys().next().value;
                    const oldestUrl = thumbnailBlobUrlCache.get(oldestKey);
                    if (oldestUrl) URL.revokeObjectURL(oldestUrl);
                    thumbnailBlobUrlCache.delete(oldestKey);
                    _thumbnailMetadata.delete(oldestKey);
                }
            }
        }

        function _mergeInflightMetadata(cacheKey, meta) {
            if (!meta || !cacheKey) return;
            let existing = _inflightMetadataPriority.get(cacheKey);
            if (!existing) {
                existing = { priority: 2, scopeBatch: null };
                _inflightMetadataPriority.set(cacheKey, existing);
            }
            /* Promote priority (lower is stronger) */
            if (typeof meta.priority === 'number' && meta.priority < existing.priority) {
                existing.priority = meta.priority;
            }
            /* Overwrite scopeBatch with the latest */
            if (meta.scopeBatch !== undefined && meta.scopeBatch !== null) {
                existing.scopeBatch = meta.scopeBatch;
            }
        }

        function _takeInflightMetadata(cacheKey) {
            const meta = _inflightMetadataPriority.get(cacheKey);
            _inflightMetadataPriority.delete(cacheKey);
            return meta || null;
        }

        function _updateRealBatchTracking(newBatch) {
            /* Accept only non-empty string batch names. Reject null, undefined,
               empty strings, numbers, objects, and virtual sentinels. */
            if (typeof newBatch !== 'string' || newBatch === '' ||
                newBatch === '__favorites__' || newBatch === '__public__') {
                return;
            }
            /* Same batch: no rotation */
            if (_realBatchCurrent === newBatch) {
                return;
            }
            _realBatchPrev = _realBatchCurrent;
            _realBatchCurrent = newBatch;
        }

        function _resolveSourceBatch(img) {
            /* For virtual views, extract real batch from image record.
               For real batch views, use currentBatch. */
            if (typeof isVirtualCollectionView === 'function' && isVirtualCollectionView()) {
                return img && img.batch ? img.batch : null;
            }
            return currentBatch || null;
        }
        function getThumbnailCacheKey(imageSrc, img) {
            return `${imageSrc}|${img.size || 0}`;
        }

        function rememberThumbnailBlobUrl(cacheKey, blobUrl, meta) {
            const existing = thumbnailBlobUrlCache.get(cacheKey);
            if (existing && existing !== blobUrl) URL.revokeObjectURL(existing);
            thumbnailBlobUrlCache.set(cacheKey, blobUrl);
            if (meta) _updateCacheMetadata(cacheKey, meta);
            _evictIfNeeded();
        }

        async function resolveThumbnailBlobUrl(imageSrc, cacheKey, meta) {
            const cachedBlobUrl = thumbnailBlobUrlCache.get(cacheKey);
            if (cachedBlobUrl) {
                if (meta) _updateCacheMetadata(cacheKey, meta);
                _touchCacheEntry(cacheKey);
                return cachedBlobUrl;
            }

            if (thumbnailBlobInflight.has(cacheKey)) {
                if (meta) _mergeInflightMetadata(cacheKey, meta);
                return thumbnailBlobInflight.get(cacheKey);
            }

            if (meta) _mergeInflightMetadata(cacheKey, meta);

            const request = fetch(imageSrc, {cache: 'force-cache'})
                .then(resp => {
                    if (!resp.ok) throw new Error(`thumbnail request failed (${resp.status})`);
                    return resp.blob();
                })
                .then(blob => {
                    const blobUrl = URL.createObjectURL(blob);
                    const mergedMeta = _takeInflightMetadata(cacheKey);
                    rememberThumbnailBlobUrl(cacheKey, blobUrl, mergedMeta);
                    return blobUrl;
                })
                .catch(error => {
                    console.warn(`Thumbnail blob cache fallback for ${imageSrc}:`, error);
                    _takeInflightMetadata(cacheKey);
                    return imageSrc;
                })
                .finally(() => {
                    thumbnailBlobInflight.delete(cacheKey);
                });
            thumbnailBlobInflight.set(cacheKey, request);
            return request;
        }

        function assignThumbnailSrcIfCached(imageEl, imageSrc, cacheKey, meta) {
            imageEl.dataset.thumbnailCacheKey = cacheKey;
            const cached = thumbnailBlobUrlCache.get(cacheKey);
            if (cached) {
                if (imageEl.getAttribute('src') !== cached) {
                    imageEl.setAttribute('src', cached);
                }
                if (meta) _updateCacheMetadata(cacheKey, meta);
                _touchCacheEntry(cacheKey);
                return true;
            }
            return false;
        }

        function setThumbnailImageSrc(imageEl, imageSrc, cacheKey, meta) {
            if (assignThumbnailSrcIfCached(imageEl, imageSrc, cacheKey, meta)) {
                return Promise.resolve();
            }
            return resolveThumbnailBlobUrl(imageSrc, cacheKey, meta).then(resolvedSrc => {
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
            _thumbnailMetadata.clear();
            _inflightMetadataPriority.clear();
        });

async function loadCurrentFolderImages() {
            if (!currentBatch || !currentFolder) return;
            const requestToken = ++folderRequestToken;
            const batch = currentBatch;
            const folder = currentFolder;
            if (currentFolder === 'public') { await loadBatchPublic(batch); return; }
            const resp = await fetch(ccApiPath(`/api/images/${batch}/${folder}?sort=${currentSort}&order=${currentOrder}`));
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
            if (isVirtualCollectionView() || isPublicView()) { updateGrid(); return; }
            if (currentBatch && currentFolder) loadCurrentFolderImages();
        }

function toggleOrder() {
            currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
            document.getElementById('sort-dir-btn').classList.toggle('asc', currentOrder === 'asc');
            if (isVirtualCollectionView() || isPublicView()) { updateGrid(); return; }
            if (currentBatch && currentFolder) loadCurrentFolderImages();
        }

function normalizeGridDensity(density) {
            return ['compact', 'comfortable', 'large'].includes(density) ? density : 'comfortable';
        }

function getGridDensityConfig(density = gridDensity) {
            if (density === 'compact') return {track: 138, gap: 7};
            if (density === 'large') return {track: 250, gap: 16};
            return {track: 180, gap: 12};
        }

function updateGridShellLayout() {
            const content = document.querySelector('.content');
            const shell = document.getElementById('grid-shell');
            const grid = document.getElementById('grid');
            if (!content || !shell || !grid) return;
            if (grid.classList.contains('is-empty')) {
                grid.style.removeProperty('--grid-columns');
                return;
            }

            const {track, gap} = getGridDensityConfig();
            const displayCount = getDisplayImages().length || grid.querySelectorAll('.thumb.loading-placeholder').length;
            if (displayCount <= 0) {
                grid.style.removeProperty('--grid-columns');
                return;
            }

            const styles = window.getComputedStyle(content);
            const paddingLeft = parseFloat(styles.paddingLeft) || 0;
            const paddingRight = parseFloat(styles.paddingRight) || 0;
            const availableWidth = Math.max(0, content.clientWidth - paddingLeft - paddingRight);
            const fittedColumns = Math.max(1, Math.floor((availableWidth + gap) / (track + gap)));
            const usedColumns = Math.max(1, Math.min(fittedColumns, displayCount));
            grid.style.setProperty('--grid-columns', String(usedColumns));
        }

function initializeGridShellLayout() {
            const content = document.querySelector('.content');
            if (!content) return;
            if (!window._gridShellResizeObserver && window.ResizeObserver) {
                window._gridShellResizeObserver = new ResizeObserver(() => updateGridShellLayout());
                window._gridShellResizeObserver.observe(content);
            } else if (!window._gridShellResizeBound) {
                window.addEventListener('resize', updateGridShellLayout);
                window._gridShellResizeBound = true;
            }
            updateGridShellLayout();
        }

function setGridDensity(density) {
            gridDensity = normalizeGridDensity(density);
            const grid = document.getElementById('grid');
            if (grid) {
                grid.classList.remove('density-compact', 'density-comfortable', 'density-large');
                grid.classList.add(`density-${gridDensity}`);
            }
            updateGridShellLayout();
            document.querySelectorAll('.density-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.density === gridDensity);
                btn.setAttribute('aria-pressed', btn.dataset.density === gridDensity ? 'true' : 'false');
            });
            localStorage.setItem(GRID_DENSITY_KEY, gridDensity);
        }

function initializeGridDensity() {
            initializeGridShellLayout();
            setGridDensity(gridDensity);
        }

function sortImagesForDisplay(imgList) {
            if (aiActiveRun && currentSort === 'score-desc') return aiSortImages(imgList);
            if (!isVirtualCollectionView() && !isPublicView()) return imgList;
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

function getCurrentDisplayImages() {
            return currentDisplayImages.length > 0 ? currentDisplayImages : getDisplayImages();
        }

function getImageDisplayIndexByName(name) {
            return getCurrentDisplayImages().findIndex(img => img.name === name);
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
            if (currentBatch === '__public__') {
                return {
                    title: 'No generated public copies',
                    detail: 'Public copies appear here after you prepare selected originals from a batch.',
                };
            }
            if (currentFolder === 'public') {
                return {
                    title: 'No public copies yet',
                    detail: 'Select images from inbox, shortlisted, or finals, then choose Prepare Public Copies.',
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
            return isVirtualCollectionView()
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

            const select = document.createElement('button');
            select.type = 'button';
            select.className = 'thumb-select';
            select.setAttribute('aria-pressed', 'false');
            select.innerHTML = `
                <svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            `;
            select.addEventListener('click', (event) => {
                event.stopPropagation();
                setSelectionMode(true);
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
            const imageSrc = ccThumbUrl(source.batch, source.folder, img.name);
            const thumbnailCacheKey = getThumbnailCacheKey(imageSrc, img);

            thumb.dataset.name = img.name;
            thumb.dataset.index = String(index);
            thumb.classList.toggle('selected', selectedImages.has(img.name));
            thumb.classList.toggle('inspected', typeof aiInspectedImageName !== 'undefined' && aiInspectedImageName === img.name);
            thumb.classList.toggle('ai-filtered-out', !shouldShow);
            thumb.classList.remove('removing');
            if (selectBtn) {
                const isSelected = selectedImages.has(img.name);
                selectBtn.classList.toggle('selected', isSelected);
                selectBtn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
                selectBtn.setAttribute('aria-label', `${isSelected ? 'Deselect' : 'Select'} ${img.name}`);
            }
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
                imageEl.dataset.thumbnailCacheKey = thumbnailCacheKey;
                /* Stage 2: pass resolved source batch for scope-aware eviction.
                   Priority starts deferred; observers promote it in the viewport loader. */
                scheduleThumbnailLoad(thumb, imageSrc, thumbnailCacheKey, 2 /* DEFERRED */, _resolveSourceBatch(img));
            }
            if (metaName) metaName.textContent = img.name;
            if (metaSize) metaSize.textContent = isVirtualCollectionView()
                ? `${img.folder || 'folder'} · ${formatSize(img.size)}`
                : formatSize(img.size);
            const metaBatch = thumb.querySelector('.meta-batch');
            if (isVirtualCollectionView()) {
                if (metaBatch) {
                    metaBatch.textContent = img.batch || '';
                    metaBatch.classList.remove('hidden');
                }
            } else if (metaBatch) {
                metaBatch.classList.add('hidden');
            }
        }

function showGridLoadingPlaceholders(batch, folder) {
            cancelScheduledViewportLoads();
            const grid = document.getElementById('grid');
            const expectedCount = allCounts[batch]?.[folder] || 0;
            gridThumbMap.clear();
            if (expectedCount <= 0) {
                grid.replaceChildren();
                updateGridShellLayout();
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
            grid.classList.remove('is-empty');
            updateGridShellLayout();
        }

function updateGrid() {
            const grid = document.getElementById('grid');
            const displayImages = getDisplayImages();
            currentDisplayImages = displayImages;

            if (images.length === 0 || displayImages.length === 0) {
                cancelScheduledViewportLoads();
                grid.classList.add('is-empty');
                grid.replaceChildren(createGridEmptyState(getGridEmptyStateMessage()));
                gridThumbMap.clear();
                updateGridShellLayout();
                return;
            }
            grid.classList.remove('is-empty');

            const activeNames = new Set(displayImages.map(img => img.name));
            for (const [name, element] of gridThumbMap.entries()) {
                if (!activeNames.has(name)) {
                    unscheduleThumbnailLoad(element);
                    element.remove();
                    gridThumbMap.delete(name);
                }
            }

            const fragment = document.createDocumentFragment();
            displayImages.forEach((img) => {
                const displayIndex = getImageDisplayIndexByName(img.name);
                let thumb = gridThumbMap.get(img.name);
                if (!thumb) {
                    thumb = createThumbElement();
                    gridThumbMap.set(img.name, thumb);
                }
                updateThumbElement(thumb, img, displayIndex);
                fragment.appendChild(thumb);
            });

            // Skip the replaceChildren() cycle when the live grid already
            // holds the desired children in the desired order. This avoids
            // a layout-thrashing detach/reattach on every poll tick, even
            // when the visible set is unchanged. The fragment appendChild
            // path above still guarantees correct ordering whenever the
            // display set actually changed.
            if (_gridChildrenMatchDesiredOrder(grid, displayImages)) {
                updateGridShellLayout();
                return;
            }
            // Replace all children atomically to prevent visible empty-grid flash
            grid.replaceChildren(fragment);
            updateGridShellLayout();
        }

function _gridChildrenMatchDesiredOrder(grid, displayImages) {
            const live = grid.children;
            if (live.length !== displayImages.length) return false;
            for (let i = 0; i < displayImages.length; i++) {
                if (live[i] !== gridThumbMap.get(displayImages[i].name)) return false;
            }
            return true;
        }
