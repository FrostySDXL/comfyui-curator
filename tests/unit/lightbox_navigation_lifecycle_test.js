"use strict";

const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("static/js/lightbox.js", "utf8");
const details = [];

function check(condition, message) {
    details.push({pass: Boolean(condition), message});
}

function flushPromises() {
    return new Promise(resolve => setImmediate(resolve));
}

function createClassList(initial = []) {
    const names = new Set(initial);
    return {
        add(...values) { values.forEach(value => names.add(value)); },
        remove(...values) { values.forEach(value => names.delete(value)); },
        contains(value) { return names.has(value); },
        toggle(value, force) {
            const enabled = force === undefined ? !names.has(value) : Boolean(force);
            if (enabled) names.add(value);
            else names.delete(value);
            return enabled;
        },
    };
}

function createElement() {
    return {
        classList: createClassList(),
        style: {},
        dataset: {},
        scrollLeft: 0,
        scrollTop: 0,
        clientWidth: 1000,
        clientHeight: 700,
        offsetWidth: 800,
        offsetHeight: 600,
        naturalWidth: 0,
        naturalHeight: 0,
        src: "",
        onload: null,
        onerror: null,
        replaceChildrenCount: 0,
        addEventListener() {},
        appendChild() {},
        replaceChildren() { this.replaceChildrenCount++; },
        querySelectorAll() { return []; },
        closest() { return {style: {}}; },
        getBoundingClientRect() { return {left: 0, top: 0, width: 800, height: 600}; },
    };
}

function createRuntime() {
    const imageUrls = ["/image/batch/inbox/a.png", "/image/batch/inbox/b.png", "/image/batch/inbox/c.png"];
    const items = ["a.png", "b.png", "c.png"].map(name => ({name}));
    const visibleImage = createElement();
    visibleImage.src = imageUrls[0];
    visibleImage.naturalWidth = 800;
    visibleImage.naturalHeight = 600;
    const lightbox = createElement();
    lightbox.classList.add("active");
    const elements = {
        lightbox,
        "lightbox-img": visibleImage,
        "lightbox-image-wrap": createElement(),
        "lightbox-info": createElement(),
        "lightbox-metadata-panel": createElement(),
        "lightbox-ai-panel": createElement(),
        "lightbox-zoom-indicator": createElement(),
        "lightbox-pin-compare-btn": createElement(),
        "lightbox-compare": createElement(),
        "lightbox-compare-img-0": createElement(),
        "lightbox-compare-img-1": createElement(),
        "lightbox-compare-wrap-0": createElement(),
        "lightbox-compare-wrap-1": createElement(),
        "lightbox-compare-label-0": createElement(),
        "lightbox-compare-label-1": createElement(),
        "lightbox-compare-zoom-0": createElement(),
        "lightbox-compare-zoom-1": createElement(),
    };
    const comparePanes = [createElement(), createElement()];
    comparePanes.forEach((pane, index) => { pane.dataset.comparePane = String(index); });
    const loaders = [];

    class MockImage {
        constructor() {
            this._src = "";
            this.onload = null;
            this.onerror = null;
            this.naturalWidth = 800;
            this.naturalHeight = 600;
            this._decodeResolve = null;
            this._decodeReject = null;
            loaders.push(this);
        }

        get src() { return this._src; }
        set src(value) {
            this._src = value;
            if (value && !this._requestedSrc) this._requestedSrc = value;
        }

        decode() {
            return new Promise((resolve, reject) => {
                this._decodeResolve = resolve;
                this._decodeReject = reject;
            });
        }

        finishLoad() {
            if (this.onload) this.onload.call(this);
        }

        finishDecode() {
            if (this._decodeResolve) this._decodeResolve();
        }

        rejectDecode() {
            if (this._decodeReject) this._decodeReject(new Error("decode failed"));
        }

        failLoad() {
            if (this.onerror) this.onerror.call(this, new Error("load failed"));
        }
    }

    const context = {
        console,
        Promise,
        Image: MockImage,
        currentIndex: 0,
        currentBatch: "batch",
        currentFolder: "inbox",
        currentSort: "date",
        selectedImages: new Set(),
        aiActiveRun: null,
        lightboxMetadataRequestToken: 0,
        currentLightboxMetadata: null,
        currentLightboxMetadataError: null,
        currentLightboxMetadataLoading: false,
        currentLightboxDimensions: {w: null, h: null},
        lightboxMetadataOpen: false,
        document: {
            getElementById(id) { return elements[id] || null; },
            querySelectorAll() { return []; },
            querySelector(selector) {
                const match = selector.match(/data-compare-pane="([01])"/);
                return match ? comparePanes[Number(match[1])] : null;
            },
            createElement() { return createElement(); },
            createTextNode(text) { return {textContent: text}; },
        },
        requestAnimationFrame(callback) { callback(); return 1; },
        getCurrentDisplayImages() { return items; },
        getImageBatchAndFolder() { return {batch: "batch", folder: "inbox"}; },
        isVirtualCollectionView() { return false; },
        isPublicView() { return false; },
        ccImageUrl(batch, folder, name) { return `/image/${batch}/${folder}/${name}`; },
        loadLightboxMetadata() { return Promise.resolve(); },
        renderLightboxMetadataPanel() {},
        syncMetadataToggleButton() {},
        syncLightboxPublicActions() {},
        aiSetInspectedImage() {},
        aiGetImageScore() { return null; },
        createTextElement() { return createElement(); },
        showToast() {},
    };
    vm.createContext(context);
    vm.runInContext(source, context, {filename: "lightbox.js"});
    return {context, elements, imageUrls, loaders};
}

