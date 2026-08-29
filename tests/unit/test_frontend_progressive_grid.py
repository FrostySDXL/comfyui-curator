import re
import subprocess
from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_virtual_grid_constants_are_bounded_and_evidence_oriented() -> None:
    source = read_frontend_js()

    assert "const VIRTUAL_GRID_MAX_THUMBNAILS = 500;" in source
    assert "const VIRTUAL_GRID_OVERSCAN_ROWS = 2;" in source
    assert 0 < 500 < 30_000


def test_update_grid_keeps_full_canonical_list_and_renders_only_window() -> None:
    body = extract_function_body(read_frontend_js(), "function updateGrid()")

    assert "currentDisplayImages = displayImages;" in body
    assert "const startIndex = startRow * columns;" in body
    assert "VIRTUAL_GRID_MAX_THUMBNAILS / columns" in body
    assert "for (let index = startIndex; index < endIndex; index++)" in body
    assert "shell.style.height" in body
    assert "translateX(-50%) translateY" in body


def test_virtual_scroll_has_one_binding_and_one_raf_guard() -> None:
    source = read_frontend_js()
    bind = extract_function_body(source, "function _bindProgressiveGridScrollGrowth(content)")
    schedule = extract_function_body(source, "function _scheduleProgressiveGridGrowthCheck()")

    assert "_progressiveGridScrollBound" in bind
    assert "content.addEventListener('scroll', () =>" in bind
    assert "_virtualGridScrollIdleTimerId = setTimeout" in bind
    assert "_progressiveGridGrowthRafId !== null" in schedule
    assert schedule.count("requestAnimationFrame(") == 1
    assert "updateGrid();" in schedule


def test_context_placeholder_and_empty_paths_reset_progressive_lifecycle() -> None:
    source = read_frontend_js()
    context_key = extract_function_body(source, "function _getProgressiveGridContextKey()")
    placeholder = extract_function_body(
        source, "function showGridLoadingPlaceholders(batch, folder)"
    )
    update_grid = extract_function_body(source, "function updateGrid()")

    for state_name in (
        "currentBatch",
        "currentFolder",
        "favoritesFilterOn",
        "currentSort",
        "currentOrder",
    ):
        assert state_name in context_key
    assert "aiFilterMode" not in context_key
    assert "aiShowOverlays" not in context_key
    assert "activeAiFilter" not in context_key
    assert "_resetProgressiveGridLifecycle();" in placeholder
    assert "if (contextChanged) _resetProgressiveGridContext(nextContextKey);" in update_grid
    assert "_resetProgressiveGridLifecycle();" in update_grid

    context_reset = extract_function_body(source, "function _resetProgressiveGridContext(")
    lifecycle_reset = extract_function_body(source, "function _resetProgressiveGridLifecycle()")
    assert "cancelScheduledViewportLoads()" not in context_reset
    assert "cancelScheduledViewportLoads()" in lifecycle_reset


def test_native_shuffle_session_rotates_and_follows_every_revision_bound_request() -> None:
    source = read_frontend_js()
    context_key = extract_function_body(source, "function _getProgressiveGridContextKey()")
    set_sort = extract_function_body(source, "function setSort(")
    wait_snapshot = extract_function_body(source, "async function _waitForFolderSnapshot(")
    page = extract_function_body(source, "async function ensureFolderPageForIndex(")
    poll = extract_function_body(source, "async function pollForChanges()")
    lookup = extract_function_body(source, "async function openMediaSearchResult(")
    select_all = extract_function_body(source, "function selectAllDisplayedImages()")
    move_selected = extract_function_body(source, "async function moveSelected(")

    assert "let folderShuffleSeed = '';" in source
    assert "function resetFolderShuffleOrder()" in source
    assert "folderShuffleSeed" in context_key
    assert "resetFolderShuffleOrder();" in set_sort
    assert "folderShuffleSeed" in wait_snapshot
    assert "folderShuffleSeed" in page
    assert "folderShuffleSeed" in poll
    assert "folderShuffleSeed" in lookup
    assert "shuffleSeed: folderShuffleSeed" in select_all
    assert "shuffle_seed: serverSelection.shuffleSeed" in move_selected
    assert source.count("shuffle_seed") >= 5


