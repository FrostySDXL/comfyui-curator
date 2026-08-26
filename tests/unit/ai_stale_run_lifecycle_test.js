/* Behavior harness: a stale compare response must not mutate the diff panel. */
const fs = require('fs');
const source = fs.readFileSync('static/js/ai-history.js', 'utf8');
const start = source.indexOf('async function aiShowRunDiff(');
const end = source.indexOf('function aiSyncRunSelects()', start);
if (start < 0 || end < 0) throw new Error('run diff helper not found');

const diffHtml = {innerHTML: '', classList: {remove() {}, add() {}}, style: {display: ''}};
const document = {getElementById(id) { return id === 'ai-run-diff' ? diffHtml : null; }};
let aiCompareRunId = 'previous';
let aiRunIds = ['current', 'previous'];
let aiActiveRun = {run_id: 'current', results: []};
let aiRunDetails = {};
let currentBatch = 'batch-a';
let stale = false;
const aiGetPreviousRunId = () => 'previous';
const aiFetchRun = async () => {
    await Promise.resolve();
    stale = true;
    return {run_id: 'previous', results: []};
};
const aiSyncCompareSelect = () => {};
const _escapeHtml = value => String(value || '');
const formatAiRunTimestamp = () => 'now';
const formatAiRunLabel = run => run.run_id;

eval(source.slice(start, end));

aiShowRunDiff(aiActiveRun, () => !stale).then(() => {
    if (diffHtml.innerHTML !== '') throw new Error('stale diff response mutated the panel');
    const renderStart = source.indexOf('async function aiRenderCurrentRunUi(');
    const renderEnd = source.indexOf('async function aiRefreshRunData(', renderStart);
    if (renderStart < 0 || renderEnd < 0) throw new Error('current-run renderer not found');
    let headerUpdates = 0;
    let thresholdUpdates = 0;
    aiRunDataRequestToken = 1;
    stale = false;
    aiThresholdScopeKey = null;
    aiFilterMode = 'all';
    aiShowRunDiff = async (_run, isCurrent) => {
        aiRunDataRequestToken = 2;
        if (!isCurrent()) return;
    };
    var aiShowRunSummary = () => {};
    var aiShowHeaderControls = () => { headerUpdates += 1; };
    var aiUpdateRunHistoryUi = () => {};
    var aiRenderThresholdPreview = () => { thresholdUpdates += 1; };
    var aiRenderImageInspector = () => {};
    var aiThresholdScopeKey = null;
    var aiThresholdValue = 70;
    var aiAppliedThreshold = null;
    var aiFilterMode = 'all';
    const aiRenderSource = source.slice(renderStart, renderEnd);
    eval(aiRenderSource);
    aiRenderCurrentRunUi(1, 'batch-a', 'current').then(result => {
        if (result !== false || headerUpdates !== 0 || thresholdUpdates !== 0) {
            throw new Error('stale current-run renderer mutated the UI');
        }
        process.stdout.write(JSON.stringify({passed: 1, failed: 0}));
    });
});
