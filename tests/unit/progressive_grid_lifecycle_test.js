#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const gridSource = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "js", "grid.js"),
    "utf8",
);
const activitySource = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "js", "activity-center.js"),
    "utf8",
);
const viewportSource = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "js", "viewport-loader.js"),
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
        if (this.tagName === "VIDEO") {
            this.pause = () => { this.paused = true; };
            this.play = () => { this.paused = false; return Promise.resolve(); };
            this.load = () => {};
            this.paused = true;
        }
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

    removeChild(node) {
        this._detach(node);
        return node;
    }

    get firstElementChild() {
        return this.children.length > 0 ? this.children[0] : null;
    }

    get lastElementChild() {
        return this.children.length > 0 ? this.children[this.children.length - 1] : null;
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

    closest(selector) {
        let node = this;
        while (node) {
            if (selectorMatches(node, selector)) return node;
            node = node.parentNode;
        }
        return null;
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

    removeAttribute(name) {
        this.attributes.delete(name);
        if (name === "src") this.src = "";
    }
}

class MockDocument {
    constructor() {
        this.readyState = "loading";
        this.addEventListener = () => {};
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
        this.content.clientTop = 0;
        this.body.appendChild(this.content);
        this.shell = this.register("grid-shell", new MockElement("div", this));
        this.grid = this.register("grid", new MockElement("div", this));
        this.content.appendChild(this.shell);
        this.shell.appendChild(this.grid);
        this.content.getBoundingClientRect = () => ({top: 0});
        this.shell.getBoundingClientRect = () => ({top: -this.content.scrollTop});
        this.register("img-count", new MockElement("span", this));
        this.register("grid-status", new MockElement("div", this));
        this.register("sort-dir-btn", new MockElement("button", this));
        this.register("lightbox", new MockElement("div", this));
        this.register("activity-center-list", new MockElement("div", this));
        this.register("activity-center-summary", new MockElement("div", this));
        this.register("activity-center-badge", new MockElement("span", this));
        this.register("activity-center-panel", new MockElement("section", this));
        this.register("activity-center-toggle", new MockElement("button", this));
        this.register("activity-center-close", new MockElement("button", this));
        this.elements.get("activity-center-list").appendChild(new MockElement("div", this));
        let contentScrollTop = 0;
        Object.defineProperty(this.content, "scrollTop", {
            get: () => contentScrollTop,
            set: (value) => {
                contentScrollTop = Math.max(
                    0,
                    Math.min(value, this.content.scrollHeight - this.content.clientHeight),
                );
            },
        });
        Object.defineProperty(this.content, "scrollHeight", {
            get: () => {
                const shellHeight = parseFloat(this.shell.style.height) || 0;
                return Math.max(this.content.clientHeight, shellHeight);
            },
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

function createHarness(options = {}) {
    const loadViewportLoader = options.loadViewportLoader === true;
    const document = new MockDocument();
    let nextRafId = 1;
    const rafQueue = new Map();
    let nextTimerId = 1;
    const timerQueue = new Map();
    const scheduleCalls = [];
    const unscheduleCalls = [];
    const scheduledElements = new Map();
    const schedulerLog = [];
    let cancelCalls = 0;
    const windowListeners = new Map();

    let context;
    const contextBase = {
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
        setTimeout(callback) {
            const id = nextTimerId++;
            timerQueue.set(id, callback);
            return id;
        },
        clearTimeout(id) {
            timerQueue.delete(id);
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
        ccApiPath: (path) => path,
        ccThumbUrl: (batch, folder, name) => `/thumb/${batch}/${folder}/${name}`,
        ccPreviewUrl: (batch, folder, name) => `/preview/${batch}/${folder}/${name}`,
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
        VIEWPORT_PRIORITY_VISIBLE: 0,
        VIEWPORT_PRIORITY_NEAR: 1,
        VIEWPORT_PRIORITY_DEFERRED: 2,
    };
    if (!loadViewportLoader) {
        contextBase.scheduleThumbnailLoad = function (element, imageSrc, cacheKey) {
            scheduleCalls.push({ element, imageSrc, cacheKey });
            scheduledElements.set(element, cacheKey);
            schedulerLog.push({ type: "schedule", element, cacheKey });
        };
        contextBase.unscheduleThumbnailLoad = function (element) {
            unscheduleCalls.push(element);
            scheduledElements.delete(element);
            schedulerLog.push({ type: "unschedule", element });
        };
        contextBase.cancelScheduledViewportLoads = function () {
            cancelCalls += 1;
            scheduledElements.clear();
        };
    }
    context = vm.createContext(contextBase);
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
        let serverSelection = null;
        let gridThumbMap = new Map();
        let displayIndexByName = new Map();
        let displayIndexByKey = new Map();
        let folderPageInflight = new Map();
        let pagedFolderMode = false;
        let folderSnapshot = null;
        let hoverPreviewsEnabled = true;
        let activeHoverPreview = null;
        let hoverPreviewTimer = null;
        let gridDensity = 'comfortable';
        let allCounts = {};
        let folderRequestToken = 0;
        const CURATOR_NATIVE = false;
        function getImageIdentityKey(img, sourceOverride = null) {
            if (!img || !img.name) return '';
            const source = sourceOverride || {batch: currentBatch, folder: currentFolder};
            return String(source.batch || '') + '\\u001f' + String(source.folder || '') + '\\u001f' + img.name;
        }
        const GRID_DENSITY_KEY = 'imageCurator.gridDensity';
        const MAX_GRID_LOADING_PLACEHOLDERS = 200;
        const THUMBNAIL_BLOB_CACHE_MAX = 1000;
        const thumbnailBlobUrlCache = new Map();
        const thumbnailBlobInflight = new Map();
    `, context);
    vm.runInContext(activitySource, context);
    vm.runInContext(gridSource, context);
    if (loadViewportLoader) {
        vm.runInContext(viewportSource, context);
    }

    return {
        context,
        document,
        scheduleCalls,
        unscheduleCalls,
        schedulerLog,
        get cancelCalls() { return cancelCalls; },
        setImages(items) { context.__items = items; vm.runInContext("images = __items", context); },
        setCounts(counts) { context.__counts = counts; vm.runInContext("allCounts = __counts", context); },
        setFetch(fn) { context.fetch = fn; },
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
        pendingTimerCount() { return timerQueue.size; },
        flushTimers() {
            const callbacks = [...timerQueue.values()];
            timerQueue.clear();
            callbacks.forEach((callback) => callback());
        },
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
    harness.dispatchWindow("resize");
    assert(harness.pendingTimerCount() === 1, "repeated resize notifications should share one settled growth recheck");
    assert(harness.pendingRafCount() === 1, "density work should remain the only immediate progressive growth frame");
    harness.flushTimers();
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
    assert(image.classList.contains("loaded"), "source change should keep the displayed thumbnail visible until replacement resolves");
}

function testPlaceholdersDoNotResurrectPreviousFolderActivity() {
            const harness = createHarness();
    const group = "folder-view:batch-a:inbox";
    harness.setCounts({"batch-a": {inbox: 4}});
    for (const [index, status] of ["running", "completed", "failed", "partial", "cancelled"].entries()) {
        const id = `old-attempt-${index}`;
        harness.evaluate(`activityRegister({id: "${id}", group: "${group}", status: "${status}", detail: "original detail"});`);
        harness.context.showGridLoadingPlaceholders("batch-a", "inbox");
        assert(harness.evaluate(`activityRecords.get('${id}').status`) === status, `placeholders must preserve ${status} folder activity state`);
        assert(harness.evaluate(`activityRecords.get('${id}').detail`) === "original detail", `placeholders must preserve ${status} activity detail`);
    }
}

function testThirtyThousandTraversalKeepsBoundedLiveWindow() {
    const harness = createHarness();
    harness.document.content.clientHeight = 900;
    harness.initialize();
    harness.setImages(makeImages(30000));
    harness.updateGrid();
    harness.updateGrid();
    assert(harness.evaluate("currentDisplayImages.length") === 30000, "canonical list should retain all 30,000 indices");
    assert(harness.document.grid.children.length <= 500, "initial live thumbnail window must stay at or below 500");
    const firstName = harness.document.grid.children[0].dataset.name;

    for (const fraction of [0.25, 0.5, 0.75, 1]) {
        harness.document.content.scrollTop = Math.floor(30000 * 192 * fraction);
        harness.document.content.dispatchEvent({type: "scroll"});
        harness.flushTimers();
        assert(harness.document.grid.children.length <= 500, `live window remains bounded at ${fraction}`);
        assert(harness.evaluate("gridThumbMap.size") <= 500, `thumb map remains bounded at ${fraction}`);
    }
    assert(harness.document.grid.children[0].dataset.name !== firstName, "far traversal recycles away the initial row");
}

function testContinuousScrollReconcilesWindowBeforeIdle() {
    const harness = createHarness();
    harness.document.content.clientHeight = 900;
    harness.initialize();
    harness.setImages(makeImages(30000));
    harness.updateGrid();
    harness.flushRaf(2);
    const firstName = harness.document.grid.children[0].dataset.name;

    harness.document.content.scrollTop = Math.floor(30000 * 192 * 0.5);
    harness.document.content.dispatchEvent({type: "scroll"});

    assert(harness.pendingRafCount() === 1, "active scrolling schedules one guarded row-window reconciliation");
    harness.flushRaf(1);
    assert(harness.document.grid.children[0].dataset.name !== firstName, "row identity follows the viewport before scroll idle");
    assert(harness.pendingTimerCount() === 1, "scroll idle work remains scheduled separately from row reconciliation");
}

function testUnchangedWindowPreservesDecodedThumbIdentity() {
    const harness = createHarness();
    harness.setImages(makeImages(30000));
    harness.updateGrid();
    harness.updateGrid();
    const first = harness.document.grid.children[0];
    const image = first.querySelector("img");
    image.setAttribute("src", "blob:decoded");
    image.classList.add("loaded");
    harness.document.resetGridMutationCounters();
    harness.updateGrid();
    assert(harness.document.grid.children[0] === first, "unchanged window preserves thumb identity");
    assert(image.getAttribute("src") === "blob:decoded", "unchanged window preserves decoded source");
    assert(harness.document.gridReplaceCount === 0, "unchanged window performs no grid replacement");
}

function testHoverPreviewAllowsOnlyOneActiveDecoder() {
    const harness = createHarness();
    const items = makeImages(2).map(item => ({...item, media_kind: "video"}));
    harness.setImages(items);
    harness.updateGrid();
    harness.updateGrid();
    const first = harness.document.grid.children[0];
    const second = harness.document.grid.children[1];
    first.dispatchEvent({type: "pointerenter"});
    harness.flushTimers();
    assert(first.classList.contains("preview-active"), "first hover activates after delay");
    second.dispatchEvent({type: "pointerenter"});
    harness.flushTimers();
    assert(!first.classList.contains("preview-active"), "second hover releases first decoder");
    assert(second.classList.contains("preview-active"), "second hover becomes active");
    assert(harness.document.grid.querySelectorAll(".preview-active").length === 1, "only one preview is active");
}

function testDensitySwitchRestoresSameAnchorItem() {
    const harness = createHarness();
    harness.initialize();
    harness.setImages(makeImages(2000));
    harness.updateGrid();

    harness.context.setGridDensity("compact");
    const compactColumns = harness.evaluate(
        "Number(document.getElementById('grid').style.getPropertyValue('--grid-columns'))",
    );
    assert(compactColumns === 8, `compact columns should be 8, got ${compactColumns}`);

    const compactTrack = 138;
    const compactGap = 7;
    const row = 37;
    harness.document.content.scrollTop = row * (compactTrack + compactGap);
    const anchorIndex = harness.evaluate("_captureGridAnchor(null, 'compact')");
    assert(
        anchorIndex === row * compactColumns,
        `compact anchor index should be ${row * compactColumns}, got ${anchorIndex}`,
    );

    harness.context.setGridDensity("large");
    const largeColumns = harness.evaluate(
        "Number(document.getElementById('grid').style.getPropertyValue('--grid-columns'))",
    );
    const largeTrack = 250;
    const largeGap = 16;
    assert(largeColumns === 4, `large columns should be 4, got ${largeColumns}`);
    const expectedScrollTop = Math.floor(anchorIndex / largeColumns) * (largeTrack + largeGap);
    assert(
        harness.document.content.scrollTop === expectedScrollTop,
        `density switch should restore scrollTop to ${expectedScrollTop}, got ${harness.document.content.scrollTop}`,
    );
}

function testDensitySwitchPreservesAnchorAgainstStaleShellHeight() {
    const harness = createHarness();
    harness.initialize();
    harness.setImages(makeImages(2000));
    harness.updateGrid();

    harness.context.setGridDensity("compact");
    harness.flushRaf(2);
    const compactColumns = harness.evaluate(
        "Number(document.getElementById('grid').style.getPropertyValue('--grid-columns'))",
    );
    assert(compactColumns === 8, `compact columns should be 8, got ${compactColumns}`);
    const compactTrack = 138;
    const compactGap = 7;

    const row = 120;
    harness.document.content.scrollTop = row * (compactTrack + compactGap);
    const anchorIndex = harness.evaluate("_captureGridAnchor(null, 'compact')");
    assert(
        anchorIndex === row * compactColumns,
        `compact anchor index should be ${row * compactColumns}, got ${anchorIndex}`,
    );

    harness.context.setGridDensity("large");
    const largeColumns = harness.evaluate(
        "Number(document.getElementById('grid').style.getPropertyValue('--grid-columns'))",
    );
    const largeTrack = 250;
    const largeGap = 16;
    assert(largeColumns === 4, `large columns should be 4, got ${largeColumns}`);
    const expectedScrollTop = Math.floor(anchorIndex / largeColumns) * (largeTrack + largeGap);
    assert(
        harness.document.content.scrollTop === expectedScrollTop,
        `density switch should restore scrollTop to ${expectedScrollTop}, got ${harness.document.content.scrollTop}`,
    );
}

function testAnchorUsesScrollerCoordinatesBelowToolbar() {
    const harness = createHarness();
    harness.document.content.clientWidth = 450;
    harness.document.content.clientHeight = 584;
    harness.document.content.getBoundingClientRect = () => ({top: 136});
    harness.document.shell.offsetTop = 150;
    harness.document.shell.getBoundingClientRect = () => ({
        top: 150 - harness.document.content.scrollTop,
    });
    harness.setImages(makeImages(600));
    harness.updateGrid();
    harness.context.setGridDensity("compact");
    harness.flushRaf(2);
    harness.document.content.scrollTop = 14330;
    assert(harness.evaluate("getGridScrollOrigin(document.getElementById('grid'))") === 14,
        "grid origin must be relative to its scroller, not the toolbar/viewport");
    assert(harness.evaluate("_captureGridAnchor()") === 294,
        "a toolbar offset must not move the anchor to the preceding row");
    harness.context.setGridDensity("large");
    assert(harness.document.content.scrollTop === 14 + 294 * 266,
        "restore must place item 294 at the scroller top");
}

function testNarrowerSidebarLayoutPresizesBeforeRestoringAnchor() {
    const harness = createHarness();
    harness.setImages(makeImages(2000));
    harness.updateGrid();
    harness.context.setGridDensity("compact");
    harness.flushRaf(2);
    harness.document.content.scrollTop = 120 * 145;
    assert(harness.evaluate("_captureGridAnchor()") === 960, "start at compact row 120");
    harness.document.content.clientWidth = 450;
    harness.context.updateGridShellLayout();
    assert(harness.document.content.scrollTop === 320 * 145,
        "sidebar narrowing must expand the spacer before restoring the same item");
}

function testDensitySwitchReversePreservesAnchorRow() {
    const harness = createHarness();
    harness.initialize();
    harness.setImages(makeImages(2000));
    harness.updateGrid();

    harness.context.setGridDensity("large");
    harness.flushRaf(2);
    const largeColumns = harness.evaluate(
        "Number(document.getElementById('grid').style.getPropertyValue('--grid-columns'))",
    );
    assert(largeColumns === 4, `large columns should be 4, got ${largeColumns}`);
    const largeTrack = 250;
    const largeGap = 16;

    const row = 80;
    harness.document.content.scrollTop = row * (largeTrack + largeGap);
    const anchorIndex = harness.evaluate("_captureGridAnchor(null, 'large')");
    assert(
        anchorIndex === row * largeColumns,
        `large anchor index should be ${row * largeColumns}, got ${anchorIndex}`,
    );

    harness.context.setGridDensity("compact");
    const compactColumns = harness.evaluate(
        "Number(document.getElementById('grid').style.getPropertyValue('--grid-columns'))",
    );
    const compactTrack = 138;
    const compactGap = 7;
    assert(compactColumns === 8, `compact columns should be 8, got ${compactColumns}`);
    const expectedScrollTop = Math.floor(anchorIndex / compactColumns) * (compactTrack + compactGap);
    assert(
        harness.document.content.scrollTop === expectedScrollTop,
        `reverse density switch should preserve the anchor row at scrollTop ${expectedScrollTop}, got ${harness.document.content.scrollTop}`,
    );
}

function testPagedLoadStatusTracksMaterialization() {
    const harness = createHarness();
    harness.evaluate(`
        pagedFolderMode = true;
        folderSnapshot = {count: 3};
        displayIndexByName = new Map([['a.png', 0], ['b.png', 1]]);
    `);
    harness.evaluate("updatePagedLoadStatus()");
    const status = harness.document.getElementById("grid-status");
    assert(status.textContent === "Loaded 2 of 3", `expected 'Loaded 2 of 3', got '${status.textContent}'`);
    assert(status.hidden === false, "status should remain visible while materializing");

    harness.evaluate("displayIndexByName.set('c.png', 2)");
    harness.evaluate("updatePagedLoadStatus()");
    assert(status.hidden === true, "status should hide once fully materialized");
    assert(status.textContent === "", "status should clear once complete");
}

async function testFolderLoadFailureShowsErrorAndRetryRecovers() {
    const harness = createHarness();
    harness.setContext({ batch: "batch-a", folder: "shortlisted" });
    harness.setCounts({ "batch-a": { shortlisted: 0 } });

    harness.setFetch(() => Promise.reject(new Error("network down")));
    await harness.evaluate("loadCurrentFolderImages()");

    const failed = harness.evaluate("activityGetLatest('folder-view:batch-a:shortlisted')");
    assert(failed.status === "failed", `activity should be failed, got ${failed.status}`);
    assert(failed.error === "Folder image load failed", `unexpected error copy: ${failed.error}`);
    assert(failed.detail === "Try opening the folder again", "unexpected detail copy");
    assert(harness.document.grid.getAttribute("aria-busy") === "false", "busy state should be cleared after failure");
    const retryButton = harness.document.grid.querySelector(".grid-retry");
    assert(!!retryButton, "Retry control should be rendered on folder-load failure");
    assert(retryButton.textContent === "Retry", "Retry control should use the Retry label");

    harness.setFetch(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve([
            { name: "a.png", size: 1 },
            { name: "b.png", size: 2 },
        ]),
    }));
    retryButton.dispatchEvent({ type: "click" });
    await new Promise((resolve) => setTimeout(resolve, 10));

    const recovered = harness.evaluate("activityGetLatest('folder-view:batch-a:shortlisted')");
    assert(recovered.status === "completed", `activity should complete after retry, got ${recovered.status}`);
    assert(harness.evaluate("images.length") === 2, "retry should recover the grid with the fetched images");
    assert(harness.document.grid.getAttribute("aria-busy") === "false", "busy state should clear after recovery");
    assert(!harness.document.grid.querySelector(".grid-retry"), "error state should be replaced after recovery");
}

async function testThumbnailFailuresAggregateAndRecover() {
    const harness = createHarness();
    harness.setContext({ batch: "batch-a", folder: "shortlisted" });
    const items = makeImages(3, "img");
    harness.setFetch(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve(items),
    }));
    await harness.evaluate("loadCurrentFolderImages()");

    const group = "folder-view:batch-a:shortlisted";
    const latest = () => harness.evaluate(`activityGetLatest('${group}')`);

    let record = latest();
    assert(record.status === "completed", `folder load should complete, got ${record.status}`);
    assert(record.completed === 3 && record.total === 3, "completed activity should read 3 of 3");
    assert(record.detail === "Folder ready · thumbnails loaded on demand", `unexpected detail: ${record.detail}`);

    const thumbs = harness.document.grid.children;
    assert(thumbs.length === 3, `expected 3 rendered thumbs, got ${thumbs.length}`);

    thumbs[0].querySelector("img").dispatchEvent({ type: "error" });
    record = latest();
    assert(record.status === "partial", `first thumbnail failure should move to partial, got ${record.status}`);
    assert(record.completed === 2 && record.total === 3, `partial should read 2 of 3, got ${record.completed} of ${record.total}`);
    assert(record.detail === "1 thumbnail failed · Retry available on the tiles", `unexpected detail: ${record.detail}`);

    thumbs[1].querySelector("img").dispatchEvent({ type: "error" });
    record = latest();
    assert(record.status === "partial", "second thumbnail failure should keep partial");
    assert(record.completed === 1 && record.total === 3, `partial should read 1 of 3, got ${record.completed} of ${record.total}`);
    assert(record.detail === "2 thumbnails failed · Retry available on the tiles", `unexpected detail: ${record.detail}`);

    harness.evaluate("retryThumbnailLoad(document.getElementById('grid').children[0])");
    thumbs[0].querySelector("img").dispatchEvent({ type: "load" });
    record = latest();
    assert(record.status === "partial", "one recovered tile should keep partial");
    assert(record.completed === 2 && record.total === 3, `partial should read 2 of 3, got ${record.completed} of ${record.total}`);
    assert(record.detail === "1 thumbnail failed · Retry available on the tiles", `unexpected detail: ${record.detail}`);

    harness.evaluate("retryThumbnailLoad(document.getElementById('grid').children[1])");
    thumbs[1].querySelector("img").dispatchEvent({ type: "load" });
    record = latest();
    assert(record.status === "completed", `full recovery should complete, got ${record.status}`);
    assert(record.completed === 3 && record.total === 3, `completed should read 3 of 3, got ${record.completed} of ${record.total}`);
    assert(record.detail === "Folder ready · thumbnails loaded on demand", `unexpected detail: ${record.detail}`);
}

function testLoaderNeverWritesLoadingDetailOntoTerminalRecord() {
    const harness = createHarness({ loadViewportLoader: true });
    harness.setContext({ batch: "batch-a", folder: "inbox" });
    harness.setImages(makeImages(1));
    harness.updateGrid();

    const group = "folder-view:batch-a:inbox";
    for (const status of ["completed", "partial", "failed", "cancelled"]) {
        harness.evaluate(
            `activityRegister({id: 'folder-view:batch-a:inbox:attempt', group: '${group}', kind: 'snapshot', title: 'Load folder view', scope: 'batch-a / inbox', status: '${status}', completed: 1, total: 1, detail: 'folder ready detail'})`,
        );
        harness.evaluate(
            "scheduleThumbnailLoad(document.getElementById('grid').children[0], '/thumb/x.png?v=1', 'key-visible', 0, null)",
        );
        const record = harness.evaluate(`activityGetLatest('${group}')`);
        assert(record.status === status, `loader must not change terminal status ${status}`);
        assert(record.detail === "folder ready detail", `loader must not mutate detail for terminal ${status}, got ${record.detail}`);
        harness.evaluate("activityRemove('folder-view:batch-a:inbox:attempt')");
    }
}

async function main() {
    testThirtyThousandTraversalKeepsBoundedLiveWindow();
    testContinuousScrollReconcilesWindowBeforeIdle();
    testUnchangedWindowPreservesDecodedThumbIdentity();
    testHoverPreviewAllowsOnlyOneActiveDecoder();
    testPlaceholdersDoNotResurrectPreviousFolderActivity();
    testDensitySwitchRestoresSameAnchorItem();
    testDensitySwitchPreservesAnchorAgainstStaleShellHeight();
    testDensitySwitchReversePreservesAnchorRow();
    testAnchorUsesScrollerCoordinatesBelowToolbar();
    testNarrowerSidebarLayoutPresizesBeforeRestoringAnchor();
    testPagedLoadStatusTracksMaterialization();
    await testFolderLoadFailureShowsErrorAndRetryRecovers();
    await testThumbnailFailuresAggregateAndRecover();
    testLoaderNeverWritesLoadingDetailOntoTerminalRecord();
    process.stdout.write(`virtual grid lifecycle: ${assertionCount} assertions passed\n`);
}

main().catch((error) => {
    process.stderr.write(`${error.stack}\n`);
    process.exitCode = 1;
});
