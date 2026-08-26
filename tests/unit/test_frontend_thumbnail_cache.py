import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_thumbnail_grid_uses_blob_url_cache():
    """Thumbnail src assignment goes through the app-owned blob cache."""

    source = read_frontend_js()

    assert "const thumbnailBlobUrlCache = new Map();" in source
    assert "const thumbnailBlobInflight = new Map();" in source
    assert "function getThumbnailCacheKey(imageSrc, img)" in source
    assert "async function resolveThumbnailBlobUrl(imageSrc, cacheKey" in source
    assert "function setThumbnailImageSrc(imageEl, imageSrc, cacheKey" in source
    assert "setThumbnailImageSrc(imgEl," in source
    assert "imageEl.src = imageSrc;" not in source


def test_thumbnail_identity_uses_mtime_for_same_name_same_size_replacements():
    source = read_frontend_js()
    cache_key = extract_function_body(source, "function getThumbnailCacheKey(imageSrc, img)")
    update_thumb = extract_function_body(source, "function updateThumbElement(thumb, img, index)")

    assert "img.mtime || img.modified_at || img.size || 0" in cache_key
    assert (
        "const version = encodeURIComponent(String(img.mtime || img.modified_at || img.size || 0));"
        in update_thumb
    )
    assert "v=${version}" in update_thumb
    assert (
        "pagedFolderMode"
        not in update_thumb.split("const thumbnailCacheKey", 1)[0].split("const imageSrcBase", 1)[1]
    )


def test_stage2_cache_metadata_infrastructure():
    """Stage 2 metadata-aware LRU cache infrastructure is present."""

    source = read_frontend_js()

    assert "const _thumbnailMetadata = new Map();" in source
    assert "const _inflightMetadataPriority = new Map();" in source
    assert "let _lruTouchNext = 0;" in source
    assert "let _realBatchCurrent = null;" in source
    assert "let _realBatchPrev = null;" in source
    assert "function _touchCacheEntry(cacheKey)" in source
    assert "function _updateCacheMetadata(cacheKey, meta)" in source
    assert "function _evictIfNeeded()" in source
    assert "function _mergeInflightMetadata(cacheKey, meta)" in source
    assert "function _takeInflightMetadata(cacheKey)" in source
    assert "function _updateRealBatchTracking(newBatch)" in source
    assert "function _resolveSourceBatch(img)" in source
    assert "function _getScopeClass(scopeBatch)" in source
    assert "function _getPriorityClass(priority)" in source


def test_stage2_eviction_uses_scope_aware_ranking():
    """Eviction ranking uses scope class, priority class, and LRU tie-break."""

    source = read_frontend_js()
    evict_body = None
    try:
        from tests.unit.frontend_source import extract_function_body

        evict_body = extract_function_body(source, "function _evictIfNeeded(")
    except AssertionError:
        pass

    assert evict_body is not None, "Cannot extract _evictIfNeeded body"
    assert "_getScopeClass" in evict_body
    assert "_getPriorityClass" in evict_body
    assert "_lruTouch" in evict_body
    assert "URL.revokeObjectURL(" in evict_body


def test_stage2_beforeunload_cleans_metadata():
    """beforeunload handler cleans up Stage 2 metadata maps."""

    source = read_frontend_js()
    assert "_thumbnailMetadata.clear()" in source
    assert "_inflightMetadataPriority.clear()" in source


def test_stage2_resolve_touches_lru_on_hit():
    """resolveThumbnailBlobUrl calls _touchCacheEntry on cache hit."""

    source = read_frontend_js()
    try:
        from tests.unit.frontend_source import extract_function_body

        resolve_body = extract_function_body(source, "async function resolveThumbnailBlobUrl(")
    except AssertionError:
        resolve_body = ""

    assert "_touchCacheEntry(cacheKey)" in resolve_body, (
        "resolveThumbnailBlobUrl must touch LRU on cache hit"
    )
    assert "_mergeInflightMetadata(cacheKey, meta)" in resolve_body, (
        "resolveThumbnailBlobUrl must merge inflight metadata for pending requests"
    )
    assert "_takeInflightMetadata(cacheKey)" in resolve_body, (
        "resolveThumbnailBlobUrl must take inflight metadata on fetch completion"
    )