function loaderFor(loaders, url) {
    return loaders.find(loader => loader.src === url);
}

async function finishLoader(loader) {
    if (!loader) return;
    loader.finishLoad();
    await flushPromises();
    loader.finishDecode();
    await flushPromises();
}

async function prepareNewSession(context, loaders, targetIndex) {
    context.closeLightbox();
    context.openLightbox(targetIndex);
    const loader = loaders.at(-1);
    await finishLoader(loader);
    return loader;
}

async function testNewSessionHidesPreviousImageUntilVisibleTargetLoads() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    context.closeLightbox();
    context.openLightbox(1);

    check(!elements.lightbox.classList.contains("active"), "new session remains inactive while the target prepares");
    check(elements["lightbox-img"].src !== imageUrls[0], "new session clears the previous session src before activation");

    await finishLoader(loaderFor(loaders, imageUrls[1]));
    check(!elements.lightbox.classList.contains("active"), "decoded off-DOM target does not activate before visible-image load");
    check(elements["lightbox-img"].src === imageUrls[1], "decoded target is assigned to the hidden visible image");

    if (elements["lightbox-img"].onload) elements["lightbox-img"].onload();
    check(elements.lightbox.classList.contains("active"), "visible-image load activates the prepared new session");
    check(vm.runInContext("lightboxBaseWidth > 0 && lightboxBaseHeight > 0", context), "new session measures nonzero base dimensions before activation");
    check(vm.runInContext("lightboxZoom === 1", context), "new session activates at 100 percent zoom");
}

async function testNewSessionMeasuresUntransformedLayoutSize() {
    const {context, elements, loaders} = createRuntime();
    const visibleImage = elements["lightbox-img"];
    visibleImage.offsetWidth = 800;
    visibleImage.offsetHeight = 600;
    visibleImage.getBoundingClientRect = () => ({left: 0, top: 0, width: 780, height: 585});

    await prepareNewSession(context, loaders, 1);
    if (visibleImage.onload) visibleImage.onload();

    check(vm.runInContext("lightboxBaseWidth === 800 && lightboxBaseHeight === 600", context), "new session stores untransformed layout dimensions before activation");
    check(visibleImage.style.width === "800px" && visibleImage.style.height === "600px", "new session applies untransformed dimensions at 100 percent zoom");
}

async function testClosePreservesCommittedInlineDimensions() {
    const {context, elements, loaders} = createRuntime();
    const visibleImage = elements["lightbox-img"];
    await prepareNewSession(context, loaders, 1);
    if (visibleImage.onload) visibleImage.onload();
    const committedWidth = visibleImage.style.width;
    const committedHeight = visibleImage.style.height;

    context.closeLightbox();

    check(committedWidth !== "" && committedHeight !== "", "active measured image has explicit committed dimensions before close");
    check(visibleImage.style.width === committedWidth && visibleImage.style.height === committedHeight, "close preserves committed inline dimensions through fade-out");
}

