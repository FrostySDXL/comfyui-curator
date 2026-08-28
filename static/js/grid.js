/* Ordered classic script.
 * Defines: metadata-aware LRU thumbnail cache with scope/priority eviction,
 *          image loading, sort controls, display filtering, grid rendering.
 * Later-file globals called at runtime: aiGetImageScore, aiShouldShowImage, aiSortImages, aiScoreGradient.
 */

        const VIRTUAL_GRID_MAX_THUMBNAILS = 500;
        const VIRTUAL_GRID_OVERSCAN_ROWS = 2;
        const gridThumbPool = [];
        let _progressiveGridRenderLimit = VIRTUAL_GRID_MAX_THUMBNAILS;
        let _progressiveGridGrowthRafId = null;
        let _progressiveGridResizeTimerId = null;
        let _progressiveGridScrollBound = false;
        let _virtualGridFastScrolling = false;
        let _virtualGridScrollIdleTimerId = null;
        let _progressiveGridGeneration = 0;
        let _progressiveGridContextKey = null;
        const virtualShuffleRanks = new Map();

        function getProgressiveGridState() {
            return {
                renderedCount: gridThumbMap.size,
                renderLimit: _progressiveGridRenderLimit,
                context: _progressiveGridContextKey,
                windowStart: _virtualGridWindowStart,
                windowEnd: _virtualGridWindowEnd,
            };
        }

        let _virtualGridWindowStart = 0;
        let _virtualGridWindowEnd = 0;

        function _getProgressiveGridContextKey() {
            return JSON.stringify([
                currentBatch,
                currentFolder,
                favoritesFilterOn,
                currentSort,
                currentOrder,
                currentSort === 'shuffle' ? folderShuffleSeed : '',
                typeof workspaceSearchFilter !== 'undefined' ? (workspaceSearchFilter?.key || '') : '',
            ]);
        }

        function _cancelProgressiveGridGrowthCheck() {
            if (_progressiveGridGrowthRafId !== null) {
                cancelAnimationFrame(_progressiveGridGrowthRafId);
                _progressiveGridGrowthRafId = null;
            }
        }

        function _resetProgressiveGridContext(contextKey) {
            _progressiveGridGeneration += 1;
            _cancelProgressiveGridGrowthCheck();
            _progressiveGridRenderLimit = VIRTUAL_GRID_MAX_THUMBNAILS;
            _progressiveGridContextKey = contextKey;
            const content = document.querySelector('.content');
            if (content) content.scrollTop = 0;
        }

        function _resetProgressiveGridLifecycle() {
            _progressiveGridGeneration += 1;
            _cancelProgressiveGridGrowthCheck();
            cancelScheduledViewportLoads();
            for (const element of gridThumbMap.values()) unscheduleThumbnailLoad(element);
            _progressiveGridRenderLimit = VIRTUAL_GRID_MAX_THUMBNAILS;
            _progressiveGridContextKey = null;
            currentDisplayImages = [];
            const content = document.querySelector('.content');
            if (content) content.scrollTop = 0;
        }

        function _scheduleProgressiveGridGrowthCheck() {
            if (_progressiveGridGrowthRafId !== null) return;
            const generation = _progressiveGridGeneration;
            _progressiveGridGrowthRafId = requestAnimationFrame(() => {
                _progressiveGridGrowthRafId = null;
                if (generation !== _progressiveGridGeneration) return;
                updateGrid();
            });
        }

        function _scheduleProgressiveGridResizeCheck() {
            if (_progressiveGridResizeTimerId !== null) clearTimeout(_progressiveGridResizeTimerId);
            const generation = _progressiveGridGeneration;
            _progressiveGridResizeTimerId = setTimeout(() => {
                _progressiveGridResizeTimerId = null;
                if (generation !== _progressiveGridGeneration) return;
                _scheduleProgressiveGridGrowthCheck();
            }, 100);
        }

        function _bindProgressiveGridScrollGrowth(content) {
            if (_progressiveGridScrollBound) return;
            const settleVirtualScroll = () => {
                if (_virtualGridScrollIdleTimerId !== null) {
                    clearTimeout(_virtualGridScrollIdleTimerId);
                    _virtualGridScrollIdleTimerId = null;
                }
                _virtualGridFastScrolling = false;
                updateGrid();
            };
            const supportsScrollEnd = 'onscrollend' in content;
            content.addEventListener('scroll', () => {
                _virtualGridFastScrolling = true;
                _scheduleProgressiveGridGrowthCheck();
                if (_virtualGridScrollIdleTimerId !== null) {
                    clearTimeout(_virtualGridScrollIdleTimerId);
                }
                _virtualGridScrollIdleTimerId = setTimeout(() => {
                    settleVirtualScroll();
                }, 80);
            }, {passive: true});
            if (supportsScrollEnd) {
                content.addEventListener('scrollend', settleVirtualScroll, {passive: true});
            }
            _progressiveGridScrollBound = true;
        }

        /* ── Stage 2 cache metadata ──────────────────────────────────────
         * _thumbnailMetadata: Map<cacheKey, {priority, scopeBatch, _lruTouch, _resident}>
         *   - priority: strongest observed request priority (0=visible, 1=near, 2=deferred)
         *   - scopeBatch: real source batch for scope-aware eviction
         *   - _lruTouch: monotonic recency counter; higher = more recently used
         *   - _resident: 0 = probationary (fresh), 1 = resident (reused/outgoing-marked)
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
                meta._resident = 1; /* promote to resident on reuse */
            }
        }

        function _updateCacheMetadata(cacheKey, meta) {
            /* Creates or promotes metadata (priority, scope).
               Bumps LRU recency only when the entry is first created.
               _touchCacheEntry is the sole LRU touch point for cache reuse.
               New entries start probationary (_resident: 0). */
            if (!meta) return;
            let existing = _thumbnailMetadata.get(cacheKey);
            if (!existing) {
                _thumbnailMetadata.set(cacheKey, { priority: 2, scopeBatch: null, _lruTouch: ++_lruTouchNext, _resident: 0 });
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
                let weakestResident = Infinity;
                let weakestLruTouch = Infinity;

                for (const [key, blobUrl] of thumbnailBlobUrlCache) {
                    const meta = _thumbnailMetadata.get(key);
                    const scopeClass = _getScopeClass(meta ? meta.scopeBatch : null);
                    const priorityClass = _getPriorityClass(meta ? meta.priority : undefined);
                    const resident = meta && typeof meta._resident === 'number' ? meta._resident : 0;
                    const lruTouch = meta ? meta._lruTouch : 0;

                    /* Eviction ranking (lower = evict first):
                       1. scopeClass (0=other, 1=previous, 2=current)
                       2. priorityClass (0=deferred, 1=near, 2=visible)
                       3. resident (0=probationary, 1=resident)
                       4. lruTouch (lower = older = evict first)
                    */
                    if (scopeClass < weakestScopeProtection ||
                        (scopeClass === weakestScopeProtection && priorityClass < weakestPriorityProtection) ||
                        (scopeClass === weakestScopeProtection && priorityClass === weakestPriorityProtection && resident < weakestResident) ||
                        (scopeClass === weakestScopeProtection && priorityClass === weakestPriorityProtection && resident === weakestResident && lruTouch < weakestLruTouch)) {
                        weakestKey = key;
                        weakestScopeProtection = scopeClass;
                        weakestPriorityProtection = priorityClass;
                        weakestResident = resident;
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
            /* Mark outgoing current-batch entries as resident so they
               survive sequential A→B→A self-eviction (O(n), n <= cap). */
            const outgoingBatch = _realBatchCurrent;
            if (outgoingBatch) {
                for (const meta of _thumbnailMetadata.values()) {
                    if (meta.scopeBatch === outgoingBatch) {
                        meta._resident = 1;
                    }
                }
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
            return `${imageSrc}|${img.mtime || img.modified_at || img.size || 0}`;
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
                imageEl.dataset.loadedThumbnailCacheKey = cacheKey;
                imageEl.classList.add('loaded');
                const thumb = typeof imageEl.closest === 'function'
                    ? imageEl.closest('.thumb')
                    : null;
                clearThumbnailError(thumb, imageEl);
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

function resetPagedFolderState() {
            folderSnapshot = null;
            folderPageInflight.clear();
            pagedFolderMode = false;
            displayIndexByName.clear();
            displayIndexByKey.clear();
        }

function requiresMaterializedNativeFolder() {
            return favoritesFilterOn
                || currentSort === 'score-desc'
                || (aiShowOverlays && aiFilterMode !== 'all');
        }

function _folderTransportSort() {
            return ['date', 'name', 'shuffle'].includes(currentSort) ? currentSort : 'date';
        }

async function ensureFolderPageForIndex(index) {
            if (!pagedFolderMode || !folderSnapshot || index < 0 || index >= folderSnapshot.count) return null;
            if (images[index]) return images[index];
            const offset = Math.floor(index / FOLDER_PAGE_SIZE) * FOLDER_PAGE_SIZE;
            if (!folderPageInflight.has(offset)) {
                setGridLoadingStatus(true, 'Loading visible images…');
                const snapshot = folderSnapshot;
                const pageRequestToken = folderRequestToken;
                let promise;
                promise = apiGetFolderPage(
                    currentBatch, currentFolder, _folderTransportSort(), currentOrder,
                    snapshot.revision, offset, FOLDER_PAGE_SIZE, folderShuffleSeed,
                ).then(async resp => {
                    if (resp.status === 409) {
                        loadCurrentFolderImages({preserveScroll: true});
                        return null;
                    }
                    if (!resp.ok) return null;
                    const page = await resp.json();
                    if (!folderSnapshot || page.revision !== folderSnapshot.revision) return null;
                    page.items.forEach(item => {
                        images[item.index] = item;
                        currentDisplayImages[item.index] = item;
                        displayIndexByName.set(item.name, item.index);
                    });
                    updateGrid();
                    return images[index] || null;
                }).finally(() => {
                    if (folderPageInflight.get(offset) !== promise) return;
                    folderPageInflight.delete(offset);
                    if (folderPageInflight.size === 0 && pageRequestToken === folderRequestToken) {
                        setGridLoadingStatus(false);
                    }
                });
                folderPageInflight.set(offset, promise);
            }
            await folderPageInflight.get(offset);
            return images[index] || null;
        }

async function _waitForFolderSnapshot(batch, folder, requestToken) {
            for (let attempt = 0; attempt < 100; attempt++) {
                const resp = await apiGetFolderSnapshot(
                    batch, folder, _folderTransportSort(), currentOrder, folderShuffleSeed,
                );
                if (requestToken !== folderRequestToken) return null;
                if (resp.ok && resp.status !== 202) return resp.json();
                await new Promise(resolve => setTimeout(resolve, Math.min(250, 25 + attempt * 10)));
            }
            return null;
        }

async function loadCurrentFolderImages(options = {}) {
            if (!currentBatch || !currentFolder) return;
            const requestToken = ++folderRequestToken;
            const batch = currentBatch;
            const folder = currentFolder;
            const activityGroup = `folder-view:${batch}:${folder}`;
            const activityId = activityAttemptId(activityGroup, requestToken);
            activityRegister({
                id: activityId,
                group: activityGroup,
                kind: 'snapshot',
                title: 'Load folder view',
                scope: `${batch} / ${folder}`,
                status: 'running',
                detail: 'Reading folder snapshot…',
            });
            setGridLoadingStatus(true, 'Loading images…');
            if (currentFolder === 'public') {
                await loadBatchPublic(batch);
                if (requestToken !== folderRequestToken) {
                    activityRemove(activityId);
                } else {
                    activityComplete(activityId, 'completed', {detail: 'Public folder ready'});
                }
                return;
            }
            if (CURATOR_NATIVE) {
                const content = document.querySelector('.content');
                const priorScrollTop = content ? content.scrollTop : 0;
                const snapshot = await _waitForFolderSnapshot(batch, folder, requestToken);
                if (!snapshot || requestToken !== folderRequestToken) {
                    if (requestToken === folderRequestToken) {
                        setGridLoadingStatus(false);
                        activityComplete(activityId, 'failed', {error: 'Folder snapshot unavailable', detail: 'Try opening the folder again'});
                    } else {
                        activityRemove(activityId);
                    }
                    return;
                }
                activityUpdate(activityId, {
                    total: snapshot.count,
                    completed: 0,
                    detail: 'Snapshot ready · loading visible thumbnails…',
                });
                if (requestToken !== folderRequestToken) {
                    activityRemove(activityId);
                    return;
                }
                if (requiresMaterializedNativeFolder()) {
                    resetPagedFolderState();
                    folderSnapshot = snapshot;
                    const resp = await fetch(ccApiPath(`/api/images/${batch}/${folder}?sort=${_folderTransportSort()}&order=${currentOrder}`));
                    if (!resp.ok) {
                        if (requestToken === folderRequestToken) {
                            setGridLoadingStatus(false);
                            activityComplete(activityId, 'failed', {error: 'Folder image load failed', detail: 'Try opening the folder again'});
                        } else {
                            activityRemove(activityId);
                        }
                        return;
                    }
                    const nextImages = await resp.json();
                    if (requestToken !== folderRequestToken) {
                        activityRemove(activityId);
                        return;
                    }
                    images = nextImages;
                    displayIndexByName = new Map(images.map((img, index) => [img.name, index]));
                    updateImageCountLabel();
                    updateGrid();
                    if (options.preserveScroll && content) content.scrollTop = priorScrollTop;
                    if (requestToken !== folderRequestToken) {
                        activityRemove(activityId);
                    } else {
                        activityComplete(activityId, 'completed', {
                        completed: nextImages.length,
                        total: snapshot.count,
                        detail: 'Folder ready · thumbnails loaded on demand',
                        });
                    }
                    return;
                }
                folderSnapshot = snapshot;
                pagedFolderMode = true;
                folderPageInflight.clear();
                images = new Array(snapshot.count);
                currentDisplayImages = images;
                displayIndexByName.clear();
                updateImageCountLabel();
                updateGrid();
                if (options.preserveScroll && content) content.scrollTop = priorScrollTop;
                const firstImage = await ensureFolderPageForIndex(0);
                if (requestToken !== folderRequestToken) {
                    activityRemove(activityId);
                } else if (firstImage || snapshot.count === 0) {
                    activityComplete(activityId, 'completed', {
                        completed: Math.min(FOLDER_PAGE_SIZE, snapshot.count),
                        total: snapshot.count,
                        detail: 'Folder ready · more thumbnails load as needed',
                    });
                } else {
                    activityComplete(activityId, 'failed', {error: 'Visible folder page failed', detail: 'Try opening the folder again'});
                }
                return;
            }
            resetPagedFolderState();
            const resp = await fetch(ccApiPath(`/api/images/${batch}/${folder}?sort=${currentSort}&order=${currentOrder}`));
            if (!resp.ok) {
                if (requestToken === folderRequestToken) setGridLoadingStatus(false);
                if (requestToken === folderRequestToken) {
                    activityComplete(activityId, 'failed', {error: 'Folder image load failed', detail: 'Try opening the folder again'});
                } else {
                    activityRemove(activityId);
                }
                return;
            }
            const nextImages = await resp.json();
            if (requestToken !== folderRequestToken) {
                activityRemove(activityId);
                return;
            }
            images = nextImages;
            displayIndexByName = new Map(images.map((img, index) => [img.name, index]));
            updateImageCountLabel();
            updateGrid();
            activityComplete(activityId, 'completed', {
                completed: nextImages.length,
                total: nextImages.length,
                detail: 'Folder ready · thumbnails loaded on demand',
            });
        }

function setSort(sort) {
            currentSort = sort;
            if (sort === 'shuffle') {
                resetVirtualShuffleOrder();
                resetFolderShuffleOrder();
            }
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

function _calculateFittedGridColumns(displayCount) {
            const content = document.querySelector('.content');
            if (!content || displayCount <= 0) return 1;
            const {track, gap} = getGridDensityConfig();
            const styles = window.getComputedStyle(content);
            const paddingLeft = parseFloat(styles.paddingLeft) || 0;
            const paddingRight = parseFloat(styles.paddingRight) || 0;
            const availableWidth = Math.max(0, content.clientWidth - paddingLeft - paddingRight);
            const fitted = Math.max(1, Math.floor((availableWidth + gap) / (track + gap)));
            return Math.max(1, Math.min(fitted, displayCount));
        }

function _captureGridAnchor(columns = null, density = gridDensity) {
            const content = document.querySelector('.content');
            const grid = document.getElementById('grid');
            if (!content || !grid || currentDisplayImages.length === 0) return null;
            const usedColumns = columns || Math.max(1, Number(grid.style.getPropertyValue('--grid-columns')) || 1);
            const {track, gap} = getGridDensityConfig(density);
            const visibleTop = Math.max(0, content.scrollTop - getGridScrollOrigin(grid));
            return Math.min(currentDisplayImages.length - 1, Math.floor(visibleTop / (track + gap)) * usedColumns);
        }

function _captureGridIdentityAnchor() {
            const content = document.querySelector('.content');
            const grid = document.getElementById('grid');
            const index = _captureGridAnchor();
            const image = index === null ? null : currentDisplayImages[index];
            if (!content || !grid || !image) return null;
            const columns = Math.max(1, Number(grid.style.getPropertyValue('--grid-columns')) || 1);
            const {track, gap} = getGridDensityConfig();
            const rowTop = getGridScrollOrigin(grid) + Math.floor(index / columns) * (track + gap);
            return {
                key: getImageRenderKey(image),
                offset: content.scrollTop - rowTop,
            };
        }

function _restoreGridIdentityAnchor(anchor) {
            if (!anchor?.key) return false;
            const content = document.querySelector('.content');
            const grid = document.getElementById('grid');
            if (!content || !grid) return false;
            const index = currentDisplayImages.findIndex(image => getImageRenderKey(image) === anchor.key);
            if (index < 0) return false;
            const columns = Math.max(1, Number(grid.style.getPropertyValue('--grid-columns')) || 1);
            const {track, gap} = getGridDensityConfig();
            const rowTop = getGridScrollOrigin(grid) + Math.floor(index / columns) * (track + gap);
            content.scrollTop = Math.max(0, rowTop + anchor.offset);
            return true;
        }

function _restoreGridAnchor(index) {
            if (index === null || index < 0) return;
            const content = document.querySelector('.content');
            const grid = document.getElementById('grid');
            if (!content || !grid) return;
            const columns = Math.max(1, Number(grid.style.getPropertyValue('--grid-columns')) || 1);
            const {track, gap} = getGridDensityConfig();
            content.scrollTop = getGridScrollOrigin(grid) + Math.floor(index / columns) * (track + gap);
        }

function getGridScrollOrigin(grid) {
            const shell = document.getElementById('grid-shell');
            const content = document.querySelector('.content');
            if (shell && content) {
                // offsetTop can be relative to the page, including the toolbar.
                // Virtual rows and scrollTop must share the scroller's coordinates.
                return shell.getBoundingClientRect().top - content.getBoundingClientRect().top
                    - content.clientTop + content.scrollTop;
            }
            return Number.isFinite(grid.offsetTop) ? grid.offsetTop : 0;
        }

function updateGridShellLayout(options = {}) {
            const skipAnchorRestore = options.skipAnchorRestore === true;
            const content = document.querySelector('.content');
            const shell = document.getElementById('grid-shell');
            const grid = document.getElementById('grid');
            if (!content || !shell || !grid) return;
            if (grid.classList.contains('is-empty')) {
                grid.style.removeProperty('--grid-columns');
                return;
            }

            const displayCount = currentDisplayImages.length || grid.querySelectorAll('.thumb.loading-placeholder').length;
            if (displayCount <= 0) {
                grid.style.removeProperty('--grid-columns');
                return;
            }

            const previousColumns = Math.max(1, Number(grid.style.getPropertyValue('--grid-columns')) || 1);
            const anchorIndex = skipAnchorRestore ? null : _captureGridAnchor(previousColumns);
            const usedColumns = _calculateFittedGridColumns(displayCount);
            grid.style.setProperty('--grid-columns', String(usedColumns));
            if (!skipAnchorRestore && usedColumns !== previousColumns) {
                // Sidebar/viewport reflows can increase the scroll extent too.
                const {track, gap} = getGridDensityConfig();
                shell.style.height = `${Math.max(track, Math.ceil(displayCount / usedColumns) * (track + gap) - gap)}px`;
                _restoreGridAnchor(anchorIndex);
            }
        }

function initializeGridShellLayout() {
            const content = document.querySelector('.content');
            if (!content) return;
            _bindProgressiveGridScrollGrowth(content);
            if (!window._gridShellResizeObserver && window.ResizeObserver) {
                window._gridShellResizeObserver = new ResizeObserver(() => {
                    updateGridShellLayout();
                    _scheduleProgressiveGridResizeCheck();
                });
                window._gridShellResizeObserver.observe(content);
            } else if (!window._gridShellResizeBound) {
                window.addEventListener('resize', () => {
                    updateGridShellLayout();
                    _scheduleProgressiveGridResizeCheck();
                });
                window._gridShellResizeBound = true;
            }
            updateGridShellLayout();
        }

function setGridDensity(density) {
            const previousDensity = gridDensity;
            const anchorIndex = _captureGridAnchor(null, previousDensity);
            gridDensity = normalizeGridDensity(density);
            const grid = document.getElementById('grid');
            if (grid) {
                grid.classList.remove('density-compact', 'density-comfortable', 'density-large');
                grid.classList.add(`density-${gridDensity}`);
            }
            updateGridShellLayout({skipAnchorRestore: true});
            const shell = document.getElementById('grid-shell');
            if (grid && shell) {
                const columns = Math.max(1, Number(grid.style.getPropertyValue('--grid-columns')) || 1);
                const count = currentDisplayImages.length || Number(grid.dataset.canonicalCount) || 0;
                if (count > 0) {
                    const {track, gap} = getGridDensityConfig();
                    shell.style.height = `${Math.max(track, Math.ceil(count / columns) * (track + gap) - gap)}px`;
                }
            }
            _restoreGridAnchor(anchorIndex);
            _scheduleProgressiveGridGrowthCheck();
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

function resetVirtualShuffleOrder() {
            virtualShuffleRanks.clear();
        }

function resetFolderShuffleOrder() {
            folderShuffleGeneration += 1;
            folderShuffleSeed = `${folderShuffleSession}-${folderShuffleGeneration}`;
        }

function getVirtualShuffleRank(img) {
            const key = getImageRenderKey(img);
            if (!virtualShuffleRanks.has(key)) virtualShuffleRanks.set(key, Math.random());
            return virtualShuffleRanks.get(key);
        }

function sortImagesForDisplay(imgList) {
            if (aiActiveRun && currentSort === 'score-desc') return aiSortImages(imgList);
            if (!isVirtualCollectionView() && !isPublicView()) return imgList;
            if (currentSort === 'shuffle') {
                imgList.forEach(img => getVirtualShuffleRank(img));
                return [...imgList].sort((a, b) => {
                    const rankDifference = getVirtualShuffleRank(a) - getVirtualShuffleRank(b);
                    if (rankDifference !== 0) return rankDifference;
                    return getImageRenderKey(a).localeCompare(getImageRenderKey(b));
                });
            }
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
            if (typeof pagedFolderMode !== 'undefined' && pagedFolderMode) return images;
            const favoritesFiltered = favoritesFilterOn ? images.filter(img => img.favorite === true) : images;
            const filtered = aiShowOverlays && aiFilterMode !== 'all'
                ? favoritesFiltered.filter(img => aiShouldShowImage(img))
                : favoritesFiltered;
            return sortImagesForDisplay(filtered);
        }

function getImageRenderKey(img) {
            if (!img) return '';
            if (!isVirtualCollectionView()) return String(img.name || '');
            const source = getImageBatchAndFolder(img);
            return `${source.batch || ''}\u001f${source.folder || ''}\u001f${img.name || ''}`;
        }

function getCurrentDisplayImages() {
            return currentDisplayImages.length > 0 ? currentDisplayImages : getDisplayImages();
        }

function getImageDisplayIndexByName(name) {
            if (typeof displayIndexByName !== 'undefined' && displayIndexByName.has(name)) return displayIndexByName.get(name);
            return getCurrentDisplayImages().findIndex(img => img && img.name === name);
        }

function getImageDisplayIndex(img) {
            if (!img) return -1;
            if (!isVirtualCollectionView()) return getImageDisplayIndexByName(img.name);
            const key = getImageRenderKey(img);
            if (displayIndexByKey.has(key)) return displayIndexByKey.get(key);
            return getCurrentDisplayImages().findIndex(candidate => getImageRenderKey(candidate) === key);
        }

function getGridEmptyStateMessage() {
            if (isWorkspaceSearchView()) {
                return {
                    title: 'No media match this workspace filter',
                    detail: 'Edit the search terms or clear the filter to return to the previous review view.',
                };
            }
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
            const displayCount = typeof pagedFolderMode !== 'undefined' && pagedFolderMode && folderSnapshot ? folderSnapshot.count : getDisplayImages().length;
            if (images.length === 0) countEl.textContent = '';
            else if (favoritesFilterOn && displayCount !== images.length) countEl.textContent = ` (${displayCount} of ${images.length})`;
            else countEl.textContent = ` (${images.length})`;
        }

function setGridLoadingStatus(loading, message = '') {
            const grid = document.getElementById('grid');
            const status = document.getElementById('grid-status');
            if (grid) grid.setAttribute('aria-busy', loading ? 'true' : 'false');
            if (!status) return;
            status.setAttribute('aria-live', 'polite');
            status.hidden = !loading;
            status.textContent = loading ? message : '';
        }

function getImageBatchAndFolder(img) {
            return img && img.batch && img.folder
                ? {batch: img.batch, folder: img.folder}
                : {batch: currentBatch, folder: currentFolder};
        }

function getImageIndexByName(name) {
            if (typeof displayIndexByName !== 'undefined' && displayIndexByName.has(name)) return displayIndexByName.get(name);
            return images.findIndex(img => img && img.name === name);
        }

function stopActiveHoverPreview() {
            if (hoverPreviewTimer) {
                clearTimeout(hoverPreviewTimer);
                hoverPreviewTimer = null;
            }
            if (!activeHoverPreview) return;
            const video = activeHoverPreview.querySelector('.thumb-hover-preview');
            if (video) {
                video.pause();
                video.removeAttribute('src');
                video.load();
            }
            activeHoverPreview.classList.remove('preview-active');
            activeHoverPreview = null;
        }

function scheduleHoverPreview(thumb) {
            if (!hoverPreviewsEnabled || !thumb.classList.contains('preview-capable')) return;
            stopActiveHoverPreview();
            hoverPreviewTimer = setTimeout(() => {
                hoverPreviewTimer = null;
                const video = thumb.querySelector('.thumb-hover-preview');
                if (!video || !video.dataset.previewSrc || !thumb.isConnected) return;
                activeHoverPreview = thumb;
                thumb.classList.add('preview-active');
                video.src = video.dataset.previewSrc;
                const started = video.play();
                if (started && typeof started.catch === 'function') {
                    started.catch(() => stopActiveHoverPreview());
                }
            }, 180);
        }

function toggleHoverPreviews() {
            hoverPreviewsEnabled = !hoverPreviewsEnabled;
            localStorage.setItem(HOVER_PREVIEWS_KEY, hoverPreviewsEnabled ? 'true' : 'false');
            if (!hoverPreviewsEnabled) stopActiveHoverPreview();
            const toggle = document.getElementById('hover-preview-toggle');
            if (toggle) {
                toggle.checked = hoverPreviewsEnabled;
                toggle.setAttribute('aria-checked', hoverPreviewsEnabled ? 'true' : 'false');
            }
            showToast(`Hover previews ${hoverPreviewsEnabled ? 'on' : 'off'}`);
        }

function markThumbnailLoaded(img) {
            img.dataset.loadedThumbnailCacheKey = img.dataset.thumbnailCacheKey || '';
            img.classList.add('loaded');
            clearThumbnailError(img.closest('.thumb'), img);
        }

function markThumbnailError(img) {
            const thumb = img.closest('.thumb');
            if (!thumb || !img.dataset.thumbnailCacheKey) return;
            img.classList.remove('loaded');
            delete img.dataset.loadedThumbnailCacheKey;
            thumb.dataset.thumbnailErrorCacheKey = img.dataset.thumbnailCacheKey;
            thumb.classList.add('thumbnail-failed');
            const errorPanel = thumb.querySelector('.thumbnail-error');
            if (!errorPanel) return;
            errorPanel.replaceChildren();
            const copy = document.createElement('span');
            copy.className = 'thumbnail-error-copy';
            const mediaType = thumb.dataset.mediaKind || 'media';
            copy.textContent = `${thumb.dataset.name || 'Thumbnail'} (${mediaType}) unavailable`;
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'thumbnail-retry';
            retry.textContent = 'Retry';
            retry.setAttribute('aria-label', `Retry loading ${thumb.dataset.name || 'thumbnail'}`);
            retry.addEventListener('click', (event) => {
                event.stopPropagation();
                retryThumbnailLoad(thumb);
            });
            errorPanel.append(copy, retry);
            errorPanel.hidden = false;
        }

function clearThumbnailError(thumb, imageEl) {
            if (!thumb) return;
            if (imageEl && thumb.dataset.thumbnailErrorCacheKey &&
                thumb.dataset.thumbnailErrorCacheKey !== imageEl.dataset.thumbnailCacheKey) return;
            thumb.classList.remove('thumbnail-failed');
            delete thumb.dataset.thumbnailErrorCacheKey;
            const errorPanel = thumb.querySelector('.thumbnail-error');
            if (errorPanel) {
                errorPanel.hidden = true;
                errorPanel.replaceChildren();
            }
        }

function retryThumbnailLoad(thumb) {
            if (!thumb || !thumb.isConnected) return;
            const imageEl = thumb.querySelector('img');
            const cacheKey = thumb.dataset.thumbnailErrorCacheKey || imageEl?.dataset.thumbnailCacheKey;
            const imageSrc = imageEl?.dataset.thumbnailSource;
            if (!imageEl || !cacheKey || !imageSrc) return;
            unscheduleThumbnailLoad(thumb);
            clearThumbnailError(thumb, imageEl);
            imageEl.classList.remove('loaded');
            delete imageEl.dataset.loadedThumbnailCacheKey;
            imageEl.removeAttribute('src');
            scheduleThumbnailLoad(
                thumb, imageSrc, cacheKey, VIEWPORT_PRIORITY_VISIBLE,
                thumb.dataset.sourceBatch || null, {immediate: true},
            );
        }

function createThumbImageElement() {
            const img = document.createElement('img');
            img.draggable = false;
            img.addEventListener('load', () => markThumbnailLoaded(img));
            img.addEventListener('error', () => markThumbnailError(img));
            return img;
        }

function createThumbElement() {
            const thumb = document.createElement('div');
            thumb.className = 'thumb';
            thumb.tabIndex = -1;
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

            const img = createThumbImageElement();

            const preview = document.createElement('video');
            preview.className = 'thumb-hover-preview';
            preview.muted = true;
            preview.loop = true;
            preview.playsInline = true;
            preview.preload = 'none';
            preview.addEventListener('error', () => stopActiveHoverPreview());
            thumb.addEventListener('pointerenter', () => scheduleHoverPreview(thumb));
            thumb.addEventListener('pointerleave', () => {
                if (activeHoverPreview === thumb || hoverPreviewTimer) stopActiveHoverPreview();
            });

            const metaBatch = document.createElement('span');
            metaBatch.className = 'meta-batch hidden';

            const meta = document.createElement('div');
            meta.className = 'thumb-meta';
            meta.innerHTML = '<span class="meta-name"></span><span class="meta-detail"></span>';

            const errorPanel = document.createElement('div');
            errorPanel.className = 'thumbnail-error';
            errorPanel.hidden = true;
            errorPanel.setAttribute('role', 'alert');

            thumb.append(badge, select, favStar, img, preview, metaBatch, meta, errorPanel);
            return thumb;
        }

function getThumbRenderSignature(img, index) {
            const scoreResult = aiGetImageScore ? aiGetImageScore(img.name) : null;
            const shouldShow = aiShouldShowImage ? aiShouldShowImage(img) : true;
            const source = getImageBatchAndFolder(img);
            const selected = typeof serverSelection !== 'undefined' && serverSelection
                ? !serverSelection.excluded.has(img.name)
                : selectedImages.has(img.name);
            return JSON.stringify([
                index,
                img.name,
                img.size,
                img.mtime,
                img.favorite === true,
                img.media_kind || '',
                source.batch,
                source.folder,
                selected,
                typeof aiInspectedImageKey !== 'undefined' && aiInspectedImageKey === getImageIdentityKey(img, source),
                shouldShow,
                aiShowOverlays,
                scoreResult ? scoreResult.score : null,
                scoreResult ? scoreResult.total : null,
                scoreResult ? scoreResult.failed === true : null,
                isVirtualCollectionView(),
                _virtualGridFastScrolling,
            ]);
        }

function updateThumbElement(thumb, img, index) {
            const scoreResult = aiGetImageScore ? aiGetImageScore(img.name) : null;
            const shouldShow = aiShouldShowImage ? aiShouldShowImage(img) : true;
            const badge = thumb.querySelector('.ai-score-badge');
            const selectBtn = thumb.querySelector('.thumb-select');
            let imageEl = thumb.querySelector('img');
            const previewEl = thumb.querySelector('.thumb-hover-preview');
            const metaName = thumb.querySelector('.meta-name');
            const metaSize = thumb.querySelector('.meta-detail');
            const favStar = thumb.querySelector('.favorite-star');
            const source = getImageBatchAndFolder(img);
            const imageSrcBase = ccThumbUrl(source.batch, source.folder, img.name);
            const version = encodeURIComponent(String(img.mtime || img.modified_at || img.size || 0));
            const imageSrc = `${imageSrcBase}${imageSrcBase.includes('?') ? '&' : '?'}v=${version}`;
            const thumbnailCacheKey = getThumbnailCacheKey(imageSrc, img);

            thumb.dataset.name = img.name;
            thumb.dataset.imageKey = getImageRenderKey(img);
            thumb.dataset.inspectorKey = getImageIdentityKey(img, source);
            thumb.dataset.index = String(index);
            thumb.dataset.mediaKind = img.media_kind || 'media';
            thumb.dataset.sourceBatch = source.batch || '';
            const selected = typeof serverSelection !== 'undefined' && serverSelection
                ? !serverSelection.excluded.has(img.name)
                : selectedImages.has(img.name);
            thumb.classList.toggle('selected', selected);
            thumb.classList.toggle('inspected', typeof aiInspectedImageKey !== 'undefined' && aiInspectedImageKey === getImageIdentityKey(img, source));
            thumb.classList.toggle('ai-filtered-out', !shouldShow);
            thumb.classList.remove('removing');
            const previewCapable = img.media_kind === 'animated_image' || img.media_kind === 'video';
            thumb.classList.toggle('preview-capable', previewCapable);
            thumb.classList.toggle('media-audio', img.media_kind === 'audio');
            if (previewEl) {
                previewEl.dataset.previewSrc = previewCapable
                    ? ccPreviewUrl(source.batch, source.folder, img.name)
                    : '';
            }
            if (selectBtn) {
                const isSelected = selected;
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
                clearThumbnailError(thumb, imageEl);
                if (imageEl.dataset.thumbnailCacheKey) unscheduleThumbnailLoad(thumb);
                if (_virtualGridFastScrolling) {
                    thumb.dataset.pendingThumbnailCacheKey = thumbnailCacheKey;
                } else {
                    delete thumb.dataset.pendingThumbnailCacheKey;
                    imageEl.dataset.thumbnailCacheKey = thumbnailCacheKey;
                    imageEl.dataset.thumbnailSource = imageSrc;
                    /* Stage 2: pass resolved source batch for scope-aware eviction.
                       Priority starts deferred; observers promote it in the viewport loader. */
                    scheduleThumbnailLoad(thumb, imageSrc, thumbnailCacheKey, 2 /* DEFERRED */, _resolveSourceBatch(img));
                }
            } else if (imageEl) {
                imageEl.dataset.thumbnailSource = imageSrc;
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
            _resetProgressiveGridLifecycle();
            const grid = document.getElementById('grid');
            setGridLoadingStatus(true, 'Loading images…');
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
            const shell = document.getElementById('grid-shell');
            const {track, gap} = getGridDensityConfig();
            const columns = _calculateFittedGridColumns(placeholderCount);
            if (shell) {
                shell.style.height = `${Math.max(track, Math.ceil(placeholderCount / columns) * (track + gap) - gap)}px`;
            }
            grid.style.transform = 'translateX(-50%)';
        }

        function updateGrid() {
            const grid = document.getElementById('grid');
            const shell = document.getElementById('grid-shell');
            const displayImages = getDisplayImages();
            currentDisplayImages = displayImages;
            grid.dataset.canonicalCount = String(displayImages.length);
            if (typeof pagedFolderMode === 'undefined' || !pagedFolderMode) {
                displayIndexByName = new Map(
                    displayImages.filter(Boolean).map((img, index) => [img.name, index])
                );
                displayIndexByKey = new Map(
                    displayImages.filter(Boolean).map((img, index) => [getImageRenderKey(img), index])
                );
            }
            const nextContextKey = _getProgressiveGridContextKey();
            const contextChanged = nextContextKey !== _progressiveGridContextKey;
            if (contextChanged) _resetProgressiveGridContext(nextContextKey);

            if (images.length === 0 || displayImages.length === 0) {
                setGridLoadingStatus(false);
                _resetProgressiveGridLifecycle();
                grid.classList.add('is-empty');
                if (shell) shell.style.height = '';
                grid.style.transform = '';
                grid.style.paddingTop = '';
                grid.style.paddingBottom = '';
                grid.replaceChildren(createGridEmptyState(getGridEmptyStateMessage()));
                gridThumbMap.clear();
                updateGridShellLayout();
                return;
            }
            grid.classList.remove('is-empty');
            setGridLoadingStatus(false);
            if (typeof pagedFolderMode !== 'undefined' && pagedFolderMode && folderPageInflight.size > 0) {
                setGridLoadingStatus(true, 'Loading visible images…');
            }
            const content = document.querySelector('.content');
            const {track, gap} = getGridDensityConfig();
            const columns = _calculateFittedGridColumns(displayImages.length);
            grid.style.setProperty('--grid-columns', String(columns));
            const rowSpan = track + gap;
            const gridTop = getGridScrollOrigin(grid);
            grid.dataset.virtualScrollTop = String(content ? content.scrollTop : 0);
            const visibleTop = Math.max(0, (content ? content.scrollTop : 0) - gridTop);
            const firstVisibleRow = Math.floor(visibleTop / rowSpan);
            const viewportRows = Math.ceil((content ? content.clientHeight : track * 4) / rowSpan);
            const maxWindowRows = Math.max(1, Math.floor(VIRTUAL_GRID_MAX_THUMBNAILS / columns));
            const requestedStartRow = Math.max(0, firstVisibleRow - VIRTUAL_GRID_OVERSCAN_ROWS);
            const desiredRows = Math.min(
                maxWindowRows,
                viewportRows + (VIRTUAL_GRID_OVERSCAN_ROWS * 2),
            );
            const totalRows = Math.ceil(displayImages.length / columns);
            const startRow = Math.min(requestedStartRow, Math.max(0, totalRows - desiredRows));
            const endRow = Math.min(totalRows, startRow + desiredRows);
            const startIndex = startRow * columns;
            const endIndex = Math.min(displayImages.length, endRow * columns);
            if (typeof maybeLoadMoreWorkspaceSearchResults === 'function') {
                maybeLoadMoreWorkspaceSearchResults(endIndex);
            }
            _virtualGridWindowStart = startIndex;
            _virtualGridWindowEnd = endIndex;
            grid.style.paddingTop = '';
            grid.style.paddingBottom = '';
            if (shell) shell.style.height = `${Math.max(track, totalRows * rowSpan - gap)}px`;
            grid.style.transform = `translateX(-50%) translateY(${startRow * rowSpan}px)`;

            if (typeof pagedFolderMode !== 'undefined' && pagedFolderMode && endIndex > startIndex) {
                ensureFolderPageForIndex(startIndex);
                ensureFolderPageForIndex(endIndex - 1);
            }

            const renderedEntries = [];
            for (let index = startIndex; index < endIndex; index++) {
                renderedEntries.push({img: displayImages[index], index});
            }
            const activeKeys = new Set(renderedEntries.filter(entry => entry.img).map(entry => getImageRenderKey(entry.img)));
            for (const [key, element] of gridThumbMap.entries()) {
                if (!activeKeys.has(key)) {
                    if (activeHoverPreview === element) stopActiveHoverPreview();
                    unscheduleThumbnailLoad(element);
                    gridThumbMap.delete(key);
                    if (gridThumbPool.length < VIRTUAL_GRID_MAX_THUMBNAILS) {
                        gridThumbPool.push(element);
                    }
                }
            }
            const renderedNodes = [];
            renderedEntries.forEach(({img, index}) => {
                if (!img) {
                    const placeholder = document.createElement('div');
                    placeholder.className = 'thumb loading-placeholder';
                    placeholder.setAttribute('aria-hidden', 'true');
                    renderedNodes.push(placeholder);
                    return;
                }
                const imageKey = getImageRenderKey(img);
                let thumb = gridThumbMap.get(imageKey);
                if (!thumb) {
                    thumb = gridThumbPool.pop() || createThumbElement();
                    gridThumbMap.set(imageKey, thumb);
                }
                const renderSignature = getThumbRenderSignature(img, index);
                if (thumb.dataset.renderSignature !== renderSignature) {
                    updateThumbElement(thumb, img, index);
                    thumb.dataset.renderSignature = renderSignature;
                }
                renderedNodes.push(thumb);
            });
            const alreadyOrdered = grid.children.length === renderedNodes.length
                && renderedNodes.every((node, index) => grid.children[index] === node);
            if (alreadyOrdered) {
                updateGridShellLayout();
                return;
            }
            renderedNodes.forEach((node, index) => {
                const current = grid.children[index] || null;
                if (current !== node) grid.insertBefore(node, current);
            });
            while (grid.children.length > renderedNodes.length) {
                grid.removeChild(grid.lastElementChild);
            }
            updateGridShellLayout();
        }

function _gridChildrenMatchDesiredOrder(grid, displayImages) {
            const live = grid.children;
            if (live.length !== displayImages.length) return false;
            for (let i = 0; i < displayImages.length; i++) {
                if (live[i] !== gridThumbMap.get(getImageRenderKey(displayImages[i]))) return false;
            }
            return true;
        }
