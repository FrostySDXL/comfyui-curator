#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

(async () => {

function deferred() {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return {promise, resolve};
}

function extractFunction(sourceText, signature) {
    const start = sourceText.indexOf(signature);
    if (start < 0) throw new Error(`missing ${signature}`);
    const open = sourceText.indexOf("{", start);
    let depth = 0;
    for (let i = open; i < sourceText.length; i += 1) {
        if (sourceText[i] === "{") depth += 1;
        if (sourceText[i] === "}" && --depth === 0) return sourceText.slice(start, i + 1);
    }
    throw new Error(`unterminated ${signature}`);
}

const source = [
    "static/js/state.js",
    "static/js/ai-state.js",
    "static/js/ai-panel.js",
    "static/js/ai-inspector.js",
].map((file) => fs.readFileSync(file, "utf8")).join("\n");
const metadataSource = fs.readFileSync("static/js/metadata.js", "utf8");
const favoritesSource = fs.readFileSync("static/js/favorites.js", "utf8");
const pollingSource = fs.readFileSync("static/js/polling.js", "utf8");

const context = {
    console,
    window: {},
    localStorage: {getItem() { return null; }, setItem() {}},
    document: {
        querySelectorAll() { return []; },
        getElementById() { return {replaceChildren() {}, append() {}, appendChild() {}, style: {}, classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }}}; },
        createElement() { return {className: '', append() {}, appendChild() {}, setAttribute() {}, classList: {add() {}, toggle() {}}, replaceChildren() {}}; },
    },
    createTextElement() { return {className: '', append() {}, appendChild() {}, setAttribute() {}, classList: {add() {}, toggle() {}}}; },
    isInteractionBusy() { return false; },
    currentBatch: "batch-a",
    currentFolder: "shortlisted",
};
vm.createContext(context);
vm.runInContext(source, context, {filename: "state-transitions.js"});
vm.runInContext(metadataSource, context, {filename: "metadata.js"});
vm.runInContext("getImageBatchAndFolder = (img) => ({batch: img.batch || currentBatch, folder: img.folder || currentFolder});", context);

const inbox = {name: "portrait.png"};

assert.equal(
    context.getImageIdentityKey(inbox, {batch: "batch-a", folder: "inbox"}),
    "batch-a\u001finbox\u001fportrait.png",
);
assert.notEqual(
    context.getImageIdentityKey(inbox, {batch: "batch-a", folder: "inbox"}),
    context.getImageIdentityKey({name: "portrait.png"}, {batch: "batch-a", folder: "shortlisted"}),
    "same filename in different folders must not share inspector identity",
);

vm.runInContext("currentBatch = 'batch-a'; currentFolder = 'inbox'; images = [{name: 'portrait.png'}]", context);
context.aiSetInspectedImage(inbox, {batch: "batch-a", folder: "inbox"});
assert.equal(vm.runInContext("aiInspectedImageKey", context), "batch-a\u001finbox\u001fportrait.png");
assert.equal(vm.runInContext("images.length", context), 1);
assert.equal(vm.runInContext("getImageIdentityKey(images[0])", context), "batch-a\u001finbox\u001fportrait.png");
assert.equal(vm.runInContext("aiGetInspectedImage()?.name", context), "portrait.png", "current source target resolves before transition");
vm.runInContext("currentFolder = 'shortlisted'; images = [{name: 'portrait.png'}]", context);
assert.equal(vm.runInContext("aiGetInspectedImage()", context), null, "stale source-qualified target must not resolve in new folder");

// Virtual collections retain source identity even when filenames collide.
vm.runInContext("currentBatch = '__favorites__'; currentFolder = null; images = [{name: 'same.png', batch: 'a', folder: 'inbox'}, {name: 'same.png', batch: 'b', folder: 'finals'}]", context);
const virtualThumb = {dataset: {inspectorKey: "b\u001ffinals\u001fsame.png"}, classList: {toggle(_name, value) { this.inspected = value; }}};
context.document.querySelectorAll = () => [virtualThumb];
context.aiSetInspectedImage({name: "same.png", batch: "b", folder: "finals"});
assert.equal(vm.runInContext("aiGetInspectedImage().batch", context), "b", "virtual duplicate filename resolves by source");
assert.equal(virtualThumb.classList.inspected, true, "virtual thumb highlight uses source identity");

context.aiSetInspectedImage(inbox, {batch: "batch-a", folder: "inbox"});
const metadataTokenBeforeTransition = vm.runInContext("inspectorMetadataRequestToken", context);
context.beginViewTransition({clearImages: true});
assert.equal(vm.runInContext("aiGetInspectedImage()", context), null, "view transition invalidates inspector target");
assert.equal(
    vm.runInContext("inspectorMetadataRequestToken", context),
    metadataTokenBeforeTransition + 1,
    "view transition invalidates delayed metadata responses",
);

