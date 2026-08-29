/* Ordered classic script.
 * Defines: startup initialization and intervals.
 */
initializeSidebarState();
initializeAiSidebarState();
initializeGridDensity();
initializeViewMenu();
initializeActionBarSafeArea();
initializeCompareCandidateTray();
_bindCustomSelectKeys();
_bindDelegatedEvents();
// Sync batch sort button highlights with stored preference
document.querySelectorAll('.batch-sort-btn').forEach(b => b.classList.toggle('active', b.dataset.bsort === batchSort));
setInterval(() => {
    pollForChanges().catch(() => { console.warn('pollForChanges failed'); });
}, 5000);
setInterval(() => {
    pollImportAvailability().catch(() => { console.warn('pollImportAvailability failed'); });
}, 1000);
setInterval(() => {
    pollNativeBatchSummaries().catch(() => { console.warn('pollNativeBatchSummaries failed'); });
}, 10000);
loadBatches();
pollImportAvailability();
loadMoveHistory();
