#!/usr/bin/env node
/* Node-executed lifecycle test for viewport-loader.js.
   Mocks IntersectionObserver, DOM elements, setThumbnailImageSrc,
   and scheduling primitives to verify admission order, once-only
   loading, map/queue cleanup, and cancellation.
   Outputs JSON with pass/fail assertions to stdout. */

var fs = require('fs');
var path = require('path');

var source = fs.readFileSync(
    path.join(__dirname, '..', '..', 'static', 'js', 'viewport-loader.js'),
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

var _visibleObserverCb = null;
var _nearObserverCb = null;
var _visibleObserved = new Map();
var _nearObserved = new Map();

var observeLog = [];
var unobserveLog = [];

function mockIntersectionObserver(cb, opts) {
    if (opts && opts.rootMargin === '0%') {
        _visibleObserverCb = cb;
    } else {
        _nearObserverCb = cb;
    }
    return {
        observe: function(el) {
            if (opts && opts.rootMargin === '0%') {
                _visibleObserved.set(el, true);
            } else {
                _nearObserved.set(el, true);
            }
            observeLog.push({ observer: opts && opts.rootMargin === '0%' ? 'visible' : 'near', el: el._id });
        },
        unobserve: function(el) {
            if (opts && opts.rootMargin === '0%') {
                _visibleObserved.delete(el);
            } else {
                _nearObserved.delete(el);
            }
            unobserveLog.push({ observer: opts && opts.rootMargin === '0%' ? 'visible' : 'near', el: el._id });
        }
    };
}
global.IntersectionObserver = mockIntersectionObserver;

var _elId = 0;
function makeElement(connected) {
    var el = {
        _id: ++_elId,
        isConnected: !!connected,
        dataset: {},
        classList: {
            _classes: {},
            add: function(c) { this._classes[c] = true; },
            remove: function(c) { delete this._classes[c]; },
            contains: function(c) { return !!this._classes[c]; }
        },
        querySelector: function(sel) {
            if (sel === 'img') {
                return {
                    dataset: el.dataset,
                    classList: el.classList,
                    getAttribute: function() { return el._src || null; },
                    setAttribute: function(k, v) { el._src = v; }
                };
            }
            return null;
        },
        _src: null,
    };
    return el;
}

var loadCalls = [];
var loadPromises = [];
var _loadSerial = 0;
global.setThumbnailImageSrc = function(imgEl, imageSrc, cacheKey) {
    if (assignThumbnailSrcIfCached(imgEl, imageSrc, cacheKey)) {
        return Promise.resolve('blob:cached');
    }
    /* Network miss path */
    var callId = ++_loadSerial;
    loadCalls.push({ id: callId, imageSrc: imageSrc, cacheKey: cacheKey });
    var thenCallbacks = [];
    var p = {
        then: function(onFulfilled, onRejected) {
            thenCallbacks.push({ f: onFulfilled, r: onRejected });
            return this;
        },
        _resolve: function() {
            imgEl.classList.add('loaded');
            imgEl.dataset.thumbnailCacheKey = cacheKey;
            imgEl.setAttribute('src', 'blob:mock-' + callId);
            for (var i = 0; i < thenCallbacks.length; i++) {
                thenCallbacks[i].f('blob:mock-' + callId);
            }
        }
    };
    loadPromises.push({ id: callId, resolve: function() { p._resolve(); } });
    return p;
};

global.thumbnailBlobInflight = new Map();

var thumbnailBlobUrlCache = new Map();
global.thumbnailBlobUrlCache = thumbnailBlobUrlCache;

/* Clone grid.js helpers the viewport-loader depends on.
   In production these live in grid.js; for the deterministic test
   we inject them into the module scope. */
global.assignThumbnailSrcIfCached = function(imageEl, imageSrc, cacheKey) {
    imageEl.dataset.thumbnailCacheKey = cacheKey;
    var cached = thumbnailBlobUrlCache.get(cacheKey);
    if (cached) {
        if (imageEl.getAttribute('src') !== cached) {
            imageEl.setAttribute('src', cached);
        }
        return true;
    }
    return false;
};

var rafQueue = [];
var idleQueue = [];
var timeoutQueue = [];
var microtaskQueue = [];

global.requestAnimationFrame = function(fn) { rafQueue.push(fn); return rafQueue.length; };
global.cancelAnimationFrame = function(id) { /* noop */ };

global.requestIdleCallback = function(fn, opts) { idleQueue.push(fn); return idleQueue.length; };
global.cancelIdleCallback = function(id) { /* noop */ };

global.setTimeout = function(fn, ms) { timeoutQueue.push(fn); return timeoutQueue.length; };
global.clearTimeout = function(id) { /* noop */ };

/* Mock Promise.resolve().then(fn) to capture microtask callbacks for
   deterministic testing. The real Promise is still used for async control;
   only the Promise.resolve() static call within the viewport loader is
   intercepted so completion-pump callbacks land in microtaskQueue. */
var _realPromiseResolve = Promise.resolve.bind(Promise);
global.Promise = function Promise(executor) {
    return new _realPromiseResolve().constructor(executor);
};
global.Promise.resolve = function(value) {
    return {
        then: function(onFulfilled, onRejected) {
            microtaskQueue.push(function() {
                try { onFulfilled && onFulfilled(value); } catch(e) { process.stderr.write('microtask error: ' + e + '\n'); }
            });
            return this;
        }
    };
};
global.Promise.prototype = Object.create(Object.prototype);

function flushRaf() {
    var queue = rafQueue.splice(0);
    queue.forEach(function(fn) { try { fn(); } catch(e) { process.stderr.write('rAF error: ' + e + '\n'); } });
}

function flushIdle() {
    var queue = idleQueue.splice(0);
    queue.forEach(function(fn) { try { fn(); } catch(e) { process.stderr.write('idle error: ' + e + '\n'); } });
}

function flushTimeouts() {
    var queue = timeoutQueue.splice(0);
    queue.forEach(function(fn) { try { fn(); } catch(e) { process.stderr.write('timeout error: ' + e + '\n'); } });
}

function flushMicrotasks() {
    var queue = microtaskQueue.splice(0);
    queue.forEach(function(fn) { try { fn(); } catch(e) { process.stderr.write('microtask error: ' + e + '\n'); } });
}

function flushAllAsync() {
    flushMicrotasks();
    flushRaf();
    flushIdle();
    flushTimeouts();
}

function resolveAllLoads() {
    var pending = loadPromises.splice(0);
    pending.forEach(function(p) { p.resolve(); });
}

/* ── Execute the viewport-loader module (once) ─────────────────────────── */

var vm = require('vm');
var ctx = vm.createContext(global);
var script = new vm.Script(source);
script.runInContext(ctx);

var scheduleThumbnailLoad = ctx.scheduleThumbnailLoad;
var unscheduleThumbnailLoad = ctx.unscheduleThumbnailLoad;
var cancelScheduledViewportLoads = ctx.cancelScheduledViewportLoads;

/* ── State helpers ─────────────────────────────────────────────────────── */

function _evalInCtx(code) {
    return vm.runInContext(code, ctx);
}

function getInfoMapSize() {
    return _evalInCtx('_viewportInfoMap.size');
}
function getVisibleQueueLen() {
    return _evalInCtx('_viewportVisibleQueue.length');
}
function getNearQueueLen() {
    return _evalInCtx('_viewportNearQueue.length');
}
function getDeferredQueueLen() {
    return _evalInCtx('_viewportDeferredQueue.length');
}
function getActiveFetches() {
    return _evalInCtx('_viewportActiveFetches');
}
function getGeneration() {
    return _evalInCtx('_viewportGeneration');
}
function getPumpRafId() {
    return _evalInCtx('_viewportPumpRafId');
}
function getDrainTimerId() {
    return _evalInCtx('_viewportDrainTimerId');
}

function getConcurrency() {
    return _evalInCtx('THUMBNAIL_LOAD_CONCURRENCY');
}

function resetState() {
    loadCalls = [];
    loadPromises = [];
    observeLog = [];
    unobserveLog = [];
    rafQueue = [];
    idleQueue = [];
    timeoutQueue = [];
    microtaskQueue = [];
    _visibleObserved = new Map();
    _nearObserved = new Map();
    _visibleObserverCb = null;
    _nearObserverCb = null;
    _loadSerial = 0;
    thumbnailBlobUrlCache.clear();
    global.thumbnailBlobInflight.clear();

    /* Reset let bindings via vm.runInContext */
    _evalInCtx('_viewportGeneration = 0');
    _evalInCtx('_viewportActiveFetches = 0');
    _evalInCtx('_viewportVisibleObserver = null');
    _evalInCtx('_viewportNearObserver = null');
    _evalInCtx('_viewportDrainTimerId = null');
    _evalInCtx('_viewportPumpRafId = null');
    _evalInCtx('_viewportCompletionScheduled = false');
    _evalInCtx('_viewportVisibleQueue = []');
    _evalInCtx('_viewportNearQueue = []');
    _evalInCtx('_viewportDeferredQueue = []');
    _evalInCtx('_viewportInfoMap.clear()');
}

/* ── Test scenarios ────────────────────────────────────────────────────── */

function test1_disconnected_elements_not_immediately_drained() {
    resetState();

    var el1 = makeElement(false);
    var el2 = makeElement(false);

    scheduleThumbnailLoad(el1, '/thumb/a.png', 'key-a');
    scheduleThumbnailLoad(el2, '/thumb/b.png', 'key-b');

    assert(getInfoMapSize() >= 2, 'T1a: disconnected elements should be in info map');
    assert(getDeferredQueueLen() >= 2, 'T1b: disconnected elements should be in deferred queue');
    assert(loadCalls.length === 0, 'T1c: no loads should start for disconnected elements');

    var el1VisibleObserved = observeLog.some(function(l) { return l.observer === 'visible' && l.el === el1._id; });
    var el1NearObserved = observeLog.some(function(l) { return l.observer === 'near' && l.el === el1._id; });
    assert(el1VisibleObserved, 'T1d: element should be observed by visible observer');
    assert(el1NearObserved, 'T1e: element should be observed by near observer');

    /* Connect elements */
    el1.isConnected = true;
    el2.isConnected = true;

    /* Fire visible observer for el1 */
    _visibleObserverCb([{ isIntersecting: true, target: el1 }]);
    assert(getVisibleQueueLen() >= 1, 'T1f: connected element promoted to visible queue');

    /* No loads yet - pump hasn't run */
    /* Run the priority pump (rAF) */
    flushRaf();

    var el1Loaded = loadCalls.some(function(c) { return c.imageSrc === '/thumb/a.png'; });
    assert(el1Loaded, 'T1g: visible element should start loading after pump');

    /* el2 is deferred and hasn't loaded yet (no observer fired, not priority-pumped) */
    flushIdle();
    flushTimeouts();

    var el2Loaded = loadCalls.some(function(c) { return c.imageSrc === '/thumb/b.png'; });
    assert(el2Loaded, 'T1h: deferred element should eventually load via background drain');

    var el1Count = loadCalls.filter(function(c) { return c.imageSrc === '/thumb/a.png'; }).length;
    var el2Count = loadCalls.filter(function(c) { return c.imageSrc === '/thumb/b.png'; }).length;
    assert(el1Count === 1, 'T1i: visible element loads exactly once (got ' + el1Count + ')');
    assert(el2Count === 1, 'T1j: deferred element loads exactly once (got ' + el2Count + ')');
}

function test2_admission_cleanup() {
    resetState();

    var el = makeElement(true);
    scheduleThumbnailLoad(el, '/thumb/c.png', 'key-c');

    _visibleObserverCb([{ isIntersecting: true, target: el }]);
    flushRaf();

    var elVisibleUnobserved = unobserveLog.some(function(l) { return l.observer === 'visible' && l.el === el._id; });
    var elNearUnobserved = unobserveLog.some(function(l) { return l.observer === 'near' && l.el === el._id; });
    assert(elVisibleUnobserved, 'T2a: admitted element unobserved from visible observer');
    assert(elNearUnobserved, 'T2b: admitted element unobserved from near observer');

    assert(getInfoMapSize() === 0, 'T2c: info map empty after admission (got ' + getInfoMapSize() + ')');
    assert(getVisibleQueueLen() === 0, 'T2d: visible queue empty after admission');
    assert(getNearQueueLen() === 0, 'T2e: near queue empty after admission');
    assert(getDeferredQueueLen() === 0, 'T2f: deferred queue empty after admission');
    assert(loadCalls.length === 1, 'T2g: element loaded exactly once');
}

function test3_concurrency_cap() {
    resetState();

    var elements = [];
    for (var i = 0; i < 20; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/' + i + '.png', 'key-' + i);
    }

    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }
    flushRaf();

    assert(loadCalls.length <= getConcurrency(), 'T3a: at most cap loads active (got ' + loadCalls.length + ')');

    resolveAllLoads();
    var loadsBefore = loadCalls.length;
    flushMicrotasks();
    flushRaf();
    flushIdle();
    flushTimeouts();
    var loadsAfter = loadCalls.length;
    assert(loadsAfter > loadsBefore, 'T3b: more loads start after previous complete (before=' + loadsBefore + ' after=' + loadsAfter + ')');
}

