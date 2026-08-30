#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function deferred() {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return {promise, resolve};
}

function makeNode(id = '') {
    return {
        value: id === "media-search-scope" ? "folder" : (id === "media-search-input" ? "needle" : ""),
        disabled: false,
        hidden: false,
        style: {},
        textContent: "",
        classList: {
            classes: new Set(["active"]),
            add(name) { this.classes.add(name); },
            remove(name) { this.classes.delete(name); },
            toggle(name, force) { if (force) this.classes.add(name); else this.classes.delete(name); },
            contains(name) { return this.classes.has(name); },
        },
        replaceChildren() {},
        append() {},
        appendChild() {},
        setAttribute() {},
        removeAttribute() {},
        focus() {},
        querySelector() { return null; },
    };
}

function makeContext() {
    const nodes = new Map();
    const toasts = [];
    const context = {
        console,
        setTimeout,
        clearTimeout,
        window: {},
        localStorage: {getItem() { return null; }, setItem() {}},
        document: {
            body: {classList: {toggle() {}}},
            querySelectorAll() { return []; },
            querySelector() { return null; },
            getElementById(id) {
                if (!nodes.has(id)) nodes.set(id, makeNode(id));
                return nodes.get(id);
            },
            createElement() { return makeNode(); },
            createTextNode() { return {}; },
        },
        createTextElement() { return makeNode(); },
        showToast(message) { toasts.push(message); },
        fetch() { throw new Error("unexpected fetch"); },
        apiSearchMedia() { throw new Error("unexpected search"); },
        resetPagedFolderState() {},
        resetSelectionState() {},
        resetAiBatchState() {},
        updateImageCountLabel() {},
        updateGrid() {},
        hideLightbox() {},
        closeLightbox() {},
        _releaseFocusTrap() {},
        _promptCloseDropdown() {},
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync("static/js/state.js", "utf8"), context, {filename: "state.js"});
    vm.runInContext(fs.readFileSync("static/js/prompts.js", "utf8"), context, {filename: "prompts.js"});
    vm.runInContext([
        "currentBatch = 'batch-a'; currentFolder = 'inbox';",
        "librarySearchTab = 'images';",
        "renderMediaSearchResults = () => {};",
        "syncWorkspaceSearchFilterBar = () => {};",
        "resetPagedFolderState = () => {}; resetSelectionState = () => {}; resetAiBatchState = () => {};",
        "updateImageCountLabel = () => {}; updateGrid = () => {};",
    ].join("\n"), context);
    return {context, nodes, toasts};
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

async function testClearRestoresLegacyAndPagedAnchors() {
    async function prepareContext() {
        const fixture = makeContext();
        const anchor = {key: "anchor.png", offset: 13};
        const restored = [];
        fixture.context._captureGridIdentityAnchor = () => anchor;
        fixture.context._restoreGridIdentityAnchor = value => {
            restored.push(value);
            return true;
        };
        fixture.context.apiSearchMedia = () => Promise.resolve({
            ok: true,
            json: async () => ({
                items: [{name: "match.png", batch: "batch-a", folder: "inbox"}],
                total: 1,
            }),
        });
        fixture.context.fetch = () => Promise.resolve({
            ok: true,
            json: async () => ({favorites: []}),
        });
        fixture.context.selectFolder = async (batch, folder) => {
            vm.runInContext(
                `currentBatch = ${JSON.stringify(batch)}; currentFolder = ${JSON.stringify(folder)};`,
                fixture.context,
            );
        };
        await fixture.context.applyMediaSearchToWorkspace();
        return {fixture, anchor, restored};
    }

    const legacy = await prepareContext();
    vm.runInContext("pagedFolderMode = false; folderSnapshot = null;", legacy.fixture.context);
    await legacy.fixture.context.clearWorkspaceSearchFilter();
    assert.deepEqual(legacy.restored, [legacy.anchor], "legacy Clear must restore its captured grid anchor");

    const paged = await prepareContext();
    const pageCalls = [];
    const lookupCalls = [];
    paged.fixture.context._folderTransportSort = () => "date";
    paged.fixture.context.apiGetFolderItemIndex = (...args) => {
        lookupCalls.push(args);
        return Promise.resolve({ok: true, json: async () => ({index: 256})});
    };
    paged.fixture.context.ensureFolderPageForIndex = async index => {
        pageCalls.push(index);
    };
    vm.runInContext(
        "pagedFolderMode = true; folderSnapshot = {revision: 'revision-1', count: 30000};",
        paged.fixture.context,
    );
    await paged.fixture.context.clearWorkspaceSearchFilter();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(lookupCalls.length, 1, "paged Clear must perform one O(1) anchor lookup");
    assert.equal(lookupCalls[0][0], "batch-a");
    assert.equal(lookupCalls[0][1], "inbox");
    assert.equal(lookupCalls[0][4], "revision-1");
    assert.equal(lookupCalls[0][5], paged.anchor.key);
    assert.deepEqual(pageCalls, [256], "paged Clear must load the anchor page before restoring scroll");
    assert.deepEqual(paged.restored, [paged.anchor], "paged Clear must restore its captured grid anchor");
}

async function main() {
    const folderContext = makeContext();
    const folderTabs = folderContext.context.document.getElementById("folder-tabs");
    vm.runInContext([
        extractFunction(fs.readFileSync("static/js/batches.js", "utf8"), "async function selectFolder("),
        extractFunction(fs.readFileSync("static/js/publish.js", "utf8"), "async function loadBatchPublic("),
        extractFunction(fs.readFileSync("static/js/publish.js", "utf8"), "function normalizePublicItems("),
        "saveBatchState = () => {}; updateAutoImportQuickAction = () => {}; showGridLoadingPlaceholders = () => {}; updateFolderTabs = () => {};",
        "loadCurrentFolderImages = async () => {};",
        "apiGetBatchPublic = async () => []; activityComplete = () => {}; activityAttemptId = (g, t) => g + ':' + t; activityRegister = () => {}; activityRemove = () => {}; setGridLoadingStatus = () => {};",
        "currentBatch = '__search__'; currentFolder = null; workspaceSearchFilter = {}; workspaceSearchReturnContext = {batch: 'batch-a', folder: 'shortlisted'};",
    ].join("\n"), folderContext.context);
    await folderContext.context.clearWorkspaceSearchFilter();
    assert.equal(vm.runInContext("currentBatch", folderContext.context), "batch-a");
    assert.equal(vm.runInContext("currentFolder", folderContext.context), "shortlisted");
    assert.equal(vm.runInContext("workspaceSearchFilter", folderContext.context), null);
    assert.equal(vm.runInContext("workspaceSearchReturnContext", folderContext.context), null);
    assert.equal(folderTabs.classList.contains("visible"), true, "real-folder clear restores folder rail visibility");
    vm.runInContext("currentBatch = '__search__'; currentFolder = null; workspaceSearchFilter = {}; workspaceSearchReturnContext = {batch: 'batch-a', folder: 'public'};", folderContext.context);
    folderTabs.classList.remove("visible");
    await folderContext.context.clearWorkspaceSearchFilter();
    assert.equal(vm.runInContext("currentFolder", folderContext.context), "public");
    assert.equal(folderTabs.classList.contains("visible"), true, "batch public clear restores folder rail visibility");

    const delayedView = makeContext();
    const delayedViewSearch = deferred();
    let delayedViewRenders = 0;
    delayedView.context.apiSearchMedia = () => delayedViewSearch.promise;
    delayedView.context.renderMediaSearchResults = () => { delayedViewRenders += 1; };
    const delayedViewApply = delayedView.context.applyMediaSearchToWorkspace();
    vm.runInContext("currentBatch = 'batch-b'; currentFolder = 'finals'; beginViewTransition({clearImages: true});", delayedView.context);
    delayedViewSearch.resolve({ok: true, json: async () => ({items: [{name: "stale.png"}], total: 1})});
    await delayedViewApply;
    assert.equal(delayedViewRenders, 0, "delayed search cannot render after view-only transition");
    assert.deepEqual(delayedView.toasts, [], "delayed search emits no stale toast after transition");

    const delayedFavoritesView = makeContext();
    const delayedFavoritesSearch = deferred();
    const delayedFavorites = deferred();
    const delayedFavoritesStarted = deferred();
    delayedFavoritesView.context.apiSearchMedia = () => delayedFavoritesSearch.promise;
    delayedFavoritesView.context.fetch = () => { delayedFavoritesStarted.resolve(); return delayedFavorites.promise; };
    const delayedFavoritesApply = delayedFavoritesView.context.applyMediaSearchToWorkspace();
    delayedFavoritesSearch.resolve({ok: true, json: async () => ({items: [{name: "stale.png"}], total: 1})});
    await delayedFavoritesStarted.promise;
    vm.runInContext("currentBatch = 'batch-b'; currentFolder = 'finals'; beginViewTransition({clearImages: true});", delayedFavoritesView.context);
    delayedFavorites.resolve({ok: true, json: async () => ({favorites: []})});
    await delayedFavoritesApply;
    assert.equal(vm.runInContext("workspaceSearchFilter", delayedFavoritesView.context), null, "favorites await cannot publish after view transition");

    const virtual = makeContext();
    vm.runInContext("currentBatch = '__favorites__'; currentFolder = null;", virtual.context);
    virtual.context.apiSearchMedia = () => Promise.resolve({ok: true, json: async () => ({items: [{name: "fav.png", batch: "batch-a", folder: "inbox"}], total: 1})});
    virtual.context.fetch = () => Promise.resolve({ok: true, json: async () => ({favorites: []})});
    await virtual.context.applyMediaSearchToWorkspace();
    assert.equal(vm.runInContext("workspaceSearchFilter.scope", virtual.context), "all", "virtual favorite scope normalizes folder control to all");

    const preview = makeContext();
    const previewJson = deferred();
    const previewJsonStarted = deferred();
    preview.context.apiSearchMedia = () => Promise.resolve({ok: true, json: () => { previewJsonStarted.resolve(); return previewJson.promise; }});
    const previewLoad = preview.context.runMediaSearch();
    await previewJsonStarted.promise;
    const applyData = {items: [{name: "applied.png", batch: "batch-a", folder: "inbox"}], total: 1};
    preview.context.apiSearchMedia = () => Promise.resolve({ok: true, json: async () => applyData});
    preview.context.fetch = () => Promise.resolve({ok: true, json: async () => ({favorites: []})});
    await preview.context.applyMediaSearchToWorkspace();
    previewJson.resolve({items: [{name: "obsolete.png"}], total: 1});
    await previewLoad;
    assert.equal(vm.runInContext("mediaSearchResults.items[0].name", preview.context), "applied.png", "obsolete preview JSON cannot overwrite applied results");

    const roundTrip = makeContext();
    const roundTripSearch = deferred();
    roundTrip.context.apiSearchMedia = () => roundTripSearch.promise;
    roundTrip.context.fetch = () => Promise.resolve({ok: true, json: async () => ({favorites: []})});
    const roundTripApply = roundTrip.context.applyMediaSearchToWorkspace();
    vm.runInContext("currentBatch = 'batch-b'; currentFolder = 'finals'; beginViewTransition({clearImages: true}); currentBatch = 'batch-a'; currentFolder = 'inbox'; beginViewTransition({clearImages: true});", roundTrip.context);
    roundTripSearch.resolve({ok: true, json: async () => ({items: [{name: "stale.png"}], total: 1})});
    await roundTripApply;
    assert.equal(vm.runInContext("workspaceSearchFilter", roundTrip.context), null, "navigate away and back still invalidates stale apply");

    const {context, nodes, toasts} = makeContext();
    const search = deferred();
    const favorites = deferred();
    let favoritesStarted = false;
    context.apiSearchMedia = () => search.promise;
    context.fetch = () => { favoritesStarted = true; return favorites.promise; };
    const applyButton = context.document.getElementById("media-search-apply-btn");
    const apply = context.applyMediaSearchToWorkspace();
    search.resolve({ok: true, json: async () => ({items: [{name: "fresh.png", batch: "batch-a", folder: "inbox"}], total: 1})});
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(favoritesStarted, true, "search response must reach the favorites await before navigation");
    context.hidePromptsModal();
    vm.runInContext("currentBatch = 'batch-b'; currentFolder = 'finals'; beginViewTransition({clearImages: true});", context);
    favorites.resolve({ok: true, json: async () => ({favorites: []})});
    await apply;
    assert.equal(vm.runInContext("currentBatch", context), "batch-b", "navigation owns the view");
    assert.equal(vm.runInContext("workspaceSearchFilter", context), null, "stale apply does not install a filter");
    assert.deepEqual(toasts, [], "stale apply does not emit a success toast");
    assert.equal(applyButton.disabled, false, "hide cancellation re-enables the apply button");

    const success = makeContext();
    const successSearch = deferred();
    const successFavorites = deferred();
    success.context.apiSearchMedia = () => successSearch.promise;
    success.context.fetch = () => successFavorites.promise;
    const successApplyButton = success.context.document.getElementById("media-search-apply-btn");
    const successfulApply = success.context.applyMediaSearchToWorkspace();
    successSearch.resolve({ok: true, json: async () => ({
        items: [{name: "fresh.png", batch: "batch-a", folder: "inbox"}], total: 1,
    })});
    await Promise.resolve();
    successFavorites.resolve({ok: true, json: async () => ({favorites: [{batch: "batch-a", folder: "inbox", filename: "fresh.png"}]})});
    await successfulApply;
    assert.equal(vm.runInContext("currentBatch", success.context), "__search__", "successful apply enters search view");
    assert.equal(vm.runInContext("workspaceSearchReturnContext.batch", success.context), "batch-a");
    assert.equal(vm.runInContext("workspaceSearchReturnContext.folder", success.context), "inbox");
    assert.equal(vm.runInContext("images.length", success.context), 1, "successful apply installs returned items");
    assert.equal(vm.runInContext("images[0].favorite", success.context), true, "successful apply maps favorite status");
    assert.equal(successApplyButton.disabled, false, "successful apply restores its button");

    const edited = makeContext();
    const editedSearch = deferred();
    const editedFavorites = deferred();
    edited.context.apiSearchMedia = () => editedSearch.promise;
    edited.context.fetch = () => editedFavorites.promise;
    const editedApply = edited.context.applyMediaSearchToWorkspace();
    editedSearch.resolve({ok: true, json: async () => ({items: [{name: "old.png"}], total: 1})});
    await new Promise((resolve) => setTimeout(resolve, 0));
    edited.context.document.getElementById("media-search-input").value = "changed";
    edited.context.scheduleMediaSearch();
    assert.equal(edited.context.document.getElementById("media-search-apply-btn").disabled, false, "input edits cancel and re-enable apply");
    edited.context.setLibrarySearchTab("prompts");
    edited.context.setLibrarySearchTab("images");
    editedFavorites.resolve({ok: true, json: async () => ({favorites: []})});
    await editedApply;
    assert.equal(vm.runInContext("workspaceSearchFilter", edited.context), null, "edited query invalidates pending apply");
    assert.deepEqual(edited.toasts, [], "edited query emits no stale toast");

    const overlap = makeContext();
    const firstSearch = deferred();
    const firstFavorites = deferred();
    const secondSearch = deferred();
    let searchCalls = 0;
    overlap.context.apiSearchMedia = () => (++searchCalls === 1 ? firstSearch.promise : secondSearch.promise);
    overlap.context.fetch = () => firstFavorites.promise;
    const firstApply = overlap.context.applyMediaSearchToWorkspace();
    firstSearch.resolve({ok: true, json: async () => ({items: [{name: "first.png"}], total: 1})});
    await new Promise((resolve) => setTimeout(resolve, 0));
    overlap.context.document.getElementById("media-search-input").value = "second";
    const secondApply = overlap.context.applyMediaSearchToWorkspace();
    firstFavorites.resolve({ok: true, json: async () => ({favorites: []})});
    await firstApply;
    assert.equal(overlap.context.document.getElementById("media-search-apply-btn").disabled, true, "old apply cannot re-enable newer apply");
    secondSearch.resolve({ok: true, json: async () => ({items: [{name: "second.png"}], total: 1})});
    await new Promise((resolve) => setTimeout(resolve, 0));
    await secondApply;
    assert.equal(vm.runInContext("workspaceSearchFilter.query", overlap.context), "second", "newer apply remains current");
    assert.equal(vm.runInContext("images[0].name", overlap.context), "second.png", "newer apply wins the overlap");
    assert.equal(overlap.context.document.getElementById("media-search-apply-btn").disabled, false, "newer apply re-enables its button");
    await testClearRestoresLegacyAndPagedAnchors();
    console.log("media search apply lifecycle checks passed");
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