def test_same_window_reconciliation_preserves_live_grid() -> None:
    body = extract_function_body(read_frontend_js(), "function updateGrid()")

    assert "const alreadyOrdered" in body
    assert "if (alreadyOrdered)" in body
    assert "unscheduleThumbnailLoad(element);" in body
    assert "grid.insertBefore(node, current);" in body


def test_reused_thumb_unschedules_stale_key_before_replacement_schedule() -> None:
    body = extract_function_body(
        read_frontend_js(), "function updateThumbElement(thumb, img, index)"
    )

    changed_key = body.split(
        "if (imageEl && imageEl.dataset.thumbnailCacheKey !== thumbnailCacheKey)", 1
    )[1]
    unschedule = changed_key.index("unscheduleThumbnailLoad(thumb)")
    assign_key = changed_key.index("imageEl.dataset.thumbnailCacheKey = thumbnailCacheKey;")
    schedule = changed_key.index("scheduleThumbnailLoad(thumb, imageSrc")
    assert unschedule < assign_key < schedule
    assert "if (imageEl.dataset.thumbnailCacheKey)" in changed_key[:assign_key]


def test_pooled_thumb_tracks_desired_and_decoded_keys_without_blanking() -> None:
    source = read_frontend_js()
    create_image = extract_function_body(source, "function createThumbImageElement()")
    mark_loaded = extract_function_body(source, "function markThumbnailLoaded(img)")
    update_thumb = extract_function_body(source, "function updateThumbElement(thumb, img, index)")

    assert "img.addEventListener('load', () => markThumbnailLoaded(img));" in create_image
    assert (
        "img.dataset.loadedThumbnailCacheKey = img.dataset.thumbnailCacheKey || '';" in mark_loaded
    )
    assert "img.classList.add('loaded');" in mark_loaded
    assert "imageEl.dataset.thumbnailCacheKey = thumbnailCacheKey;" in update_thumb
    assert "classList.remove('loaded')" not in update_thumb


def test_virtual_window_reconciliation_moves_only_changed_edge_nodes() -> None:
    source = read_frontend_js()
    body = extract_function_body(source, "function updateGrid()")

    assert "if (current !== node) grid.insertBefore(node, current);" in body
    assert "while (grid.children.length > renderedNodes.length)" in body
    assert "grid.removeChild(grid.lastElementChild);" in body


def test_continuous_scroll_defers_recycled_thumbnail_source_work() -> None:
    source = read_frontend_js()
    update_body = extract_function_body(source, "function updateThumbElement(thumb, img, index)")

    assert "let _virtualGridFastScrolling = false;" in source
    assert "_virtualGridScrollIdleTimerId = setTimeout" in source
    assert "}, 80);" in source
    assert "if (_virtualGridFastScrolling)" in update_body
    assert "thumb.dataset.pendingThumbnailCacheKey = thumbnailCacheKey;" in update_body


def test_grid_shell_columns_use_full_canonical_display_count() -> None:
    source = read_frontend_js()

    assert (
        "const displayCount = currentDisplayImages.length || "
        "grid.querySelectorAll('.thumb.loading-placeholder').length;"
    ) in source


def test_dynamic_benchmark_dispatches_production_scroll_event() -> None:
    benchmark = Path("scripts/benchmark_thumbnails.py").read_text(encoding="utf-8")

    assert "dynamic-traversal-growth-v1" in benchmark
    assert "content.dispatchEvent(new Event('scroll', {bubbles: true}));" in benchmark
    assert "dispatchEvent(new Event('scroll'" in benchmark


def test_content_scroller_disables_browser_scroll_anchoring() -> None:
    css = Path("static/css/grid.css").read_text(encoding="utf-8")
    rule = re.search(r"\.content\s*\{[^{}]*\}", css)
    assert rule is not None, ".content rule not found in grid.css"
    assert "overflow-anchor: none" in rule.group(0), (
        ".content rule must set overflow-anchor: none so browser scroll anchoring "
        "does not override the JS-restored scrollTop during a density switch"
    )


def test_density_switch_presets_shell_height_before_anchor_restore() -> None:
    source = read_frontend_js()
    set_density = extract_function_body(source, "function setGridDensity(density)")

    assert "function updateGridShellLayout(options = {})" in source
    assert "const skipAnchorRestore = options.skipAnchorRestore === true;" in source
    assert re.search(r"updateGridShellLayout\(\{\s*skipAnchorRestore:\s*true\s*\}\)", set_density)
    assert set_density.index("shell.style.height") < set_density.index(
        "_restoreGridAnchor(anchorIndex)"
    )


