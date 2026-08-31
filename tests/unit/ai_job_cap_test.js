#!/usr/bin/env node
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function makeNode(value = "") {
    return {
        value,
        checked: false,
        disabled: false,
        textContent: "",
        children: [],
        style: {},
        classList: {toggle() {}},
        replaceChildren(...children) { this.children = children; },
    };
}

function makeContext(elementText, qualityFlags) {
    const nodes = new Map([
        ["ai-elements", makeNode(elementText)],
        ["ai-element-cap-status", makeNode()],
        ["ai-score-summary", makeNode()],
        ["ai-submit-btn", makeNode()],
        ["ai-source-folder", makeNode("inbox")],
        ["ai-model", makeNode("vision")],
        ["ai-move-toggle", makeNode()],
        ["ai-top-n", makeNode("15")],
        ["ai-dest-folder", makeNode("shortlisted")],
    ]);
    const toasts = [];
    let fetches = 0;
    const context = vm.createContext({
        console,
        document: {getElementById(id) { return nodes.get(id) || null; }},
        currentBatch: "batch-a",
        createTextElement(_tag, _className, text) { return {textContent: text}; },
        aiCollectQualityFlags() { return qualityFlags; },
        showToast(message) { toasts.push(message); },
        activityRegister() {},
        aiShowJobStatus() {},
        aiStartPolling() {},
        ccApiPath(path) { return path; },
        fetch() {
            fetches += 1;
            return Promise.resolve({ok: false, json: async () => ({error: "stopped by harness"})});
        },
    });
    vm.runInContext(fs.readFileSync("static/js/ai-state.js", "utf8"), context);
    vm.runInContext(fs.readFileSync("static/js/ai-job.js", "utf8"), context);
    return {context, nodes, toasts, get fetches() { return fetches; }};
}

(async () => {
    const over = makeContext("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk\nl", ["anatomy"]);
    vm.runInContext("aiUpdateScoreSummary()", over.context);
    assert.equal(over.nodes.get("ai-submit-btn").disabled, true, "overflow disables submit");
    assert.match(over.nodes.get("ai-element-cap-status").textContent, /maximum 12/i);
    await vm.runInContext("aiSubmitJob()", over.context);
    assert.equal(over.fetches, 0, "overflow submit must not fetch");
    assert.match(over.toasts.at(-1), /12/);

    const exact = makeContext("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk", ["anatomy"]);
    vm.runInContext("aiUpdateScoreSummary()", exact.context);
    assert.equal(exact.nodes.get("ai-submit-btn").disabled, false, "exact cap remains valid");
    await vm.runInContext("aiSubmitJob()", exact.context);
    assert.equal(exact.fetches, 1, "exact cap submits");
    process.stdout.write(JSON.stringify({passed: 7, failed: 0}));
})().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