async function testCloseCancelsNewSessionDuringLoadAndDecode() {
    for (const phase of ["load", "decode"]) {
        const {context, elements, imageUrls, loaders} = createRuntime();
        context.closeLightbox();
        context.openLightbox(1);
        const targetLoader = loaderFor(loaders, imageUrls[1]);
        if (phase === "decode") {
            targetLoader.finishLoad();
            await flushPromises();
        }
        context.closeLightbox();
        if (phase === "load") targetLoader.finishLoad();
        targetLoader.finishDecode();
        await flushPromises();

        check(!elements.lightbox.classList.contains("active"), `close during ${phase} keeps the new session inactive`);
        check(elements["lightbox-img"].src !== imageUrls[1], `close during ${phase} prevents target assignment`);
    }
}

async function testCloseAfterAssignmentCancelsVisibleLoadCompletion() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    await prepareNewSession(context, loaders, 1);
    const staleVisibleLoad = elements["lightbox-img"].onload;

    check(typeof staleVisibleLoad === "function", "new session waits with a guarded visible-image load handler");
    context.closeLightbox();
    if (staleVisibleLoad) staleVisibleLoad();

    check(!elements.lightbox.classList.contains("active"), "close after assignment prevents stale visible load activation");
    check(vm.runInContext("lightboxBaseWidth === 0 && lightboxBaseHeight === 0", context), "stale visible load cannot capture closed-session dimensions");
}

async function testRapidCloseReopenAllowsOnlyLatestSessionToActivate() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    await prepareNewSession(context, loaders, 1);
    const staleVisibleLoad = elements["lightbox-img"].onload;

    context.closeLightbox();
    context.openLightbox(2);
    if (staleVisibleLoad) staleVisibleLoad();
    check(!elements.lightbox.classList.contains("active"), "stale prior-session visible load cannot activate a reopen");
    check(elements["lightbox-img"].src !== imageUrls[1], "reopen does not expose the prior session target");

    await finishLoader(loaderFor(loaders, imageUrls[2]));
    check(!elements.lightbox.classList.contains("active"), "latest reopen still waits for its own visible load");
    if (elements["lightbox-img"].onload) elements["lightbox-img"].onload();
    check(elements.lightbox.classList.contains("active"), "latest reopen activates after its visible target loads");
    check(elements["lightbox-img"].src === imageUrls[2], "latest reopen target wins");
}

async function testNewSessionFailureLeavesGridVisible() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    context.closeLightbox();
    context.openLightbox(1);
    loaderFor(loaders, imageUrls[1]).failLoad();
    await flushPromises();

    check(!elements.lightbox.classList.contains("active"), "initial-open failure leaves the overlay inactive");
    check(elements["lightbox-img"].src !== imageUrls[0], "initial-open failure does not restore the previous session image");
}

async function testCurrentImageRemainsVisibleUntilDecode() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    context.navigate(1);

    check(elements["lightbox-img"].src === imageUrls[0], "navigation keeps the current src until the target is ready");
    check(elements["lightbox-img"].style.opacity !== "0", "navigation never hides the current image while loading");

    const targetLoader = loaderFor(loaders, imageUrls[1]);
    check(Boolean(targetLoader), "navigation starts an off-DOM target loader");
    if (!targetLoader) return;
    targetLoader.finishLoad();
    await flushPromises();
    check(elements["lightbox-img"].src === imageUrls[0], "load completion alone does not swap before decode");
    targetLoader.finishDecode();
    await flushPromises();
    check(elements["lightbox-img"].src === imageUrls[1], "decoded target replaces the visible image");
}

async function testStaleNavigationCannotOverwriteNewerTarget() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    context.navigate(1);
    const staleLoader = loaderFor(loaders, imageUrls[1]);
    context.navigate(1);
    const currentLoader = loaderFor(loaders, imageUrls[2]);

    await finishLoader(staleLoader);
    check(elements["lightbox-img"].src === imageUrls[0], "superseded completion leaves the old visible image untouched");
    await finishLoader(currentLoader);
    check(elements["lightbox-img"].src === imageUrls[2], "latest navigation target wins after decode");
}

