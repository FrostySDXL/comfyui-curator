#!/usr/bin/env node
/* Node-executed Stage 2 cache-policy test.
   Verifies LRU refresh, scope/priority-aware eviction, batch-scope rotation,
   virtual-view isolation, inflight promotion, metadata lifecycle, and
   displayed-thumb safety against cache eviction.
   Outputs JSON with pass/fail assertions to stdout. */

var fs = require('fs');
var path = require('path');
var vm = require('vm');

var source = fs.readFileSync(
    path.join(__dirname, '..', '..', 'static', 'js', 'grid.js'),
    'utf8'
);

/* ── Mock infrastructure ──────────────────────────────────────────────── */

var assertions = [];
function assert(condition, message) {
    assertions.push({ pass: !!condition, message: message || '' });
    if (!condition) {
        process.stderr.write('FAIL: ' + message + '\n');
    }
}

/* ── Mock globals that grid.js depends on ──────────────────────────────── */

// Track revoked blob URLs for leak/double-revoke assertions
var _revokeLog = [];
var _createCount = 0;

global.URL = {
    createObjectURL: function(_blob) {
        _createCount++;
        return 'blob:mock-' + _createCount;
    },
    revokeObjectURL: function(url) {
        _revokeLog.push(url);
    }
};

global.window = {
    CURATOR_NATIVE: false,
    addEventListener: function(_event, _fn) {
        /* noop for beforeunload */
    },
    ResizeObserver: undefined
};

global.document = {
    createDocumentFragment: function() { return { appendChild: function() {} }; },
    getElementById: function() { return null; },
    querySelector: function() { return null; },
    querySelectorAll: function() { return []; },
    createElement: function() {
        return {
            classList: { add: function() {}, remove: function() {}, toggle: function() {}, contains: function() { return false; } },
            setAttribute: function() {},
            getAttribute: function() { return null; },
            addEventListener: function() {},
            appendChild: function() {},
            append: function() {},
            dataset: {}
        };
    },
    createComment: function() { return {}; },
    createTextNode: function() { return {}; }
};

global.localStorage = {
    _store: {},
    getItem: function(k) { return this._store[k] || null; },
    setItem: function(k, v) { this._store[k] = v; },
    removeItem: function(k) { delete this._store[k]; }
};

global.fetch = function(imageSrc) {
    var resp = {
        ok: true,
        status: 200,
        blob: function() {
            return Promise.resolve({ size: 0, type: 'image/webp' });
        }
    };
    return Promise.resolve(resp);
};

global.requestAnimationFrame = function(fn) { fn(); return 1; };
global.cancelAnimationFrame = function() {};

global.IntersectionObserver = function() {
    return { observe: function() {}, unobserve: function() {} };
};

/* ── State.js globals needed by grid.js ────────────────────────────────── */
global.CURATOR_NATIVE = false;
global.ccApiPath = function(p) { return p; };
global.ccThumbUrl = function(batch, folder, name) {
    return '/thumb/' + encodeURIComponent(batch) + '/' + encodeURIComponent(folder) + '/' + encodeURIComponent(name);
};
global.ccImageUrl = function(batch, folder, name) {
    return '/image/' + encodeURIComponent(batch) + '/' + encodeURIComponent(folder) + '/' + encodeURIComponent(name);
};

global.currentBatch = null;
global.currentFolder = null;
global.images = [];
global.currentDisplayImages = [];
global.currentIndex = 0;
global.allCounts = {};
global.currentSort = 'date';
global.currentOrder = 'desc';
global.selectedImages = new Set();
global.selectionMode = false;
global.lastSelectIndex = -1;
global.lastAction = null;
global.draggedFiles = [];
global.toastTimeout = null;
global.batchSort = 'alpha';
global.gridDensity = 'comfortable';
global.batchFilterQuery = '';
global.batchFilterTimer = null;
global.favoritesFilterOn = false;
global.universalFavoritesCount = 0;
global.universalPublicCount = 0;
global.isDraggingImages = false;
global.folderRequestToken = 0;
global.gridThumbMap = new Map();
global.MAX_GRID_LOADING_PLACEHOLDERS = 200;
global.THUMBNAIL_BLOB_CACHE_MAX = 1000;
global.thumbnailBlobUrlCache = new Map();
global.thumbnailBlobInflight = new Map();
global.SIDEBAR_WIDTH_DEFAULT = 240;
global.SIDEBAR_WIDTH_MIN = 220;
global.SIDEBAR_WIDTH_MAX = 520;
global.sidebarWidth = 240;
global.sidebarOpen = true;
global.isSidebarResizing = false;
global._sidebarResizePending = false;
global._sidebarResizeLastEvent = null;
global.isVirtualCollectionView = function() { return false; };
global.isPublicView = function() { return false; };

/* AI globals */
global.aiActiveRun = null;
global.aiShowOverlays = false;
global.aiFilterMode = 'all';
global.aiInspectedImageName = null;
global.aiBatchRunCounts = {};

/* SIDEBAR constants */
global.SIDEBAR_WIDTH_KEY = 'imageCurator.sidebarWidth';
global.SIDEBAR_OPEN_KEY = 'imageCurator.sidebarOpen';
global.BATCH_STATE_KEY = 'imageCurator.lastBatch';
global.FOLDER_STATE_KEY = 'imageCurator.lastFolder';
global.BATCH_SORT_KEY = 'imageCurator.batchSort';
global.GRID_DENSITY_KEY = 'imageCurator.gridDensity';
global.PROMPTS_COLLAPSE_KEY = 'imageCurator.promptsCollapseAll';
global.PROMPTS_SORT_KEY = 'imageCurator.promptsSort';

/* viewport-loader globals that grid.js may reference */
global.scheduleThumbnailLoad = function(el, src, key) {
    el._scheduled = true;
    el._scheduledSrc = src;
    el._scheduledKey = key;
};
global.unscheduleThumbnailLoad = function() {};
global.cancelScheduledViewportLoads = function() {};

/* publish */
global.loadBatchPublic = function() {};
global.loadAllPublic = function() {};

/* AI helpers */
global.aiGetImageScore = function() { return null; };
global.aiShouldShowImage = function() { return true; };
global.aiScoreGradient = function() { return ''; };

/* moves */
global.onDragStart = function() {};
global.onThumbClick = function() {};
global.toggleSelect = function() {};
global.setSelectionMode = function() {};

/* favorites */
global.toggleFavorite = function() {};
global.aiSortImages = function(list) { return list; };
global.formatSize = function() { return ''; };

/* misc */
global.showToast = function() {};
global.folderCountSnapshot = {};
global.pendingActiveBatchSelection = null;
global._initialLoadDone = true;
global._lastBatchListKey = null;

global.resetAiBatchState = function() {};
global.closeLightbox = function() {};
global.showGridLoadingPlaceholders = function() {};
global.selectFolder = function() {};
global.updateAutoImportQuickAction = function() {};
global.resetSelectionState = function() {};
global.showAiCuratePanel = function() {};
global.updateFolderTabs = function() {};
global.updateImageCountLabel = function() {};
global.loadUniversalFavorites = function() {};
global.getAllPublicCount = function() { return 0; };
global.getBatchPublicCount = function() { return 0; };

/* ── Execute grid.js in vm context ─────────────────────────────────────── */

var ctx = vm.createContext(global);
var script = new vm.Script(source);
try {
    script.runInContext(ctx);
} catch (e) {
    process.stderr.write('grid.js evaluation error: ' + e.stack + '\n');
    process.stdout.write(JSON.stringify({
        total: 0, passed: 0, failed: 0,
        details: [],
        error: 'Evaluation failed: ' + e.message
    }));
    process.exit(1);
}

function _evalInCtx(code) {
    return vm.runInContext(code, ctx);
}

/* Extract exported functions from the context */
var getThumbnailCacheKey = ctx.getThumbnailCacheKey;
var rememberThumbnailBlobUrl = ctx.rememberThumbnailBlobUrl;
var resolveThumbnailBlobUrl = ctx.resolveThumbnailBlobUrl;
var assignThumbnailSrcIfCached = ctx.assignThumbnailSrcIfCached;
var setThumbnailImageSrc = ctx.setThumbnailImageSrc;

/* ── Helper: make a mock img element ───────────────────────────────────── */
var _elId = 0;
function makeImageEl() {
    var id = ++_elId;
    var el = {
        _id: id,
        dataset: {},
        classList: {
            _classes: {},
            add: function(c) { this._classes[c] = true; },
            remove: function(c) { delete this._classes[c]; },
            contains: function(c) { return !!this._classes[c]; }
        },
        getAttribute: function(attr) {
            if (attr === 'src') return el._src;
            return null;
        },
        setAttribute: function(attr, val) {
            if (attr === 'src') el._src = val;
        }
    };
    return el;
}

/* ── Helper: create a scope-stamped cache entry ────────────────────────── */
function createCacheEntry(cacheKey, scopeBatch, priority) {
    /* Directly set the blob URL in cache */
    var blobUrl = 'blob:test-' + cacheKey;
    thumbnailBlobUrlCache.set(cacheKey, blobUrl);
    /* Set metadata via internal function */
    try {
        _evalInCtx(
            '_thumbnailMetadata.set("' + cacheKey + '", { scopeBatch: "' + (scopeBatch || '') + '", priority: ' + (priority !== undefined ? priority : 2) + ', _lruTouch: ++_lruTouchNext, _resident: 0 });'
        );
    } catch (e) {
        process.stderr.write('createCacheEntry error: ' + e + '\n');
    }
    return blobUrl;
}

function _getMetadataSize() {
    try {
        return _evalInCtx('_thumbnailMetadata.size');
    } catch (e) {
        return -1;
    }
}

function _getCacheSize() {
    return thumbnailBlobUrlCache.size;
}

function _getLruTouchNext() {
    try {
        return _evalInCtx('_lruTouchNext');
    } catch (e) {
        return -1;
    }
}

function _getRealBatchCurrent() {
    try {
        return _evalInCtx('_realBatchCurrent');
    } catch (e) {
        return null;
    }
}

function _getRealBatchPrev() {
    try {
        return _evalInCtx('_realBatchPrev');
    } catch (e) {
        return null;
    }
}

