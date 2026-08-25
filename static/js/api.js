/* Ordered classic script.
 * Defines: API wrapper helpers for frontend route calls.
 * First-split wrapper inventory: feature files still keep direct fetch calls
 * where they intentionally preserve legacy raw Response handling, non-OK early
 * returns, or local catch behavior. Migrate callers one route family at a time
 * only after verifying each wrapper preserves the caller's response semantics.
 */
async function apiGetBatches() {
    const resp = await fetch(ccApiPath('/api/batches'));
    if (!resp.ok) throw new Error('batch request failed');
    return resp.json();
}

async function apiGetNativeSettings() {
    const resp = await fetch(ccApiPath('/api/settings'));
    if (!resp.ok) throw new Error('settings request failed');
    return resp.json();
}

async function apiSaveNativeSettings(body) {
    return apiPostJson('/api/settings', body);
}

async function apiGetImages(batch, folder, sort, order) {
    const resp = await fetch(ccApiPath(`/api/images/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}?sort=${encodeURIComponent(sort)}&order=${encodeURIComponent(order)}`));
    if (!resp.ok) throw new Error('images request failed');
    return resp.json();
}

async function apiGetFolderSnapshot(batch, folder, sort, order) {
    return fetch(ccApiPath(`/api/v2/folders/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}/snapshot?sort=${encodeURIComponent(sort)}&order=${encodeURIComponent(order)}`));
}

async function apiGetFolderPage(batch, folder, sort, order, revision, offset, limit) {
    return fetch(ccApiPath(`/api/v2/folders/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}/items?sort=${encodeURIComponent(sort)}&order=${encodeURIComponent(order)}&revision=${encodeURIComponent(revision)}&offset=${encodeURIComponent(offset)}&limit=${encodeURIComponent(limit)}`));
}

async function apiGetFolderItemIndex(batch, folder, sort, order, revision, name) {
    const params = new URLSearchParams({sort, order, revision, name});
    return fetch(ccApiPath(`/api/v2/folders/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}/lookup?${params.toString()}`));
}

async function apiPollFolderSnapshot(batch, folder, sort, order, revision) {
    return fetch(ccApiPath(`/api/v2/folders/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}/poll?sort=${encodeURIComponent(sort)}&order=${encodeURIComponent(order)}&revision=${encodeURIComponent(revision || '')}`));
}

async function apiPostJson(url, body) {
    return fetch(ccApiPath(url), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
}

async function apiSetActiveBatch(batch) {
    return apiPostJson('/api/active-batch', {batch: batch});
}

async function apiImportAll(batch) {
    return apiPostJson('/api/import-all', {batch: batch});
}

async function apiCreateBatch(name) {
    return apiPostJson('/api/batches', {name: name});
}

async function apiMoveBatch(batch, filenames, source, destination) {
    return apiPostJson('/api/move-batch', {batch, filenames, source, destination});
}

async function apiMoveImage(batch, filename, source, destination) {
    return apiPostJson('/api/move', {batch, filename, source, destination});
}

async function apiDeleteRejects(batch) {
    return fetch(ccApiPath(`/api/delete-rejects/${encodeURIComponent(batch)}`), {method: 'POST'});
}

async function apiGetUniversalFavorites() {
    const resp = await fetch(ccApiPath('/api/favorites'));
    if (!resp.ok) throw new Error('favorites request failed');
    return resp.json();
}

async function apiPublishExport(body) {
    return apiPostJson('/api/publish/export', body);
}

async function apiGetBatchPublic(batch) {
    const resp = await fetch(ccApiPath(`/api/public/${encodeURIComponent(batch)}`));
    if (!resp.ok) throw new Error('batch public request failed');
    return resp.json();
}

async function apiGetAllPublic() {
    const resp = await fetch(ccApiPath('/api/public'));
    if (!resp.ok) throw new Error('public request failed');
    return resp.json();
}

async function apiGetPublicDestinations(path = '') {
    const resp = await fetch(ccApiPath(`/api/public/destinations?path=${encodeURIComponent(path)}`));
    if (!resp.ok) throw new Error('public destinations request failed');
    return resp.json();
}

async function apiCopyPublic(destination, items) {
    return apiPostJson('/api/public/copy', {destination, items});
}

async function apiMovePublic(destination, items) {
    return apiPostJson('/api/public/move', {destination, items});
}

async function apiDeletePublic(items) {
    return apiPostJson('/api/public/delete', {items});
}

async function apiToggleUniversalFavorite(batch, filename) {
    return apiPostJson('/api/favorites', {batch, filename});
}

async function apiToggleBatchFavorite(batch, filename) {
    return apiPostJson(`/api/favorites/${encodeURIComponent(batch)}`, {filename});
}

async function apiGetPromptHistory(batch) {
    const url = batch
        ? ccApiPath(`/api/prompt-history/${encodeURIComponent(batch)}?check_stale=true`)
        : ccApiPath('/api/prompt-history');
    return fetch(url);
}

async function apiBuildPromptIndex(batch) {
    return fetch(ccApiPath(`/api/prompt-history/${encodeURIComponent(batch)}/build`), {method: 'POST'});
}

async function apiSearchMedia(query, options) {
    options = options || {};
    const params = new URLSearchParams({q: query || '', limit: String(options.limit || 200)});
    if (options.offset) params.set('offset', String(options.offset));
    if (options.snapshot) params.set('snapshot', options.snapshot);
    if (options.batch) params.set('batch', options.batch);
    if (options.folder) params.set('folder', options.folder);
    return fetch(ccApiPath('/api/search?' + params.toString()));
}

async function apiBuildMediaSearchIndex(batch) {
    return fetch(ccApiPath(`/api/search-index/${encodeURIComponent(batch)}/build`), {method: 'POST'});
}

async function apiGetImageMetadata(batch, folder, name) {
    const resp = await fetch(ccApiPath(`/api/image-metadata/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}/${encodeURIComponent(name)}`));
    if (!resp.ok) throw new Error(`metadata request failed (${resp.status})`);
    return resp.json();
}

async function apiPreviewAiElements(body) {
    return apiPostJson('/api/ai-curate/preview-elements', body);
}

async function apiSubmitAiJob(body) {
    return apiPostJson('/api/ai-curate/jobs', body);
}

async function apiGetAiJob(jobId) {
    return fetch(ccApiPath(`/api/ai-curate/jobs/${encodeURIComponent(jobId)}`));
}

async function apiCancelAiJob(jobId) {
    return fetch(ccApiPath(`/api/ai-curate/jobs/${encodeURIComponent(jobId)}/cancel`), {method: 'POST'});
}

async function apiGetAiRuns(batch) {
    return fetch(ccApiPath(`/api/ai-curate/batches/${encodeURIComponent(batch)}/runs`));
}

async function apiGetAiRun(batch, runId) {
    return fetch(ccApiPath(`/api/ai-curate/batches/${encodeURIComponent(batch)}/runs/${encodeURIComponent(runId)}`));
}

async function apiGetAiElementHistory(batch, limit = 10) {
    return fetch(ccApiPath(`/api/ai-curate/batches/${encodeURIComponent(batch)}/element-history?limit=${encodeURIComponent(limit)}`));
}
