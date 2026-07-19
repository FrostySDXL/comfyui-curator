/* Ordered classic script.
 * Defines: viewport-aware thumbnail load scheduling with three-tier priority,
 *          bounded concurrency (16), promotion without duplication, approach-triggered
 *          loading (deferred items never auto-drain; they load only when
 *          promoted by observer callbacks), and safe unschedule/cancellation.
 *          Uses a single rAF priority pump and a single microtask completion pump.
 *          Passes priority + resolved source-batch metadata to the cache layer
 *          for scope/priority-aware LRU eviction (Stage 2).
 *          An explicit IntersectionObserver-unavailable fallback eagerly loads
 *          through bounded concurrency when observers cannot exist.
 * Relies on: grid.js (setThumbnailImageSrc, assignThumbnailSrcIfCached), state.js (folderRequestToken).
 * Note: _resolveSourceBatch is defined in grid.js and consumed by grid.js, not here.
 * After this stage, IntersectionObserver controls load START only.
 * Thumbnails that are already displayed NEVER have their src cleared, replaced,
 * unloaded, or re-shimmered on viewport exit.
 */

const THUMBNAIL_LOAD_CONCURRENCY = 16;

const VIEWPORT_PRIORITY_VISIBLE = 0;
const VIEWPORT_PRIORITY_NEAR = 1;
const VIEWPORT_PRIORITY_DEFERRED = 2;

const _viewportInfoMap = new Map();

let _viewportGeneration = 0;
let _viewportActiveFetches = 0;
let _viewportVisibleObserver = null;
let _viewportNearObserver = null;
let _viewportDrainTimerId = null;
let _viewportPumpRafId = null;
let _viewportCompletionScheduled = false;
let _viewportVisibleQueue = [];
let _viewportNearQueue = [];
let _viewportDeferredQueue = [];

function _ensureViewportObservers() {
    if (_viewportVisibleObserver) return;
    if (typeof IntersectionObserver === 'undefined') return;

    /* Use the .content scroll container as the observer root so that
       rootMargin refers to the scrollable grid area, not the browser
       viewport. If .content is unexpectedly absent, fall back to
       root: null (viewport), which is safe but provides less precise
       near-band detection through the clipped scroll ancestor. */
    var scrollRoot = document.querySelector('.content') || null;

    _viewportVisibleObserver = new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].isIntersecting) {
                var el = entries[i].target;
                var info = _viewportInfoMap.get(el);
                if (info && info.priority > VIEWPORT_PRIORITY_VISIBLE) {
                    info.priority = VIEWPORT_PRIORITY_VISIBLE;
                    _removeInfoFromQueues(info);
                    _viewportVisibleQueue.push(info);
                }
            }
        }
        if (entries.length > 0) _requestPriorityPump();
    }, { root: scrollRoot, rootMargin: '0%', threshold: 0 });

    _viewportNearObserver = new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].isIntersecting) {
                var el = entries[i].target;
                var info = _viewportInfoMap.get(el);
                if (info && info.priority > VIEWPORT_PRIORITY_NEAR) {
                    info.priority = VIEWPORT_PRIORITY_NEAR;
                    _removeInfoFromQueues(info);
                    _viewportNearQueue.push(info);
                }
            }
        }
        if (entries.length > 0) _requestPriorityPump();
    }, { root: scrollRoot, rootMargin: '100%', threshold: 0 });
}

function _removeInfoFromQueues(info) {
    var vi = _viewportVisibleQueue.indexOf(info);
    if (vi !== -1) _viewportVisibleQueue.splice(vi, 1);
    var ni = _viewportNearQueue.indexOf(info);
    if (ni !== -1) _viewportNearQueue.splice(ni, 1);
    var di = _viewportDeferredQueue.indexOf(info);
    if (di !== -1) _viewportDeferredQueue.splice(di, 1);
}

function _admitAndLoad(info) {
    _removeInfoFromQueues(info);
    _viewportInfoMap.delete(info.element);
    if (_viewportVisibleObserver) {
        _viewportVisibleObserver.unobserve(info.element);
        _viewportNearObserver.unobserve(info.element);
    }
    _startViewportLoad(info);
}

function _startViewportLoad(info) {
    if (info.generation !== _viewportGeneration) return;
    var el = info.element;
    if (!el || !el.isConnected) return;
    var imgEl = el.querySelector('img');
    if (!imgEl) return;

    if (imgEl.classList.contains('loaded') && imgEl.dataset.thumbnailCacheKey === info.cacheKey) {
        return;
    }

    /* Build metadata for cache-layer admission with priority and
       resolved source-batch scope (Stage 2). */
    var meta = { priority: info.priority, scopeBatch: info.scopeBatch || null };

    /* Cache-hit fast path: a synchronous blobjectURL lookup in grid.js
       assigns the src immediately without consuming a concurrency slot.
       __target__: viewport-loader.js -> grid.js */
    if (assignThumbnailSrcIfCached(imgEl, info.imageSrc, info.cacheKey, meta)) {
        return;
    }

    /* Network-miss path: consumes a concurrency slot */
    _viewportActiveFetches++;
    var loadPromise = setThumbnailImageSrc(imgEl, info.imageSrc, info.cacheKey, meta);

    function decrementAndDrain() {
        _viewportActiveFetches--;
        _scheduleCompletionPump();
    }
    if (loadPromise && typeof loadPromise.then === 'function') {
        loadPromise.then(decrementAndDrain, decrementAndDrain);
    } else {
        _viewportActiveFetches--;
        _scheduleCompletionPump();
    }
}