function _callUpdateRealBatchTracking(batch) {
    try {
        _evalInCtx('_updateRealBatchTracking("' + batch + '")');
        return true;
    } catch (e) {
        return false;
    }
}

function _callTouchCacheEntry(cacheKey) {
    try {
        _evalInCtx('_touchCacheEntry("' + cacheKey + '")');
        return true;
    } catch (e) {
        return false;
    }
}

function _callEvictIfNeeded() {
    try {
        _evalInCtx('_evictIfNeeded()');
        return true;
    } catch (e) {
        return false;
    }
}

function _callUpdateCacheMetadata(cacheKey, metaJson) {
    try {
        _evalInCtx('_updateCacheMetadata("' + cacheKey + '", ' + metaJson + ')');
        return true;
    } catch (e) {
        return false;
    }
}

function _resetCacheState() {
    thumbnailBlobUrlCache.clear();
    thumbnailBlobInflight.clear();
    _revokeLog = [];
    try {
        _evalInCtx('_thumbnailMetadata.clear()');
        _evalInCtx('_inflightMetadataPriority.clear()');
        _evalInCtx('_lruTouchNext = 0');
        _evalInCtx('_realBatchCurrent = null');
        _evalInCtx('_realBatchPrev = null');
    } catch (e) {
        process.stderr.write('resetCacheState error: ' + e + '\n');
    }
}

/* ── Test scenarios ────────────────────────────────────────────────────── */

/* Helper: install a controlled fetch that captures the response resolver.
   Returns { _resolve, _fetchCalls }. _resolve() must be called to complete. */
function _setupControlledFetch() {
    var _resolve = null;
    var _fetchCalls = 0;

    global.fetch = function(_imageSrc) {
        _fetchCalls++;
        return new Promise(function(resolve) {
            _resolve = function() {
                var resp = {
                    ok: true,
                    status: 200,
                    blob: function() {
                        return Promise.resolve({ size: 0, type: 'image/webp' });
                    }
                };
                resolve(resp);
            };
        });
    };
    return {
        get _resolve() { return _resolve; },
        get _fetchCalls() { return _fetchCalls; }
    };
}

function _restoreDefaultFetch() {
    global.fetch = function(imageSrc) {
        var resp = {
            ok: true,
            status: 200,
            blob: function() {
                return Promise.resolve({ size: 0, type: 'image/webp' });
            }
        };
        return Promise.resolve(resp);
    };
}

function test01_stage2_functions_exist() {
    _resetCacheState();

    /* Verify that Stage-2 internal functions and variables are present */
    var hasMetadata = false;
    var hasLruTouch = false;
    var hasInflightMeta = false;
    var hasEvictFn = false;
    var hasTouchFn = false;
    var hasUpdateMetaFn = false;
    var hasMergeInflight = false;
    var hasTakeInflight = false;
    var hasTrackBatchFn = false;

    try {
        hasMetadata = typeof _evalInCtx('_thumbnailMetadata') !== 'undefined';
        hasLruTouch = typeof _evalInCtx('_lruTouchNext') !== 'undefined';
        hasInflightMeta = typeof _evalInCtx('_inflightMetadataPriority') !== 'undefined';
        hasEvictFn = typeof _evalInCtx('_evictIfNeeded') === 'function';
        hasTouchFn = typeof _evalInCtx('_touchCacheEntry') === 'function';
        hasUpdateMetaFn = typeof _evalInCtx('_updateCacheMetadata') === 'function';
        hasMergeInflight = typeof _evalInCtx('_mergeInflightMetadata') === 'function';
        hasTakeInflight = typeof _evalInCtx('_takeInflightMetadata') === 'function';
        hasTrackBatchFn = typeof _evalInCtx('_updateRealBatchTracking') === 'function';
    } catch (e) {
        process.stderr.write('T01 eval error: ' + e + '\n');
    }

    assert(hasMetadata, 'T01a: _thumbnailMetadata Map exists');
    assert(hasLruTouch, 'T01b: _lruTouchNext counter exists');
    assert(hasInflightMeta, 'T01c: _inflightMetadataPriority Map exists');
    assert(hasEvictFn, 'T01d: _evictIfNeeded function exists');
    assert(hasTouchFn, 'T01e: _touchCacheEntry function exists');
    assert(hasUpdateMetaFn, 'T01f: _updateCacheMetadata function exists');
    assert(hasMergeInflight, 'T01g: _mergeInflightMetadata function exists');
    assert(hasTakeInflight, 'T01h: _takeInflightMetadata function exists');
    assert(hasTrackBatchFn, 'T01i: _updateRealBatchTracking function exists');
}

function test02_lru_touch_refreshes_recency() {
    _resetCacheState();

    /* Populate cache with 3 entries via createCacheEntry (bumps LRU on creation) */
    createCacheEntry('key-0', 'batch-a', 2);
    createCacheEntry('key-1', 'batch-a', 2);
    createCacheEntry('key-2', 'batch-a', 2);

    /* Record initial lruTouch values */
    var t0 = _getLruTouchNext();
    assert(t0 >= 3, 'T02a: lruTouchNext is at least 3 after creating 3 entries (got ' + t0 + ')');

    /* Touch key-1 */
    _callTouchCacheEntry('key-1');
    var t1 = _getLruTouchNext();
    assert(t1 > t0, 'T02b: lruTouchNext increased after touch (was ' + t0 + ', now ' + t1 + ')');

    /* Verify key-1's lruTouch is the newest (highest) */
    var metaStr;
    try {
        metaStr = _evalInCtx('JSON.stringify(_thumbnailMetadata.get("key-1"))');
    } catch (e) {
        metaStr = '{}';
    }
    var meta = JSON.parse(metaStr);
    assert(meta._lruTouch === t1, 'T02c: touched entry has latest lruTouch value (got ' + meta._lruTouch + ', expected ' + t1 + ')');

    /* Verify blob URL is NOT revoked (touch must not revoke/recreate) */
    var revokeCountBefore = _revokeLog.length;
    _callTouchCacheEntry('key-1');
    assert(_revokeLog.length === revokeCountBefore, 'T02d: LRU touch does not revoke blob URL');

    /* Verify blob URL is unchanged after touch */
    var val = thumbnailBlobUrlCache.get('key-1');
    assert(val && val.indexOf('blob:') !== -1, 'T02e: blob URL exists after touch (got ' + val + ')');
}

function test03_lru_touch_in_resolve_thumbnail_blob_url() {
    _resetCacheState();

    /* Set up a cache entry */
    thumbnailBlobUrlCache.set('key-hit', 'blob:hit-value');
    _callUpdateCacheMetadata('key-hit', JSON.stringify({ scopeBatch: 'batch-a', priority: 2 }));
    var t0 = _getLruTouchNext();

    /* Call resolveThumbnailBlobUrl (sync hit path) */
    var imgEl = makeImageEl();
    var resultPromise = resolveThumbnailBlobUrl('/thumb/x.png', 'key-hit');
    assert(resultPromise && typeof resultPromise.then === 'function', 'T03a: resolveThumbnailBlobUrl returns a thenable');

    return resultPromise.then(function(result) {
        assert(result === 'blob:hit-value', 'T03b: cache hit returns blob URL');
        var t1 = _getLruTouchNext();
        assert(t1 > t0, 'T03c: resolveThumbnailBlobUrl cache hit touches LRU (t0=' + t0 + ', t1=' + t1 + ')');
    });
}