async function testCompletedNeighborPreloadsStayBoundedAndRetained() {
    const {context, imageUrls, loaders} = createRuntime();
    vm.runInContext("_prefetchAdjacentImages(lightboxImageToken)", context);
    const neighbors = loaders.filter(loader => loader.src === imageUrls[1] || loader.src === imageUrls[2]);
    for (const loader of neighbors) await finishLoader(loader);
    const registrySize = vm.runInContext("_prefetchRegistry.size", context);

    check(neighbors.length === 2, "prefetch creates only the two adjacent loaders");
    check(registrySize === 2, "decoded adjacent loaders remain retained for the active neighborhood");
    check(registrySize <= 2, "retained prefetch registry stays bounded to two entries");
}

async function testCompletedPreloadIsConsumedByNavigation() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    vm.runInContext("_prefetchAdjacentImages(lightboxImageToken)", context);
    const targetLoader = loaderFor(loaders, imageUrls[1]);
    const otherLoader = loaderFor(loaders, imageUrls[2]);
    await finishLoader(targetLoader);
    await finishLoader(otherLoader);
    const loadersBeforeNavigation = loaders.length;

    context.targetLoader = targetLoader;
    context.navigate(1);
    check(loaders.length === loadersBeforeNavigation, "ready neighbor navigation constructs no replacement target loader");
    check(vm.runInContext("!_prefetchRegistry.has('/image/batch/inbox/b.png')", context), "ready neighbor entry is consumed from the preload registry synchronously");
    check(vm.runInContext("_pendingSingleImageLoader.entry.img === targetLoader", context), "navigation takes ownership of the retained ready loader");
    check(elements["lightbox-img"].src === imageUrls[0], "ready preload swap waits for its promise microtask");

    await flushPromises();
    const targetLoaderCount = loaders.filter(loader => loader._requestedSrc === imageUrls[1]).length;
    const registryKeys = vm.runInContext("Array.from(_prefetchRegistry.keys())", context);
    check(elements["lightbox-img"].src === imageUrls[1], "retained ready preload swaps on the promise microtask");
    check(vm.runInContext("_pendingSingleImageLoader === null", context), "ready preload navigation releases pending ownership after swap");
    check(targetLoaderCount === 1, "preload reuse creates exactly one Image for the navigation target");
    check(registryKeys.length === 2, "preload reuse reconciles a bounded two-entry active neighborhood");
    check(registryKeys.includes(imageUrls[0]) && registryKeys.includes(imageUrls[2]), "preload reuse reconciles the new previous and next neighbors");
}

async function testDecodeRejectionCommitsLoadedTarget() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    context.navigate(1);
    const targetLoader = loaderFor(loaders, imageUrls[1]);
    targetLoader.finishLoad();
    await flushPromises();
    check(elements["lightbox-img"].src === imageUrls[0], "decode-rejection fallback does not swap before rejection is known");
    targetLoader.rejectDecode();
    await flushPromises();

    check(elements["lightbox-img"].src === imageUrls[1], "successful load commits when decode rejects");
    check(vm.runInContext("_pendingSingleImageLoader === null", context), "decode-rejection fallback clears pending ownership");
    check(vm.runInContext("_prefetchRegistry.size <= 2", context), "decode-rejection fallback reconciles bounded neighbors");
}

async function testCompareEntryCancelsPendingSingleLoader() {
    for (const compareEntry of ["openCompareLightbox", "openStickyCompareLightbox"]) {
        const {context, imageUrls, loaders} = createRuntime();
        context.navigate(1);
        const pendingLoader = loaderFor(loaders, imageUrls[1]);
        if (compareEntry === "openCompareLightbox") {
            context.selectedImages.add("a.png");
            context.selectedImages.add("b.png");
        }
        context[compareEntry]();

        check(vm.runInContext("_pendingSingleImageLoader === null", context), `${compareEntry} clears pending single-image ownership immediately`);
        check(pendingLoader.src === "", `${compareEntry} disposes the pending single-image loader`);
        check(pendingLoader.onload === null && pendingLoader.onerror === null, `${compareEntry} detaches pending single-image handlers`);
    }
}

