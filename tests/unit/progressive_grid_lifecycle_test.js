#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const gridSource = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "js", "grid.js"),
    "utf8",
);

let assertionCount = 0;
function assert(condition, message) {
    assertionCount += 1;
    if (!condition) throw new Error(message);
}

class MockClassList {
    constructor(owner) {
        this.owner = owner;
        this.values = new Set();
    }

    add(...names) {
        names.forEach((name) => this.values.add(name));
        this._sync();
    }

    remove(...names) {
        names.forEach((name) => this.values.delete(name));
        this._sync();
    }

    toggle(name, force) {
        const enabled = force === undefined ? !this.values.has(name) : !!force;
        if (enabled) this.values.add(name);
        else this.values.delete(name);
        this._sync();
        return enabled;
    }

    contains(name) {
        return this.values.has(name);
    }

    setFromString(value) {
        this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
        this._sync();
    }

    _sync() {
        this.owner._className = [...this.values].join(" ");
    }
}

function selectorMatches(element, selector) {
    if (selector === "img") return element.tagName === "IMG";
    if (selector.startsWith(".")) {
        const classes = selector.slice(1).split(".");
        return classes.every((name) => element.classList.contains(name));
    }
    return false;
}

class MockElement {
    constructor(tagName, document) {
        this.tagName = String(tagName).toUpperCase();
        this.ownerDocument = document;
        this.parentNode = null;
        this.children = [];
        this.dataset = {};
        this.attributes = new Map();
        this.listeners = new Map();
        this.classList = new MockClassList(this);
        this._className = "";
        this.textContent = "";
        this.draggable = false;
        this.tabIndex = 0;
        this.type = "";
        this.isFragment = this.tagName === "#FRAGMENT";
        this.style = {
            values: new Map(),
            setProperty: (name, value) => this.style.values.set(name, String(value)),
            removeProperty: (name) => this.style.values.delete(name),
            getPropertyValue: (name) => this.style.values.get(name) || "",
        };
    }

    get className() {
        return this._className;
    }

    set className(value) {
        this.classList.setFromString(value);
    }

    get isConnected() {
        if (this === this.ownerDocument.documentElement) return true;
        return !!this.parentNode && this.parentNode.isConnected;
    }

    set innerHTML(value) {
        this.replaceChildren();
        if (String(value).includes("meta-name")) {
            const name = this.ownerDocument.createElement("span");
            name.className = "meta-name";
            const detail = this.ownerDocument.createElement("span");
            detail.className = "meta-detail";
            this.append(name, detail);
        }
    }

    get innerHTML() {
        return "";
    }

    append(...nodes) {
        nodes.forEach((node) => this.appendChild(node));
    }

    appendChild(node) {
        if (node.isFragment) {
            [...node.children].forEach((child) => this.appendChild(child));
            return node;
        }
        if (node.parentNode) node.parentNode._detach(node);
        node.parentNode = this;
        this.children.push(node);
        return node;
    }

    insertBefore(node, reference) {
        if (node.isFragment) {
            [...node.children].forEach((child) => this.insertBefore(child, reference));
            return node;
        }
        if (node === reference) return node;
        if (node.parentNode) node.parentNode._detach(node);
        const index = reference ? this.children.indexOf(reference) : -1;
        node.parentNode = this;
        if (index < 0) this.children.push(node);
        else this.children.splice(index, 0, node);
        return node;
    }

    replaceChildren(...nodes) {
        if (this === this.ownerDocument.grid) this.ownerDocument.gridReplaceCount += 1;
        this.children.forEach((child) => { child.parentNode = null; });
        this.children = [];
        nodes.forEach((node) => this.appendChild(node));
        if (this === this.ownerDocument.grid) {
            this.ownerDocument.minimumGridChildren = Math.min(
                this.ownerDocument.minimumGridChildren,
                this.children.length,
            );
        }
    }

    _detach(node) {
        const index = this.children.indexOf(node);
        if (index >= 0) this.children.splice(index, 1);
        node.parentNode = null;
        if (this === this.ownerDocument.grid) {
            this.ownerDocument.gridDetachCount += 1;
            this.ownerDocument.minimumGridChildren = Math.min(
                this.ownerDocument.minimumGridChildren,
                this.children.length,
            );
        }
    }

