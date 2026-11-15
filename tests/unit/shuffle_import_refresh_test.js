'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const controls = {
    'active-batch-select': {value: 'one'},
    'pending-count': {textContent: '1'},
    'img-count': {textContent: ''},
    lightbox: {classList: {contains: () => false}},
};
const document = {getElementById: id => controls[id], querySelector: () => null};
const ctx = vm.createContext({
    document, console, window: {addEventListener: () => {}}, CURATOR_NATIVE: false, currentBatch: 'one', currentFolder: 'inbox',
    currentSort: 'shuffle', currentOrder: 'asc', images: [{name: 'b', size: 1}, {name: 'a', size: 1}],
    allCounts: {one: {inbox: 3}}, PAGED_FOLDER_THRESHOLD: 2000, folderSnapshot: null,
    selectedImages: new Set(['a']), serverSelection: null, viewTransitionToken: 1,
    isDraggingImages: false, isSidebarResizing: false, isAiSidebarResizing: false,
    isVirtualCollectionView: () => false, isPublicView: () => false, getViewScopeKey: () => 'one/inbox',
    activityRegister: () => {}, activityUpdate: () => {}, activityComplete: () => {}, showToast: () => {},
    ccApiPath: path => path, aiLatestRun: null, drawCount: 0,
    updateGrid: () => { ctx.drawCount++; },
    fetch: async url => ({ok: true, json: async () => url.includes('import-all')
        ? {count: 1, pending_count: 0} : url.includes('/api/images/')
            ? [{name: 'new', size: 1}, {name: 'a', size: 1}, {name: 'b', size: 1}] : {runs: []}}),
});
for (const file of ['static/js/batches.js', 'static/js/polling.js']) {
    vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
}
vm.runInContext('loadBatches = async () => {}; pollImportAvailability = async () => {}', ctx);
(async () => {
    await vm.runInContext('importAll()', ctx);
    assert.deepEqual(ctx.images.map(x => x.name), ['b', 'a'], 'selection defers refresh');
    ctx.selectedImages.clear();
    await vm.runInContext('pollForChanges()', ctx);
    assert.deepEqual(ctx.images.map(x => x.name), ['b', 'a', 'new'], 'append while preserving shuffle order');
    assert.equal(ctx.drawCount, 1);
    await vm.runInContext('pollForChanges()', ctx);
    assert.equal(ctx.drawCount, 1, 'ordinary shuffle polling does not reshuffle');

    // A manual import pushes a legacy folder over the paging threshold. Hold
    // the real loader at its snapshot boundary while another poll and selection
    // race it; only a later idle, owned attempt may replace the legacy grid.
    vm.runInContext(fs.readFileSync('static/js/grid.js', 'utf8'), ctx, {filename: 'static/js/grid.js'});
    ctx.currentSort = 'date';
    ctx.images = [{name: 'old', size: 1}];
    ctx.allCounts = {one: {inbox: 1999}};
    ctx.folderSnapshot = null;
    ctx.folderRequestToken = 0;
    ctx.folderPageInflight = new Map();
    ctx.displayIndexByName = new Map();
    ctx.currentDisplayImages = ctx.images;
    ctx.FOLDER_PAGE_SIZE = 256;
    ctx.folderShuffleSeed = '';
    ctx.activityAttemptId = () => 'load';
    ctx.activityRemove = () => {};
    ctx.setGridLoadingStatus = () => {};
    ctx.updateImageCountLabel = () => {};
    ctx.updatePagedLoadStatus = () => {};
    let pageAttempts = 0;
    ctx.apiGetFolderPage = async () => {
        pageAttempts++;
        if (pageAttempts === 1) return {ok: false};
        return {ok: true, json: async () => ({revision: 'r1', items: [{index: 0, name: 'new', size: 1}]})};
    };
    let releaseSnapshot, started;
    const snapshotStarted = new Promise(resolve => { started = resolve; });
    let attempts = 0;
    ctx.waitSnapshot = async () => {
        attempts++;
        if (attempts === 1) { started(); await new Promise(resolve => { releaseSnapshot = resolve; }); }
        return {revision: 'r1', count: 2000};
    };
    vm.runInContext(`
        loadBatches = async () => { allCounts.one.inbox = 2000; };
        _waitForFolderSnapshot = waitSnapshot;
        requiresMaterializedNativeFolder = () => false;
        updateGrid = () => { drawCount++; };
        _completeFolderViewActivity = () => {};
    `, ctx);
    const firstImport = vm.runInContext('importAll()', ctx);
    await snapshotStarted;
    await vm.runInContext('pollForChanges()', ctx);
    assert.equal(attempts, 1, 'concurrent polls share one transition');
    ctx.selectedImages.add('old');
    releaseSnapshot();
    await firstImport;
    assert.deepEqual(ctx.images.map(x => x.name), ['old'], 'late snapshot cannot replace selection');
    assert.equal(ctx.folderSnapshot, null);
    ctx.selectedImages.clear();
    await vm.runInContext('pollForChanges()', ctx);
    assert.equal(attempts, 2, 'cancelled transition retries');
    assert.deepEqual(ctx.images.map(x => x.name), ['old'], 'failed page leaves legacy view intact');
    assert.equal(ctx.folderSnapshot, null);
    assert.notEqual(vm.runInContext('pendingImportRefresh', ctx), null, 'failure retains pending refresh');
    await vm.runInContext('pollForChanges()', ctx);
    assert.equal(attempts, 3, 'failed page retries');
    assert.equal(ctx.folderSnapshot.revision, 'r1');
    assert.equal(ctx.images.length, 2000);
    assert.equal(ctx.images[0].name, 'new');
    assert.equal(vm.runInContext('pendingImportRefresh', ctx), null, 'successful transition clears pending refresh');

    // Crossing the threshold in Shuffle switches to the snapshot's canonical
    // indexed order; the newly imported item and lookup must agree with it.
    ctx.currentSort = 'shuffle';
    ctx.images = [{name: 'old-a', size: 1}, {name: 'old-b', size: 1}];
    ctx.folderSnapshot = null;
    ctx.folderShuffleSeed = 'shuffle-seed';
    ctx.waitSnapshot = async () => ({revision: 'shuffle-r', count: 2000});
    let pageArgs;
    ctx.apiGetFolderPage = async (...args) => {
        pageArgs = args;
        return {ok: true, json: async () => ({revision: 'shuffle-r', items: [
            {index: 0, name: 'old-b', size: 1},
            {index: 1, name: 'imported', size: 1},
            {index: 2, name: 'old-a', size: 1},
        ]})};
    };
    vm.runInContext('_waitForFolderSnapshot = waitSnapshot', ctx);
    await vm.runInContext('importAll()', ctx);
    assert.equal(ctx.folderSnapshot.revision, 'shuffle-r');
    assert.deepEqual(Array.from(ctx.images.slice(0, 3), x => x.name), ['old-b', 'imported', 'old-a']);
    assert.equal(ctx.displayIndexByName.get('imported'), 1, 'new media resolves to canonical page index');
    assert.equal(ctx.currentDisplayImages[1].name, 'imported');
    assert.equal(pageArgs[2], 'shuffle');
    assert.equal(pageArgs[4], 'shuffle-r');
    assert.equal(pageArgs[7], 'shuffle-seed');
    assert.equal(vm.runInContext('pendingImportRefresh', ctx), null);

    ctx.images = [{name: 'old', size: 1}];
    ctx.folderSnapshot = null;
    ctx.getViewScopeKey = () => `${ctx.currentBatch}/${ctx.currentFolder}`;
    let releaseOld, oldStarted;
    const oldReady = new Promise(resolve => { oldStarted = resolve; });
    ctx.waitSnapshot = async () => {
        oldStarted();
        await new Promise(resolve => { releaseOld = resolve; });
        return {revision: 'old-revision', count: 2000};
    };
    vm.runInContext('_waitForFolderSnapshot = waitSnapshot', ctx);
    const staleImport = vm.runInContext('importAll()', ctx);
    await oldReady;
    ctx.currentBatch = 'two';
    ctx.viewTransitionToken++;
    ctx.folderRequestToken++;
    ctx.images = [{name: 'new-view', size: 1}];
    releaseOld();
    await staleImport;
    assert.deepEqual(ctx.images.map(x => x.name), ['new-view'], 'late threshold response cannot reclaim a newer view');
    assert.equal(ctx.folderSnapshot, null);
    console.log('shuffle import refresh and threshold transition passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