// The real selection reset owner clears selected state and mode.
vm.runInContext([
    "updateSelectionVisuals = () => {}; updateActionBar = () => {}; setSelectionMode = (active) => { selectionMode = active; };",
    extractFunction(fs.readFileSync("static/js/moves.js", "utf8"), "function resetSelectionState()"),
    "selectedImages = new Set(['same.png']); selectionMode = true; resetSelectionState();",
].join("\n"), context);
assert.equal(vm.runInContext("selectedImages.size === 0 && selectionMode === false", context), true, "transition reset clears real selection state");

// Snapshot selection counts drive the inspector after Select All/exclusions.
vm.runInContext("serverSelection = {count: 10, excluded: new Set()};", context);
assert.equal(vm.runInContext("getInspectorSelectionCount()", context), 10);
vm.runInContext("serverSelection.excluded.add('item-1');", context);
assert.equal(vm.runInContext("getInspectorSelectionCount()", context), 9);
vm.runInContext("serverSelection.excluded = new Set(Array.from({length: 10}, (_, i) => 'item-' + i));", context);
assert.equal(vm.runInContext("getInspectorSelectionCount()", context), 0);
vm.runInContext("serverSelection = null;", context);
assert.equal(vm.runInContext("getInspectorSelectionCount()", context), 0);

// Delayed metadata must not publish after a scope transition.
vm.runInContext("getImageBatchAndFolder = (img) => ({batch: currentBatch, folder: currentFolder});", context);
const metadataResponse = deferred();
context.fetch = () => metadataResponse.promise;
vm.runInContext("currentBatch = 'batch-a'; currentFolder = 'inbox'; images = [{name: 'portrait.png'}]; inspectorActiveTab = 'metadata';", context);
const metadataLoad = context.loadInspectorMetadata({name: "portrait.png"});
context.beginViewTransition({clearImages: true});
metadataResponse.resolve({ok: true, json: async () => ({has_metadata: true})});
await metadataLoad;
assert.equal(vm.runInContext("inspectorMetadata", context), null, "stale metadata response is ignored after transition");

// Virtual favorite responses must be scoped to the request and view.
vm.runInContext([
    "saveBatchState = () => {}; resetAiBatchState = () => {}; updateImageCountLabel = () => {};",
    "updateGrid = () => {}; updateAllFavoritesCount = () => {}; updateAutoImportQuickAction = () => {};",
    "createTextElement = () => ({});",
    extractFunction(favoritesSource, "async function loadUniversalFavorites()"),
].join("\n"), context);
const favoriteResponse = deferred();
context.fetch = () => favoriteResponse.promise;
const favoriteLoad = context.loadUniversalFavorites();
vm.runInContext("currentBatch = 'batch-b'; currentFolder = 'inbox'; beginViewTransition({clearImages: true});", context);
favoriteResponse.resolve({ok: true, json: async () => ({favorites: [{filename: 'stale.png', batch: 'old', folder: 'inbox'}]})});
await favoriteLoad;
assert.equal(vm.runInContext("images.length", context), 0, "stale virtual response does not replace current view");

// Poll results must be ignored when interaction/scope changes during awaits.
vm.runInContext([
    "loadBatches = async () => {}; aiLatestRun = null; aiShowOverlays = false; aiFilterMode = 'all';",
    "aiCompareRunId = 'latest'; aiRefreshRunData = async () => {}; updateGrid = () => {}; showCurrentImage = () => {};",
    "buildImageSignature = (list) => list.map(img => img.name).join('|');",
    extractFunction(pollingSource, "async function pollForChanges()"),
    "currentBatch = 'batch-c'; currentFolder = 'inbox'; images = [{name: 'keep.png'}];",
].join("\n"), context);
const pollImages = deferred();
const pollRuns = deferred();
context.fetch = (url) => url.includes("/runs") ? pollRuns.promise : pollImages.promise;
const pollLoad = context.pollForChanges();
await Promise.resolve();
context.beginViewTransition({clearImages: true});
pollImages.resolve({ok: true, json: async () => [{name: 'stale.png'}]});
pollRuns.resolve({ok: true, json: async () => ({runs: []})});
await pollLoad;
assert.equal(vm.runInContext("images.length", context), 0, "stale polling response does not repopulate a new view");

// A user interaction beginning after transport completes still blocks apply.
vm.runInContext("currentBatch = 'batch-d'; currentFolder = 'inbox'; images = [{name: 'keep.png'}]; let busy = false; isInteractionBusy = () => busy;", context);
const busyImages = deferred();
const busyRuns = deferred();
context.fetch = (url) => url.includes("/runs") ? busyRuns.promise : busyImages.promise;
const busyLoad = context.pollForChanges();
await Promise.resolve();
vm.runInContext("busy = true", context);
busyImages.resolve({ok: true, json: async () => [{name: 'busy-stale.png'}]});
busyRuns.resolve({ok: true, json: async () => ({runs: []})});
await busyLoad;
assert.equal(vm.runInContext("images[0].name", context), "keep.png", "busy interaction blocks polling image apply");

console.log("state transition lifecycle checks passed");
})().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
