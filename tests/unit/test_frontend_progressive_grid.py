import re
import subprocess
from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_progressive_grid_constants_are_bounded_and_evidence_oriented() -> None:
    source = read_frontend_js()

    assert "const PROGRESSIVE_GRID_INITIAL_LIMIT = 120;" in source
    assert "const PROGRESSIVE_GRID_APPEND_CHUNK = 120;" in source
    assert "const PROGRESSIVE_GRID_NEAR_END_PX = 800;" in source
    assert 0 < 120 < 2000


def test_update_grid_keeps_full_canonical_list_and_renders_only_prefix() -> None:
    body = extract_function_body(read_frontend_js(), "function updateGrid()")

    assert "currentDisplayImages = displayImages;" in body
    assert "displayImages.slice(0, _progressiveGridRenderLimit)" in body
    assert "new Set(renderedImages.map(img => img.name))" in body
    assert "renderedImages.forEach((img" in body


def test_progressive_scroll_has_one_binding_and_one_raf_guard() -> None:
    source = read_frontend_js()
    bind = extract_function_body(source, "function _bindProgressiveGridScrollGrowth(content)")
    schedule = extract_function_body(source, "function _scheduleProgressiveGridGrowthCheck()")

    assert "_progressiveGridScrollBound" in bind
    assert "content.addEventListener('scroll', _scheduleProgressiveGridGrowthCheck" in bind
    assert "_progressiveGridGrowthRafId !== null" in schedule
    assert schedule.count("requestAnimationFrame(") == 1
    assert "PROGRESSIVE_GRID_APPEND_CHUNK" in schedule


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


def test_same_context_reconciliation_does_not_replace_live_grid() -> None:
    body = extract_function_body(read_frontend_js(), "function updateGrid()")

    assert "grid.insertBefore(thumb, liveAtIndex);" in body
    assert "unscheduleThumbnailLoad(element);" in body
    assert "grid.replaceChildren(fragment);" not in body


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


def test_grid_shell_columns_use_full_canonical_display_count() -> None:
    body = extract_function_body(read_frontend_js(), "function updateGridShellLayout()")

    assert (
        "const displayCount = currentDisplayImages.length || "
        "grid.querySelectorAll('.thumb.loading-placeholder').length;"
    ) in body


def test_dynamic_benchmark_dispatches_production_scroll_growth_event() -> None:
    benchmark = Path("scripts/benchmark_thumbnails.py").read_text(encoding="utf-8")

    assert "dynamic-traversal-growth-v1" in benchmark
    assert "content.dispatchEvent(new Event('scroll', {bubbles: true}));" in benchmark
    assert re.search(r"currentRendered\s*<\s*targetCount", benchmark)


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
    assert int(match.group(1)) >= 78