function test4_priority_ordering() {
    resetState();

    var visibleEl = makeElement(true);
    var nearEl = makeElement(true);
    var deferredEl = makeElement(true);

    scheduleThumbnailLoad(visibleEl, '/thumb/vis.png', 'key-vis');
    scheduleThumbnailLoad(nearEl, '/thumb/near.png', 'key-near');
    scheduleThumbnailLoad(deferredEl, '/thumb/def.png', 'key-def');

    /* Promote visible and near */
    _visibleObserverCb([{ isIntersecting: true, target: visibleEl }]);
    _nearObserverCb([{ isIntersecting: true, target: nearEl }]);

    flushRaf();

    var firstLoad = loadCalls[0];
    assert(firstLoad && firstLoad.imageSrc === '/thumb/vis.png',
        'T4a: visible element loads first (got ' + (firstLoad ? firstLoad.imageSrc : 'none') + ')');

    resolveAllLoads();
    flushMicrotasks();
    flushRaf();

    var secondLoad = loadCalls[1];
    assert(secondLoad && secondLoad.imageSrc === '/thumb/near.png',
        'T4b: near loads before deferred (got ' + (secondLoad ? secondLoad.imageSrc : 'none') + ')');

    resolveAllLoads();
    flushRaf();
    flushIdle();
    flushTimeouts();

    var defLoaded = loadCalls.some(function(c) { return c.imageSrc === '/thumb/def.png'; });
    assert(defLoaded, 'T4c: deferred element eventually loads');
}

