'use strict';
// Execute shipped classic scripts with deterministic DOM/event/timer doubles.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const listeners = new Map();
const timers = new Map();
let nextTimer = 1;
let observerCallback;
class Element {
    constructor(id = '') {
        this.id = id;
        this.attrs = {};
        this.dataset = {};
        this.parentNode = null;
        this.classes = new Set();
        this.classList = {
            contains: c => this.classes.has(c),
            add: c => this.classes.add(c),
            remove: c => this.classes.delete(c),
            toggle: (c, on) => on ? this.classes.add(c) : this.classes.delete(c),
        };
        this.listeners = {};
        this.style = {setProperty() {}};
        this.children = [];
    }
    get className() { return [...this.classes].join(' '); }
    set className(value) { this.classes = new Set(value.split(/\s+/).filter(Boolean)); }
    querySelector(selector) {
        for (const child of this.children) {
            if (selector.startsWith('.') && child.classes.has(selector.slice(1))) return child;
            const nested = child.querySelector(selector);
            if (nested) return nested;
        }
        return null;
    }
    appendChild(child) { return this.insertBefore(child, null); }
    prepend(child) { this.insertBefore(child, this.children[0] || null); }
    insertBefore(child, before) {
        child.remove();
        const index = before ? this.children.indexOf(before) : this.children.length;
        this.children.splice(index, 0, child);
        child.parentNode = this;
        return child;
    }
    remove() {
        if (!this.parentNode) return;
        if (this.contains(document.activeElement)) document.activeElement = outside;
        this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1);
        this.parentNode = null;
    }
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
    fire(type, extra = {}) { for (const fn of this.listeners[type] || []) fn.call(this, {target: this, ...extra}); }
    setAttribute(key, value) { this.attrs[key] = value; }
    contains(el) { return el === this || this.children.some(c => c.contains(el)); }
    focus() { document.activeElement = this; dispatch('focusin', {target: this}); }
}
const ids = ['batch-sidebar', 'batch-peek-trigger', 'batch-peek-close', 'batch-sidebar-toggle-btn',
    'batch-search', 'sidebar-resizer', 'lightbox', 'prompts-modal', 'folder-tabs', 'active-batch-select'];