def test_folder_load_failure_finalizes_activity_and_renders_retry() -> None:
    source = read_frontend_js()

    assert "async function loadCurrentFolderImages(options = {}) {" in source
    assert "} catch (error) {" in source
    assert "console.warn('loadCurrentFolderImages failed:', error);" in source
    assert "function failFolderLoad(requestToken, activityId, errorText, detail) {" in source
    assert "function showFolderErrorState(message = {}) {" in source
    assert "function createGridErrorState(message = {}) {" in source
    fail = extract_function_body(source, "function failFolderLoad(")
    assert "setGridLoadingStatus(false)" in fail
    assert "activityComplete(activityId, 'failed'" in fail
    assert "showFolderErrorState({title: errorText, detail})" in fail
    assert "grid-retry" in source
    assert "Retry loading folder" in source
    assert "loadCurrentFolderImages();" in source


def test_public_folder_load_uses_distinct_title_and_count() -> None:
    source = read_frontend_js()
    public = source.split("async function loadBatchPublic(batch) {", 1)[1].split(
        "async function loadAllPublic", 1
    )[0]
    load = source.split("async function loadCurrentFolderImages(options = {}) {", 1)[1]

    assert "title: 'Load public view'" in public
    assert "scope: batch" in public
    assert "completed: images.length" in public
    assert "total: images.length" in public
    assert "loadBatchPublic(currentBatch)" in load


def test_native_paged_load_status_indicator() -> None:
    source = read_frontend_js()
    status = source.split("function updatePagedLoadStatus() {", 1)[1].split(
        "function setGridLoadingStatus", 1
    )[0]

    assert "Loaded ${loaded} of ${total}" in status
    assert "setGridLoadingStatus(true, `Loaded ${loaded} of ${total}`)" in status
    assert "setGridLoadingStatus(false)" in status
    assert "updatePagedLoadStatus()" in source


def test_progressive_grid_node_lifecycle() -> None:
    completed = subprocess.run(
        ["node", "tests/unit/progressive_grid_lifecycle_test.js"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    match = re.search(r"(\d+) assertions passed", completed.stdout)
    assert match is not None, completed.stdout
    assert int(match.group(1)) >= 15


def test_viewport_loader_guards_detail_updates_on_terminal_status() -> None:
    source = read_frontend_js()
    schedule = extract_function_body(source, "function scheduleThumbnailLoad(element")

    assert "activityGetLatest(`folder-view:${currentBatch}:${currentFolder}`)" in schedule
    assert "folderActivity.status === 'running'" in schedule
    assert "folderActivity.detail !== 'Loading visible thumbnails…'" in schedule
    assert "activityUpdate(folderActivity.id, {detail: 'Loading visible thumbnails…'})" in schedule


def test_folder_view_aggregates_thumbnail_failures_into_partial_activity() -> None:
    source = read_frontend_js()
    load_start = source.index("async function loadCurrentFolderImages(options = {})")
    load = source[load_start : load_start + 2000]
    complete = extract_function_body(source, "function _completeFolderViewActivity(activityId")
    failure = extract_function_body(source, "function _recordFolderViewThumbnailFailure()")
    recovery = extract_function_body(source, "function _recordFolderViewThumbnailRecovery()")
    mark_error = extract_function_body(source, "function markThumbnailError(img)")
    mark_loaded = extract_function_body(source, "function markThumbnailLoaded(img)")

    assert "_folderViewThumbFailures = 0;" in load
    assert "_folderViewActivityId = activityId;" in load
    assert "activityComplete(activityId, 'partial'" in complete
    assert "completed: _folderViewLoadedCount()" in complete
    assert "_folderViewThumbFailures += 1;" in failure
    assert "record.status === 'completed' || record.status === 'partial'" in failure
    assert "_folderViewThumbFailures -= 1;" in recovery
    assert "_folderViewThumbFailures === 0" in recovery
    assert "if (!wasFailed) _recordFolderViewThumbnailFailure();" in mark_error
    assert "_recordFolderViewThumbnailRecovery();" in mark_loaded
    assert "Retry available on the tiles" in source
