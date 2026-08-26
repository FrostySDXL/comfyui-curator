/* Behavior harness for the pure AI threshold classification helper. */
const fs = require('fs');
const source = fs.readFileSync('static/js/ai-overlays.js', 'utf8');
const start = source.indexOf('function aiGetNormalizedScore(');
const end = source.indexOf('function aiGetImageScore(');
if (start < 0 || end < 0) throw new Error('threshold helpers not found');
var aiActiveRun = null;
var aiThresholdValue = 70;
var aiAppliedThreshold = null;
var aiFilterMode = 'all';
var aiShowOverlays = false;
eval(source.slice(start, end));

const result = aiBuildThresholdPreview([
    {filename: 'high.png', score: 9, total: 10, failed: false},
    {filename: 'low.png', normalized_score: 40, failed: false},
    {filename: 'broken.png', score: -1, failed: true, error_message: 'timeout'},
    {filename: 'pending.png', score: -1, total: 0, failed: false},
], 70);

const assertions = [
    ['atOrAbove', result.atOrAbove === 1],
    ['below', result.below === 1],
    ['failed', result.failed === 1],
    ['unscored', result.unscored === 1],
    ['range min', result.range.min === 40],
    ['range max', result.range.max === 90],
    ['cutoff', result.cutoff === 70],
    ['scored count', result.scored === 2],
];

const thresholdInput = {value: '70'};
const thresholdStatus = {textContent: ''};
const thresholdPanel = {
    hidden: false,
    classList: {
        classes: new Set(),
        toggle(name, force) {
            if (force === undefined ? !this.classes.has(name) : force) this.classes.add(name);
            else this.classes.delete(name);
        },
        contains(name) { return this.classes.has(name); },
    },
};
const thresholdApply = {disabled: false};
const filterSelect = {value: 'all', options: [{value: 'all'}, {value: 'threshold'}]};
const overlayToggle = {checked: false};
const document = {getElementById(id) {
    return {
        'ai-score-threshold': thresholdInput,
        'ai-threshold-preview-status': thresholdStatus,
        'ai-threshold-preview': thresholdPanel,
        'ai-threshold-apply': thresholdApply,
        'ai-filter-mode': filterSelect,
        'ai-overlay-toggle': overlayToggle,
    }[id] || null;
}};
aiActiveRun = {results: [
    {filename: 'failed.png', failed: true},
    {filename: 'unknown.png', failed: false, score: -1, total: 0},
]};
let gridRefreshes = 0;
aiRefreshFilteredGrid = () => { gridRefreshes += 1; };
aiRenderThresholdPreview(aiActiveRun);
assertions.push(['no scored copy', thresholdStatus.textContent.includes('No scored images')]);
assertions.push(['no scored apply disabled', thresholdApply.disabled === true]);
aiApplyThresholdFilter();
assertions.push(['no scored apply no-op', aiFilterMode === 'all' && gridRefreshes === 0]);
aiActiveRun = {results: [
    {filename: 'high.png', normalized_score: 90, failed: false},
    {filename: 'low.png', normalized_score: 40, failed: false},
    {filename: 'broken.png', failed: true},
    {filename: 'pending.png', failed: false, score: -1, total: 0},
]};
aiRenderThresholdPreview(aiActiveRun);
assertions.push(['scored cutoff percent copy', thresholdStatus.textContent.includes('At or above 70%')]);
assertions.push(['scored range percent copy', thresholdStatus.textContent.includes('40%–90%')]);
assertions.push(['scored apply enabled', thresholdApply.disabled === false]);
thresholdInput.value = '80';
aiApplyThresholdFilter();
assertions.push(['successful apply sets threshold mode', aiFilterMode === 'threshold']);
assertions.push(['successful apply refreshes grid', gridRefreshes === 1]);
assertions.push(['successful apply marks preview', thresholdPanel.classList.contains('is-applied')]);
aiClearThresholdFilter();
assertions.push(['clear restores all mode', aiFilterMode === 'all' && filterSelect.value === 'all']);
assertions.push(['clear removes applied marker', !thresholdPanel.classList.contains('is-applied')]);

const historySource = fs.readFileSync('static/js/ai-history.js', 'utf8');
const failureStart = historySource.indexOf('function aiGetFailureDisplayData(');
const failureEnd = historySource.indexOf('function aiGetRunDisplayStatus(', failureStart);
if (failureStart < 0 || failureEnd < 0) throw new Error('failure display helper not found');
var AI_FAILURE_DETAIL_LIMIT = 25;
eval(historySource.slice(failureStart, failureEnd));
const failureData = aiGetFailureDisplayData(Array.from({length: 30}, (_, i) => ({filename: `failed-${i}.png`, failed: true})));
assertions.push(['failure visible limit', failureData.visible.length === 25]);
assertions.push(['failure hidden count', failureData.hiddenCount === 5]);

const jobSource = fs.readFileSync('static/js/ai-job.js', 'utf8');
const statusStart = jobSource.indexOf('function aiGetJobStatusCopy(');
const statusEnd = jobSource.indexOf('function aiShowJobStatus(', statusStart);
if (statusStart < 0 || statusEnd < 0) throw new Error('job status helper not found');
eval(jobSource.slice(statusStart, statusEnd));
assertions.push(['partial status', aiGetJobStatusCopy({status: 'completed', totals: {scored: 4, failed: 2}})[0] === 'Completed with failures']);
assertions.push(['wholly failed status', aiGetJobStatusCopy({status: 'completed', totals: {scored: 0, failed: 2}})[0] === 'Failed']);
const failed = assertions.filter(([, pass]) => !pass);
if (failed.length) {
    throw new Error(`threshold harness failed: ${failed.map(([name]) => name).join(', ')}`);
}
process.stdout.write(JSON.stringify({passed: assertions.length, failed: 0}));
