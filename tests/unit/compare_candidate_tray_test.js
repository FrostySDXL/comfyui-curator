/* Behavior harness for candidate ordering, mixed-media filtering, and tray launch. */
const fs = require('fs');
const selection = fs.readFileSync('static/js/selection.js', 'utf8');
const lightbox = fs.readFileSync('static/js/lightbox.js', 'utf8');
const orderStart = selection.indexOf('function syncCompareCandidateOrder()');
const orderEnd = selection.indexOf('function removeCompareCandidate(', orderStart);
const limitStart = selection.indexOf('function getVisibleCompareCandidates(');
const limitEnd = selection.indexOf('function syncCompareCandidateOrder(', limitStart);
const removeStart = selection.indexOf('function removeCompareCandidate(');
const removeEnd = selection.indexOf('function moveCompareCandidate(', removeStart);
const launchStart = selection.indexOf('function launchCompareCandidateTray()');
const launchEnd = selection.indexOf('function selectAllDisplayedImages(', launchStart);
const openStart = lightbox.indexOf('function openCompareLightbox(');
const openEnd = lightbox.indexOf('function openStickyCompareLightbox(', openStart);
if ([orderStart, orderEnd, limitStart, limitEnd, removeStart, removeEnd, launchStart, launchEnd, openStart, openEnd].some(i => i < 0)) {
    throw new Error('candidate tray runtime helpers not found');
}

let selectedImages = new Set(['a.png', 'b.png', 'c.png', 'clip.mp4']);
let compareCandidateOrder = ['c.png', 'a.png'];
const currentImages = [
    {name: 'a.png', media_kind: 'image'},
    {name: 'b.png', media_kind: 'image'},
    {name: 'clip.mp4', media_kind: 'video'},
    {name: 'c.png', media_kind: 'image'},
];
const getCurrentDisplayImages = () => currentImages;
const isStillReviewMedia = img => !img.media_kind || img.media_kind === 'image';
const COMPARE_CANDIDATE_VISIBLE_LIMIT = 6;
eval(selection.slice(limitStart, limitEnd));
const manyCandidates = Array.from({length: 30}, (_, index) => ({name: `candidate-${index}.png`}));
if (getVisibleCompareCandidates(manyCandidates).length !== 6) throw new Error('tray rendered more than six candidates');
eval(selection.slice(orderStart, orderEnd));

let ordered = syncCompareCandidateOrder();
if (ordered.map(img => img.name).join(',') !== 'c.png,a.png,b.png') throw new Error('order did not preserve and append candidates');
if (selectedImages.size !== 4) throw new Error('ordering mutated canonical selection');

let updateVisuals = 0;
let updateBar = 0;
const updateSelectionVisuals = () => { updateVisuals += 1; };
const updateActionBar = () => { updateBar += 1; };
const getImageDisplayIndexByName = name => currentImages.findIndex(img => img.name === name);
eval(selection.slice(removeStart, removeEnd));
removeCompareCandidate('a.png');
if (selectedImages.has('a.png') || updateVisuals !== 1 || updateBar !== 1) throw new Error('remove did not update selection');

let launchFocus = {focus() { this.focused = true; }, focused: false};
const elements = {
    'compare-candidate-tray': {hidden: false},
    'compare-candidate-list': {replaceChildren() {}},
    'compare-candidate-status': {textContent: ''},
    'compare-candidate-launch': {},
};
const document = {getElementById(id) { return elements[id] || null; }};
const getImageBatchAndFolder = () => ({batch: 'batch', folder: 'inbox'});
const ccThumbUrl = () => '/thumb';
const renderCompareCandidateTray = () => {};
const openCompareLightboxWithSelection = (pair, focus) => { globalThis.openedPair = pair; globalThis.openedFocus = focus; };
eval(selection.slice(launchStart, launchEnd));
launchCompareCandidateTray();
if (openedPair.map(img => img.name).join(',') !== 'c.png,b.png') throw new Error('launch did not use first two ordered candidates');
if (openedFocus !== elements['compare-candidate-launch']) throw new Error('launch focus target missing');
if (selectedImages.has('clip.mp4') !== true) throw new Error('mixed media selection was changed');

process.stdout.write(JSON.stringify({passed: 6, failed: 0}));
