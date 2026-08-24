"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const sourcePath = path.join(__dirname, "..", "..", "scripts", "benchmark_thumbnails.py");
const source = fs.readFileSync(sourcePath, "utf8");
let assertionCount = 0;

function check(condition, message) {
    assertionCount += 1;
    assert.ok(condition, message);
}

function equal(actual, expected, message) {
    assertionCount += 1;
    assert.equal(actual, expected, message);
}

function extractRawString(name) {
    const marker = `${name} = r\"\"\"`;
    const start = source.indexOf(marker);
    assert.notEqual(start, -1, `${name} was not found`);
    const bodyStart = start + marker.length;
    const end = source.indexOf('\n\"\"\"', bodyStart);
    assert.notEqual(end, -1, `${name} terminator was not found`);
    return source.slice(bodyStart, end);
}

function runAsyncScript(script, options) {
    const state = options.sharedState || {
        expectedCount: options.expectedCount,
        renderedCount: options.renderedCount,
        chunkSize: options.chunkSize || 10,
        rowHeight: options.rowHeight || 100,
        loaded: new Set(),
        scrollPositions: [],
        growthCount: 0,
        scrollTop: 0,
    };
    if (!options.sharedState) {
        const initialLoadedCount = options.initialLoadedCount ?? state.renderedCount;
        for (let index = 0; index < initialLoadedCount; index += 1) state.loaded.add(index);
    }

    let now = 0;
    let completed;
    const frames = [];
    let growthPending = false;
    const scrollListeners = [];

    function scheduleGridGrowth() {
        if (growthPending || options.allowGrowth === false || state.renderedCount >= state.expectedCount) return;
        growthPending = true;
        frames.push(() => {
            growthPending = false;
            const before = state.renderedCount;
            state.renderedCount = Math.min(
                state.expectedCount,
                state.renderedCount + state.chunkSize,
            );
            for (let index = before; index < state.renderedCount; index += 1) {
                state.loaded.add(index);
            }
            state.growthCount += 1;
        });
    }

    function dispatchContentScroll() {
        const event = {
            type: "scroll",
            propagationStopped: false,
            stopImmediatePropagation() {
                this.propagationStopped = true;
            },
        };
        for (const listener of scrollListeners.filter((entry) => entry.capture)) {
            listener.callback(event);
            if (event.propagationStopped) return true;
        }
        scheduleGridGrowth();
        if (event.propagationStopped) return true;
        for (const listener of scrollListeners.filter((entry) => !entry.capture)) {
            listener.callback(event);
            if (event.propagationStopped) break;
        }
        return true;
    }

    const content = {
        clientHeight: options.clientHeight || 500,
        _scrollTop: state.scrollTop,
        get scrollHeight() {
            if (options.fixedScrollHeight !== undefined) return options.fixedScrollHeight;
            return Math.max(this.clientHeight, state.renderedCount * state.rowHeight);
        },
        get scrollTop() {
            return this._scrollTop;
        },
        set scrollTop(value) {
            const previousScrollTop = this._scrollTop;
            const bottom = Math.max(0, this.scrollHeight - this.clientHeight);
            this._scrollTop = Math.max(0, Math.min(Number(value), bottom));
            state.scrollTop = this._scrollTop;
            state.scrollPositions.push(this._scrollTop);
            const distanceToBottom = this.scrollHeight - this.clientHeight - this._scrollTop;
            if (
                options.productionScrollGrowth
                && this._scrollTop !== previousScrollTop
                && distanceToBottom <= (options.nearEndPx || 800)
            ) {
                dispatchContentScroll();
            }
        },
        dispatchEvent() {
            if (options.productionScrollGrowth) dispatchContentScroll();
            else if (options.allowGrowth !== false && state.renderedCount < state.expectedCount) {
                const before = state.renderedCount;
                state.renderedCount = Math.min(state.expectedCount, state.renderedCount + state.chunkSize);
                for (let index = before; index < state.renderedCount; index += 1) state.loaded.add(index);
                state.growthCount += 1;
            }
            return true;
        },
        addEventListener(type, callback, optionsValue) {
            if (type !== "scroll") return;
            const capture = optionsValue === true || Boolean(optionsValue && optionsValue.capture);
            scrollListeners.push({ callback, capture });
        },
        removeEventListener(type, callback, optionsValue) {
            if (type !== "scroll") return;
            const capture = optionsValue === true || Boolean(optionsValue && optionsValue.capture);
            const index = scrollListeners.findIndex(
                (entry) => entry.callback === callback && entry.capture === capture,
            );
            if (index >= 0) scrollListeners.splice(index, 1);
        },
    };

    function images() {
        return Array.from({ length: state.renderedCount }, (_, index) => ({
            classList: {
                contains(name) {
                    if (name !== "loaded" || !state.loaded.has(index)) return false;
                    if (options.unsettledAtOrAfter !== undefined && content.scrollTop >= options.unsettledAtOrAfter) {
                        const firstVisible = Math.floor(content.scrollTop / state.rowHeight);
                        if (index === firstVisible) return false;
                    }
                    return true;
                },
            },
            getBoundingClientRect() {
                const top = index * state.rowHeight - content.scrollTop;
                return { top, bottom: top + state.rowHeight };
            },
        }));
    }

    const document = {
        querySelector: (selector) => (selector === ".content" ? content : null),
        querySelectorAll(selector) {
            const allImages = images();
            if (selector.endsWith("img.loaded")) {
                return allImages.filter((image) => image.classList.contains("loaded"));
            }
            if (selector.endsWith(" img")) return allImages;
            if (selector === "#grid .thumb:not(.loading-placeholder)") {
                return allImages.map((image) => ({ querySelector: () => image }));
            }
            return [];
        },
    };
    const context = vm.createContext({
        document,
        window: { innerHeight: content.clientHeight },
        performance: { now: () => now },
        requestAnimationFrame: (callback) => frames.push(callback),
        Event: class Event {},
        console,
    });
    const args = [
        ...(options.scriptArguments || [
            options.expectedCount,
            options.targetCount,
            options.maxFrames || 5000,
            options.mode,
        ]),
        (result) => {
            completed = result;
        },
    ];
    context.__args = args;
    vm.runInContext(`(function() {${script}\n}).apply(null, __args);`, context);
    for (let guard = 0; completed === undefined && guard < 10000; guard += 1) {
        const callback = frames.shift();
        assert.ok(callback, "script stopped scheduling animation frames before completion");
        now += 50;
        callback(now);
    }
    assert.notEqual(completed, undefined, "script did not complete within the mock frame guard");
    return { result: completed, state, content };
}