function _requestPriorityPump() {
    if (_viewportPumpRafId !== null) return;
    _viewportPumpRafId = requestAnimationFrame(function () {
        _viewportPumpRafId = null;
        _runPriorityPump();
    });
}

function _cancelPriorityPump() {
    if (_viewportPumpRafId !== null) {
        cancelAnimationFrame(_viewportPumpRafId);
        _viewportPumpRafId = null;
    }
}

function _scheduleCompletionPump() {
    if (_viewportCompletionScheduled) return;
    _viewportCompletionScheduled = true;
    var gen = _viewportGeneration;
    Promise.resolve().then(function () {
        _viewportCompletionScheduled = false;
        if (_viewportGeneration !== gen) return;
        _runCompletionPump();
    });
}

function _cancelCompletionPump() {
    _viewportCompletionScheduled = false;
}

function _runCompletionPump() {
    _drainNext(VIEWPORT_PRIORITY_VISIBLE);
    _drainNext(VIEWPORT_PRIORITY_NEAR);
    /* Never drain deferred in the normal observer path.
       Distant thumbnails load only on observer approach.
       Fallback: when IntersectionObserver is unavailable, eagerly
       drain deferred through completion waves. */
    if (!_viewportVisibleObserver) {
        _drainNext(VIEWPORT_PRIORITY_DEFERRED);
    }
}

function _runPriorityPump() {
    _drainNext(VIEWPORT_PRIORITY_VISIBLE);
    _drainNext(VIEWPORT_PRIORITY_NEAR);
    /* Never drain deferred from priority pump.
       Distant thumbnails load only on observer approach. */
}

function _drainNext(priority) {
    var queue;
    if (priority === VIEWPORT_PRIORITY_VISIBLE) {
        queue = _viewportVisibleQueue;
    } else if (priority === VIEWPORT_PRIORITY_NEAR) {
        queue = _viewportNearQueue;
    } else {
        queue = _viewportDeferredQueue;
    }
    while (_viewportActiveFetches < THUMBNAIL_LOAD_CONCURRENCY && queue.length > 0) {
        var info = queue.shift();
        if (!info) break;
        if (info.element && info.element.isConnected && info.generation === _viewportGeneration) {
            _admitAndLoad(info);
        }
    }
}

function _scheduleBackgroundDrain() {
    /* With IntersectionObserver available, deferred work
       loads only on observer approach. Never auto-drain in the
       normal browser path. The fallback path (no IntersectionObserver)
       eagerly drains below. */
    if (_viewportVisibleObserver) return;
    if (_viewportDrainTimerId !== null) return;
    _viewportDrainTimerId = _createIdleCallback(function () {
        _viewportDrainTimerId = null;
        _drainNext(VIEWPORT_PRIORITY_DEFERRED);
        /* Re-arm only when deferred items remain AND capacity is available.
           While all slots are full, the priority pump from observer promotions
           or load completions will pick up deferred work. This prevents a
           hot callback loop in the setTimeout(fn,0) fallback path. */
        if (_viewportDeferredQueue.length > 0 && _viewportActiveFetches < THUMBNAIL_LOAD_CONCURRENCY) {
            _scheduleBackgroundDrain();
        }
    });
}

function _createIdleCallback(fn) {
    if (typeof requestIdleCallback === 'function') {
        return requestIdleCallback(fn, { timeout: 1000 });
    }
    return setTimeout(fn, 0);
}

function _cancelBackgroundDrain() {
    if (_viewportDrainTimerId === null) return;
    if (typeof cancelIdleCallback === 'function') {
        cancelIdleCallback(_viewportDrainTimerId);
    } else {
        clearTimeout(_viewportDrainTimerId);
    }
    _viewportDrainTimerId = null;
}

function scheduleThumbnailLoad(element, imageSrc, cacheKey, priority, scopeBatch) {
    _ensureViewportObservers();

    var info = {
        element: element,
        imageSrc: imageSrc,
        cacheKey: cacheKey,
        generation: _viewportGeneration,
        priority: typeof priority === 'number' ? priority : VIEWPORT_PRIORITY_DEFERRED,
        scopeBatch: scopeBatch || null
    };

    _viewportInfoMap.set(element, info);
    _viewportDeferredQueue.push(info);

    if (_viewportVisibleObserver) {
        _viewportVisibleObserver.observe(element);
        _viewportNearObserver.observe(element);
    }
    /* Only arm background drain in the no-observer fallback.
       With IntersectionObserver, deferred items load on approach only. */
    if (!_viewportVisibleObserver) {
        _scheduleBackgroundDrain();
    }
}

function unscheduleThumbnailLoad(element) {
    var info = _viewportInfoMap.get(element);
    if (!info) return;

    if (_viewportVisibleObserver) {
        _viewportVisibleObserver.unobserve(element);
        _viewportNearObserver.unobserve(element);
    }
    _removeInfoFromQueues(info);
    _viewportInfoMap.delete(element);
}

function cancelScheduledViewportLoads() {
    _viewportGeneration++;
    _cancelPriorityPump();
    _cancelCompletionPump();
    _cancelBackgroundDrain();
    _viewportVisibleQueue = [];
    _viewportNearQueue = [];
    _viewportDeferredQueue = [];
    if (_viewportVisibleObserver) {
        _viewportInfoMap.forEach(function (_info, el) {
            _viewportVisibleObserver.unobserve(el);
            _viewportNearObserver.unobserve(el);
        });
    }
    _viewportInfoMap.clear();
}
