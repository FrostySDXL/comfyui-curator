#!/usr/bin/env node
/* Regression harness for AI job cancellation wiring.
 *
 * Reproduces the native ComfyUI smoke-test failure where clicking the AI
 * sidebar Cancel button produced HTTP 404 "job not found": the click listener
 * handed the DOM event to aiCancelJob() as its jobId argument, so the request
 * path contained "[object PointerEvent]" instead of the active run id.
 *
 * Covers three things against the real ordered frontend sources:
 *   1. the sidebar Cancel button binding in events.js,
 *   2. Activity Center cancellation, which must keep using its explicit run id,
 *   3. aiCancelJob() ignoring a leaked DOM event argument.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..");
const KNOWN_JOB_IDS = new Set(["run-sidebar", "run-explicit", "run-current"]);

class FakeClassList {
    constructor() { this.values = new Set(); }
    add(...values) { values.forEach(value => this.values.add(value)); }
    remove(...values) { values.forEach(value => this.values.delete(value)); }
    contains(value) { return this.values.has(value); }
    toggle(value, force) {
        const next = force === undefined ? !this.values.has(value) : Boolean(force);
        if (next) this.values.add(value);
        else this.values.delete(value);
        return next;
    }
}

class FakeElement {
    constructor(tagName) {
        this.tagName = String(tagName || "div");
        this.children = [];
        this.dataset = {};
        this.attributes = {};
        this.classList = new FakeClassList();
        this.listeners = {};
        this.style = {};
        this.hidden = false;
        this.disabled = false;
        this.value = "";
        this.checked = false;
        this.className = "";
        this._text = "";
    }
    append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
    appendChild(node) { this.children.push(node); return node; }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    get firstElementChild() { return this.children[0] || null; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    addEventListener(type, handler) {
        if (!this.listeners[type]) this.listeners[type] = [];
        this.listeners[type].push(handler);
    }
    removeEventListener(type, handler) {
        this.listeners[type] = (this.listeners[type] || []).filter(item => item !== handler);
    }
    dispatch(type, event) {
        const payload = event || {type, target: this, currentTarget: this};
        (this.listeners[type] || []).forEach(handler => handler.call(this, payload));
    }
    click() { this.dispatch("click"); }
    focus() { this.focused = true; }
    querySelector() { return null; }
    querySelectorAll() { return []; }
    closest() { return null; }
    set textContent(value) { this._text = String(value ?? ""); this.children = []; }
    get textContent() {
        return this._text + this.children.map(child => child.textContent || "").join("");
    }
    find(predicate) {
        for (const child of this.children) {
            if (predicate(child)) return child;
            const nested = child.find ? child.find(predicate) : null;
            if (nested) return nested;
        }
        return null;
    }
}

const elements = new Map([
    ["ai-submit-btn", new FakeElement("button")],
    ["ai-cancel-btn", new FakeElement("button")],
    ["ai-job-section", new FakeElement("section")],
    ["ai-job-state", new FakeElement("span")],
    ["ai-job-progress", new FakeElement("p")],
    ["ai-status-dot", new FakeElement("span")],
    ["activity-center-list", new FakeElement("div")],
    ["activity-center-summary", new FakeElement("div")],
    ["activity-center-badge", new FakeElement("span")],
    ["activity-center-panel", new FakeElement("section")],
    ["activity-center-toggle", new FakeElement("button")],
    ["activity-center-close", new FakeElement("button")],
]);
const aiJobStatusRegion = new FakeElement("div");
const documentListeners = {};

const document = {
    readyState: "complete",
    activeElement: elements.get("activity-center-toggle"),
    getElementById(id) { return elements.get(id) || null; },
    querySelector(selector) {
        return selector === "#ai-job-section .ai-job-status" ? aiJobStatusRegion : null;
    },
    querySelectorAll() { return []; },
    addEventListener(type, handler) {
        if (!documentListeners[type]) documentListeners[type] = [];
        documentListeners[type].push(handler);
    },
    createElement(tagName) { return new FakeElement(tagName); },
};

const fetches = [];
const toasts = [];
const sandbox = {
    console,
    Date,
    Map,
    Set,
    Number,
    String,
    Promise,
    JSON,
    Object,
    Array,
    Boolean,
    Math,
    parseInt,
    parseFloat,
    isNaN,
    document,
    window: {addEventListener() {}, removeEventListener() {}},
    localStorage: {getItem() { return null; }, setItem() {}, removeItem() {}},
    showToast(message) { toasts.push(String(message)); },
    aiSetPanelTab() {},
    fetch(url) {
        fetches.push(String(url));
        const match = String(url).match(/\/jobs\/([^/]+)\/cancel$/);
        if (match && KNOWN_JOB_IDS.has(decodeURIComponent(match[1]))) {
            return Promise.resolve({ok: true, json: async () => ({success: true})});
        }
        return Promise.resolve({ok: false, json: async () => ({error: "job not found"})});
    },
};
/* Any other global referenced while binding unrelated UI is inert; only the AI
   cancel path is asserted here. */
