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
    const attributes = {};
    return {
        classList: createClassList(),
        style: {},
        dataset: {},
        scrollLeft: 0,
        scrollTop: 0,
        clientWidth: 1000,
        clientHeight: 700,
        scrollWidth: 1000,
        scrollHeight: 700,
        offsetWidth: 800,
        offsetHeight: 600,
        naturalWidth: 0,
        naturalHeight: 0,
        src: "",
        onload: null,
        onerror: null,
        hidden: false,
        paused: true,
        playCalls: 0,
        replaceChildrenCount: 0,
        addEventListener() {},
        setAttribute(name, value) { attributes[name] = String(value); },
        getAttribute(name) { return attributes[name] || null; },
        setPointerCapture() {},
        hasPointerCapture() { return false; },
        releasePointerCapture() {},
        pause() { this.paused = true; },
        play() { this.playCalls++; this.paused = false; return Promise.resolve(); },
        load() {},
        removeAttribute(name) { if (name === "src") this.src = ""; },
        appendChild() {},
        replaceChildren() { this.replaceChildrenCount++; },
        setProperty() {},
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
        "lightbox-video": createElement(),
        "lightbox-audio": createElement(),
        "lightbox-audio-art": createElement(),
        "lightbox-audio-player": createElement(),
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
        "lightbox-compare-divider": createElement(),
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
        lightboxVideoAutoplayLoopEnabled: true,
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
        ccThumbUrl(batch, folder, name) { return `/thumb/${batch}/${folder}/${name}`; },
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
    return {context, elements, imageUrls, loaders, items};
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

async function testWorkspaceSearchNavigationReanchorsAfterPageReorder() {
    const {context, items} = createRuntime();
    items.splice(0, items.length, {name: "a.png"}, {name: "b.png"});
    context.currentIndex = 1;
    context.workspaceSearchFilter = {hasMore: true};
    context.isWorkspaceSearchView = () => true;
    context.getImageRenderKey = item => item.name;
    context.loadMoreWorkspaceSearchResults = async () => {
        items.splice(0, items.length,
            {name: "c.png"}, {name: "a.png"}, {name: "b.png"}, {name: "d.png"});
        return true;
    };

    await context.navigate(1);

    check(context.currentIndex === 3,
        "workspace search navigation reanchors the active image before advancing after page reorder");
}

function testStickyCandidateWalkPreservesGridAnchorAndOrder() {
    const {context, items} = createRuntime();
    context.currentIndex = 1;
    context.openStickyCompareLightbox();
    const namesBefore = items.map(item => item.name);
    context.navigateStickyCompare(1);

    check(context.currentIndex === 1, "sticky candidate walk preserves the originating grid anchor");
    check(context.getActiveLightboxImage().name === "a.png", "sticky candidate walk advances only the candidate pane");
    check(items.map(item => item.name).join(",") === namesBefore.join(","), "sticky candidate walk preserves canonical display order");
}

function testCompareSyncCanLinkAndUnlinkPaneZoom() {
    const {context} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    context.zoomComparePane(0, 0.2);
    check(vm.runInContext("lightboxCompareViewState[0].zoom === 1.2 && lightboxCompareViewState[1].zoom === 1.2", context),
        "compare zoom starts linked across panes");
    context.setLightboxCompareSync(false);
    context.zoomComparePane(0, 0.2);
    check(vm.runInContext("lightboxCompareViewState[0].zoom === 1.4 && lightboxCompareViewState[1].zoom === 1.2", context),
        "compare zoom can be unlinked per pane");
}

function testCompareSplitTogglesWithoutReloadingOriginals() {
    const {context, elements} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    const firstSrc = elements["lightbox-compare-img-0"].src;
    const secondSrc = elements["lightbox-compare-img-1"].src;
    check(context.toggleLightboxCompareSplit() === true, "still-image compare accepts A/B split mode");
    check(elements["lightbox-compare-img-0"].src === firstSrc && elements["lightbox-compare-img-1"].src === secondSrc,
        "A/B split toggles in place without reloading original image sources");
    check(context.toggleLightboxCompareSplit() === true, "A/B split toggles back to side-by-side");
}

function testAdvanceComparePairMovesBothPanesWithoutChangingGridAnchor() {
    const {context, items} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    const namesBefore = items.map(item => item.name);
    context.advanceComparePair(1);
    check(context.currentIndex === 0, "advancing the pair preserves the originating grid anchor");
    check(vm.runInContext("lightboxCompareItems[0].name === 'b.png' && lightboxCompareItems[1].name === 'c.png'", context),
        "advance pair shifts both compare panes in display order");
    check(items.map(item => item.name).join(",") === namesBefore.join(","), "advance pair does not reorder the display list");
}

function testSplitHitTestingSelectsVisiblePaneByDividerPosition() {
    const {context} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    context.toggleLightboxCompareSplit();
    const paneTarget = {closest() { return null; }};
    check(context.getActiveComparePaneIndexFromEvent({target: paneTarget, clientX: 200}) === 0,
        "split click on the left visible half activates pane A");
    check(context.getActiveComparePaneIndexFromEvent({target: paneTarget, clientX: 700}) === 1,
        "split click on the right visible half activates pane B");
}

function testSplitDividerDragDoesNotStartImagePan() {
    const {context, elements} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    context.toggleLightboxCompareSplit();
    const dividerTarget = {closest(selector) {
        return selector === "#lightbox-compare-divider" ? elements["lightbox-compare-divider"] : null;
    }};
    const event = {
        target: dividerTarget,
        currentTarget: elements["lightbox-compare"],
        pointerId: 1,
        clientX: 400,
        preventDefault() {},
    };
    context.startLightboxCompareSplitDrag(event);
    context.startLightboxPan(event);
    check(vm.runInContext("lightboxCompareSplitDragging === true && lightboxComparePanState === null", context),
        "split divider drag does not start compare image pan");
    context.endLightboxCompareSplitDrag(event);
}

function testSplitDividerKeyboardUpdatesPositionAndAria() {
    const {context, elements} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    context.toggleLightboxCompareSplit();
    const divider = elements["lightbox-compare-divider"];
    const preventDefault = () => {};
    context.handleLightboxCompareSplitKeydown({key: "ArrowRight", preventDefault});
    check(vm.runInContext("lightboxCompareSplitPosition === 52", context), "split divider ArrowRight moves by a small step");
    context.handleLightboxCompareSplitKeydown({key: "Home", preventDefault});
    check(vm.runInContext("lightboxCompareSplitPosition === 8", context), "split divider Home reaches the lower bound");
    context.handleLightboxCompareSplitKeydown({key: "End", preventDefault});
    check(vm.runInContext("lightboxCompareSplitPosition === 92", context), "split divider End reaches the upper bound");
    check(divider.getAttribute("aria-valuenow") === "92", "split divider keeps aria-valuenow synchronized");
}

function testLinkedResetAndReplacementKeepPaneZoomsEqual() {
    const {context} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    context.zoomComparePane(0, 0.2);
    context.resetLightboxZoom();
    check(vm.runInContext("lightboxCompareViewState[0].zoom === 1 && lightboxCompareViewState[1].zoom === 1", context),
        "linked reset returns both compare panes to 100 percent");
    context.zoomComparePane(0, 0.2);
    context.openStickyCompareLightbox();
    context.navigateStickyCompare(1);
    check(vm.runInContext("lightboxCompareViewState[0].zoom === lightboxCompareViewState[1].zoom", context),
        "linked candidate replacement preserves equal pane zoom state");
}

function testUnlinkedResetKeepsOtherPaneZoom() {
    const {context} = createRuntime();
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    context.setLightboxCompareSync(false);
    context.zoomComparePane(0, 0.2);
    context.zoomComparePane(1, 0.4);
    context.resetLightboxZoom();
    check(vm.runInContext("lightboxCompareViewState[0].zoom === 1.2 && lightboxCompareViewState[1].zoom === 1", context),
        "unlinked reset changes only the active compare pane");
}

function testStickyCompareSkipsInterleavedNonStillMedia() {
    const {context, items} = createRuntime();
    items.splice(0, items.length,
        {name: "a.png"},
        {name: "video.mp4", media_kind: "video"},
        {name: "b.png"},
        {name: "audio.mp3", media_kind: "audio"},
        {name: "c.png"});
    context.currentIndex = 0;
    context.openStickyCompareLightbox();
    check(vm.runInContext("lightboxCompareItems[0].name === 'a.png' && lightboxCompareItems[1].name === 'b.png'", context),
        "sticky compare chooses the next still candidate across mixed media");
    context.navigateStickyCompare(1);
    check(context.getActiveLightboxImage().name === "c.png", "sticky candidate walk skips interleaved video and audio");
    context.navigateStickyCompare(1);
    check(context.getActiveLightboxImage().name === "b.png", "sticky candidate walk wraps among still images only");
    check(context.currentIndex === 0, "mixed-media candidate walk preserves the originating grid anchor");
}

function testPairAdvanceSkipsInterleavedNonStillMedia() {
    const {context, items} = createRuntime();
    items.splice(0, items.length,
        {name: "a.png"},
        {name: "video.mp4", media_kind: "video"},
        {name: "b.png"},
        {name: "audio.mp3", media_kind: "audio"},
        {name: "c.png"});
    context.selectedImages.add("a.png");
    context.selectedImages.add("b.png");
    context.openCompareLightbox();
    context.advanceComparePair(1);
    check(vm.runInContext("lightboxCompareItems[0].name === 'b.png' && lightboxCompareItems[1].name === 'c.png'", context),
        "pair advance skips interleaved non-still media");
    context.advanceComparePair(1);
    check(vm.runInContext("lightboxCompareItems[0].name === 'c.png' && lightboxCompareItems[1].name === 'a.png'", context),
        "pair advance wraps over the still-image sequence");
    check(context.currentIndex === 0, "mixed-media pair advance preserves the originating grid anchor");
}

function testStickyCompareRefusesNonStillSingleLightbox() {
    const {context, items} = createRuntime();
    items[0].media_kind = "video";
    context.currentIndex = 0;
    const toasts = [];
    context.showToast = message => toasts.push(message);
    context.openStickyCompareLightbox();
    check(vm.runInContext("lightboxCompareMode === false", context), "non-still single lightbox does not enter compare mode");
    check(toasts.some(message => message.includes("Still images only")), "non-still compare refusal explains still-image requirement");
}

function testTypedVideoNavigationReleasesPlayerResource() {
    const {context, elements, items} = createRuntime();
    items[1].media_kind = "video";
    context.openLightbox(1);
    check(elements.lightbox.classList.contains("typed-media"), "video opens typed-media lightbox mode");
    check(elements["lightbox-video"].src.endsWith("/b.png"), "video player receives original media URL");
    check(elements["lightbox-video"].hidden === false, "video player is visible");
    context.navigate(1);
    check(elements["lightbox-video"].src === "", "navigating away releases video source");
    check(elements["lightbox-video"].paused === true, "navigating away pauses video playback");
}

function testTypedVideoAutoplaysLoopsAndTogglesBeforeNativeFocus() {
    const {context, elements, items} = createRuntime();
    const video = elements["lightbox-video"];
    items[1].media_kind = "video";

    context.openLightbox(1);
    check(video.autoplay === true, "video reflects the enabled autoplay preference");
    check(video.loop === true, "video reflects the enabled loop preference");
    check(video.playCalls === 1 && video.paused === false, "video starts without a native-control click");

    check(context.toggleLightboxVideoPlayback() === true, "visible video accepts app-level playback toggle");
    check(video.paused === true, "first app-level toggle pauses the video");
    check(context.toggleLightboxVideoPlayback() === true, "paused video accepts a second playback toggle");
    check(video.playCalls === 2 && video.paused === false, "second app-level toggle resumes the video");
}

function testTypedAudioCloseReleasesPlayerAndArtwork() {
    const {context, elements, items} = createRuntime();
    items[0].media_kind = "audio";
    context.openLightbox(0);
    check(elements["lightbox-audio-player"].src.endsWith("/a.png"), "audio player receives original media URL");
    check(elements["lightbox-audio-art"].src.includes("/thumb/"), "audio lightbox displays poster artwork");
    context.closeLightbox();
    check(elements["lightbox-audio-player"].src === "", "closing releases audio source");
    check(elements["lightbox-audio-art"].src === "", "closing releases audio artwork");
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
    await testWorkspaceSearchNavigationReanchorsAfterPageReorder();
    testStickyCandidateWalkPreservesGridAnchorAndOrder();
    testCompareSyncCanLinkAndUnlinkPaneZoom();
    testCompareSplitTogglesWithoutReloadingOriginals();
    testAdvanceComparePairMovesBothPanesWithoutChangingGridAnchor();
    testSplitHitTestingSelectsVisiblePaneByDividerPosition();
    testSplitDividerDragDoesNotStartImagePan();
    testSplitDividerKeyboardUpdatesPositionAndAria();
    testLinkedResetAndReplacementKeepPaneZoomsEqual();
    testUnlinkedResetKeepsOtherPaneZoom();
    testStickyCompareSkipsInterleavedNonStillMedia();
    testPairAdvanceSkipsInterleavedNonStillMedia();
    testStickyCompareRefusesNonStillSingleLightbox();
    await testCompletedNeighborPreloadsStayBoundedAndRetained();
    await testCompletedPreloadIsConsumedByNavigation();
    await testDecodeRejectionCommitsLoadedTarget();
    await testCompareEntryCancelsPendingSingleLoader();
    await testLoaderErrorPreservesVisibleImageAndClearsOwnership();
    await testResolvedPreloadsDetachEventHandlers();
    testIsLightboxOpenPendingReturnsFalseWhenNoPendingOpen();
    testIsLightboxOpenPendingReturnsTrueWhenPendingOpenExists();
    testPendingOpenCancelViaEscapePreservesNormalGridState();
    testTypedVideoNavigationReleasesPlayerResource();
    testTypedVideoAutoplaysLoopsAndTogglesBeforeNativeFocus();
    testTypedAudioCloseReleasesPlayerAndArtwork();
    const failed = details.filter(detail => !detail.pass).length;
    process.stdout.write(JSON.stringify({total: details.length, failed, details}));
    process.exitCode = failed === 0 ? 0 : 1;
})().catch(error => {
    process.stderr.write(String(error.stack || error));
    process.exitCode = 1;
});