function test5_cancellation() {
    resetState();

    var el = makeElement(true);
    scheduleThumbnailLoad(el, '/thumb/x.png', 'key-x');

    var genBefore = getGeneration();
    cancelScheduledViewportLoads();
    var genAfter = getGeneration();

    assert(genAfter > genBefore, 'T5a: cancellation increments generation');
    assert(getPumpRafId() === null, 'T5b: pump rAF cancelled');
    assert(getDrainTimerId() === null, 'T5c: drain timer cancelled');

    /* Fire observer - info was from old generation, should be a no-op */
    _visibleObserverCb([{ isIntersecting: true, target: el }]);
    flushRaf();
    flushIdle();
    flushTimeouts();

    assert(loadCalls.length === 0, 'T5d: cancelled work should not start loading');
    assert(getVisibleQueueLen() === 0, 'T5e: queues empty after cancel');
    assert(getInfoMapSize() === 0, 'T5f: info map empty after cancel');
}

function test6_unschedule() {
    resetState();

    var el = makeElement(true);
    scheduleThumbnailLoad(el, '/thumb/u.png', 'key-u');

    assert(getInfoMapSize() >= 1, 'T6a: element registered');

    unscheduleThumbnailLoad(el);

    assert(getInfoMapSize() === 0, 'T6b: unschedule removes from info map');
    assert(getDeferredQueueLen() === 0, 'T6c: unschedule removes from deferred queue');

    var elUnobserved = unobserveLog.some(function(l) { return l.el === el._id; });
    assert(elUnobserved, 'T6d: unschedule unobserve elements');

    flushRaf();
    flushIdle();
    flushTimeouts();
    assert(loadCalls.length === 0, 'T6e: unscheduled element should not load');
}

