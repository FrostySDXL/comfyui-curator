#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function node() {
    const children = [];
    return {value: "", style: {}, disabled: false, textContent: "", innerHTML: "", children,
        classList: {add() {}, remove() {}, contains() { return false; }},
        setAttribute() {}, replaceChildren() {}, appendChild(child) { children.push(child); }, append() {}, focus() {},
        querySelector() { return null; }, addEventListener() {}};
}
function response(payload, ok = true) { return {ok, json: async () => payload}; }
function context() {
    const nodes = new Map();
    const fetches = [];
    const c = {
        console, window: {}, localStorage: {getItem() { return null; }, setItem() {}},
        document: {getElementById(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
            querySelector() { return null; }, querySelectorAll() { return []; }, createElement() { return node(); },
            createTextNode() { return {}; }, addEventListener() {}},
        fetch: async (...args) => { fetches.push(args); return response({operations: []}); },
        showToast() {}, hideToast() {}, _escapeHtml: (x) => String(x ?? ""), _trapFocus() {}, _releaseFocusTrap() {},
        getViewScopeKey: () => "batch-a\u001finbox", getCurrentDisplayImages: () => [],
        getImageRenderKey: (img) => img.name, updateImageCountLabel() {}, updateGrid() {}, loadBatches() {},
        getDisplayImages: () => [], getActiveLightboxImage: () => null, showCurrentImage() {},
        loadCurrentFolderImages: async () => {}, resetSelectionState() {}, isVirtualCollectionView: () => false,
        isPublicView: () => false, CSS: {escape: (x) => x}, setTimeout, clearTimeout,
    };
    vm.createContext(c);
    vm.runInContext(fs.readFileSync("static/js/state.js", "utf8"), c);
    vm.runInContext(fs.readFileSync("static/js/moves.js", "utf8"), c);
    return {c, nodes, fetches};
}

(async () => {
    const x = context();
    const calls = [];
    x.c.fetch = async (url, options) => {
        calls.push([url, options]);
        if (url.endsWith("move-history")) return response({operations: [{id: "op-2", batch: "batch-a", source: "inbox", destination: "finals", count: 1, created_at: "2026-08-27T12:00:00Z", status: "available", can_undo: true}, {id: "op-1", batch: "batch-a", source: "inbox", destination: "shortlisted", count: 2, status: "partial", restored: 1, can_undo: true}]});
        return response({success: true, moved: 1, skipped: 0, remaining: 0, status: "undone"});
    };
    await x.c.loadMoveHistory();
    assert.equal(vm.runInContext("lastAction.operationId", x.c), "op-2", "reload selects newest eligible operation");
    await x.c.undoLastMove();
    assert.equal(calls.filter(([url]) => url.endsWith("move-batch/undo")).length, 1);

    // Duplicate Ctrl+Z/History clicks share the in-flight guard.
    let release;
    const pending = new Promise((resolve) => { release = resolve; });
    x.c.fetch = (url) => url.endsWith("move-batch/undo") ? pending : response({operations: [{id: "op-3", batch: "batch-a", status: "available", can_undo: true}]});
    vm.runInContext("lastAction = {operationId: 'op-3'}", x.c);
    const first = x.c.undoMoveOperation("op-3");
    const second = x.c.undoMoveOperation("op-3");
    assert.equal(vm.runInContext("moveHistoryUndoInflight", x.c), "op-3");
    release(response({success: true, moved: 1, status: "undone"}));
    await Promise.all([first, second]);

    // Partial retry remains honest and exposes the server error without deleting the record.
    const p = context();
    p.c.fetch = async (url) => url.endsWith("move-history") ? response({operations: [{id: "op-p", batch: "batch-a", source: "inbox", destination: "finals", count: 2, status: "partial", restored: 1, can_undo: true, error: "destination exists"}]}) : response({success: false, error: "destination exists", status: "partial"}, false);
    await p.c.loadMoveHistory();
    await p.c.undoMoveOperation("op-p");
    assert.match(p.nodes.get("move-history-list").children[0].innerHTML, /destination exists/);

    // Dragging a normal selection uses filenames; snapshot selection uses revision/exclusions.
    const drag = context();
    let moved;
    drag.c.getCurrentDisplayImages = () => [{name: "a.png"}];
    drag.c.moveBatch = async (files, destination) => { moved = {files, destination}; };
    drag.c.moveSelected = async (destination) => { moved = {snapshot: true, destination}; };
    vm.runInContext("currentBatch='batch-a'; currentFolder='inbox'; selectedImages = new Set(['a.png']);", drag.c);
    drag.c.onDragStart({dataTransfer: {setData() {}, effectAllowed: ""}, target: {addEventListener() {}}}, 0);
    drag.c.onDrop({preventDefault() {}}, "shortlisted", node());
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(JSON.stringify(moved), JSON.stringify({files: ["a.png"], destination: "shortlisted"}));
    vm.runInContext("serverSelection={revision: 'r1', excluded: new Set(['other.png'])};", drag.c);
    drag.c.onDragStart({dataTransfer: {setData() {}, effectAllowed: ""}, target: {addEventListener() {}}}, 0);
    drag.c.onDrop({preventDefault() {}}, "finals", node());
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(JSON.stringify(moved), JSON.stringify({snapshot: true, destination: "finals"}));
    vm.runInContext("serverSelection={revision: 'r1', excluded: new Set(['a.png'])};", drag.c);
    drag.c.onDragStart({dataTransfer: {setData() {}, effectAllowed: ""}, target: {addEventListener() {}}}, 0);
    drag.c.onDrop({preventDefault() {}}, "rejects", node());
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(JSON.stringify(moved), JSON.stringify({files: ["a.png"], destination: "rejects"}), "excluded snapshot thumb moves singly");
    vm.runInContext("currentBatch='__favorites__'; currentFolder=null; draggedFiles=['a.png'];", drag.c);
    drag.c.isVirtualCollectionView = () => true;
    drag.c.onDrop({preventDefault() {}}, "finals", node());
    assert.equal(JSON.stringify(moved), JSON.stringify({files: ["a.png"], destination: "rejects"}), "virtual view blocks drag mutation");

    // Lightbox move parses success=false and cannot mutate a navigated-away view.
    const lightbox = context();
    let lightboxLoads = 0;
    lightbox.c.getLightboxImages = () => [{name: "lb.png"}];
    lightbox.c.getImageBatchAndFolder = () => ({batch: "batch-a", folder: "inbox"});
    lightbox.c.getImageDisplayIndexByName = () => 0;
    lightbox.c.getViewScopeKey = () => "batch-a\u001finbox";
    lightbox.c.getActiveLightboxImage = () => ({name: "lb.png"});
    lightbox.c.fetch = async () => response({success: false, error: "conflict"});
    lightbox.c.loadCurrentFolderImages = async () => { lightboxLoads += 1; };
    vm.runInContext("currentBatch='batch-a'; currentFolder='inbox';", lightbox.c);
    await lightbox.c.moveImage("finals");
    assert.equal(lightboxLoads, 0, "success=false does not refresh as a move");
    lightbox.c.fetch = async () => { lightbox.c.getViewScopeKey = () => "batch-b\u001finbox"; return response({success: true, operation_id: "op-lb"}); };
    await lightbox.c.moveImage("finals");
    assert.equal(lightboxLoads, 0, "stale lightbox response cannot refresh new view");

    // Execute the real snapshot drag -> moveSelected -> fetch chain, not a stubbed mover.
    const snapshot = context();
    snapshot.c.getCurrentDisplayImages = () => [{name: "selected.mp4"}];
    let snapshotPayload;
    snapshot.c.fetch = async (url, options) => {
        if (url.endsWith('/move-batch')) {
            snapshotPayload = JSON.parse(options.body);
            return response({success: true, moved: 9, operation_id: 'snapshot-op'});
        }
        return response({operations: []});
    };
    vm.runInContext("currentBatch='batch-a'; currentFolder='inbox'; currentSort='name'; currentOrder='asc'; serverSelection={revision:'revision-9',shuffleSeed:'',excluded:new Set(['excluded.png'])};", snapshot.c);
    snapshot.c.onDragStart({dataTransfer: {setData() {}}, target: {addEventListener() {}}}, 0);
    snapshot.c.onDrop({preventDefault() {}}, 'shortlisted', node());
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.deepEqual(snapshotPayload, {batch:'batch-a',source:'inbox',destination:'shortlisted',selection:{type:'snapshot',revision:'revision-9',sort:'name',order:'asc',shuffle_seed:'',excluded:['excluded.png']}});

    // A failed authoritative history read must not undo an older cached operation.
    const failedRead = context();
    const failedReadToasts = [];
    let failedReadPosts = 0;
    failedRead.c.showToast = text => failedReadToasts.push(text);
    vm.runInContext("moveHistory=[{id:'old',status:'available',can_undo:true}];", failedRead.c);
    failedRead.c.fetch = async (_url, options) => {
        if (options?.method === 'POST') failedReadPosts++;
        return response({error:'History storage unavailable'}, false);
    };
    await failedRead.c.undoLastMove();
    assert.equal(failedReadPosts, 0);
    assert.equal(failedReadToasts.at(-1), 'History storage unavailable');

    // Undo inserts an earlier image but keeps the currently reviewed image selected.
    const continuity = context();
    const viewer = continuity.c.document.getElementById('lightbox');
    viewer.classList.contains = name => name === 'active';
    vm.runInContext("currentBatch='batch-a';currentFolder='inbox';images=[{name:'reviewing.png'}];currentIndex=0;", continuity.c);
    continuity.c.getActiveLightboxImage = () => ({name:'reviewing.png'});
    continuity.c.getDisplayImages = () => vm.runInContext('images', continuity.c);
    continuity.c.loadCurrentFolderImages = async () => vm.runInContext("images=[{name:'restored.png'},{name:'reviewing.png'}];", continuity.c);
    let displayedIndex = -1;
    continuity.c.showCurrentImage = () => { displayedIndex = vm.runInContext('currentIndex', continuity.c); };
    continuity.c.fetch = async url => url.endsWith('move-history') ? response({operations:[]}) : response({success:true,moved:1,status:'undone'});
    await continuity.c.undoMoveOperation('continuity-op');
    assert.equal(displayedIndex, 1, 'undo keeps the current image by identity, not old numeric index');

    const moving = context();
    let resets = 0;
    let reloads = 0;
    moving.c.resetSelectionState = () => { resets++; };
    moving.c.loadCurrentFolderImages = async () => { reloads++; };
    moving.c.fetch = async url => url.endsWith('move-history') ? response({operations:[]}) : response({success:true,moved:1,operation_id:'moving-op'});
    vm.runInContext("currentBatch='batch-a';currentFolder='inbox';", moving.c);
    moving.c.animateThumbRemoval = async () => vm.runInContext("currentBatch='batch-b';viewTransitionToken++;", moving.c);
    await moving.c.moveBatch(['a.png'], 'finals');
    assert.equal(resets, 0, 'navigation during removal animation preserves new-view selection');
    assert.equal(reloads, 0, 'navigation during removal animation cannot refresh another view');

    moving.c.animateThumbRemoval = async () => { throw new Error('partial result must not animate all requested names'); };
    await moving.c.moveBatch(['a.png','b.png'], 'finals');
    assert.equal(reloads, 1, 'partial moves reload actual folder membership');
    console.log("move history and drag lifecycle checks passed");
})();