    remove() {
        if (this.parentNode) this.parentNode._detach(this);
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    querySelectorAll(selector) {
        const results = [];
        const visit = (node) => {
            node.children.forEach((child) => {
                if (selectorMatches(child, selector)) results.push(child);
                visit(child);
            });
        };
        visit(this);
        return results;
    }

    addEventListener(type, callback) {
        if (!this.listeners.has(type)) this.listeners.set(type, []);
        this.listeners.get(type).push(callback);
    }

    dispatchEvent(event) {
        event.target = event.target || this;
        event.currentTarget = this;
        (this.listeners.get(event.type) || []).forEach((callback) => callback(event));
        return true;
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
        if (name === "class") this.className = value;
    }

    getAttribute(name) {
        return this.attributes.has(name) ? this.attributes.get(name) : null;
    }
}

class MockDocument {
    constructor() {
        this.elements = new Map();
        this.gridReplaceCount = 0;
        this.gridDetachCount = 0;
        this.minimumGridChildren = Infinity;
        this.documentElement = new MockElement("html", this);
        this.body = new MockElement("body", this);
        this.documentElement.appendChild(this.body);
        this.content = new MockElement("main", this);
        this.content.className = "content";
        this.content.clientWidth = 1200;
        this.content.clientHeight = 100;
        this.content.scrollTop = 0;
        this.body.appendChild(this.content);
        this.shell = this.register("grid-shell", new MockElement("div", this));
        this.grid = this.register("grid", new MockElement("div", this));
        this.content.appendChild(this.shell);
        this.shell.appendChild(this.grid);
        this.register("img-count", new MockElement("span", this));
        this.register("sort-dir-btn", new MockElement("button", this));
        this.register("lightbox", new MockElement("div", this));
        Object.defineProperty(this.content, "scrollHeight", {
            get: () => Math.max(this.content.clientHeight, this.grid.children.length * 10),
        });
    }

    resetGridMutationCounters() {
        this.gridReplaceCount = 0;
        this.gridDetachCount = 0;
        this.minimumGridChildren = this.grid.children.length;
    }

    register(id, element) {
        element.id = id;
        this.elements.set(id, element);
        return element;
    }

    createElement(tagName) {
        return new MockElement(tagName, this);
    }

    createDocumentFragment() {
        return new MockElement("#fragment", this);
    }

    getElementById(id) {
        return this.elements.get(id) || null;
    }

    querySelector(selector) {
        if (selector === ".content") return this.content;
        if (selector === "#grid") return this.grid;
        return null;
    }