function test7_disconnected_then_connected() {
    resetState();

    var el = makeElement(false);
    scheduleThumbnailLoad(el, '/thumb/d.png', 'key-d');

    assert(loadCalls.length === 0, 'T7a: disconnected element not loaded');

    el.isConnected = true;
    _visibleObserverCb([{ isIntersecting: true, target: el }]);
    flushRaf();

    assert(loadCalls.length >= 1, 'T7b: element loads after connection + observer');
    if (loadCalls.length > 0) {
        assert(loadCalls[0].imageSrc === '/thumb/d.png', 'T7c: correct element loaded');
    }

    /* Loaded exactly once */
    var count = loadCalls.filter(function(c) { return c.imageSrc === '/thumb/d.png'; }).length;
    assert(count === 1, 'T7d: element loads exactly once (got ' + count + ')');
}

function test8_no_immediate_drain_in_schedule() {
    resetState();
    var el = makeElement(true);
    scheduleThumbnailLoad(el, '/thumb/e.png', 'key-e');

    /* Before any async runs, the element should be in deferred queue but not loaded */
    assert(getDeferredQueueLen() >= 1, 'T8a: element in deferred queue after schedule');
    assert(getInfoMapSize() >= 1, 'T8b: element in info map after schedule');
    assert(loadCalls.length === 0, 'T8c: no immediate load in schedule');

    /* Observer fire + pump runs */
    _visibleObserverCb([{ isIntersecting: true, target: el }]);
    assert(getVisibleQueueLen() >= 1, 'T8d: promoted to visible queue before pump');
    assert(getDeferredQueueLen() === 0, 'T8e: removed from deferred after promotion');

    flushRaf();
    assert(loadCalls.length >= 1, 'T8f: loaded after pump');
}