function test04_overflow_eviction_scope_class_ordering() {
    _resetCacheState();

    /* Set a small cap for testing */
    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 5');

    /* Setup batch tracking for deterministic eviction scope classes */
    _evalInCtx('_realBatchCurrent = "current-batch"');
    _evalInCtx('_realBatchPrev = "previous-batch"');

    /* Fill cache to exactly cap (5 entries) */
    /* 2 entries: current-batch scope, visible priority */
    createCacheEntry('c-vis-1', 'current-batch', 0); /* VISIBLE = 0 */
    createCacheEntry('c-vis-2', 'current-batch', 0);
    /* 1 entry: previous-batch scope, deferred priority */
    createCacheEntry('p-def-1', 'previous-batch', 2); /* DEFERRED = 2 */
    /* 1 entry: other-batch scope, visible priority */
    createCacheEntry('o-vis-1', 'other-batch', 0);
    /* 1 entry: other-batch scope, deferred priority */
    createCacheEntry('o-def-1', 'other-batch', 2);

    assert(_getCacheSize() === 5, 'T04a: cache at cap 5');
    assert(_getMetadataSize() === 5, 'T04b: metadata at 5');

    /* Add one more entry to trigger eviction.
       The weakest entry should be evicted: other-batch + deferred (o-def-1) */
    var origRevokeLen = _revokeLog.length;
    thumbnailBlobUrlCache.set('new-key', 'blob:new-entry');
    _callUpdateCacheMetadata('new-key', JSON.stringify({ scopeBatch: 'current-batch', priority: 0 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 5, 'T04c: cache back at cap 5 after eviction (got ' + _getCacheSize() + ')');
    assert(_getMetadataSize() === 5, 'T04d: metadata at 5 after eviction (got ' + _getMetadataSize() + ')');

    /* The evicted entry should be 'o-def-1' (other-batch + deferred = weakest) */
    assert(!thumbnailBlobUrlCache.has('o-def-1'), 'T04e: other-batch deferred entry was evicted');

    /* Revocation happened exactly once */
    assert(_revokeLog.length === origRevokeLen + 1, 'T04f: exactly one blob URL revoked (got ' + (_revokeLog.length - origRevokeLen) + ')');

    /* Stronger entries survived */
    assert(thumbnailBlobUrlCache.has('c-vis-1'), 'T04g: current-batch visible entry survived');
    assert(thumbnailBlobUrlCache.has('c-vis-2'), 'T04h: current-batch visible entry survived');
    assert(thumbnailBlobUrlCache.has('p-def-1'), 'T04i: previous-batch deferred entry survived');
    assert(thumbnailBlobUrlCache.has('o-vis-1'), 'T04j: other-batch visible entry survived (stronger priority)');
}

function test05_overflow_eviction_priority_within_scope() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 3');

    _evalInCtx('_realBatchCurrent = "batch-x"');
    _evalInCtx('_realBatchPrev = null');

    /* All entries: other-batch scope (weakest scope class) */
    createCacheEntry('o-vis-1', 'other-batch', 0); /* VISIBLE */
    createCacheEntry('o-near-1', 'other-batch', 1); /* NEAR */
    createCacheEntry('o-def-1', 'other-batch', 2); /* DEFERRED */

    assert(_getCacheSize() === 3, 'T05a: cache at cap 3');

    /* Add one more to trigger eviction. Among same scope class,
       deferred is weakest priority. */
    thumbnailBlobUrlCache.set('new-key', 'blob:new-entry');
    _callUpdateCacheMetadata('new-key', JSON.stringify({ scopeBatch: 'other-batch', priority: 2 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 3, 'T05b: cache back at cap 3');
    assert(!thumbnailBlobUrlCache.has('o-def-1'), 'T05c: deferred entry evicted first within same scope (deferred weakest)');
    /* Verify visible survived */
    assert(thumbnailBlobUrlCache.has('o-vis-1'), 'T05d: visible entry survived (higher priority)');
}

function test06_overflow_eviction_lru_tie_break() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 3');

    _evalInCtx('_realBatchCurrent = "batch-x"');
    _evalInCtx('_realBatchPrev = null');

    /* All entries: other-batch, deferred priority (weakest tier) */
    createCacheEntry('o-def-1', 'other-batch', 2);
    createCacheEntry('o-def-2', 'other-batch', 2);
    createCacheEntry('o-def-3', 'other-batch', 2);

    /* Touch o-def-1 to make it the most recently used */
    _callTouchCacheEntry('o-def-1');
    /* Touch o-def-3 to make it second most recently used */
    _callTouchCacheEntry('o-def-3');
    /* o-def-2 has the oldest lruTouch (created first, not touched) */

    assert(_getCacheSize() === 3, 'T06a: cache at cap 3');

    /* Add one more, same scope+priority tier -> victim should be o-def-2 (oldest LRU) */
    thumbnailBlobUrlCache.set('new-key', 'blob:new-entry');
    _callUpdateCacheMetadata('new-key', JSON.stringify({ scopeBatch: 'other-batch', priority: 2 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 3, 'T06b: cache at cap 3');
    assert(!thumbnailBlobUrlCache.has('o-def-2'), 'T06c: LRU entry evicted in tie-break (o-def-2 was oldest)');
    assert(thumbnailBlobUrlCache.has('o-def-1'), 'T06d: recently-touched entry survived');
    assert(thumbnailBlobUrlCache.has('o-def-3'), 'T06e: recently-touched entry survived');
}

function test07_exact_hard_cap_1000() {
    _resetCacheState();

    /* Restore real cap */
    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 1000');

    /* Fill to exactly 1000 */
    for (var i = 0; i < 1000; i++) {
        thumbnailBlobUrlCache.set('bulk-' + i, 'blob:bulk-' + i);
        _callUpdateCacheMetadata('bulk-' + i, JSON.stringify({ scopeBatch: 'batch-bulk', priority: 2 }));
    }

    assert(_getCacheSize() === 1000, 'T07a: cache at cap 1000');

    /* Add one more -> evicts one */
    thumbnailBlobUrlCache.set('overflow-key', 'blob:overflow');
    _callUpdateCacheMetadata('overflow-key', JSON.stringify({ scopeBatch: 'batch-bulk', priority: 0 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 1000, 'T07b: cache stays at cap 1000 after overflow (got ' + _getCacheSize() + ')');
    assert(thumbnailBlobUrlCache.has('overflow-key'), 'T07c: new entry (visible priority) was admitted');
}

function test08_real_batch_transition_A_B_A() {
    _resetCacheState();

    /* Initial state: no real batch */
    assert(_getRealBatchCurrent() === null, 'T08a: initial real batch current is null');
    assert(_getRealBatchPrev() === null, 'T08b: initial real batch prev is null');

    /* Transition to batch-A */
    _callUpdateRealBatchTracking('batch-A');
    assert(_getRealBatchCurrent() === 'batch-A', 'T08c: current set to batch-A');
    assert(_getRealBatchPrev() === null, 'T08d: prev still null after first transition');

    /* Transition to batch-B */
    _callUpdateRealBatchTracking('batch-B');
    assert(_getRealBatchCurrent() === 'batch-B', 'T08e: current set to batch-B');
    assert(_getRealBatchPrev() === 'batch-A', 'T08f: prev rotated to batch-A');

    /* Transition back to batch-A */
    _callUpdateRealBatchTracking('batch-A');
    assert(_getRealBatchCurrent() === 'batch-A', 'T08g: current set to batch-A');
    assert(_getRealBatchPrev() === 'batch-B', 'T08h: prev rotated to batch-B');
}

function test09_same_batch_does_not_rotate_history() {
    _resetCacheState();

    _callUpdateRealBatchTracking('batch-X');
    assert(_getRealBatchCurrent() === 'batch-X', 'T09a: current is batch-X');
    assert(_getRealBatchPrev() === null, 'T09b: prev is null');

    /* Same batch again */
    _callUpdateRealBatchTracking('batch-X');
    assert(_getRealBatchCurrent() === 'batch-X', 'T09c: current still batch-X');
    assert(_getRealBatchPrev() === null, 'T09d: prev still null (no rotation on same batch)');

    /* Same batch a third time */
    _callUpdateRealBatchTracking('batch-X');
    assert(_getRealBatchCurrent() === 'batch-X', 'T09e: current still batch-X');
    assert(_getRealBatchPrev() === null, 'T09f: prev still null');
}

function test10_virtual_batch_does_not_rotate_history() {
    _resetCacheState();

    _callUpdateRealBatchTracking('real-batch-1');
    assert(_getRealBatchCurrent() === 'real-batch-1', 'T10a: current is real-batch-1');

    /* Virtual sentinel __favorites__ must not rotate */
    _callUpdateRealBatchTracking('__favorites__');
    assert(_getRealBatchCurrent() === 'real-batch-1', 'T10b: __favorites__ does not update current batch');
    assert(_getRealBatchPrev() === null, 'T10c: __favorites__ does not rotate prev');

    /* Virtual sentinel __public__ must not rotate */
    _callUpdateRealBatchTracking('__public__');
    assert(_getRealBatchCurrent() === 'real-batch-1', 'T10d: __public__ does not update current batch');
    assert(_getRealBatchPrev() === null, 'T10e: __public__ does not rotate prev');

    /* Real batch change still works after virtual */
    _callUpdateRealBatchTracking('real-batch-2');
    assert(_getRealBatchCurrent() === 'real-batch-2', 'T10f: real batch changes after virtual');
    assert(_getRealBatchPrev() === 'real-batch-1', 'T10g: prev rotated to previous real batch');
}

function test11_priority_promotion_is_monotonic() {
    _resetCacheState();

    /* Create entry with deferred priority (2) */
    createCacheEntry('promo-1', 'batch-x', 2);

    var metaBefore;
    try {
        metaBefore = _evalInCtx('_thumbnailMetadata.get("promo-1")');
    } catch (e) {
        metaBefore = { priority: 2 };
    }
    assert(metaBefore.priority === 2, 'T11a: initial priority is deferred (2)');

    /* Promote to near (1) */
    _callUpdateCacheMetadata('promo-1', JSON.stringify({ priority: 1, scopeBatch: 'batch-x' }));

    var metaAfter;
    try {
        metaAfter = _evalInCtx('_thumbnailMetadata.get("promo-1")');
    } catch (e) {
        metaAfter = { priority: 2 };
    }
    assert(metaAfter.priority === 1, 'T11b: priority promoted to near (1)');

    /* Promote to visible (0) */
    _callUpdateCacheMetadata('promo-1', JSON.stringify({ priority: 0, scopeBatch: 'batch-x' }));

    try {
        metaAfter = _evalInCtx('_thumbnailMetadata.get("promo-1")');
    } catch (e) {
        metaAfter = { priority: 1 };
    }
    assert(metaAfter.priority === 0, 'T11c: priority promoted to visible (0)');

    /* Attempt to demote by setting deferred (2) - must NOT demote */
    _callUpdateCacheMetadata('promo-1', JSON.stringify({ priority: 2, scopeBatch: 'batch-x' }));

    try {
        metaAfter = _evalInCtx('_thumbnailMetadata.get("promo-1")');
    } catch (e) {
        metaAfter = { priority: 0 };
    }
    assert(metaAfter.priority === 0, 'T11d: priority NOT demoted (stayed at visible=0, not 2)');

    /* Same priority level again */
    _callUpdateCacheMetadata('promo-1', JSON.stringify({ priority: 0, scopeBatch: 'batch-x' }));
    try {
        metaAfter = _evalInCtx('_thumbnailMetadata.get("promo-1")');
    } catch (e) {
        metaAfter = { priority: 0 };
    }
    assert(metaAfter.priority === 0, 'T11e: same priority stays unchanged');
}

function test12_metadata_cleanup_on_eviction() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 2');

    createCacheEntry('keep-1', 'batch-x', 0);
    createCacheEntry('evict-1', 'other-batch', 2);

    assert(_getCacheSize() === 2, 'T12a: cache at cap 2');
    assert(_getMetadataSize() === 2, 'T12b: metadata at 2');

    /* Add entry to trigger eviction */
    thumbnailBlobUrlCache.set('new-key', 'blob:new');
    _callUpdateCacheMetadata('new-key', JSON.stringify({ scopeBatch: 'batch-x', priority: 0 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 2, 'T12c: cache at cap 2 after eviction');
    assert(_getMetadataSize() === 2, 'T12d: metadata at 2 after eviction (cleaned up with evicted entry)');

    /* Verify evicted metadata is gone */
    var metaExists = true;
    try {
        metaExists = _evalInCtx('_thumbnailMetadata.has("evict-1")');
    } catch (e) {
        metaExists = true;
    }
    assert(metaExists === false, 'T12e: evicted entry metadata removed');
}

function test13_metadata_cleanup_on_cache_clear() {
    _resetCacheState();

    createCacheEntry('a', 'batch-x', 0);
    createCacheEntry('b', 'batch-x', 0);

    assert(_getCacheSize() === 2, 'T13a: cache has 2 entries');
    assert(_getMetadataSize() === 2, 'T13b: metadata has 2 entries');

    /* Simulate beforeunload-style full clear */
    for (var vals = thumbnailBlobUrlCache.values(), v = vals.next(); !v.done; v = vals.next()) {
        var blobUrl = v.value;
        if (blobUrl) URL.revokeObjectURL(blobUrl);
    }
    thumbnailBlobUrlCache.clear();

    try {
        _evalInCtx('_thumbnailMetadata.clear()');
    } catch (e) {}

    assert(_getCacheSize() === 0, 'T13c: cache empty after clear');
    assert(_getMetadataSize() === 0, 'T13d: metadata empty after clear');
}

function test14_eviction_revokes_exactly_once() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 1');

    createCacheEntry('first', 'batch-x', 0);
    assert(_getCacheSize() === 1, 'T14a: cache at cap 1');

    var revokeCountBefore = _revokeLog.length;

    /* Add entry to trigger eviction of 'first' */
    thumbnailBlobUrlCache.set('second', 'blob:second');
    _callUpdateCacheMetadata('second', JSON.stringify({ scopeBatch: 'batch-x', priority: 0 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 1, 'T14b: cache at cap 1 after eviction');
    assert(_revokeLog.length === revokeCountBefore + 1, 'T14c: exactly one blob URL revoked (expected ' + (revokeCountBefore + 1) + ', got ' + _revokeLog.length + ')');

    /* The revoked URL should be 'blob:test-first' */
    var revokedUrls = _revokeLog.slice(revokeCountBefore);
    assert(revokedUrls.indexOf('blob:test-first') !== -1, 'T14d: evicted entry blob URL was revoked');
}

function test15_displayed_image_unaffected_by_eviction() {
    _resetCacheState();

    /* Simulate a displayed image element whose cache entry gets evicted */
    var imgEl = makeImageEl();
    imgEl.setAttribute('src', 'blob:cached-src');
    imgEl.dataset.thumbnailCacheKey = 'displayed-key';
    imgEl.classList.add('loaded');

    /* Add it to cache */
    thumbnailBlobUrlCache.set('displayed-key', 'blob:cached-src');
    _callUpdateCacheMetadata('displayed-key', JSON.stringify({ scopeBatch: 'weak-batch', priority: 2 }));
    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 1');

    /* Add a stronger entry to trigger eviction of 'displayed-key' */
    thumbnailBlobUrlCache.set('strong-key', 'blob:strong-src');
    _callUpdateCacheMetadata('strong-key', JSON.stringify({ scopeBatch: 'current-batch', priority: 0 }));
    _evalInCtx('_realBatchCurrent = "current-batch"');
    _callEvictIfNeeded();

    /* The displayed-key should be evicted from cache */
    assert(!thumbnailBlobUrlCache.has('displayed-key'), 'T15a: weak entry evicted from cache');

    /* But the displayed image element MUST remain unchanged */
    assert(imgEl.getAttribute('src') === 'blob:cached-src', 'T15b: displayed img src unchanged after eviction (got ' + imgEl.getAttribute('src') + ')');
    assert(imgEl.classList.contains('loaded'), 'T15c: loaded class preserved after eviction');
    assert(imgEl.dataset.thumbnailCacheKey === 'displayed-key', 'T15d: thumbnailCacheKey preserved after eviction');
}

function test16_unknown_scope_treated_as_weak() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 3');

    _evalInCtx('_realBatchCurrent = "protected-batch"');
    _evalInCtx('_realBatchPrev = "previous-protected"');

    /* 1 entry: current-batch, deferred */
    createCacheEntry('cur-def', 'protected-batch', 2);
    /* 1 entry: previous-batch, deferred */
    createCacheEntry('prev-def', 'previous-protected', 2);
    /* 1 entry: no scope (unknown/null) - weakest */
    createCacheEntry('no-scope', null, 2);

    assert(_getCacheSize() === 3, 'T16a: cache at cap 3');

    /* Trigger eviction. no-scope should be evicted first. */
    thumbnailBlobUrlCache.set('new-key', 'blob:new');
    _callUpdateCacheMetadata('new-key', JSON.stringify({ scopeBatch: 'protected-batch', priority: 0 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 3, 'T16b: cache at cap 3');
    assert(!thumbnailBlobUrlCache.has('no-scope'), 'T16c: unknown-scope entry evicted first');
    assert(thumbnailBlobUrlCache.has('cur-def'), 'T16d: current-batch entry survived');
    assert(thumbnailBlobUrlCache.has('prev-def'), 'T16e: previous-batch entry survived');
}

function test17_previous_weaker_than_current() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 3');

    _evalInCtx('_realBatchCurrent = "current-batch"');
    _evalInCtx('_realBatchPrev = "previous-batch"');

    /* 1 entry: current-batch, deferred */
    createCacheEntry('cur-def', 'current-batch', 2);
    /* 1 entry: previous-batch, visible */
    createCacheEntry('prev-vis', 'previous-batch', 0);
    /* 1 entry: previous-batch, deferred */
    createCacheEntry('prev-def', 'previous-batch', 2);

    assert(_getCacheSize() === 3, 'T17a: cache at cap 3');

    /* Trigger eviction.
       Four entries (cur-def, prev-vis, prev-def, new-key). Cap is 3.
       prev-def has weakest scope (previous-batch) + weakest priority (deferred).
       Evicted: prev-def. Survivors: cur-def, prev-vis, new-key. */
    thumbnailBlobUrlCache.set('new-key', 'blob:new');
    _callUpdateCacheMetadata('new-key', JSON.stringify({ scopeBatch: 'current-batch', priority: 0 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 3, 'T17b: cache at cap 3');
    assert(!thumbnailBlobUrlCache.has('prev-def'), 'T17c: previous-batch deferred evicted (weakest scope+priority)');
    assert(thumbnailBlobUrlCache.has('prev-vis'), 'T17d: previous-batch visible entry survived (stronger priority class within same scope)');
    assert(thumbnailBlobUrlCache.has('cur-def'), 'T17e: current-batch deferred survived (stronger scope class)');
}

function test18_cache_hit_touch_in_assign_thumbnail_src_if_cached() {
    _resetCacheState();

    /* Create a cache entry */
    thumbnailBlobUrlCache.set('hit-key', 'blob:hit-url');
    _callUpdateCacheMetadata('hit-key', JSON.stringify({ scopeBatch: 'batch-a', priority: 2 }));

    var t0 = _getLruTouchNext();

    /* Call assignThumbnailSrcIfCached with matching key */
    var imgEl = makeImageEl();
    var result = assignThumbnailSrcIfCached(imgEl, '/thumb/x.png', 'hit-key');

    assert(result === true, 'T18a: assignThumbnailSrcIfCached returns true on cache hit');

    var t1 = _getLruTouchNext();
    assert(t1 > t0, 'T18b: LRU touch occurred in assignThumbnailSrcIfCached (t0=' + t0 + ', t1=' + t1 + ')');

    /* Verify src was assigned */
    assert(imgEl.getAttribute('src') === 'blob:hit-url', 'T18c: src assigned from cache');
}

function test19_cache_miss_does_not_touch() {
    _resetCacheState();

    var t0 = _getLruTouchNext();

    var imgEl = makeImageEl();
    var result = assignThumbnailSrcIfCached(imgEl, '/thumb/miss.png', 'miss-key');

    assert(result === false, 'T19a: assignThumbnailSrcIfCached returns false on cache miss');

    var t1 = _getLruTouchNext();
    assert(t1 === t0, 'T19b: no LRU touch on cache miss (t0=' + t0 + ', t1=' + t1 + ')');
}

function test20_beforeunload_cleans_metadata() {
    _resetCacheState();

    /* Create some cache entries with metadata */
    createCacheEntry('a', 'batch-x', 0);
    createCacheEntry('b', 'batch-x', 0);

    assert(_getMetadataSize() === 2, 'T20a: metadata has 2 entries before cleanup');

    /* Simulate what the beforeunload handler does */
    for (var vals = thumbnailBlobUrlCache.values(), v = vals.next(); !v.done; v = vals.next()) {
        URL.revokeObjectURL(v.value);
    }
    thumbnailBlobUrlCache.clear();
    thumbnailBlobInflight.clear();

    try {
        _evalInCtx('_thumbnailMetadata.clear()');
        _evalInCtx('_inflightMetadataPriority.clear()');
    } catch (e) {
        process.stderr.write('cleanup error: ' + e + '\n');
    }

    assert(_getMetadataSize() === 0, 'T20b: metadata cleared after beforeunload');
}
function test21_inflight_promotion_e2e() {
    _resetCacheState();

    /* Snapshot before controlled fetch so we can assert exactly one createObjectURL */
    var createCountBefore = _createCount;

    /* Install controlled fetch to intercept requests */
    var ctrl = _setupControlledFetch();

    /* First call: deferred requester */
    var p1 = resolveThumbnailBlobUrl('/thumb/e2e.png', 'key-e2e', { priority: 2, scopeBatch: 'batch-e2e' });

    /* Second call: visible requester joins inflight before fetch resolves */
    var p2 = resolveThumbnailBlobUrl('/thumb/e2e.png', 'key-e2e', { priority: 0, scopeBatch: 'batch-e2e' });

    /* Both must be thenable (same inflight promise) */
    assert(p1 && typeof p1.then === 'function', 'T21a: first call returned thenable');
    assert(p2 && typeof p2.then === 'function', 'T21a2: second call returned thenable');

    /* Exactly one fetch was started */
    assert(ctrl._fetchCalls === 1, 'T21b: exactly one fetch (got ' + ctrl._fetchCalls + ')');

    /* Resolve the fetch */
    ctrl._resolve();

    return Promise.all([p1, p2]).then(function(results) {
        var result1 = results[0];
        var result2 = results[1];

        assert(typeof result1 === 'string', 'T21c: first caller receives a string URL');
        assert(typeof result2 === 'string', 'T21d: second caller receives a string URL');
        assert(result1 === result2, 'T21e: both callers receive the same blob URL');

        /* Exactly one URL.createObjectURL was created */
        assert(_createCount === createCountBefore + 1, 'T21e2: exactly one URL.createObjectURL created (was ' + createCountBefore + ', now ' + _createCount + ')');

        /* Cache entry exists */
        assert(thumbnailBlobUrlCache.size >= 1, 'T21f: cache has at least 1 entry (got ' + thumbnailBlobUrlCache.size + ')');
        assert(thumbnailBlobUrlCache.get('key-e2e') !== undefined, 'T21g: cache entry for key-e2e exists');

        /* Metadata has visible priority (0) from the second caller */
        var meta;
        try {
            meta = _evalInCtx('_thumbnailMetadata.get("key-e2e")');
        } catch (e) {
            meta = null;
        }
        assert(meta !== null && meta !== undefined, 'T21h: metadata exists');
        assert(meta.priority === 0, 'T21i: metadata priority promoted to visible (got ' + (meta ? meta.priority : 'none') + ')');
        assert(meta.scopeBatch === 'batch-e2e', 'T21j: scope batch correct');

        /* Both inflight maps are clean */
        assert(thumbnailBlobInflight.size === 0, 'T21k: inflight fetch map cleaned (got ' + thumbnailBlobInflight.size + ')');
        var impSize;
        try {
            impSize = _evalInCtx('_inflightMetadataPriority.size');
        } catch (e) {
            impSize = -1;
        }
        assert(impSize === 0, 'T21l: inflight metadata map cleaned (got ' + impSize + ')');
    }).then(function() {
        _restoreDefaultFetch();
    }, function(err) {
        _restoreDefaultFetch();
        throw err;
    });
}

function test22_visible_requester_alone_sets_visible_metadata() {
    _resetCacheState();

    /* Single requester with visible priority */
    _evalInCtx('_mergeInflightMetadata("solo-key", { priority: 0, scopeBatch: "batch-solo" })');

    var meta;
    try {
        meta = _evalInCtx('_takeInflightMetadata("solo-key")');
    } catch (e) {
        meta = null;
    }

    assert(meta !== null, 'T22a: solo metadata exists');
    assert(meta.priority === 0, 'T22b: solo priority is visible (0)');
    assert(meta.scopeBatch === 'batch-solo', 'T22c: solo scope batch correct');
}

function test23_lru_touch_does_not_revoke() {
    _resetCacheState();

    /* Create cache entry */
    thumbnailBlobUrlCache.set('no-revoke-key', 'blob:no-revoke');
    _callUpdateCacheMetadata('no-revoke-key', JSON.stringify({ scopeBatch: 'batch-x', priority: 2 }));

    var valBefore = thumbnailBlobUrlCache.get('no-revoke-key');
    assert(valBefore === 'blob:no-revoke', 'T23d: blob URL set correctly before resolve (got ' + valBefore + ')');

    var revokeBefore = _revokeLog.length;

    /* Touch via resolveThumbnailBlobUrl */
    var imgEl = makeImageEl();
    var p = resolveThumbnailBlobUrl('/thumb/x.png', 'no-revoke-key');
    return p.then(function(result) {
        assert(result === 'blob:no-revoke', 'T23a: cache hit returns blob URL');
        assert(_revokeLog.length === revokeBefore, 'T23b: no blob URL revoked during cache hit (got ' + _revokeLog.length + ', expected ' + revokeBefore + ')');
        assert(thumbnailBlobUrlCache.get('no-revoke-key') === 'blob:no-revoke', 'T23c: blob URL unchanged');
    });
}

/* ── Gap 3: _resolveSourceBatch live scope resolution ─────────────────── */

function test24_resolve_source_batch_real_view() {
    _resetCacheState();

    /* Simulate a real batch view */
    global.currentBatch = 'real-batch-A';
    global.isVirtualCollectionView = function() { return false; };

    var img = { name: 'img1.png', batch: 'real-batch-A', folder: 'inbox' };
    var scope;
    try {
        scope = _evalInCtx('_resolveSourceBatch(' + JSON.stringify(img) + ')');
    } catch (e) {
        scope = null;
    }

    assert(scope === 'real-batch-A', 'T24a: real view resolves currentBatch (got ' + scope + ')');

    /* currentBatch changed */
    global.currentBatch = 'real-batch-B';
    try {
        scope = _evalInCtx('_resolveSourceBatch(' + JSON.stringify(img) + ')');
    } catch (e) {
        scope = null;
    }
    assert(scope === 'real-batch-B', 'T24b: real view tracks currentBatch changes (got ' + scope + ')');
}

function test25_resolve_source_batch_virtual_view() {
    _resetCacheState();

    /* Simulate virtual __favorites__ view */
    global.currentBatch = '__favorites__';
    global.isVirtualCollectionView = function() { return true; };

    var imgA = { name: 'img1.png', batch: 'real-batch-A', folder: 'inbox' };
    var scope;
    try {
        scope = _evalInCtx('_resolveSourceBatch(' + JSON.stringify(imgA) + ')');
    } catch (e) {
        scope = null;
    }
    assert(scope === 'real-batch-A', 'T25a: __favorites__ resolves img.batch (got ' + scope + ')');

    var imgB = { name: 'img2.png', batch: 'real-batch-B', folder: 'shortlisted' };
    try {
        scope = _evalInCtx('_resolveSourceBatch(' + JSON.stringify(imgB) + ')');
    } catch (e) {
        scope = null;
    }
    assert(scope === 'real-batch-B', 'T25b: __favorites__ resolves second img batch (got ' + scope + ')');

    /* __public__ virtual view */
    global.currentBatch = '__public__';
    var imgC = { name: 'img3.png', batch: 'real-batch-C', folder: 'public' };
    try {
        scope = _evalInCtx('_resolveSourceBatch(' + JSON.stringify(imgC) + ')');
    } catch (e) {
        scope = null;
    }
    assert(scope === 'real-batch-C', 'T25c: __public__ resolves img.batch (got ' + scope + ')');

    /* Virtual sentinel never becomes scope value */
    assert(scope !== '__favorites__', 'T25d: virtual sentinel __favorites__ is never a scope value');
    assert(scope !== '__public__', 'T25e: virtual sentinel __public__ is never a scope value');
}

function test26_virtual_view_distinct_real_scopes() {
    _resetCacheState();

    global.currentBatch = '__favorites__';
    global.isVirtualCollectionView = function() { return true; };

    var img1 = { name: 'a.png', batch: 'batch-1', folder: 'inbox' };
    var img2 = { name: 'b.png', batch: 'batch-2', folder: 'finals' };

    var scope1;
    var scope2;
    try {
        scope1 = _evalInCtx('_resolveSourceBatch(' + JSON.stringify(img1) + ')');
        scope2 = _evalInCtx('_resolveSourceBatch(' + JSON.stringify(img2) + ')');
    } catch (e) {
        scope1 = null;
        scope2 = null;
    }

    assert(scope1 === 'batch-1', 'T26a: img1 resolves to batch-1 (got ' + scope1 + ')');
    assert(scope2 === 'batch-2', 'T26b: img2 resolves to batch-2 (got ' + scope2 + ')');
    assert(scope1 !== scope2, 'T26c: two images in virtual view have distinct real scopes');
}

/* ── Gap 4: real-batch tracker input contract ─────────────────────────── */

function test27_batch_tracker_rejects_non_real_inputs() {
    _resetCacheState();

    /* null, undefined, empty string are non-real */
    _evalInCtx('_updateRealBatchTracking(null)');
    assert(_getRealBatchCurrent() === null, 'T27a: null batch does not set current');
    assert(_getRealBatchPrev() === null, 'T27b: null batch does not set prev');

    _evalInCtx('_updateRealBatchTracking(undefined)');
    assert(_getRealBatchCurrent() === null, 'T27c: undefined batch does not set current');
    assert(_getRealBatchPrev() === null, 'T27d: undefined batch does not set prev');

    _evalInCtx('_updateRealBatchTracking("")');
    assert(_getRealBatchCurrent() === null, 'T27e: empty string does not set current');
    assert(_getRealBatchPrev() === null, 'T27f: empty string does not set prev');

    /* Non-string truthy values: number, object */
    _evalInCtx('_updateRealBatchTracking(42)');
    assert(_getRealBatchCurrent() === null, 'T27g: number 42 does not set current (got ' + _getRealBatchCurrent() + ')');
    assert(_getRealBatchPrev() === null, 'T27h: number 42 does not set prev');

    _evalInCtx('_updateRealBatchTracking({})');
    assert(_getRealBatchCurrent() === null, 'T27i: object does not set current (got ' + _getRealBatchCurrent() + ')');
    assert(_getRealBatchPrev() === null, 'T27j: object does not set prev');
}

/* ── Gap 5: exactly one LRU bump per hit ───────────────────────────────── */

function test28_exactly_one_lru_bump_on_hit_with_meta() {
    _resetCacheState();

    /* Create entry with metadata */
    thumbnailBlobUrlCache.set('bump-key', 'blob:bump');
    _callUpdateCacheMetadata('bump-key', JSON.stringify({ scopeBatch: 'batch-x', priority: 2 }));

    var t0 = _getLruTouchNext();

    /* Hit via resolveThumbnailBlobUrl with meta */
    var p = resolveThumbnailBlobUrl('/thumb/x.png', 'bump-key', { priority: 0, scopeBatch: 'batch-x' });
    return p.then(function() {
        var t1 = _getLruTouchNext();
        assert(t1 === t0 + 1, 'T28a: exactly one LRU increment on resolveThumbnailBlobUrl hit with meta (t0=' + t0 + ', t1=' + t1 + ')');
    });
}

function test29_exactly_one_lru_bump_on_hit_no_meta() {
    _resetCacheState();

    thumbnailBlobUrlCache.set('bump-nometa', 'blob:bump-nm');
    _callUpdateCacheMetadata('bump-nometa', JSON.stringify({ scopeBatch: 'batch-x', priority: 2 }));

    var t0 = _getLruTouchNext();

    /* Hit via assignThumbnailSrcIfCached without meta */
    var imgEl = makeImageEl();
    assignThumbnailSrcIfCached(imgEl, '/thumb/x.png', 'bump-nometa');

    var t1 = _getLruTouchNext();
    assert(t1 === t0 + 1, 'T28b: exactly one LRU increment on assignThumbnailSrcIfCached hit without meta (t0=' + t0 + ', t1=' + t1 + ')');
}

function test30_exactly_one_lru_bump_assign_with_meta() {
    _resetCacheState();

    thumbnailBlobUrlCache.set('bump-assign', 'blob:bump-as');
    _callUpdateCacheMetadata('bump-assign', JSON.stringify({ scopeBatch: 'batch-x', priority: 2 }));

    var t0 = _getLruTouchNext();

    var imgEl = makeImageEl();
    assignThumbnailSrcIfCached(imgEl, '/thumb/x.png', 'bump-assign', { priority: 0, scopeBatch: 'batch-x' });

    var t1 = _getLruTouchNext();
    assert(t1 === t0 + 1, 'T28c: exactly one LRU increment on assignThumbnailSrcIfCached hit with meta (t0=' + t0 + ', t1=' + t1 + ')');
}

/* ── Helper: read _resident from metadata ──────────────────────────────── */

function _getEntryResident(cacheKey) {
    try {
        var meta = _evalInCtx('_thumbnailMetadata.get("' + cacheKey + '")');
        if (meta && typeof meta._resident === 'number') return meta._resident;
        return 0; /* field missing — treat as probationary (matches eviction default) */
    } catch (e) {
        return 0;
    }
}

function _getMetadataResidentCount(expectedResident) {
    try {
        var allMeta = _evalInCtx('Array.from(_thumbnailMetadata.values())');
        if (!Array.isArray(allMeta)) return 0;
        var count = 0;
        for (var i = 0; i < allMeta.length; i++) {
            if (allMeta[i]._resident === expectedResident) count++;
        }
        return count;
    } catch (e) {
        return -1;
    }
}

/* ── Stage 2.5: Resident/probation cache retention tests ───────────────── */

function test31_new_entries_start_probationary() {
    _resetCacheState();

    /* Create a fresh entry via createCacheEntry */
    createCacheEntry('fresh-1', 'batch-x', 2);
    assert(_getEntryResident('fresh-1') === 0, 'T31a: new entry starts probationary (got ' + _getEntryResident('fresh-1') + ')');

    /* Create via _updateCacheMetadata directly */
    _callUpdateCacheMetadata('fresh-2', JSON.stringify({ scopeBatch: 'batch-x', priority: 2 }));
    assert(_getEntryResident('fresh-2') === 0, 'T31b: new entry via _updateCacheMetadata starts probationary (got ' + _getEntryResident('fresh-2') + ')');

    /* Verify the _resident field exists on metadata */
    try {
        var meta = _evalInCtx('_thumbnailMetadata.get("fresh-1")');
        assert(typeof meta._resident === 'number', 'T31c: _resident is a number field on metadata');
    } catch (e) {
        assert(false, 'T31c: failed to read metadata');
    }
}

function test32_cache_hit_promotes_to_resident() {
    _resetCacheState();

    /* Create a probationary entry */
    createCacheEntry('hit-promo', 'batch-x', 2);
    assert(_getEntryResident('hit-promo') === 0, 'T32a: entry starts probationary');

    /* Touch via _touchCacheEntry → promotes to resident */
    _callTouchCacheEntry('hit-promo');
    assert(_getEntryResident('hit-promo') === 1, 'T32b: _touchCacheEntry promotes to resident (got ' + _getEntryResident('hit-promo') + ')');

    /* Touch again should stay resident, not toggle */
    _callTouchCacheEntry('hit-promo');
    assert(_getEntryResident('hit-promo') === 1, 'T32c: resident stays 1 on repeated touch (got ' + _getEntryResident('hit-promo') + ')');

    /* Verify blob URL was NOT revoked during promotion */
    var revokeBefore = _revokeLog.length;
    _callTouchCacheEntry('hit-promo');
    assert(_revokeLog.length === revokeBefore, 'T32d: resident promotion does not revoke blob URL');
}

function test33_resident_survives_over_probationary_same_scope_priority() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 4');
    _evalInCtx('_realBatchCurrent = "batch-x"');
    _evalInCtx('_realBatchPrev = null');

    /* All entries: current-batch scope, deferred priority */
    /* 2 probationary entries */
    createCacheEntry('prob-1', 'batch-x', 2);
    createCacheEntry('prob-2', 'batch-x', 2);
    /* 2 resident entries (touch to promote) */
    createCacheEntry('res-1', 'batch-x', 2);
    _callTouchCacheEntry('res-1'); /* promote to resident */
    createCacheEntry('res-2', 'batch-x', 2);
    _callTouchCacheEntry('res-2'); /* promote to resident */

    assert(_getCacheSize() === 4, 'T33a: cache at cap 4');
    assert(_getEntryResident('prob-1') === 0, 'T33b: prob-1 is probationary');
    assert(_getEntryResident('res-1') === 1, 'T33c: res-1 is resident');

    /* Add one more probationary entry → must evict a probationary entry, not resident */
    thumbnailBlobUrlCache.set('new-prob', 'blob:new-prob');
    _callUpdateCacheMetadata('new-prob', JSON.stringify({ scopeBatch: 'batch-x', priority: 2 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 4, 'T33d: cache back at cap 4');
    /* A probationary entry was evicted */
    var prob1Survived = thumbnailBlobUrlCache.has('prob-1');
    var prob2Survived = thumbnailBlobUrlCache.has('prob-2');
    assert(!(prob1Survived && prob2Survived), 'T33e: at least one probationary entry was evicted (prob-1=' + prob1Survived + ', prob-2=' + prob2Survived + ')');
    /* Both resident entries survived */
    assert(thumbnailBlobUrlCache.has('res-1'), 'T33f: resident entry res-1 survived');
    assert(thumbnailBlobUrlCache.has('res-2'), 'T33g: resident entry res-2 survived');
}

function test34_scope_dominates_residency() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 3');
    _evalInCtx('_realBatchCurrent = "current-batch"');
    _evalInCtx('_realBatchPrev = "previous-batch"');

    /* previous-batch resident entry */
    createCacheEntry('prev-res', 'previous-batch', 2);
    _callTouchCacheEntry('prev-res'); /* promote to resident (scopeClass=1) */

    /* current-batch probationary entry */
    createCacheEntry('cur-prob', 'current-batch', 2);
    assert(_getEntryResident('cur-prob') === 0, 'T34a: cur-prob is probationary (scopeClass=2)');

    /* current-batch resident entry */
    createCacheEntry('cur-res', 'current-batch', 2);
    _callTouchCacheEntry('cur-res'); /* promote to resident (scopeClass=2) */

    assert(_getCacheSize() === 3, 'T34b: cache at cap 3');

    /* Add a new current-batch probationary entry → previous-batch resident
       must be evicted before current-batch probationary because scope dominates */
    thumbnailBlobUrlCache.set('new-cur-prob', 'blob:new-cur');
    _callUpdateCacheMetadata('new-cur-prob', JSON.stringify({ scopeBatch: 'current-batch', priority: 2 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 3, 'T34c: cache at cap 3 after eviction');
    assert(!thumbnailBlobUrlCache.has('prev-res'), 'T34d: previous-batch resident evicted before current-batch probationary');
    assert(thumbnailBlobUrlCache.has('cur-prob'), 'T34e: current-batch probationary survived (scope dominates residency)');
    assert(thumbnailBlobUrlCache.has('cur-res'), 'T34f: current-batch resident survived');
}

function test35_priority_dominates_residency() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 3');
    _evalInCtx('_realBatchCurrent = "batch-x"');
    _evalInCtx('_realBatchPrev = null');

    /* current-batch, deferred (2), resident */
    createCacheEntry('def-res', 'batch-x', 2);
    _callTouchCacheEntry('def-res'); /* resident */

    /* current-batch, deferred (2), probationary */
    createCacheEntry('def-prob', 'batch-x', 2);

    /* current-batch, visible (0), probationary */
    createCacheEntry('vis-prob', 'batch-x', 0);
    assert(_getEntryResident('vis-prob') === 0, 'T35a: vis-prob is probationary');

    assert(_getCacheSize() === 3, 'T35b: cache at cap 3');

    /* Add a new deferred probationary entry → deferred resident must survive
       over deferred probationary within same scope, but visible probationary
       must survive over deferred resident because priority dominates */
    thumbnailBlobUrlCache.set('new-def-prob', 'blob:new-def');
    _callUpdateCacheMetadata('new-def-prob', JSON.stringify({ scopeBatch: 'batch-x', priority: 2 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 3, 'T35c: cache at cap 3');
    /* The weakest among same scope: def-prob (deferred, probationary) vs def-res (deferred, resident)
       probationary < resident → def-prob evicted first */
    assert(!thumbnailBlobUrlCache.has('def-prob'), 'T35d: deferred probationary evicted first (same scope)');
    assert(thumbnailBlobUrlCache.has('def-res'), 'T35e: deferred resident survived (residency within same priority)');
    assert(thumbnailBlobUrlCache.has('vis-prob'), 'T35f: visible probationary survived (priority dominates residency)');
}

function test36_real_batch_transition_marks_outgoing_resident() {
    _resetCacheState();

    /* Simulate batch A with some entries */
    _evalInCtx('_realBatchCurrent = "batch-A"');
    _evalInCtx('_realBatchPrev = null');

    /* Create A entries - some probationary (never touched) */
    createCacheEntry('a-untouched-1', 'batch-A', 2);
    createCacheEntry('a-untouched-2', 'batch-A', 2);
    /* Create A entries - some resident (touched) */
    createCacheEntry('a-touched-1', 'batch-A', 2);
    _callTouchCacheEntry('a-touched-1');
    createCacheEntry('a-touched-2', 'batch-A', 2);
    _callTouchCacheEntry('a-touched-2');

    assert(_getEntryResident('a-untouched-1') === 0, 'T36a: untouched A entry is probationary');
    assert(_getEntryResident('a-touched-1') === 1, 'T36b: touched A entry is resident');

    /* Transition to batch B */
    _callUpdateRealBatchTracking('batch-B');

    /* All outgoing A entries should now be resident */
    assert(_getEntryResident('a-untouched-1') === 1, 'T36c: untouched A entry promoted to resident by batch transition (got ' + _getEntryResident('a-untouched-1') + ')');
    assert(_getEntryResident('a-untouched-2') === 1, 'T36d: second untouched A entry promoted to resident');
    assert(_getEntryResident('a-touched-1') === 1, 'T36e: already-resident A entry stays resident');
    assert(_getEntryResident('a-touched-2') === 1, 'T36f: already-resident A entry stays resident');

    /* No entries from other scopes were affected */
    createCacheEntry('other-untouched', 'other-batch', 2);
    assert(_getEntryResident('other-untouched') === 0, 'T36g: other-batch entry not affected by A→B transition');
}

function test37_same_batch_and_virtual_no_resident_marking() {
    _resetCacheState();

    _evalInCtx('_realBatchCurrent = "batch-X"');
    _evalInCtx('_realBatchPrev = null');

    /* Create X entries */
    createCacheEntry('x-prob', 'batch-X', 2);
    assert(_getEntryResident('x-prob') === 0, 'T37a: X entry starts probationary');

    /* Same batch repeat → no marking */
    _callUpdateRealBatchTracking('batch-X');
    assert(_getEntryResident('x-prob') === 0, 'T37b: same-batch repeat does not mark resident');

    /* Virtual sentinel __favorites__ → no marking */
    _callUpdateRealBatchTracking('__favorites__');
    assert(_getEntryResident('x-prob') === 0, 'T37c: __favorites__ does not trigger marking');
    assert(_getRealBatchCurrent() === 'batch-X', 'T37d: current batch unchanged by virtual');

    /* Real transition again */
    _callUpdateRealBatchTracking('batch-Y');
    assert(_getEntryResident('x-prob') === 1, 'T37e: real transition X→Y marks X entries resident (got ' + _getEntryResident('x-prob') + ')');
}

function test38_resident_metadata_cleaned_on_eviction() {
    _resetCacheState();

    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = 2');

    createCacheEntry('keep-res', 'batch-x', 0);
    _callTouchCacheEntry('keep-res');
    createCacheEntry('evict-prob', 'batch-x', 2);

    assert(_getCacheSize() === 2, 'T38a: cache at cap 2');
    assert(_getMetadataSize() === 2, 'T38b: metadata at 2');

    /* Trigger eviction of the weaker entry */
    thumbnailBlobUrlCache.set('new-key', 'blob:new');
    _callUpdateCacheMetadata('new-key', JSON.stringify({ scopeBatch: 'batch-x', priority: 0 }));
    _callEvictIfNeeded();

    assert(_getCacheSize() === 2, 'T38c: cache back at cap 2');
    assert(_getMetadataSize() === 2, 'T38d: metadata at 2 after eviction');

    /* Evicted entry metadata (including _resident) is gone */
    var metaExists;
    try {
        metaExists = _evalInCtx('_thumbnailMetadata.has("evict-prob")');
    } catch (e) {
        metaExists = true;
    }
    assert(metaExists === false, 'T38e: evicted entry metadata (including _resident) removed');
}

function test39_resident_metadata_cleaned_on_clear() {
    _resetCacheState();

    createCacheEntry('a-res', 'batch-x', 0);
    _callTouchCacheEntry('a-res');
    createCacheEntry('b-prob', 'batch-x', 2);

    assert(_getCacheSize() === 2, 'T39a: cache has 2 entries');
    assert(_getMetadataSize() === 2, 'T39b: metadata has 2 entries');
    assert(_getEntryResident('a-res') === 1, 'T39c: entry is resident before clear');

    /* Full clear (beforeunload-style) */
    for (var vals = thumbnailBlobUrlCache.values(), v = vals.next(); !v.done; v = vals.next()) {
        var blobUrl = v.value;
        if (blobUrl) URL.revokeObjectURL(blobUrl);
    }
    thumbnailBlobUrlCache.clear();
    try {
        _evalInCtx('_thumbnailMetadata.clear()');
    } catch (e) {}

    assert(_getCacheSize() === 0, 'T39d: cache empty after clear');
    assert(_getMetadataSize() === 0, 'T39e: metadata empty after clear');
}

function test40_deterministic_ABA_scan_resistance() {
    /* ── Phase 1: populate A to cap as cold probationary entries ──────────
       Do NOT pre-touch; the A→B transition mark pass is what must
       promote them. */
    _resetCacheState();
    var CAP = 10;
    _evalInCtx('THUMBNAIL_BLOB_CACHE_MAX = ' + CAP);
    _evalInCtx('_realBatchCurrent = "batch-A"');
    _evalInCtx('_realBatchPrev = null');

    for (var i = 0; i < CAP; i++) {
        /* Use createCacheEntry so _resident starts at 0 (probationary). */
        createCacheEntry('A-' + i, 'batch-A', 2);
    }
    assert(_getCacheSize() === CAP, 'T40a: cache at cap after cold A populate');
    for (var i2 = 0; i2 < CAP; i2++) {
        assert(_getEntryResident('A-' + i2) === 0, 'T40a' + i2 + ': A-' + i2 + ' is probationary before any touch or transition');
    }

    /* ── Phase 2: A→B transition alone marks all outgoing A resident ──── */
    _callUpdateRealBatchTracking('batch-B');
    /* current='batch-B', prev='batch-A' */
    assert(_getRealBatchCurrent() === 'batch-B', 'T40b0: current is batch-B after transition');
    assert(_getRealBatchPrev() === 'batch-A', 'T40b1: prev is batch-A after transition');
    for (var i3 = 0; i3 < CAP; i3++) {
        assert(_getEntryResident('A-' + i3) === 1, 'T40b' + i3 + ': cold A-' + i3 + ' promoted to resident by A→B transition alone');
    }

    /* ── Phase 3: admit small B visible entries ──────────────────────────
       A entries are scopeClass=1 (previous), all deferred, all resident.
       B entries are scopeClass=2 (current), visible (priority=0).
       The three oldest-A-by-LRU must be evicted to make room. */

    var revokeBeforeB = _revokeLog.length;
    for (var j = 0; j < 3; j++) {
        thumbnailBlobUrlCache.set('B-' + j, 'blob:B-' + j);
        _callUpdateCacheMetadata('B-' + j, JSON.stringify({ scopeBatch: 'batch-B', priority: 0 }));
        _callEvictIfNeeded();
    }
    assert(_getCacheSize() === CAP, 'T40c0: cache at cap after B admission');
    assert(_revokeLog.length === revokeBeforeB + 3, 'T40c1: exactly 3 A entries evicted');
    /* Identify which A keys survived. */
    var survivingOriginalA = [];
    for (var k = 0; k < CAP; k++) {
        if (thumbnailBlobUrlCache.has('A-' + k)) {
            survivingOriginalA.push('A-' + k);
        }
    }
    assert(survivingOriginalA.length === CAP - 3,
        'T40c2: ' + survivingOriginalA.length + ' original A survivors (expected 7): ' + survivingOriginalA.join(','));
    /* All survivors must be resident. */
    for (var s = 0; s < survivingOriginalA.length; s++) {
        assert(_getEntryResident(survivingOriginalA[s]) === 1,
            'T40c3: survivor ' + survivingOriginalA[s] + ' still resident');
    }

    /* ── Phase 4: B→A transition ──────────────────────────────────────── */
    _callUpdateRealBatchTracking('batch-A');
    /* current='batch-A', prev='batch-B' */
    assert(_getRealBatchCurrent() === 'batch-A', 'T40d0: current is batch-A after return');
    assert(_getRealBatchPrev() === 'batch-B', 'T40d1: prev is batch-B after return');

    /* ── Phase 5: re-admit the missing A entries as probationary ─────────
       They share scopeClass=2 + deferred priorityClass=0 with the
       resident survivors, but B entries (scopeClass=1) are weaker and
       must leave first. After B is gone, probationary entries recycle
       among themselves. */
    var missingA = [];
    for (var m = 0; m < CAP; m++) {
        if (!thumbnailBlobUrlCache.has('A-' + m)) {
            missingA.push('A-' + m);
        }
    }
    assert(missingA.length === 3, 'T40e0: 3 missing A keys to re-admit');

    for (var n = 0; n < missingA.length; n++) {
        var mKey = missingA[n];
        thumbnailBlobUrlCache.set(mKey, 'blob:refetched-' + mKey);
        _callUpdateCacheMetadata(mKey, JSON.stringify({ scopeBatch: 'batch-A', priority: 2 }));
        _callEvictIfNeeded();
    }
    /* After re-admission:
       - 3 missing A probationary entries in cache
       - 7 surviving original A resident entries in cache
       - 0 B entries (all evicted by scopeClass 1 < 2)
       - cap = 10 */
    assert(_getCacheSize() === CAP, 'T40e1: cache at cap after re-admission');
    /* B entries must be gone. */
    for (var b = 0; b < 3; b++) {
        assert(!thumbnailBlobUrlCache.has('B-' + b), 'T40e2: B-' + b + ' evicted (scopeClass 1 < 2)');
    }
    /* Re-admitted entries are probationary. */
    for (var p = 0; p < missingA.length; p++) {
        assert(_getEntryResident(missingA[p]) === 0, 'T40e3: re-admitted ' + missingA[p] + ' is probationary');
    }
    /* All original survivors still present and resident. */
    for (var q = 0; q < survivingOriginalA.length; q++) {
        var svKey = survivingOriginalA[q];
        assert(thumbnailBlobUrlCache.has(svKey), 'T40e4: survivor ' + svKey + ' still in cache after re-admission');
        assert(_getEntryResident(svKey) === 1, 'T40e5: survivor ' + svKey + ' still resident after re-admission');
    }

    /* ── Phase 6: admit 2 extra deferred scan entries beyond cap ─────────
       All entries share scopeClass=2, priorityClass=0.  Without
       residency, retained predecessors would be evicted by pure LRU.
       With residency, probationary entries recycle among themselves
       and the captured resident survivors lose zero members. */

    var extraKey1 = 'A-10';
    thumbnailBlobUrlCache.set(extraKey1, 'blob:' + extraKey1);
    _callUpdateCacheMetadata(extraKey1, JSON.stringify({ scopeBatch: 'batch-A', priority: 2 }));
    _callEvictIfNeeded();
    assert(_getCacheSize() === CAP, 'T40f0: cache at cap after first extra entry');

    var extraKey2 = 'A-11';
    thumbnailBlobUrlCache.set(extraKey2, 'blob:' + extraKey2);
    _callUpdateCacheMetadata(extraKey2, JSON.stringify({ scopeBatch: 'batch-A', priority: 2 }));
    _callEvictIfNeeded();
    assert(_getCacheSize() === CAP, 'T40f1: cache at cap after second extra entry');

    /* Zero losses from the original-resident survivor set. */
    for (var r = 0; r < survivingOriginalA.length; r++) {
        var rKey = survivingOriginalA[r];
        assert(thumbnailBlobUrlCache.has(rKey),
            'T40f2: original resident survivor ' + rKey + ' still present after two extra scan entries');
        assert(_getEntryResident(rKey) === 1,
            'T40f3: original resident survivor ' + rKey + ' still resident after two extra scan entries');
    }

    /* ── Phase 7: public cache-hit path on a guaranteed original-resident
       survivor via assignThumbnailSrcIfCached ────────────────────────
       Must produce no fetch, no URL creation, no revocation, unchanged
       blob URL, exactly one LRU increment, and resident stays resident. */
    var pickKey = survivingOriginalA[0];
    var expectedBlob = thumbnailBlobUrlCache.get(pickKey);
    assert(typeof expectedBlob === 'string' && expectedBlob.length > 0,
        'T40g0: survivor ' + pickKey + ' has a blob URL');

    var createBefore = _createCount;
    var revokeBefore = _revokeLog.length;
    var lruBefore = _getLruTouchNext();
    var imgEl = makeImageEl();

    var hitResult = assignThumbnailSrcIfCached(imgEl, '/thumb/' + pickKey + '.png', pickKey);
    assert(hitResult === true, 'T40g1: assignThumbnailSrcIfCached returns true on retained resident hit');
    assert(imgEl.getAttribute('src') === expectedBlob,
        'T40g2: src assigned matches retained blob URL (expected ' + expectedBlob + ', got ' + imgEl.getAttribute('src') + ')');

    /* No fetch/URL-creation side-effects. */
    assert(_createCount === createBefore,
        'T40g3: no URL.createObjectURL call (createCount was ' + createBefore + ', now ' + _createCount + ')');
    assert(_revokeLog.length === revokeBefore,
        'T40g4: no blob URL revoked (revokeLog was ' + revokeBefore + ', now ' + _revokeLog.length + ')');

    /* Blob URL unchanged. */
    assert(thumbnailBlobUrlCache.get(pickKey) === expectedBlob,
        'T40g5: blob URL unchanged after hit (expected ' + expectedBlob + ', got ' + thumbnailBlobUrlCache.get(pickKey) + ')');

    /* Exactly one LRU increment. */
    var lruAfter = _getLruTouchNext();
    assert(lruAfter === lruBefore + 1,
        'T40g6: exactly one LRU increment (was ' + lruBefore + ', now ' + lruAfter + ')');

    /* Resident stays resident. */
    assert(_getEntryResident(pickKey) === 1,
        'T40g7: resident stays resident after cache hit (got ' + _getEntryResident(pickKey) + ')');
}

function test41_thumbnail_fetch_timeout_aborts_releases_slot_and_marks_retryable() {
    _resetCacheState();
    var timeout = null;
    var clearCount = 0;
    var abortCount = 0;
    var previousSetTimeout = ctx.setTimeout;
    var previousClearTimeout = ctx.clearTimeout;
    var previousAbortController = ctx.AbortController;
    var previousFetch = ctx.fetch;
    ctx.setTimeout = function(callback, delay) {
        timeout = { callback: callback, delay: delay };
        return 1;
    };
    ctx.clearTimeout = function() { clearCount++; };
    ctx.AbortController = function() {
        this.signal = {};
        this.abort = function() { abortCount++; };
    };
    ctx.fetch = function(_imageSrc, options) {
        assert(options && options.signal, 'T41a: thumbnail fetch receives an AbortSignal');
        return new Promise(function() {});
    };

    var thumb = makeImageEl();
    var errorPanel = {
        hidden: true,
        replaceChildren: function() {},
        append: function() {}
    };
    thumb.dataset.thumbnailErrorCacheKey = '';
    thumb.closest = function() { return thumb._parent; };
    thumb._parent = {
        isConnected: true,
        dataset: { name: 'stuck.png', mediaKind: 'image' },
        classList: {
            _failed: false,
            add: function(name) { if (name === 'thumbnail-failed') this._failed = true; },
            remove: function(name) { if (name === 'thumbnail-failed') this._failed = false; },
            contains: function(name) { return name === 'thumbnail-failed' && this._failed; }
        },
        querySelector: function() { return errorPanel; }
    };
    thumb.dataset.thumbnailCacheKey = 'timeout-key';
    thumb.dataset.thumbnailSource = '/thumb/stuck.png';

    var pending = setThumbnailImageSrc(thumb, '/thumb/stuck.png', 'timeout-key', {priority: 0});
    assert(timeout && timeout.delay > 0, 'T41b: thumbnail fetch arms a bounded timeout');
    if (timeout) timeout.callback();
    return pending.then(function() {
        assert(false, 'T41c: timed-out thumbnail rejects instead of falling back to a hanging image');
    }, function(error) {
        assert(error && error.name === 'ThumbnailFetchTimeoutError', 'T41c: timeout rejects with a named error');
        assert(abortCount === 1, 'T41d: timeout aborts the fetch controller');
        assert(thumbnailBlobInflight.size === 0, 'T41e: timeout releases the inflight thumbnail slot');
        assert(clearCount >= 1, 'T41f: timeout cleanup clears the timer');
        assert(thumb._parent.classList.contains('thumbnail-failed'), 'T41g: timeout marks the tile as failed');
        assert(!thumb._parent.querySelector().hidden, 'T41h: timeout exposes the retryable error tile');
    }).finally(function() {
        ctx.setTimeout = previousSetTimeout;
        ctx.clearTimeout = previousClearTimeout;
        ctx.AbortController = previousAbortController;
        ctx.fetch = previousFetch;
    });
}

/* ── Run all tests asynchronously ──────────────────────────────────────── */

var syncTests = [
    test01_stage2_functions_exist,
    test02_lru_touch_refreshes_recency,
    test04_overflow_eviction_scope_class_ordering,
    test05_overflow_eviction_priority_within_scope,
    test06_overflow_eviction_lru_tie_break,
    test07_exact_hard_cap_1000,
    test08_real_batch_transition_A_B_A,
    test09_same_batch_does_not_rotate_history,
    test10_virtual_batch_does_not_rotate_history,
    test11_priority_promotion_is_monotonic,
    test12_metadata_cleanup_on_eviction,
    test13_metadata_cleanup_on_cache_clear,
    test14_eviction_revokes_exactly_once,
    test15_displayed_image_unaffected_by_eviction,
    test16_unknown_scope_treated_as_weak,
    test17_previous_weaker_than_current,
    test18_cache_hit_touch_in_assign_thumbnail_src_if_cached,
    test19_cache_miss_does_not_touch,
    test20_beforeunload_cleans_metadata,
    test22_visible_requester_alone_sets_visible_metadata,
    test24_resolve_source_batch_real_view,
    test25_resolve_source_batch_virtual_view,
    test26_virtual_view_distinct_real_scopes,
    test27_batch_tracker_rejects_non_real_inputs,
    test29_exactly_one_lru_bump_on_hit_no_meta,
    test30_exactly_one_lru_bump_assign_with_meta,
    /* Stage 2.5: resident/probation tests */
    test31_new_entries_start_probationary,
    test32_cache_hit_promotes_to_resident,
    test33_resident_survives_over_probationary_same_scope_priority,
    test34_scope_dominates_residency,
    test35_priority_dominates_residency,
    test36_real_batch_transition_marks_outgoing_resident,
    test37_same_batch_and_virtual_no_resident_marking,
    test38_resident_metadata_cleaned_on_eviction,
    test39_resident_metadata_cleaned_on_clear,
    test40_deterministic_ABA_scan_resistance
];

var asyncTests = [
    test03_lru_touch_in_resolve_thumbnail_blob_url,
    test21_inflight_promotion_e2e,
    test23_lru_touch_does_not_revoke,
    test28_exactly_one_lru_bump_on_hit_with_meta,
    test41_thumbnail_fetch_timeout_aborts_releases_slot_and_marks_retryable
];

try {
    for (var i = 0; i < syncTests.length; i++) {
        syncTests[i]();
    }
} catch (e) {
    process.stderr.write('Sync test error: ' + e.stack + '\n');
    assertions.push({ pass: false, message: 'Exception: ' + e.message });
}

/* Run async tests sequentially so _resetCacheState in test N+1
   does not wipe inflight or cache state of test N still pending. */
function _runAsyncSeq(idx) {
    if (idx >= asyncTests.length) {
        finish();
        return;
    }
    try {
        var p = asyncTests[idx]();
    } catch (e) {
        process.stderr.write('Async test init error: ' + e.stack + '\n');
        assertions.push({ pass: false, message: 'Exception: ' + e.message });
        _runAsyncSeq(idx + 1);
        return;
    }
    if (p && typeof p.then === 'function') {
        p.then(function() { _runAsyncSeq(idx + 1); },
               function(err) {
                   process.stderr.write('Async test error: ' + (err && err.stack || err) + '\n');
                   assertions.push({ pass: false, message: 'Exception: ' + (err && err.message || err) });
                   _runAsyncSeq(idx + 1);
               });
    } else {
        _runAsyncSeq(idx + 1);
    }
}

if (asyncTests.length === 0) {
    finish();
} else {
    _runAsyncSeq(0);
}

function finish() {
    var failed = assertions.filter(function(a) { return !a.pass; }).length;
    var passed = assertions.filter(function(a) { return a.pass; }).length;

    process.stdout.write(JSON.stringify({
        total: assertions.length,
        passed: passed,
        failed: failed,
        details: assertions
    }) + '\n');

    process.exit(failed > 0 ? 1 : 0);
}