    querySelectorAll(selector) {
        if (selector === "#grid .thumb") return this.grid.querySelectorAll(".thumb");
        return [];
    }
}

function createHarness() {
    const document = new MockDocument();
    let nextRafId = 1;
    const rafQueue = new Map();
    const scheduleCalls = [];
    const unscheduleCalls = [];
    const scheduledElements = new Map();
    const schedulerLog = [];
    let cancelCalls = 0;
    const windowListeners = new Map();

    let context;
    context = vm.createContext({
        console,
        document,
        URL: { createObjectURL: () => "blob:test", revokeObjectURL: () => {} },
        fetch: () => Promise.reject(new Error("unexpected fetch")),
        requestAnimationFrame(callback) {
            const id = nextRafId++;
            rafQueue.set(id, callback);
            return id;
        },
        cancelAnimationFrame(id) {
            rafQueue.delete(id);
        },
        window: {
            addEventListener(type, callback) {
                if (!windowListeners.has(type)) windowListeners.set(type, []);
                windowListeners.get(type).push(callback);
            },
            getComputedStyle() {
                return { paddingLeft: "0", paddingRight: "0" };
            },
            ResizeObserver: null,
        },
        localStorage: { getItem: () => null, setItem: () => {} },
        formatSize: (size) => String(size || 0),
        ccThumbUrl: (batch, folder, name) => `/thumb/${batch}/${folder}/${name}`,
        isVirtualCollectionView: () => false,
        isPublicView: () => false,
        aiGetImageScore: () => null,
        aiShouldShowImage: (img) => context.aiFilterMode !== "failed" || img.name.endsWith("0000.png"),
        aiSortImages: (items) => items,
        aiScoreGradient: () => "",
        aiActiveRun: null,
        aiShowOverlays: false,
        aiFilterMode: "all",
        aiInspectedImageName: null,
        onDragStart: () => {},
        onThumbClick: () => {},
        setSelectionMode: () => {},
        toggleSelect: () => {},
        toggleFavorite: () => {},
        scheduleThumbnailLoad(element, imageSrc, cacheKey) {
            scheduleCalls.push({ element, imageSrc, cacheKey });
            scheduledElements.set(element, cacheKey);
            schedulerLog.push({ type: "schedule", element, cacheKey });
        },
        unscheduleThumbnailLoad(element) {
            unscheduleCalls.push(element);
            scheduledElements.delete(element);
            schedulerLog.push({ type: "unschedule", element });
        },
        cancelScheduledViewportLoads() {
            cancelCalls += 1;
            scheduledElements.clear();
        },
    });
    context.window.window = context.window;
    context.window.document = document;
    context.window.requestAnimationFrame = context.requestAnimationFrame;
    context.window.cancelAnimationFrame = context.cancelAnimationFrame;

    vm.runInContext(`
        let currentBatch = 'batch-a';
        let currentFolder = 'inbox';
        let images = [];
        let currentDisplayImages = [];
        let currentSort = 'date';
        let currentOrder = 'desc';
        let favoritesFilterOn = false;
        let selectedImages = new Set();
        let gridThumbMap = new Map();
        let gridDensity = 'comfortable';
        let allCounts = {};
        let folderRequestToken = 0;
        const GRID_DENSITY_KEY = 'imageCurator.gridDensity';
        const MAX_GRID_LOADING_PLACEHOLDERS = 200;
        const THUMBNAIL_BLOB_CACHE_MAX = 1000;
        const thumbnailBlobUrlCache = new Map();
        const thumbnailBlobInflight = new Map();
    `, context);
    vm.runInContext(gridSource, context);

    return {
        context,
        document,
        scheduleCalls,
        unscheduleCalls,
        schedulerLog,
        get cancelCalls() { return cancelCalls; },
        setImages(items) { context.__items = items; vm.runInContext("images = __items", context); },
        setCounts(counts) { context.__counts = counts; vm.runInContext("allCounts = __counts", context); },
        setContext(values) {
            context.__contextValues = values;
            vm.runInContext(`
                if (__contextValues.batch !== undefined) currentBatch = __contextValues.batch;
                if (__contextValues.folder !== undefined) currentFolder = __contextValues.folder;
                if (__contextValues.sort !== undefined) currentSort = __contextValues.sort;
                if (__contextValues.order !== undefined) currentOrder = __contextValues.order;
                if (__contextValues.favorites !== undefined) favoritesFilterOn = __contextValues.favorites;
                if (__contextValues.aiFilter !== undefined) aiFilterMode = __contextValues.aiFilter;
                if (__contextValues.aiOverlays !== undefined) aiShowOverlays = __contextValues.aiOverlays;
            `, context);
        },
        evaluate(expression) { return vm.runInContext(expression, context); },
        updateGrid() { context.updateGrid(); },
        initialize() { context.initializeGridShellLayout(); },
        flushRaf(waves = 1) {
            for (let wave = 0; wave < waves; wave += 1) {
                const callbacks = [...rafQueue.values()];
                rafQueue.clear();
                callbacks.forEach((callback) => callback());
            }
        },
        pendingRafCount() { return rafQueue.size; },
        isScheduled(element) { return scheduledElements.has(element); },
        scheduledKey(element) { return scheduledElements.get(element) || null; },
        dispatchWindow(type) {
            (windowListeners.get(type) || []).forEach((callback) => callback({ type }));
        },
    };
}

function makeImages(count, prefix = "image") {
    return Array.from({ length: count }, (_, index) => ({
        name: `${prefix}-${String(index).padStart(4, "0")}.png`,
        size: index + 1,
        favorite: false,
    }));
}

function testBoundedInitialPrefix() {
    const harness = createHarness();
    harness.setImages(makeImages(2000));
    harness.updateGrid();

    const initialLimit = harness.evaluate("PROGRESSIVE_GRID_INITIAL_LIMIT");
    assert(initialLimit === 120, `initial limit should be 120, got ${initialLimit}`);
    assert(harness.evaluate("currentDisplayImages.length") === 2000, "canonical display list should retain all 2,000 images");
    assert(harness.document.grid.children.length <= initialLimit, "initial DOM should be bounded by the initial limit");
    assert(harness.evaluate("gridThumbMap.size") <= initialLimit, "gridThumbMap should contain only rendered thumbs");
}

function testSmallListRendersAll() {
    const harness = createHarness();
    harness.setImages(makeImages(100));
    harness.updateGrid();

    assert(harness.document.grid.children.length === 100, "a list below the initial limit should render completely");
    assert(harness.evaluate("gridThumbMap.size") === 100, "small-list map should contain every rendered thumb");
    assert(harness.evaluate("currentDisplayImages.length") === 100, "small canonical list should remain complete");
}

function testFarAndNearScrollGrowth() {
    const harness = createHarness();
    harness.initialize();
    harness.setImages(makeImages(500));
    harness.updateGrid();
    harness.flushRaf(2);

    const initialCount = harness.document.grid.children.length;
    harness.document.content.scrollTop = 0;
    harness.document.content.dispatchEvent({ type: "scroll" });
    harness.flushRaf(2);
    assert(harness.document.grid.children.length === initialCount, "far-from-bottom scroll should not append");

    harness.document.content.scrollTop = harness.document.content.scrollHeight - harness.document.content.clientHeight;
    harness.document.content.dispatchEvent({ type: "scroll" });
    harness.document.content.dispatchEvent({ type: "scroll" });
    assert(harness.pendingRafCount() === 1, "repeated scroll events should share one guarded rAF");
    harness.flushRaf(1);
    assert(harness.document.grid.children.length === initialCount + 120, "one near-end wave should append exactly one chunk");
    assert(new Set(harness.document.grid.children).size === harness.document.grid.children.length, "appended DOM should not contain duplicate elements");
}

function testProgrammaticBottomDispatchEventuallyRendersAll() {
    const harness = createHarness();
    harness.initialize();
    harness.setImages(makeImages(500));
    harness.updateGrid();

    let guard = 0;
    while (harness.document.grid.children.length < 500 && guard < 20) {
        harness.document.content.scrollTop = harness.document.content.scrollHeight - harness.document.content.clientHeight;
        harness.document.content.dispatchEvent({ type: "scroll" });
        harness.document.content.dispatchEvent({ type: "scroll" });
        harness.flushRaf(2);
        guard += 1;
    }

    assert(harness.document.grid.children.length === 500, "programmatic bottom scroll dispatch should eventually render all approached chunks");
    assert(harness.evaluate("gridThumbMap.size") === 500, "eventual growth should keep one map entry per rendered image");
    assert(harness.evaluate("currentDisplayImages.length") === 500, "growth should not truncate the canonical list");
}

function testUnchangedPollingPreservesLiveThumbState() {
    const harness = createHarness();
    const items = makeImages(300);
    harness.setImages(items);
    harness.updateGrid();
    const first = harness.document.grid.children[0];
    const image = first.querySelector("img");
    image.setAttribute("src", "blob:retained");
    image.classList.add("loaded");
    first.classList.add("selected", "inspected");
    harness.evaluate(`selectedImages.add('${items[0].name}'); aiInspectedImageName = '${items[0].name}'`);
    const scheduleCount = harness.scheduleCalls.length;
    harness.document.resetGridMutationCounters();

    harness.updateGrid();

    assert(harness.document.grid.children[0] === first, "unchanged polling should preserve thumb object identity");
    assert(image.getAttribute("src") === "blob:retained", "unchanged polling should preserve thumbnail src");
    assert(image.classList.contains("loaded"), "unchanged polling should preserve loaded state");
    assert(first.classList.contains("selected") && first.classList.contains("inspected"), "unchanged polling should preserve selected and inspected state");
    assert(harness.scheduleCalls.length === scheduleCount, "unchanged polling should not schedule a thumbnail twice");
    assert(harness.document.gridDetachCount === 0 && harness.document.gridReplaceCount === 0, "unchanged polling should not detach or replace live children");
}

function testSameContextPrefixReconcilesWithoutEmptyFlash() {
    const harness = createHarness();
    const items = makeImages(200);
    harness.setImages(items);
    harness.updateGrid();
    const retained = harness.document.grid.children[0];
    const entering = items[150];
    const reordered = [entering, ...items.filter((item) => item !== entering)];
    harness.document.resetGridMutationCounters();
    harness.setImages(reordered);

    harness.updateGrid();

    assert(harness.document.grid.children[0].dataset.name === entering.name, "changed prefix should reconcile to canonical order");
    assert(harness.document.grid.children[1] === retained, "same-context reconciliation should reuse retained elements");
    assert(harness.document.gridReplaceCount === 0, "same-context reconciliation should not replace the full grid");
    assert(harness.document.minimumGridChildren > 0, "same-context reconciliation should not expose an empty grid");
    assert(harness.unscheduleCalls.length === 1, "one image leaving the rendered prefix should be unscheduled once");
}

function growOneChunk(harness) {
    harness.document.content.scrollTop = harness.document.content.scrollHeight - harness.document.content.clientHeight;
    harness.document.content.dispatchEvent({ type: "scroll" });
    harness.flushRaf(2);
}

function testContextResetAndSameContextLimitPreservation() {
    const harness = createHarness();
    harness.initialize();
    const items = makeImages(400, "inbox");
    harness.setImages(items);
    harness.updateGrid();
    growOneChunk(harness);
    assert(harness.document.grid.children.length === 240, "setup should grow the retained render limit to 240");

    harness.setImages([...items, ...makeImages(20, "added")]);
    harness.updateGrid();
    assert(harness.document.grid.children.length === 240, "same-context polling should preserve the current render limit");
    assert(harness.evaluate("getProgressiveGridState().renderLimit") === 240, "observability state should expose the preserved limit");

    const first = harness.document.grid.children[0];
    const second = harness.document.grid.children[1];
    const firstImage = first.querySelector("img");
    firstImage.setAttribute("src", "blob:sort-retained");
    firstImage.classList.add("loaded");
    first.classList.add("selected", "inspected");
    harness.evaluate(`selectedImages.add('${items[0].name}'); aiInspectedImageName = '${items[0].name}'`);
    const scheduleCount = harness.scheduleCalls.length;
    const cancelCount = harness.cancelCalls;
    harness.document.content.scrollTop = 500;
    harness.setContext({ sort: "name", order: "asc" });
    harness.setImages([items[1], items[0], ...items.slice(2)]);
    harness.updateGrid();
    assert(harness.document.grid.children.length === 120, "sort context change should return to the initial prefix");
    assert(harness.document.content.scrollTop === 0, "sort context change should reset grid scroll to top");
    assert(harness.document.grid.children[0] === second && harness.document.grid.children[1] === first, "sort context reconciliation should reuse matching element objects in new order");
    assert(firstImage.getAttribute("src") === "blob:sort-retained" && firstImage.classList.contains("loaded"), "sort context reconciliation should preserve same-key src and loaded state");
    assert(first.classList.contains("selected") && first.classList.contains("inspected"), "sort context reconciliation should preserve selected and inspected state");
    assert(harness.scheduleCalls.length === scheduleCount, "sort context reconciliation should not duplicate same-key schedules");
    assert(harness.cancelCalls === cancelCount, "sort context reset should not globally cancel scheduler work");
    assert(harness.isScheduled(first), "pending same-key element should remain scheduled through context reset");
    assert(harness.evaluate("getProgressiveGridState().context").includes("name"), "observability state should expose the active sort context");
}

function testFavoritesContextReusesRetainedPrefix() {
    const harness = createHarness();
    harness.initialize();
    const items = makeImages(300).map((item, index) => ({ ...item, favorite: index % 2 === 0 }));
    harness.setImages(items);
    harness.updateGrid();
    growOneChunk(harness);
    const retained = harness.document.grid.children[0];
    const leavingCount = 120;
    const unscheduledBefore = harness.unscheduleCalls.length;
    const cancelCount = harness.cancelCalls;
    harness.document.content.scrollTop = 500;

    harness.setContext({ favorites: true });
    harness.updateGrid();

    assert(harness.document.grid.children.length === 120, "favorites context should render its bounded matching prefix");
    assert(harness.document.grid.children[0] === retained, "favorites context should reuse retained matching elements");
    assert(harness.unscheduleCalls.length - unscheduledBefore === leavingCount, "favorites context should unschedule each leaving-prefix element once");
    assert(harness.cancelCalls === cancelCount, "favorites context should not globally cancel scheduler work");
    assert(harness.document.content.scrollTop === 0, "favorites context should reset scroll to top");

    harness.setContext({ favorites: false });
    harness.updateGrid();
    assert(harness.document.grid.children[0] === retained, "disabling favorites should continue reusing retained elements");
    assert(harness.document.grid.children.length === 120, "disabling favorites should create only missing initial-prefix elements");
}

function testPlaceholderAndEmptyStatesResetProgressiveState() {
    const harness = createHarness();
    harness.initialize();
    harness.setImages(makeImages(400));
    harness.updateGrid();
    growOneChunk(harness);
    assert(harness.evaluate("getProgressiveGridState().renderLimit") === 240, "setup should grow before placeholder reset");

    harness.setCounts({ "batch-a": { inbox: 400 } });
    const cancelBeforePlaceholder = harness.cancelCalls;
    harness.context.showGridLoadingPlaceholders("batch-a", "inbox");
    assert(harness.document.grid.children.length === 200, "placeholder count should remain capped at 200");
    assert(harness.evaluate("gridThumbMap.size") === 0, "placeholders should not enter gridThumbMap");
    assert(harness.evaluate("getProgressiveGridState().renderLimit") === 120, "placeholder state should reset the progressive limit");
    assert(harness.evaluate("currentDisplayImages.length") === 0, "placeholder state should clear the canonical list until real data arrives");
    assert(harness.cancelCalls === cancelBeforePlaceholder + 1, "placeholder reset should globally cancel pending thumbnail work");

    harness.document.resetGridMutationCounters();
    harness.setImages(makeImages(400, "real"));
    harness.updateGrid();
    assert(harness.document.grid.children.length === 120, "real data after placeholders should render the initial prefix");
    assert(harness.document.grid.querySelectorAll(".loading-placeholder").length === 0, "real data should remove every placeholder");
    assert(harness.document.minimumGridChildren > 0, "placeholder replacement should not expose an empty grid");

    const cancelBeforeEmpty = harness.cancelCalls;
    harness.setImages([]);
    harness.updateGrid();
    assert(harness.evaluate("gridThumbMap.size") === 0, "empty state should clear the rendered-thumb map");
    assert(harness.evaluate("getProgressiveGridState().renderLimit") === 120, "empty state should reset the progressive limit");
    assert(harness.evaluate("getProgressiveGridState().context") === null, "empty state should clear progressive context");
    assert(harness.cancelCalls > cancelBeforeEmpty, "empty state should globally cancel pending thumbnail work");
}

function testSelectionLightboxAndResizeUseFullCanonicalList() {
    const harness = createHarness();
    harness.initialize();
    const items = makeImages(300);
    harness.setImages(items);
    harness.updateGrid();
    harness.evaluate(`selectedImages.add('${items[200].name}')`);
    growOneChunk(harness);
    const appended = harness.evaluate(`gridThumbMap.get('${items[200].name}')`);
    assert(appended.classList.contains("selected"), "an appended thumb should reflect selection made while it was unrendered");
    assert(harness.evaluate("getCurrentDisplayImages().length") === 300, "lightbox navigation source should retain the full canonical list");
    assert(harness.document.grid.children.length === 240, "lightbox access should not force additional DOM creation");

    const first = harness.document.grid.children[0];
    harness.document.content.scrollTop = 0;
    harness.context.setGridDensity("large");
    harness.dispatchWindow("resize");
    harness.flushRaf(2);
    assert(harness.evaluate("getProgressiveGridState().renderLimit") === 240, "density/resize rechecks should preserve the render limit");
    assert(harness.document.grid.children[0] === first, "density/resize rechecks should preserve thumb identity");
    assert(harness.document.grid.children.length === 240, "far resize recheck should not append or rebuild thumbs");
}

function testAiFilterChangesOnlyRenderedCssState() {
    const harness = createHarness();
    harness.initialize();
    const items = makeImages(400);
    harness.setImages(items);
    harness.updateGrid();
    growOneChunk(harness);
    const retained = harness.document.grid.children[1];
    const image = retained.querySelector("img");
    image.setAttribute("src", "blob:ai-filter-retained");
    image.classList.add("loaded");
    retained.classList.add("selected", "inspected");
    harness.evaluate(`selectedImages.add('${items[1].name}'); aiInspectedImageName = '${items[1].name}'`);
    const scheduleCount = harness.scheduleCalls.length;
    const cancelCount = harness.cancelCalls;
    harness.document.content.scrollTop = 500;

    harness.setContext({ aiOverlays: true, aiFilter: "failed" });
    harness.updateGrid();

    assert(harness.evaluate("getProgressiveGridState().renderLimit") === 240, "AI filter change should preserve the progressive limit");
    assert(harness.document.content.scrollTop === 500, "AI filter change should preserve scrollTop");
    assert(harness.document.grid.children[1] === retained, "AI filter change should preserve element identity");
    assert(image.getAttribute("src") === "blob:ai-filter-retained" && image.classList.contains("loaded"), "AI filter change should preserve src and loaded state");
    assert(retained.classList.contains("selected") && retained.classList.contains("inspected"), "AI filter change should preserve selected and inspected state");
    assert(harness.scheduleCalls.length === scheduleCount, "AI filter change should not schedule same-key thumbs again");
    assert(harness.cancelCalls === cancelCount, "AI filter change should not globally cancel thumbnail work");
    assert(retained.classList.contains("ai-filtered-out"), "AI filter change should update only the rendered CSS filter state");
}

function testReusedThumbUnschedulesBeforeSourceKeyChange() {
    const harness = createHarness();
    const items = makeImages(100);
    harness.setImages(items);
    harness.updateGrid();
    const retained = harness.document.grid.children[0];
    const image = retained.querySelector("img");
    image.setAttribute("src", "blob:old-visible-source");
    image.classList.add("loaded");
    const oldKey = harness.scheduledKey(retained);
    const retainedScheduleBefore = harness.scheduleCalls.filter((entry) => entry.element === retained).length;
    const retainedUnscheduleBefore = harness.unscheduleCalls.filter((element) => element === retained).length;
    const logBefore = harness.schedulerLog.length;

    harness.setContext({ batch: "batch-b" });
    harness.updateGrid();

    const replacementEvents = harness.schedulerLog.slice(logBefore).filter((entry) => entry.element === retained);
    assert(harness.document.grid.children[0] === retained, "source context change should reuse the same-name thumb element");
    assert(harness.unscheduleCalls.filter((element) => element === retained).length === retainedUnscheduleBefore + 1, "source cache-key change should unschedule stale work exactly once per reused thumb");
    assert(harness.scheduleCalls.filter((entry) => entry.element === retained).length === retainedScheduleBefore + 1, "source cache-key change should schedule exactly one replacement per reused thumb");
    assert(replacementEvents.length === 2 && replacementEvents[0].type === "unschedule" && replacementEvents[1].type === "schedule", "source cache-key change should unschedule before scheduling replacement work");
    assert(harness.scheduledKey(retained) !== oldKey, "replacement scheduler state should retain only the new cache key");
    assert(image.getAttribute("src") === "blob:old-visible-source", "source change should preserve the displayed src until replacement resolves");
    assert(!image.classList.contains("loaded"), "genuinely different source may restart loaded-state presentation");
}

try {
    testBoundedInitialPrefix();
    testSmallListRendersAll();
    testFarAndNearScrollGrowth();
    testProgrammaticBottomDispatchEventuallyRendersAll();
    testUnchangedPollingPreservesLiveThumbState();
    testSameContextPrefixReconcilesWithoutEmptyFlash();
    testContextResetAndSameContextLimitPreservation();
    testFavoritesContextReusesRetainedPrefix();
    testPlaceholderAndEmptyStatesResetProgressiveState();
    testSelectionLightboxAndResizeUseFullCanonicalList();
    testAiFilterChangesOnlyRenderedCssState();
    testReusedThumbUnschedulesBeforeSourceKeyChange();
    process.stdout.write(`progressive grid lifecycle: ${assertionCount} assertions passed\n`);
} catch (error) {
    process.stderr.write(`${error.stack}\n`);
    process.exitCode = 1;
}