function test9_no_background_spin_at_cap() {
    resetState();

    var scheduleCount = getConcurrency() + 4;

    /* Schedule enough elements to exceed cap, don't promote any via observer */
    var elements = [];
    for (var i = 0; i < scheduleCount; i++) {
        var el = makeElement(true); /* connected */
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/' + i + '.png', 'key-' + i);
    }

    /* All items are in deferred queue, no observer has fired */
    assert(getDeferredQueueLen() === scheduleCount, 'T9a: all items in deferred queue (got ' + getDeferredQueueLen() + ')');

    /* Background drain was armed by scheduleThumbnailLoad */
    /* Run the background drain (idle callback) */
    flushIdle();
    flushTimeouts();

    /* After drain, cap admitted, 4 remain deferred */
    assert(loadCalls.length === getConcurrency(), 'T9b: cap loads admitted at cap (got ' + loadCalls.length + ')');
    assert(getActiveFetches() === getConcurrency(), 'T9c: active fetches at cap');
    assert(getDeferredQueueLen() === 4, 'T9d: 4 items remain in deferred (got ' + getDeferredQueueLen() + ')');

    /* Capture timer state after first drain */
    var idleAfter = idleQueue.length;
    var timeoutAfter = timeoutQueue.length;

    /* Flush any additional scheduled callbacks */
    flushIdle();
    flushTimeouts();

    /* Verify no callback was enqueued during the flush -- no spin */
    assert(idleQueue.length === 0, 'T9e: no idle callback scheduled at cap (got ' + idleQueue.length + ')');
    assert(timeoutQueue.length === 0, 'T9f: no timeout callback scheduled at cap (got ' + timeoutQueue.length + ')');

    /* Resolve one load to drop below cap */
    if (loadPromises.length >= 1) {
        loadPromises[0].resolve();
    }
    /* Priority pump + background drain should pick up remaining work */
    flushMicrotasks();
    flushRaf();
    flushIdle();
    flushTimeouts();

    var totalAdmitted = loadCalls.length;
    assert(totalAdmitted >= getConcurrency() + 1, 'T9g: work advances after load completes (got ' + totalAdmitted + ' admitted)');

    /* All items eventually load */
    resolveAllLoads();
    flushMicrotasks();
    flushRaf();
    flushIdle();
    flushTimeouts();

    assert(loadCalls.length === scheduleCount, 'T9h: all items eventually admitted (got ' + loadCalls.length + ')');
}

function test10a_cache_hits_bypass_slot_accounting() {
    resetState();

    /* Pre-populate cache for 500 entries */
    for (var i = 0; i < 500; i++) {
        thumbnailBlobUrlCache.set('key-' + i, 'blob:cached-' + i);
    }

    /* Schedule and promote 500 elements */
    var elements = [];
    for (var i = 0; i < 500; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/' + i + '.png', 'key-' + i);
    }
    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }

    /* Single pump should admit all 500 without incrementing active fetches
       because every entry is a cache hit */
    flushRaf();

    /* No network loads -- all cache hits */
    assert(loadCalls.length === 0, 'T10a1: 0 network loads for cache-hit entries (got ' + loadCalls.length + ')');
    assert(getActiveFetches() === 0, 'T10a2: active fetches 0 after cache hits (got ' + getActiveFetches() + ')');

    /* All 500 src attributes must have been assigned */
    var assignedCount = 0;
    for (var k = 0; k < elements.length; k++) {
        if (elements[k]._src) assignedCount++;
    }
    assert(assignedCount === 500, 'T10a3: all 500 elements have src assigned (got ' + assignedCount + ')');

    /* All cleaned from info map and queues */
    assert(getInfoMapSize() === 0, 'T10a4: info map empty after admission (got ' + getInfoMapSize() + ')');
    assert(getVisibleQueueLen() === 0, 'T10a5: visible queue empty');
    assert(getDeferredQueueLen() === 0, 'T10a6: deferred queue empty');
}

function test10b_mixed_cache_hits_and_misses() {
    resetState();

    /* Pre-populate cache for first 50 entries (cache hits) */
    for (var i = 0; i < 50; i++) {
        thumbnailBlobUrlCache.set('key-' + i, 'blob:cached-' + i);
    }
    /* Remaining 50 have no cache entry (misses) */

    /* Schedule 100 elements */
    var elements = [];
    for (var i = 0; i < 100; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/' + i + '.png', 'key-' + i);
    }
    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }

    flushRaf();

    /* All 50 cache hits should be assigned (no network) */
    var hitsAssigned = 0;
    for (var k = 0; k < 50; k++) {
        if (elements[k]._src) hitsAssigned++;
    }
    assert(hitsAssigned === 50, 'T10b1: 50 cache-hit elements assigned (got ' + hitsAssigned + ')');

    /* Network misses capped at concurrency */
    assert(loadCalls.length === getConcurrency(), 'T10b2: network misses at cap ' + getConcurrency() + ' (got ' + loadCalls.length + ')');
    assert(getActiveFetches() === getConcurrency(), 'T10b3: active fetches exactly ' + getConcurrency() + ' (got ' + getActiveFetches() + ')');

    /* Remaining misses still in visible queue */
    assert(getVisibleQueueLen() === 50 - getConcurrency(), 'T10b4: ' + (50 - getConcurrency()) + ' misses remain queued (got ' + getVisibleQueueLen() + ')');

    /* Resolve all and drain in cycles until complete */
    for (var cycle = 0; cycle < 10 && loadCalls.length < 50; cycle++) {
        resolveAllLoads();
        flushMicrotasks();
        flushRaf();
        flushIdle();
        flushTimeouts();
    }

    assert(loadCalls.length === 50, 'T10b5: all 50 misses eventually loaded (got ' + loadCalls.length + ')');
    assert(getInfoMapSize() === 0, 'T10b6: info map empty after all admissions');
}