const elements = Object.fromEntries(ids.map(id => [id, new Element(id)]));
elements['batch-sidebar'].children.push(elements['batch-search'], elements['batch-peek-close']);
const outside = new Element('outside');
const document = {
    activeElement: outside, hidden: false,
    documentElement: new Element(), body: new Element(),
    getElementById: id => elements[id] || null,
    createElement: () => new Element(),
    createDocumentFragment: () => new Element(),
    querySelector: selector => selector.includes('.modal.active')
        ? (elements.lightbox.classes.has('active') || elements['prompts-modal'].classes.has('active') ? elements.lightbox : null)
        : null,
    querySelectorAll: selector => selector === '.modal, #lightbox' ? [elements.lightbox, elements['prompts-modal']] : [],
    addEventListener(type, fn) { const list = listeners.get(type) || []; list.push(fn); listeners.set(type, list); },
};
function dispatch(type, extra = {}) {
    const event = {target: outside, preventDefault() { this.defaultPrevented = true; }, stopImmediatePropagation() { this.stopped = true; }, ...extra};
    for (const fn of listeners.get(type) || []) { fn(event); if (event.stopped) break; }
    return event;
}
function tick(ms) {
    for (const [id, timer] of [...timers]) if (timer.delay <= ms) { timers.delete(id); timer.fn(); }
}
const stored = new Map([['open', 'false']]);
const writes = [];
const context = vm.createContext({
    document, window: {addEventListener() {}}, console,
    MutationObserver: class { constructor(fn) { observerCallback = fn; } observe() {} },
    localStorage: {getItem: key => stored.get(key) ?? null, setItem: (key, value) => { writes.push([key, value]); stored.set(key, value); }},
    setTimeout: (fn, delay) => { const id = nextTimer++; timers.set(id, {fn, delay}); return id; },
    clearTimeout: id => timers.delete(id),
    sidebarOpen: true, sidebarWidth: 260,
    SIDEBAR_WIDTH_KEY: 'width', SIDEBAR_OPEN_KEY: 'open', SIDEBAR_WIDTH_DEFAULT: 260, SIDEBAR_WIDTH_MIN: 200, SIDEBAR_WIDTH_MAX: 480,
    isDraggingImages: false, isSidebarResizing: false, isAiSidebarResizing: false,
});
const run = source => vm.runInContext(source, context);
const load = file => run(fs.readFileSync(path.join(root, file), 'utf8'));
load('static/js/sidebar.js');
run('initializeSidebarState()');
assert.equal(elements['batch-sidebar'].inert, true);
assert.equal(elements['batch-sidebar-toggle-btn'].textContent, 'Show Batches');
assert.equal(writes.length, 0);
const trigger = elements['batch-peek-trigger'];
const sidebar = elements['batch-sidebar'];
trigger.fire('pointerenter', {pointerType: 'mouse', buttons: 0});
assert.equal(run('isBatchSidebarPeeking()'), false);
tick(180);
assert.equal(run('isBatchSidebarPeeking()'), true);
assert.equal(document.activeElement, outside, 'hover never steals focus');
assert.equal(sidebar.inert, false);
assert.equal(trigger.attrs['aria-expanded'], 'true');
trigger.fire('pointerleave');
sidebar.fire('pointerenter');
tick(280);
assert.equal(run('isBatchSidebarPeeking()'), true, 'crossing edge to drawer keeps it open');
sidebar.fire('pointerleave');
tick(280);
assert.equal(run('isBatchSidebarPeeking()'), false);
trigger.fire('click');
assert.equal(document.activeElement, elements['batch-search']);
sidebar.fire('pointerleave');
tick(280);
assert.equal(run('isBatchSidebarPeeking()'), true, 'keyboard focus owns the peek after pointer leaves');
const escape = dispatch('keydown', {key: 'Escape', target: elements['batch-search']});
assert.equal(escape.defaultPrevented, true);
assert.equal(escape.stopped, true);
assert.equal(document.activeElement, trigger);
assert.equal(sidebar.inert, true);
assert.equal(writes.length, 0, 'temporary disclosure and dismiss never persist');
trigger.fire('pointerenter', {pointerType: 'touch'});
tick(180);
assert.equal(run('isBatchSidebarPeeking()'), false, 'touch uses explicit click, not hover');
trigger.fire('click');
outside.focus();
assert.equal(run('isBatchSidebarPeeking()'), false, 'tab/focus outside dismisses without focus theft');
assert.equal(document.activeElement, outside);
trigger.fire('pointerenter', {pointerType: 'mouse'});
elements.lightbox.classes.add('active');
observerCallback();
tick(180);
assert.equal(run('isBatchSidebarPeeking()'), false, 'overlay cancels pending hover');
assert.equal(trigger.hidden, true);
elements.lightbox.classes.delete('active');
observerCallback();
trigger.fire('click');
dispatch('dragstart');
assert.equal(run('isBatchSidebarPeeking()'), false);
context.isDraggingImages = true;
trigger.fire('click');
assert.equal(run('isBatchSidebarPeeking()'), false);
context.isDraggingImages = false;
run('openBatchSidebarPeek(); ensureBatchSidebarOpen()');
assert.equal(run('sidebarOpen'), true);
assert.equal(run('isBatchSidebarPeeking()'), false);
assert.equal(elements['batch-sidebar-toggle-btn'].textContent, 'Hide Batches');
assert.equal(stored.get('open'), 'true', 'normal shortcut reopening still persists');
run('toggleBatchSidebar()');
assert.equal(stored.get('open'), 'false');
load('static/js/polling.js');
run('openBatchSidebarPeek()');
assert.equal(run('isInteractionBusy()'), true);
run('dismissBatchSidebarPeek()');

