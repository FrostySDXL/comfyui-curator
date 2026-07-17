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

var rafQueue = [];
var idleQueue = [];
var timeoutQueue = [];

global.requestAnimationFrame = function(fn) { rafQueue.push(fn); return rafQueue.length; };
global.cancelAnimationFrame = function(id) { /* noop */ };

global.requestIdleCallback = function(fn, opts) { idleQueue.push(fn); return idleQueue.length; };
global.cancelIdleCallback = function(id) { /* noop */ };

global.setTimeout = function(fn, ms) { timeoutQueue.push(fn); return timeoutQueue.length; };
global.clearTimeout = function(id) { /* noop */ };

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

function flushAllAsync() {
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

function resetState() {
    loadCalls = [];
    loadPromises = [];
    observeLog = [];
    unobserveLog = [];
    rafQueue = [];
    idleQueue = [];
    timeoutQueue = [];
    _visibleObserved = new Map();
    _nearObserved = new Map();
    _visibleObserverCb = null;
    _nearObserverCb = null;
    _loadSerial = 0;

    /* Reset let bindings via vm.runInContext */
    _evalInCtx('_viewportGeneration = 0');
    _evalInCtx('_viewportActiveFetches = 0');
    _evalInCtx('_viewportVisibleObserver = null');
    _evalInCtx('_viewportNearObserver = null');
    _evalInCtx('_viewportDrainTimerId = null');
    _evalInCtx('_viewportPumpRafId = null');
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

    assert(loadCalls.length <= 8, 'T3a: at most 8 loads active (got ' + loadCalls.length + ')');

    resolveAllLoads();
    var loadsBefore = loadCalls.length;
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

    /* Schedule 12 elements, don't promote any via observer */
    var elements = [];
    for (var i = 0; i < 12; i++) {
        var el = makeElement(true); /* connected */
        elements.push(el);
        scheduleThumbnailLoad(el, '/thumb/' + i + '.png', 'key-' + i);
    }

    /* All 12 items are in deferred queue, no observer has fired */
    assert(getDeferredQueueLen() === 12, 'T9a: all items in deferred queue (got ' + getDeferredQueueLen() + ')');

    /* Background drain was armed by scheduleThumbnailLoad */
    /* Run the background drain (idle callback) */
    flushIdle();
    flushTimeouts();

    /* After drain, 8 admitted (cap), 4 remain deferred */
    assert(loadCalls.length === 8, 'T9b: 8 loads admitted at cap (got ' + loadCalls.length + ')');
    assert(getActiveFetches() === 8, 'T9c: active fetches at cap');
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
    flushRaf();
    flushIdle();
    flushTimeouts();

    var totalAdmitted = loadCalls.length;
    assert(totalAdmitted >= 9, 'T9g: work advances after load completes (got ' + totalAdmitted + ' admitted)');

    /* All items eventually load */
    resolveAllLoads();
    flushRaf();
    flushIdle();
    flushTimeouts();

    assert(loadCalls.length === 12, 'T9h: all 12 items eventually admitted (got ' + loadCalls.length + ')');
}

/* ── Run all tests ─────────────────────────────────────────────────────── */

try {
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
