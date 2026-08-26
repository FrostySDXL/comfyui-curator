#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeClassList {
    constructor() { this.values = new Set(); }
    add(...values) { values.forEach(value => this.values.add(value)); }
    remove(...values) { values.forEach(value => this.values.delete(value)); }
    toggle(value, force) {
        const next = force === undefined ? !this.values.has(value) : force;
        if (next) this.values.add(value); else this.values.delete(value);
        return next;
    }
}

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.dataset = {};
        this.attributes = {};
        this.classList = new FakeClassList();
        this.listeners = {};
        this.hidden = false;
        this.disabled = false;
        this._text = "";
    }
    append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
    appendChild(node) { this.children.push(node); return node; }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    get firstElementChild() { return this.children[0]; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    focus() { this.focused = true; }
    click() { this.listeners.click?.({}); }
    set textContent(value) { this._text = String(value ?? ""); this.children = []; }
    get textContent() {
        return this._text + this.children.map(child => child.textContent || "").join("");
    }
    find(predicate) {
        for (const child of this.children) {
            if (predicate(child)) return child;
            const nested = child.find?.(predicate);
            if (nested) return nested;
        }
        return null;
    }
}

const elements = new Map([
    ["activity-center-list", new FakeElement("div")],
    ["activity-center-summary", new FakeElement("div")],
    ["activity-center-badge", new FakeElement("span")],
    ["activity-center-panel", new FakeElement("section")],
    ["activity-center-toggle", new FakeElement("button")],
    ["activity-center-close", new FakeElement("button")],
]);

const document = {
    readyState: "loading",
    activeElement: elements.get("activity-center-toggle"),
    getElementById(id) { return elements.get(id) || null; },
    createElement(tagName) { return new FakeElement(tagName); },
    addEventListener() {},
};

const source = fs.readFileSync(path.join(__dirname, "../../static/js/activity-center.js"), "utf8");
const context = vm.createContext({
    console,
    Date,
    Map,
    Set,
    Number,
    String,
    Promise,
    document,
});
vm.runInContext(source, context, {filename: "activity-center.js"});

const register = context.activityRegister;
const update = context.activityUpdate;
const complete = context.activityComplete;
const cancel = context.activityCancel;
const remove = context.activityRemove;
const get = context.activityGet;
const render = context.activityRender;
const renderRecord = context._activityRenderRecord;
const attemptId = context.activityAttemptId;

register({id: "normalize", status: "unknown"});
assert.equal(get("normalize").status, "queued", "unknown states normalize to queued");
update("normalize", {status: "running"});
assert.equal(get("normalize").status, "running");

register({
    id: "retryable-index",
    status: "failed",
    result: "0 created",
    error: "Media search index build failed",
    completedAt: Date.now(),
});
register({id: "retryable-index", status: "running", detail: "Building indexes…"});
assert.equal(get("retryable-index").error, "", "retry clears the previous error");
assert.equal(get("retryable-index").result, "", "retry clears the previous result");
complete("retryable-index", "completed", {result: "Built 1 media search index", detail: "Search indexes ready"});
const retryCard = renderRecord(get("retryable-index"));
assert.match(retryCard.textContent, /Built 1 media search index/);
assert.doesNotMatch(retryCard.textContent, /Media search index build failed/);

register({
    id: "partial-result",
    status: "partial",
    detail: "Some public copies need attention",
    result: "2 created",
    error: "1 failed",
});
const partialCard = renderRecord(get("partial-result"));
assert.match(partialCard.textContent, /2 created/);
assert.match(partialCard.textContent, /1 failed/);

register({id: "old-success", status: "completed"});
get("old-success").completedAt = Date.now() - (5 * 60 * 1000 + 1);
render();
assert.equal(get("old-success"), null, "completed success ages out");

register({
    id: "cancel-rejected",
    status: "running",
    cancel: () => Promise.reject(new Error("backend rejected cancellation")),
});
const cancelCard = renderRecord(get("cancel-rejected"));
const cancelButton = cancelCard.find(node => node.className?.includes("activity-cancel"));
assert.ok(cancelButton, "running work exposes cancel");
cancelButton.click();
setImmediate(() => {
    assert.equal(get("cancel-rejected").status, "running", "rejected cancel returns to actionable running state");

    const oldAttempt = attemptId("folder-view:batch:inbox", 1);
    const newAttempt = attemptId("folder-view:batch:inbox", 2);
    register({id: oldAttempt, group: "folder-view:batch:inbox", status: "running"});
    register({id: newAttempt, group: "folder-view:batch:inbox", status: "running"});
    remove(oldAttempt);
    assert.equal(get(oldAttempt), null, "superseded folder attempts are removed from history");
    assert.equal(get(newAttempt).status, "running", "superseded attempt cannot cancel its replacement");

    remove("normalize");
    remove("retryable-index");
    remove("partial-result");
    remove("cancel-rejected");
    remove(newAttempt);
    register({id: "recent-success", status: "completed"});
    render();
    assert.match(elements.get("activity-center-summary").textContent, /^No active work · 1 recent$/);
    process.stdout.write("Activity Center lifecycle assertions passed\n");
});