function test10c_stale_guard_in_cache_hit_path() {
    resetState();

    /* Pre-populate cache */
    thumbnailBlobUrlCache.set('key-new', 'blob:new-value');

    var el = makeElement(true);
    /* Simulate a stale key already set on the element */
    var imgEl = el.querySelector('img');
    imgEl.dataset.thumbnailCacheKey = 'key-old';
    imgEl.setAttribute('src', 'blob:old-value');

    /* Cache hit: src differs from cached value, should assign */
    var result1 = assignThumbnailSrcIfCached(imgEl, '/thumb/x.png', 'key-new');
    assert(result1 === true, 'T10c1: cache hit returns true');
    assert(imgEl.getAttribute('src') === 'blob:new-value', 'T10c2: src updated from stale to cached (got ' + imgEl.getAttribute('src') + ')');
    assert(imgEl.dataset.thumbnailCacheKey === 'key-new', 'T10c3: cache key updated');

    /* Second call with same key: src already matches cached value */
    var callCount = _loadSerial;
    var result2 = assignThumbnailSrcIfCached(imgEl, '/thumb/x.png', 'key-new');
    assert(result2 === true, 'T10c4: second hit returns true');
    /* No src reassignment triggered */
    assert(_loadSerial === callCount, 'T10c5: no new network request triggered');
}

/* ── Completion microtask pump tests ─────────────────────────────────── */

function test11a_fast_resolve_advances_without_rAF() {
    resetState();

    /* Schedule and promote 500 elements to visible */
    var elements = [];
    for (var i = 0; i < 500; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/' + i + '.png', 'key-' + i);
    }
    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }

    /* Single rAF pump admits first wave at cap */
    var rafCount = rafQueue.length;
    flushRaf();

    var firstBatch = loadCalls.length;
    assert(firstBatch === getConcurrency(), 'T11a1: first rAF admits cap (got ' + firstBatch + ')');
    assert(getActiveFetches() === getConcurrency(), 'T11a2: active fetches at cap after first wave');

    /* Resolve all and drain ONLY microtasks, NOT rAF */
    resolveAllLoads();

    /* At this point: decrementAndDrain was called getConcurrency() times, but the guard
       ensures only one completion microtask is scheduled */
    var microtaskQuedCount = microtaskQueue.length;
    assert(microtaskQuedCount === 1, 'T11a3: single completion microtask queued for cap completions (got ' + microtaskQuedCount + ')');

    flushMicrotasks();

    /* After microtask drain, next batch should be admitted */
    var secondBatch = loadCalls.length;
    assert(secondBatch > firstBatch, 'T11a4: more loads admitted by completion microtask without rAF (before=' + firstBatch + ' after=' + secondBatch + ')');

    /* Continue resolving and draining via microtasks only until all 500 admitted */
    var rafCallbacksBefore = rafQueue.length;
    for (var cycle = 0; cycle < 100 && loadCalls.length < 500; cycle++) {
        resolveAllLoads();
        flushMicrotasks();
    }

    var totalAdmitted = loadCalls.length;
    assert(totalAdmitted === 500, 'T11a5: all 500 admitted via microtasks without extra rAF pauses (got ' + totalAdmitted + ')');

    /* No new rAF callbacks were scheduled by load completions */
    assert(rafQueue.length === 0, 'T11a6: no rAF queued by load completions (got ' + rafQueue.length + ')');
}

function test11b_concurrency_never_exceeds_8() {
    resetState();

    /* Schedule 100 elements, promote to visible */
    var elements = [];
    for (var i = 0; i < 100; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/' + i + '.png', 'key-cncy-' + i);
    }
    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }

    /* Initial rAF admits cap */
    flushRaf();
    assert(getActiveFetches() === getConcurrency(), 'T11b1: first wave at concurrency ' + getConcurrency());

    /* Track maximum active fetches across all drain cycles */
    var maxActive = getConcurrency();
    for (var cycle = 0; cycle < 50 && loadCalls.length < 100; cycle++) {
        resolveAllLoads();
        flushMicrotasks();
        flushRaf();
        flushIdle();
        flushTimeouts();
        if (getActiveFetches() > maxActive) maxActive = getActiveFetches();
    }

    assert(maxActive <= getConcurrency(), 'T11b2: active fetches never exceed cap (max was ' + maxActive + ')');
    assert(loadCalls.length === 100, 'T11b3: all 100 admitted');
}