function testProgressiveFullReachesCurrentFinalBottom() {
    const { result, state, content } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 40,
        targetCount: 40,
        renderedCount: 10,
        chunkSize: 10,
        clientHeight: 500,
        mode: "full",
    });

    equal(result.ready, true, "progressive full traversal should become ready");
    equal(result.expectedCount, 40, "result should retain the full expected count");
    equal(result.targetCount, 40, "result should retain the traversal target");
    equal(result.renderedCount, 40, "full traversal should render the expected count");
    equal(result.growthEvents.length, 3, "each progressive append should be recorded");
    equal(result.finalBottomVisited, true, "the current bottom should be visited after final growth");
    equal(result.finalScrollTop, content.scrollHeight - content.clientHeight, "final position should be exact current bottom");
    check(state.scrollPositions.includes(500), "the obsolete initial bottom should have been visited");
    check(result.finalScrollTop > 500, "completion must not reuse obsolete initial-bottom satisfaction");
}

testProgressiveFullReachesCurrentFinalBottom();

function testProgressivePartialStopsAtRenderedPrefixBottom() {
    const { result, content } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 100,
        targetCount: 40,
        renderedCount: 20,
        chunkSize: 20,
        clientHeight: 500,
        mode: "partial",
    });

    equal(result.ready, true, "progressive partial traversal should become ready");
    equal(result.expectedCount, 100, "partial result should retain full expected count");
    equal(result.targetCount, 40, "partial result should expose its bounded target");
    check(result.renderedCount >= 40, "partial traversal should reach its target count");
    check(result.renderedCount < 100, "partial traversal should stop before full expected count");
    equal(result.targetBoundaryVisited, true, "rendered-prefix boundary should be visited");
    equal(result.finalBottomVisited, true, "rendered-prefix boundary is the current bottom");
    equal(result.targetBoundary, content.scrollHeight - content.clientHeight, "serialized boundary should be the rendered-prefix bottom");
    equal(result.finalScrollTop, result.targetBoundary, "final viewport should be the settled target boundary");
}

testProgressivePartialStopsAtRenderedPrefixBottom();