const sandboxProxy = new Proxy(sandbox, {
    has: () => true,
    get(target, property) {
        if (property in target) return target[property];
        return function inertGlobalStub() { return undefined; };
    },
});

const context = vm.createContext(sandboxProxy);
function run(filename) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, filename), "utf8"), context, {filename});
}

function settle() {
    return new Promise(resolve => setImmediate(resolve));
}

function lastCancelUrl() {
    const cancelUrls = fetches.filter(url => url.endsWith("/cancel"));
    return cancelUrls.at(-1) || "";
}

(async () => {
    run("static/js/state.js");
    run("static/js/ai-state.js");
    run("static/js/ai-job.js");
    run("static/js/activity-center.js");
    run("static/js/events.js");
    vm.runInContext("_bindDelegatedEvents()", context);

    /* 1. Sidebar Cancel button: the real events.js listener must cancel the
       active job id, not stringify the click event into the request path. */
    vm.runInContext("aiCurrentJobId = 'run-sidebar'", context);
    elements.get("ai-cancel-btn").dispatch("click", {type: "click", target: elements.get("ai-cancel-btn")});
    await settle();
    assert.equal(
        lastCancelUrl(),
        "/api/curator/ai-curate/jobs/run-sidebar/cancel",
        "sidebar Cancel must target the active run id",
    );
    assert.deepEqual(toasts, ["Cancellation requested"], "sidebar Cancel must not surface a backend error");

    /* 2. Activity Center Cancel keeps cancelling the job it owns even while a
       different job is the current one. */
    fetches.length = 0;
    toasts.length = 0;
    vm.runInContext("aiCurrentJobId = 'run-current'", context);
    vm.runInContext(
        "aiShowJobStatus({run_id: 'run-explicit', status: 'running', batch: 'batch-a', totals: {images: 4, scored: 1, failed: 0}})",
        context,
    );
    const activityList = elements.get("activity-center-list");
    const activityItem = activityList.find(node => node.dataset && node.dataset.activityId === "ai:run-explicit");
    assert.ok(activityItem, "running AI job renders an Activity Center item");
    const activityCancel = activityItem.find(
        node => typeof node.className === "string" && node.className.includes("activity-cancel"),
    );
    assert.ok(activityCancel, "running AI job exposes an Activity Center Cancel action");
    activityCancel.click();
    await settle();
    assert.equal(
        lastCancelUrl(),
        "/api/curator/ai-curate/jobs/run-explicit/cancel",
        "Activity Center Cancel must use its explicit run id",
    );
    assert.deepEqual(toasts, ["Cancellation requested"], "Activity Center Cancel must not surface a backend error");

    /* 3. Even if a future listener again forwards a DOM event, cancellation
       must fall back to the active run id instead of a stringified event. */
    fetches.length = 0;
    toasts.length = 0;
    vm.runInContext("aiCancelJob({type: 'click', target: null})", context);
    await settle();
    assert.equal(
        lastCancelUrl(),
        "/api/curator/ai-curate/jobs/run-current/cancel",
        "a leaked event argument must not become a job id",
    );
    assert.deepEqual(toasts, ["Cancellation requested"], "a leaked event argument must not surface a backend error");

    process.stdout.write("AI cancel binding checks passed\n");
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