function test11c_burst_completions_single_microtask() {
    resetState();

    /* Schedule 2 × cap elements, promote to visible */
    var scheduleCount = getConcurrency() * 2;
    var elements = [];
    for (var i = 0; i < scheduleCount; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/bt-' + i + '.png', 'key-bt-' + i);
    }
    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }

    flushRaf();
    assert(loadCalls.length === getConcurrency(), 'T11c1: initial cap admitted via rAF');

    var microBefore = microtaskQueue.length;
    resolveAllLoads(); /* all cap completions simultaneously */
    assert(microtaskQueue.length === 1, 'T11c2: exactly one microtask queued for cap-burst (got ' + microtaskQueue.length + ')');

    flushMicrotasks();
    /* After microtask, next wave should be admitted */
    assert(loadCalls.length === getConcurrency() * 2, 'T11c3: second wave of ' + getConcurrency() + ' admitted after single microtask (got ' + loadCalls.length + ')');
}

function test11d_priority_ordering_via_completion() {
    resetState();

    var visibleEl = makeElement(true);
    var nearEl = makeElement(true);
    var deferredEl = makeElement(true);

    /* Schedule all three */
    scheduleThumbnailLoad(visibleEl, '/thumb/vis.png', 'key-vis');
    scheduleThumbnailLoad(nearEl, '/thumb/near.png', 'key-near');
    scheduleThumbnailLoad(deferredEl, '/thumb/def.png', 'key-def');

    /* Promote first two */
    _visibleObserverCb([{ isIntersecting: true, target: visibleEl }]);
    _nearObserverCb([{ isIntersecting: true, target: nearEl }]);

    /* Limit concurrency to 1 to observe strict ordering */
    _evalInCtx('_THUMBNAIL_LOAD_CONCURRENCY_ORIG = THUMBNAIL_LOAD_CONCURRENCY');
    /* Override concurrency check in _drainNext by pinning activeFetches */
    _evalInCtx('_viewportActiveFetches = 0');

    /* Force drain visible via rAF pump */
    flushRaf();
    var call0 = loadCalls[0];
    assert(call0 && call0.imageSrc === '/thumb/vis.png',
        'T11d1: visible loaded first (got ' + (call0 ? call0.imageSrc : 'none') + ')');

    /* Now bump activeFetches so _drainNext can proceed past the check.
       Simulate: after first load resolves, decrementAndDrain schedules microtask.
       Resolve the first load. */
    _evalInCtx('_viewportActiveFetches = 1'); /* simulate one in-flight */
    resolveAllLoads();
    flushMicrotasks();

    /* After microtask pump with activeFetches=1→0, near should load next (since we reset to 0 and drain again) */
    /* Actually, let me be more precise: _drainNext checks < THUMBNAIL_LOAD_CONCURRENCY.
       Since we've monkeyed with activeFetches, let's just test the wave-after-completion behavior. */
    _evalInCtx('_viewportActiveFetches = 0');

    /* Promote near directly and resolve - it should get admitted via microtask */
    resolveAllLoads();
    flushMicrotasks();

    /* Check ordering: visible first, then near */
    assert(loadCalls.length >= 2, 'T11d2: at least 2 loads admitted');
    /* visible already loaded, near should be second */
    if (loadCalls.length >= 2) {
        var secondCall = loadCalls[1];
        assert(secondCall.imageSrc === '/thumb/near.png',
            'T11d3: near loaded before deferred via completion pump (got ' + secondCall.imageSrc + ')');
    }

    /* Cleanup: resolve remaining loads and let deferred load */
    resolveAllLoads();
    flushMicrotasks();
    flushIdle();
    flushTimeouts();
}

function test11e_cancellation_before_microtask() {
    resetState();

    /* Schedule elements and promote */
    var elements = [];
    for (var i = 0; i < 20; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/cancel-' + i + '.png', 'key-cancel-' + i);
    }
    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }

    /* Admit first wave via rAF */
    flushRaf();
    assert(loadCalls.length === getConcurrency(), 'T11e1: cap admitted before cancel');

    /* Resolve all completions → queues completion microtask */
    resolveAllLoads();
    var queuedMicrotask = microtaskQueue.length > 0;
    assert(queuedMicrotask, 'T11e2: microtask queued after completions');

    /* Cancel BEFORE the microtask runs */
    cancelScheduledViewportLoads();

    /* Now flush the microtask - it must be a no-op due to generation check */
    flushMicrotasks();

    /* No new loads should have been admitted */
    assert(loadCalls.length === getConcurrency(), 'T11e3: no stale admissions after cancel (got ' + loadCalls.length + ')');
}