function testProgressivePartialStopsAtFirstTargetPrefixWithProductionScrollTiming() {
    const script = extractRawString("DYNAMIC_TRAVERSAL_GRID");
    const large = runAsyncScript(script, {
        expectedCount: 2000,
        targetCount: 800,
        renderedCount: 120,
        chunkSize: 120,
        rowHeight: 10,
        clientHeight: 500,
        mode: "partial",
        productionScrollGrowth: true,
    }).result;
    const medium = runAsyncScript(script, {
        expectedCount: 500,
        targetCount: 200,
        renderedCount: 120,
        chunkSize: 120,
        rowHeight: 10,
        clientHeight: 500,
        mode: "partial",
        productionScrollGrowth: true,
    }).result;

    equal(large.ready, true, "2,000-image partial traversal should become ready");
    equal(large.renderedCount, 840, "2,000-image partial traversal should stop at the first target prefix");
    check(large.renderedCount < large.expectedCount, "2,000-image partial traversal must remain bounded");
    equal(large.targetBoundaryVisited, true, "2,000-image target-prefix boundary should be visited");
    equal(large.finalBottomVisited, true, "2,000-image target-prefix boundary should be its current bottom");
    equal(large.finalScrollTop, large.targetBoundary, "2,000-image final position should match its reported boundary");
    equal(medium.ready, true, "500-image partial traversal should become ready");
    equal(medium.renderedCount, 240, "500-image partial traversal should stop at the first target prefix");
    check(medium.renderedCount < medium.expectedCount, "500-image partial traversal must remain bounded");
    equal(medium.targetBoundaryVisited, true, "500-image target-prefix boundary should be visited");
    equal(medium.finalBottomVisited, true, "500-image target-prefix boundary should be its current bottom");
    equal(medium.finalScrollTop, medium.targetBoundary, "500-image final position should match its reported boundary");
}

testProgressivePartialStopsAtFirstTargetPrefixWithProductionScrollTiming();

function testPartialThenFullPreservesRenderedAndLoadedState() {
    const script = extractRawString("DYNAMIC_TRAVERSAL_GRID");
    const partialRun = runAsyncScript(script, {
        expectedCount: 100,
        targetCount: 40,
        renderedCount: 20,
        chunkSize: 20,
        clientHeight: 500,
        mode: "partial",
    });
    const loadedAfterPartial = new Set(partialRun.state.loaded);
    const fullRun = runAsyncScript(script, {
        expectedCount: 100,
        targetCount: 100,
        renderedCount: partialRun.state.renderedCount,
        clientHeight: 500,
        mode: "full",
        sharedState: partialRun.state,
    });

    equal(partialRun.result.renderedCount, 40, "partial phase should leave a bounded rendered prefix");
    equal(fullRun.result.ready, true, "full traversal should continue from the partial state");
    equal(fullRun.result.renderedCount, 100, "full traversal should continue to expected count");
    check(
        [...loadedAfterPartial].every((index) => fullRun.state.loaded.has(index)),
        "full traversal should preserve every image loaded by partial traversal",
    );
}

testPartialThenFullPreservesRenderedAndLoadedState();

function testStaticFullDomPartialStopsAtProportionalBoundary() {
    const { result, content, state } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 100,
        targetCount: 40,
        renderedCount: 100,
        clientHeight: 500,
        mode: "partial",
    });
    const fullBottom = content.scrollHeight - content.clientHeight;
    const proportionalBoundary = Math.round(fullBottom * 0.4);

    equal(result.ready, true, "static full-DOM partial traversal should become ready");
    equal(result.targetBoundary, proportionalBoundary, "partial boundary should be proportional to target count");
    equal(result.finalScrollTop, proportionalBoundary, "partial traversal should stop at proportional boundary");
    equal(result.finalBottomVisited, false, "partial traversal should not visit the static full-grid bottom");
    check(!state.scrollPositions.includes(fullBottom), "partial traversal should not intentionally visit the remainder");
}

testStaticFullDomPartialStopsAtProportionalBoundary();

function testFinalViewportMustSettle() {
    const { result } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 20,
        targetCount: 20,
        renderedCount: 20,
        clientHeight: 500,
        mode: "full",
        unsettledAtOrAfter: 1500,
    });

    equal(result.ready, false, "an unsettled final viewport must fail readiness");
    equal(result.targetBoundaryVisited, false, "an unsettled boundary must not count as visited");
    equal(result.unsettledCount, 1, "the timed-out final viewport should be preserved as evidence");
    equal(result.stagnationReason, null, "viewport timeout should not be mislabeled as growth stagnation");
    check(result.unsettledReason.includes("did not settle"), "result should carry an actionable unsettled reason");
}

testFinalViewportMustSettle();