async function testLoaderErrorPreservesVisibleImageAndClearsOwnership() {
    const {context, elements, imageUrls, loaders} = createRuntime();
    const infoUpdatesBefore = elements["lightbox-info"].replaceChildrenCount;
    context.navigate(1);
    const targetLoader = loaderFor(loaders, imageUrls[1]);
    targetLoader.failLoad();
    await flushPromises();

    check(elements["lightbox-img"].src === imageUrls[0], "loader error preserves the current visible src");
    check(vm.runInContext("_pendingSingleImageLoader === null", context), "loader error clears pending ownership");
    check(elements["lightbox-info"].replaceChildrenCount === infoUpdatesBefore, "loader error does not publish stale image info");
    check(vm.runInContext("_prefetchRegistry.size === 0", context), "loader error does not schedule stale neighbor prefetches");
}

async function testResolvedPreloadsDetachEventHandlers() {
    const {context, imageUrls, loaders} = createRuntime();
    vm.runInContext("_prefetchAdjacentImages(lightboxImageToken)", context);
    const neighbors = loaders.filter(loader => loader.src === imageUrls[1] || loader.src === imageUrls[2]);
    for (const loader of neighbors) await finishLoader(loader);

    check(neighbors.every(loader => loader.onload === null), "resolved retained preloads detach load handlers");
    check(neighbors.every(loader => loader.onerror === null), "resolved retained preloads detach error handlers");
    check(vm.runInContext("_prefetchRegistry.size === 2", context), "handler detachment preserves retained ready preload entries");
}

function testIsLightboxOpenPendingReturnsFalseWhenNoPendingOpen() {
    const {context} = createRuntime();
    vm.runInContext("_pendingLightboxOpen = null", context);
    check(vm.runInContext("isLightboxOpenPending()", context) === false,
        "isLightboxOpenPending returns false when _pendingLightboxOpen is null");
}

function testIsLightboxOpenPendingReturnsTrueWhenPendingOpenExists() {
    const {context} = createRuntime();
    vm.runInContext("_pendingLightboxOpen = { entry: {} };", context);
    check(vm.runInContext("isLightboxOpenPending()", context) === true,
        "isLightboxOpenPending returns true when _pendingLightboxOpen is set");
}

function testPendingOpenCancelViaEscapePreservesNormalGridState() {
    const {context, elements} = createRuntime();
    context.closeLightbox();
    context.openLightbox(1);
    vm.runInContext("const wasPending = isLightboxOpenPending()", context);
    check(vm.runInContext("wasPending", context) === true,
        "pending open is reported truthfully after openLightbox starts preparation");
    context.closeLightbox();
    check(vm.runInContext("isLightboxOpenPending()", context) === false,
        "closeLightbox clears the pending open");
    check(!elements.lightbox.classList.contains("active"),
        "lightbox stays inactive after pending cancellation");
}

(async () => {
    await testNewSessionHidesPreviousImageUntilVisibleTargetLoads();
    await testNewSessionMeasuresUntransformedLayoutSize();
    await testClosePreservesCommittedInlineDimensions();
    await testCloseCancelsNewSessionDuringLoadAndDecode();
    await testCloseAfterAssignmentCancelsVisibleLoadCompletion();
    await testRapidCloseReopenAllowsOnlyLatestSessionToActivate();
    await testNewSessionFailureLeavesGridVisible();
    await testCurrentImageRemainsVisibleUntilDecode();
    await testStaleNavigationCannotOverwriteNewerTarget();
    await testCompletedNeighborPreloadsStayBoundedAndRetained();
    await testCompletedPreloadIsConsumedByNavigation();
    await testDecodeRejectionCommitsLoadedTarget();
    await testCompareEntryCancelsPendingSingleLoader();
    await testLoaderErrorPreservesVisibleImageAndClearsOwnership();
    await testResolvedPreloadsDetachEventHandlers();
    testIsLightboxOpenPendingReturnsFalseWhenNoPendingOpen();
    testIsLightboxOpenPendingReturnsTrueWhenPendingOpenExists();
    testPendingOpenCancelViaEscapePreservesNormalGridState();
    const failed = details.filter(detail => !detail.pass).length;
    process.stdout.write(JSON.stringify({total: details.length, failed, details}));
    process.exitCode = failed === 0 ? 0 : 1;
})().catch(error => {
    process.stderr.write(String(error.stack || error));
    process.exitCode = 1;
});