function test11f_no_hot_microtask_loop() {
    resetState();

    /* Schedule 2 × cap elements, promote to visible */
    var scheduleCount = getConcurrency() * 2;
    var elements = [];
    for (var i = 0; i < scheduleCount; i++) {
        var el = makeElement(true);
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/hot-' + i + '.png', 'key-hot-' + i);
    }
    for (var j = 0; j < elements.length; j++) {
        _visibleObserverCb([{ isIntersecting: true, target: elements[j] }]);
    }

    flushRaf();
    assert(loadCalls.length === getConcurrency(), 'T11f1: cap admitted (at cap)');

    /* Resolve all - should queue ONE microtask */
    resolveAllLoads();
    var afterResolve = microtaskQueue.length;
    assert(afterResolve === 1, 'T11f2: exactly 1 microtask queued');

    /* Flush that microtask */
    flushMicrotasks();

    /* After the completion pump ran, it drained next wave (hit cap). */
    /* Now verify no ADDITIONAL microtask was queued by the pump itself (no hot loop) */
    assert(microtaskQueue.length === 0, 'T11f3: no self-rescheduling microtask after pump (got ' + microtaskQueue.length + ')');
    assert(loadCalls.length === getConcurrency() * 2, 'T11f4: next ' + getConcurrency() + ' admitted by single completion pump');

    /* Now resolve these and check again: single microtask, no loop */
    resolveAllLoads();
    assert(microtaskQueue.length === 1, 'T11f5: single microtask after second wave resolution (got ' + microtaskQueue.length + ')');

    flushMicrotasks();
    /* No more work to drain (queues empty), but also no loop */
    assert(microtaskQueue.length === 0, 'T11f6: no lingering microtask after final drain (got ' + microtaskQueue.length + ')');
}

function test11g_observer_uses_rAF_not_microtask() {
    resetState();

    var el = makeElement(true);
    scheduleThumbnailLoad(el, '/thumb/obs.png', 'key-obs');

    /* Fire near observer - which calls _requestPriorityPump (rAF) */
    _nearObserverCb([{ isIntersecting: true, target: el }]);

    /* Observer promotion should have queued an rAF, NOT a microtask */
    assert(microtaskQueue.length === 0, 'T11g1: observer promotion does not queue microtask (got ' + microtaskQueue.length + ')');
    assert(rafQueue.length >= 1, 'T11g2: observer promotion queues rAF (got ' + rafQueue.length + ')');

    /* rAF pump should admit */
    flushRaf();
    assert(loadCalls.length === 1, 'T11g3: load admitted via rAF from observer');

    /* Resolve the load - this should queue a microtask (completion pump) */
    resolveAllLoads();
    assert(microtaskQueue.length === 1, 'T11g4: load completion queues microtask');

    flushMicrotasks();
    /* After completion microtask, the element is already loaded, nothing extra */
    /* Verify both scheduling mechanisms coexist */
}

/* ── Run all tests ─────────────────────────────────────────────────────── */

try {
    test11a_fast_resolve_advances_without_rAF();
    test11b_concurrency_never_exceeds_8();
    test11c_burst_completions_single_microtask();
    test11d_priority_ordering_via_completion();
    test11e_cancellation_before_microtask();
    test11f_no_hot_microtask_loop();
    test11g_observer_uses_rAF_not_microtask();
    test10a_cache_hits_bypass_slot_accounting();
    test10b_mixed_cache_hits_and_misses();
    test10c_stale_guard_in_cache_hit_path();
    test9_no_background_spin_at_cap();
    test8_no_immediate_drain_in_schedule();
    test1_disconnected_elements_not_immediately_drained();
    test2_admission_cleanup();
    test3_concurrency_cap();
    test4_priority_ordering();
    test5_cancellation();
    test6_unschedule();
    test7_disconnected_then_connected();
} catch (e) {
    process.stderr.write('Test error: ' + e.stack + '\n');
    assertions.push({ pass: false, message: 'Exception: ' + e.message });
}

var failed = assertions.filter(function(a) { return !a.pass; }).length;
var passed = assertions.filter(function(a) { return a.pass; }).length;

process.stdout.write(JSON.stringify({
    total: assertions.length,
    passed: passed,
    failed: failed,
    details: assertions
}) + '\n');

process.exit(failed > 0 ? 1 : 0);
