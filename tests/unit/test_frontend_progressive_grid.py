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
    update_thumb = extract_function_body(source, "function updateThumbElement(thumb, img, index)")

    assert (
        "img.dataset.loadedThumbnailCacheKey = img.dataset.thumbnailCacheKey || '';" in create_image
    )
    assert "imageEl.dataset.thumbnailCacheKey = thumbnailCacheKey;" in update_thumb
    assert "classList.remove('loaded')" not in source


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
    body = extract_function_body(read_frontend_js(), "function updateGridShellLayout()")

    assert (
        "const displayCount = currentDisplayImages.length || "
        "grid.querySelectorAll('.thumb.loading-placeholder').length;"
    ) in body


def test_dynamic_benchmark_dispatches_production_scroll_event() -> None:
    benchmark = Path("scripts/benchmark_thumbnails.py").read_text(encoding="utf-8")

    assert "dynamic-traversal-growth-v1" in benchmark
    assert "content.dispatchEvent(new Event('scroll', {bubbles: true}));" in benchmark
    assert "dispatchEvent(new Event('scroll'" in benchmark


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
