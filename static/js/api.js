/* Ordered classic script.
 * Defines: API wrapper helpers for frontend route calls.
 * First-split wrapper inventory: feature files still keep direct fetch calls
 * where they intentionally preserve legacy raw Response handling, non-OK early
 * returns, or local catch behavior. Migrate callers one route family at a time
 * only after verifying each wrapper preserves the caller's response semantics.
 */
async function apiGetBatches() {
    const resp = await fetch('/api/batches');
    if (!resp.ok) throw new Error('batch request failed');
    return resp.json();
}

async function apiGetImages(batch, folder, sort, order) {
    const resp = await fetch(`/api/images/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}?sort=${encodeURIComponent(sort)}&order=${encodeURIComponent(order)}`);
    if (!resp.ok) throw new Error('images request failed');
    return resp.json();
}

async function apiPostJson(url, body) {
    return fetch(url, {
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
    return fetch(`/api/delete-rejects/${encodeURIComponent(batch)}`, {method: 'POST'});
}

async function apiGetUniversalFavorites() {
    const resp = await fetch('/api/favorites');
    if (!resp.ok) throw new Error('favorites request failed');
    return resp.json();
}

async function apiToggleUniversalFavorite(batch, filename) {
    return apiPostJson('/api/favorites', {batch, filename});
}

async function apiToggleBatchFavorite(batch, filename) {
    return apiPostJson(`/api/favorites/${encodeURIComponent(batch)}`, {filename});
}

async function apiGetPromptHistory(batch) {
    const url = batch
        ? `/api/prompt-history/${encodeURIComponent(batch)}?check_stale=true`
        : '/api/prompt-history';
    return fetch(url);
}

async function apiBuildPromptIndex(batch) {
    return fetch(`/api/prompt-history/${encodeURIComponent(batch)}/build`, {method: 'POST'});
}

async function apiGetImageMetadata(batch, folder, name) {
    const resp = await fetch(`/api/image-metadata/${encodeURIComponent(batch)}/${encodeURIComponent(folder)}/${encodeURIComponent(name)}`);
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
    return fetch(`/api/ai-curate/jobs/${encodeURIComponent(jobId)}`);
}

async function apiCancelAiJob(jobId) {
    return fetch(`/api/ai-curate/jobs/${encodeURIComponent(jobId)}/cancel`, {method: 'POST'});
}

async function apiGetAiRuns(batch) {
    return fetch(`/api/ai-curate/batches/${encodeURIComponent(batch)}/runs`);
}

async function apiGetAiRun(batch, runId) {
    return fetch(`/api/ai-curate/batches/${encodeURIComponent(batch)}/runs/${encodeURIComponent(runId)}`);
}

async function apiGetAiElementHistory(batch, limit = 10) {
    return fetch(`/api/ai-curate/batches/${encodeURIComponent(batch)}/element-history?limit=${encodeURIComponent(limit)}`);
}