function testNoGrowthTerminatesWithStagnation() {
    const { result } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 40,
        targetCount: 40,
        renderedCount: 10,
        clientHeight: 500,
        mode: "full",
        allowGrowth: false,
    });

    equal(result.ready, false, "a progressive grid that never grows must fail");
    equal(result.frameCapReached, false, "growth stagnation should terminate before the global frame cap");
    check(result.stagnationReason.includes("10 of 40"), "stagnation should report rendered and target counts");
}

testNoGrowthTerminatesWithStagnation();

function testRenderedCountGrowthResetsStagnationWithoutExtentGrowth() {
    const { result } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 40,
        targetCount: 40,
        renderedCount: 10,
        chunkSize: 10,
        clientHeight: 500,
        fixedScrollHeight: 1000,
        mode: "full",
    });

    equal(result.ready, true, "rendered-count growth should satisfy bounded growth waiting");
    equal(result.renderedCount, 40, "rendered-only growth should continue to expected count");
    equal(result.growthEvents.length, 3, "rendered-only growth events should be instrumented");
    check(
        result.growthEvents.every((event) => event.prevHeight === event.newHeight),
        "rendered-only growth evidence should retain the unchanged extent",
    );
}

testRenderedCountGrowthResetsStagnationWithoutExtentGrowth();

function testShortStaticFullNeedsNoGrowth() {
    const { result } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 4,
        targetCount: 4,
        renderedCount: 4,
        clientHeight: 500,
        mode: "full",
    });

    equal(result.ready, true, "a short static full grid should be ready");
    equal(result.growthEvents.length, 0, "a complete short grid should not invent growth");
    equal(result.finalScrollTop, 0, "a non-scrollable grid has an exact bottom of zero");
    equal(result.finalBottomVisited, true, "the zero boundary should count as current bottom");
}

testShortStaticFullNeedsNoGrowth();

function testTraversalStepGapsStayWithinSafeStep() {
    const { result } = runAsyncScript(extractRawString("DYNAMIC_TRAVERSAL_GRID"), {
        expectedCount: 30,
        targetCount: 30,
        renderedCount: 30,
        clientHeight: 500,
        mode: "full",
    });
    const positions = result.visitedRegions.map((region) => region.scrollPosition);
    const gaps = positions.slice(1).map((position, index) => position - positions[index]);
    // Production virtualization keeps the viewport plus two overscan rows on
    // both sides; the exact-coverage recovery pass uses 0.5 viewport steps.
    check(gaps.every((gap) => gap <= 900), `step gaps exceeded safe virtual-window step: ${gaps.join(", ")}`);
}

testTraversalStepGapsStayWithinSafeStep();

function runViewport(options) {
    return runAsyncScript(extractRawString("VIEWPORT_SETTLE_ASYNC"), {
        expectedCount: options.expectedCount,
        renderedCount: options.renderedCount,
        clientHeight: 500,
        initialLoadedCount: options.initialLoadedCount,
        unsettledAtOrAfter: options.unsettled ? 0 : undefined,
        scriptArguments: [options.expectedCount, 150],
    }).result;
}

function testViewportSettleSupportsProgressiveAndStaticDomCounts() {
    const progressive = runViewport({ expectedCount: 100, renderedCount: 20 });
    const fullDom = runViewport({ expectedCount: 100, renderedCount: 100 });

    equal(progressive.ready, true, "a loaded progressive first viewport should settle");
    equal(progressive.state.renderedCount, 20, "state should serialize rendered count distinctly");
    equal(progressive.state.expectedCount, 100, "state should preserve full expected count");
    equal(fullDom.ready, true, "current full-DOM behavior should remain valid");
    equal(fullDom.state.renderedCount, 100, "full DOM state should report its rendered count");
}

testViewportSettleSupportsProgressiveAndStaticDomCounts();

function testViewportSettleRejectsEmptyAndVisibleUnsettledStates() {
    const empty = runViewport({ expectedCount: 100, renderedCount: 0 });
    const unsettled = runViewport({ expectedCount: 100, renderedCount: 20, unsettled: true });

    equal(empty.ready, false, "zero rendered thumbnails must not satisfy first viewport readiness");
    equal(unsettled.ready, false, "visible unloaded images must not satisfy first viewport readiness");
    check(unsettled.state.visibleLoaded < unsettled.state.visibleCount, "timeout state should preserve visible-unsettled evidence");
}

testViewportSettleRejectsEmptyAndVisibleUnsettledStates();
console.log(`benchmark dynamic traversal: ${assertionCount} assertions passed`);