def test_stage2_assign_touches_lru_on_hit():
    """assignThumbnailSrcIfCached calls _touchCacheEntry on cache hit."""

    source = read_frontend_js()
    try:
        from tests.unit.frontend_source import extract_function_body

        assign_body = extract_function_body(source, "function assignThumbnailSrcIfCached(")
    except AssertionError:
        assign_body = ""

    assert "_touchCacheEntry(cacheKey)" in assign_body, (
        "assignThumbnailSrcIfCached must touch LRU on cache hit"
    )
    assert "_updateCacheMetadata(cacheKey, meta)" in assign_body, (
        "assignThumbnailSrcIfCached must update metadata on cache hit"
    )


def test_stage2_update_thumb_passes_scope_to_schedule():
    """updateThumbElement passes resolved source batch to scheduleThumbnailLoad."""

    source = read_frontend_js()
    try:
        from tests.unit.frontend_source import extract_function_body

        update_body = extract_function_body(source, "function updateThumbElement(")
    except AssertionError:
        update_body = ""

    assert "scheduleThumbnailLoad(thumb, imageSrc, thumbnailCacheKey" in update_body, (
        "updateThumbElement must delegate to scheduleThumbnailLoad"
    )
    assert "_resolveSourceBatch(img)" in update_body, (
        "updateThumbElement must use _resolveSourceBatch(img) for scope resolution"
    )


def test_stage2_batch_tracking_integration():
    """_updateRealBatchTracking is called from selectBatch for real batches."""

    source = read_frontend_js()
    try:
        from tests.unit.frontend_source import extract_function_body

        select_body = extract_function_body(source, "function selectBatch(")
    except AssertionError:
        select_body = ""

    assert "_updateRealBatchTracking(batch)" in select_body, (
        "selectBatch must call _updateRealBatchTracking for real batch changes"
    )
    assert "typeof _updateRealBatchTracking === 'function'" in select_body, (
        "selectBatch must guard _updateRealBatchTracking with typeof check"
    )


def test_stage2_start_viewport_load_passes_meta():
    """_startViewportLoad passes priority and scopeBatch metadata to cache."""

    source = read_frontend_js()
    try:
        from tests.unit.frontend_source import extract_function_body

        start_body = extract_function_body(source, "function _startViewportLoad(")
    except AssertionError:
        start_body = ""

    assert "meta = { priority: info.priority, scopeBatch:" in start_body, (
        "_startViewportLoad must build metadata object from info"
    )
    assert "assignThumbnailSrcIfCached(imgEl, info.imageSrc, info.cacheKey, meta)" in start_body, (
        "_startViewportLoad must pass meta to assignThumbnailSrcIfCached"
    )
    assert "setThumbnailImageSrc(imgEl, info.imageSrc, info.cacheKey, meta)" in start_body, (
        "_startViewportLoad must pass meta to setThumbnailImageSrc"
    )


def test_stage2_schedule_accepts_priority_and_scope():
    """scheduleThumbnailLoad accepts priority, scope, and optional retry options."""

    source = read_frontend_js()
    signature = (
        "function scheduleThumbnailLoad(element, imageSrc, cacheKey, priority, scopeBatch, options)"
    )
    assert signature in source, "scheduleThumbnailLoad must accept optional retry options"
    assert "priority" in signature and "scopeBatch" in signature


def test_thumbnail_cache_policy_node():
    """Deterministic Node-executed Stage 2 cache-policy test.
    Verifies LRU refresh, scope/priority eviction, inflight promotion
    end-to-end, real/virtual batch scope resolution, batch tracking
    input contract, and single-LRU-bump per hit."""

    node_exe = "node"
    script_path = str(Path("tests/unit/thumbnail_cache_policy_test.js"))
    try:
        result = subprocess.run(
            [node_exe, script_path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path.cwd()),
        )
    except FileNotFoundError:
        pytest.skip("node executable not found")
    except subprocess.TimeoutExpired:
        pytest.fail("Node cache policy test timed out after 60s")

    stderr = result.stderr.strip()
    if stderr:
        print(f"Node cache policy test stderr:\n{stderr}", file=sys.stderr)

    try:
        report = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(
            f"Node cache policy test produced invalid JSON.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{stderr}"
        )

    failures = [d for d in report["details"] if not d["pass"]]
    if failures:
        fail_msgs = "\n".join(f"  - {d['message']}" for d in failures)
        pytest.fail(
            f"Node cache policy test: {report['failed']}/{report['total']} failed:\n{fail_msgs}"
        )

    assert report["failed"] == 0, f"Expected 0 failures, got {report['failed']}/{report['total']}"