// Delayed background responses must not replace the navigation under a pointer.
load('static/js/batches.js');
let releaseJson;
let jsonStarted;
const jsonReady = new Promise(resolve => { jsonStarted = resolve; });
context.ccApiPath = x => x;
context.fetch = async () => ({ok: true, json: () => new Promise(resolve => { releaseJson = resolve; jsonStarted(); })});
context.isWorkspaceSearchView = () => false;
context.BATCH_STATE_KEY = 'batch';
context.FOLDER_STATE_KEY = 'folder';
context.currentBatch = null;
context.currentFolder = 'inbox';
context.loadUniversalFavorites = () => { context.chosen = '__favorites__'; };
context.loadAllPublic = () => { context.chosen = '__public__'; };
async function main() {
    const pending = run('loadBatches({background: true})');
    await jsonReady;
    run('openBatchSidebarPeek()');
    releaseJson({batches: ['late'], counts: {}});
    await pending; // Would throw on missing rendering DOM if the busy guard failed.
    assert.equal(run('isBatchSidebarPeeking()'), true);
    run("selectBatch('__favorites__')");
    assert.equal(context.chosen, '__favorites__', 'selection uses existing virtual navigation');
    assert.equal(run('isBatchSidebarPeeking()'), false);
    run("openBatchSidebarPeek(); selectBatch('__public__')");
    assert.equal(context.chosen, '__public__');
    assert.equal(stored.get('open'), 'false');
    for (const name of ['beginViewTransition', 'resetAiBatchState', 'showGridLoadingPlaceholders', '_focusSelectedWorkspaceControl', 'showAiCuratePanel']) context[name] = () => {};
    run('selectFolder = (batch, folder) => { selectedDestination = [batch, folder]; }');
    run("openBatchSidebarPeek(); selectBatch('normal-batch')");
    assert.equal(run('currentBatch'), 'normal-batch');
    assert.equal(run("selectedDestination.join('/')"), 'normal-batch/inbox', 'real selection keeps ordinary inbox navigation');
    assert.equal(stored.get('open'), 'false');
    assert.equal(run('isBatchSidebarPeeking()'), false);

    // A delayed AI-count enrichment is another independent source of repaint.
    context.currentBatch = null;
    context.batchSort = 'alpha';
    context.batchFilterQuery = '';
    context.aiBatchRunCounts = {};
    context.fetch = async () => ({ok: true, json: async () => ({batches: ['existing'], counts: {}, active_batch: ''})});
    let releaseAi;
    context.aiLoadBatchRunCounts = () => new Promise(resolve => { releaseAi = resolve; });
    context.updateAllFavoritesCount = () => {};
    context.updateAllPublicCount = async () => {};
    context.renderCount = 0;
    run("_initialLoadDone = true; _lastBatchListKey = 'existing'; _syncCustomSelectDisplay = () => {}; savedRenderBatchList = renderBatchList; renderBatchList = () => { renderCount++; }");
    await run('loadBatches()');
    assert.equal(context.renderCount, 1);
    run('openBatchSidebarPeek()');
    releaseAi();
    await Promise.resolve();
    assert.equal(context.renderCount, 1, 'late AI enrichment cannot replace a peek navigation row');
    run('renderBatchList = savedRenderBatchList');
    const list = elements['batch-list'] = new Element('batch-list');
    sidebar.appendChild(list);
    context.universalFavoritesCount = 0;
    context.universalPublicCount = 0;
    context.aiBatchRunCounts = {one: 1, two: 1};
    context.allCounts = {one: {inbox: 4}};
    run('renderBatchList(["one", "two"])');
    const one = list.children[2].querySelector('.batch-name');
    const count = one.querySelector('.batch-count');
    one.focus();
    list.scrollTop = 75;
    run('renderBatchList(["two", "one"])');
    assert.equal(list.children[3].querySelector('.batch-name'), one, 'sort reuses row DOM');
    assert.equal(document.activeElement, one, 'sort restores focus after DOM relocation');
    assert.equal(list.scrollTop, 75);
    // A foreground search response may commit after Tab has moved into a row.
    let foregroundReady;
    const foregroundStarted = new Promise(resolve => { foregroundReady = resolve; });
    context.fetch = async () => ({ok: true, json: () => new Promise(resolve => {
        releaseJson = resolve; foregroundReady();
    })});
    run('_lastBatchListKey = "one,two"');
    const foreground = run('loadBatches()');
    await foregroundStarted;
    releaseJson({batches: ['one', 'two'], counts: {one: {inbox: 8}}, active_batch: ''});
    await foreground;
    assert.equal(list.children[2].querySelector('.batch-name'), one, 'foreground response retains pending click target');
    assert.equal(one.querySelector('.batch-count'), count, 'even nested pointer targets survive count updates');
    assert.equal(count.textContent, '8');
    assert.equal(document.activeElement, one, 'foreground response keeps row keyboard focus');
    run('renderBatchList(["two"])');
    assert.equal(document.activeElement, elements['batch-search'], 'filtered-out focused batch returns focus to search');
    // Bind the real shared sort click handlers, not a peek-specific implementation.
    const sorts = ['alpha', 'count', 'recent', 'ai'].map(sort => {
        const button = new Element();
        button.dataset.bsort = sort;
        sidebar.appendChild(button);
        return button;
    });
    const getById = document.getElementById;
    const query = document.querySelector;
    const queryAll = document.querySelectorAll;
    document.getElementById = () => null;
    document.querySelector = () => null;
    document.querySelectorAll = selector => selector === '.batch-sort-btn' ? sorts : [];
    context.aiUpdateScoreSummary = () => {};
    load('static/js/events.js');
    run('_bindDelegatedEvents()');
    document.getElementById = getById;
    document.querySelector = query;
    document.querySelectorAll = selector => selector === '.batch-sort-btn' ? sorts : queryAll(selector);
    context.BATCH_SORT_KEY = 'sort';
    context.aiBatchRunCounts = {one: 4, two: 3, three: 1};
    context.fetch = async () => ({ok: true, json: async () => ({
        batches: ['one', 'three', 'two'], active_batch: '',
        counts: {one: {inbox: 1}, two: {inbox: 9}, three: {inbox: 3}},
        batch_meta: {one: {modified_at: 10}, two: {modified_at: 20}, three: {modified_at: 30}},
    })});
    run('_lastBatchListKey = "one,three,two"; savedLoadBatches = loadBatches; loadBatches = () => (sortRefresh = savedLoadBatches())');
    const expectedOrders = {
        alpha: ['one', 'three', 'two'], count: ['two', 'three', 'one'],
        recent: ['three', 'two', 'one'], ai: ['one', 'two', 'three'],
    };
    for (const button of sorts) {
        // Native <button> keyboard activation dispatches the same click with detail=0;
        // the DOM double verifies that path/focus, not browser default key synthesis.
        button.focus();
        button.fire('click', {detail: button.dataset.bsort === 'recent' ? 0 : 1});
        await run('sortRefresh');
        const sort = button.dataset.bsort;
        assert.equal(run('batchSort'), sort);
        assert.equal(stored.get('sort'), sort, 'peek uses the normal persisted sort preference');
        assert.equal(sorts.filter(b => b.classes.has('active')).length, 1);
        assert.equal(button.classes.has('active'), true);
        const actualOrder = list.children.slice(2).map(item => item.querySelector('.batch-name').dataset.batch);
        assert.deepEqual(actualOrder, expectedOrders[sort]);
        sidebar.fire('pointerleave');
        tick(280);
        assert.equal(document.activeElement, button, 'refresh keeps the shared sort button focused');
        assert.equal(run('isBatchSidebarPeeking()'), true, 'sorting and keyboard focus retain peek');
        assert.equal(run('sidebarOpen'), false);
        assert.equal(stored.get('open'), 'false', 'sort never reopens or persists the full sidebar');
    }
    // Pointer-only sorting also retains the peek without borrowing keyboard focus.
    outside.focus();
    run('openBatchSidebarPeek()');
    sorts[0].fire('click', {detail: 1});
    await run('sortRefresh');
    assert.equal(run('isBatchSidebarPeeking()'), true);
    assert.equal(document.activeElement, outside);
    console.log('batch sidebar peek lifecycle checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
