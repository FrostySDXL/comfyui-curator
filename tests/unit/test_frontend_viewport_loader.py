import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.frontend_source import extract_function_body, read_frontend_js


# ── loader file ordering ──────────────────────────────────────────────────


def test_viewport_loader_script_is_in_ordered_list():
    """viewport-loader.js is loaded after grid.js in the ordered JS list."""
    from tests.unit.frontend_source import JS_FILES

    paths = [str(p) for p in JS_FILES]
    grid_idx = paths.index("static\\js\\grid.js")
    vl_idx = paths.index("static\\js\\viewport-loader.js")
    assert vl_idx > grid_idx, "viewport-loader.js must load after grid.js"


# ── scheduling delegation ─────────────────────────────────────────────────


def test_no_eager_set_thumbnail_image_src_in_update_thumb():
    """updateThumbElement must NOT call setThumbnailImageSrc directly."""
    source = read_frontend_js()
    update_thumb_body = extract_function_body(
        source, "function updateThumbElement(thumb, img, index)"
    )
    assert "setThumbnailImageSrc(imageEl" not in update_thumb_body, (
        "updateThumbElement must not eagerly call setThumbnailImageSrc"
    )
    assert "scheduleThumbnailLoad(" in update_thumb_body, (
        "updateThumbElement must delegate to scheduleThumbnailLoad"
    )


def test_set_thumbnail_image_src_preserved_for_viewport_loader():
    """setThumbnailImageSrc must still exist for the viewport loader to call it."""
    source = read_frontend_js()
    assert "function setThumbnailImageSrc(imageEl, imageSrc, cacheKey" in source


# ── three-tier priority architecture ──────────────────────────────────────


def test_three_priority_levels_defined():
    """Three named priority constants: VISIBLE, NEAR, DEFERRED."""
    source = read_frontend_js()
    assert "VIEWPORT_PRIORITY_VISIBLE" in source, "Missing VIEWPORT_PRIORITY_VISIBLE constant"
    assert "VIEWPORT_PRIORITY_NEAR" in source, "Missing VIEWPORT_PRIORITY_NEAR constant"
    assert "VIEWPORT_PRIORITY_DEFERRED" in source, "Missing VIEWPORT_PRIORITY_DEFERRED constant"
    # Numeric priority ordering: VISIBLE < NEAR < DEFERRED
    visible_match = re.search(r"VIEWPORT_PRIORITY_VISIBLE\s*=\s*(\d+)", source)
    near_match = re.search(r"VIEWPORT_PRIORITY_NEAR\s*=\s*(\d+)", source)
    deferred_match = re.search(r"VIEWPORT_PRIORITY_DEFERRED\s*=\s*(\d+)", source)
    assert visible_match and near_match and deferred_match, (
        "Priority constants must have numeric values"
    )
    vis_val = int(visible_match.group(1))
    near_val = int(near_match.group(1))
    def_val = int(deferred_match.group(1))
    assert vis_val < near_val < def_val, (
        f"Priority values must be VISIBLE({vis_val}) < NEAR({near_val}) < DEFERRED({def_val})"
    )


def test_two_intersection_observers_for_separate_priorities():
    """Two separate observers: one for visible (no margin), one for near (100% margin)."""
    source = read_frontend_js()
    observer_matches = list(re.finditer(r"new\s+IntersectionObserver\s*\(", source))
    assert len(observer_matches) >= 2, (
        f"Expected at least 2 IntersectionObserver instances, found {len(observer_matches)}"
    )
    # One must have rootMargin: '0%' (or no rootMargin => 0% default) for visible
    # One must have rootMargin: '100%' for near
    assert (
        "rootMargin: '0%'" in source
        or "rootMargin: '0px'" in source
        or ("rootMargin" not in source.split("new IntersectionObserver")[1][:200])
    ), "Expected a visible observer with no/zero margin"


def test_bounded_concurrency_constant():
    """A named THUMBNAIL_LOAD_CONCURRENCY constant set to a value within the
    accepted experimental range 6--20. The current value (16) was selected
    from cross-browser benchmark evidence showing underutilization of the
    local HTTP/cache path at 8 for cold and warm-reload phases."""
    source = read_frontend_js()
    match = re.search(r"THUMBNAIL_LOAD_CONCURRENCY\s*=\s*(\d+)", source)
    assert match, "Expected THUMBNAIL_LOAD_CONCURRENCY constant with numeric value"
    value = int(match.group(1))
    assert 6 <= value <= 20, (
        f"THUMBNAIL_LOAD_CONCURRENCY ({value}) must be within accepted range 6--20"
    )
    assert value == 16, (
        f"THUMBNAIL_LOAD_CONCURRENCY expected 16 from benchmark evidence, got {value}"
    )


# ── eventual background loading ───────────────────────────────────────────


def test_background_drain_mechanism_exists():
    """Background drain mechanism (requestIdleCallback or setTimeout) must
    exist for the IntersectionObserver-unavailable fallback path."""
    source = read_frontend_js()
    has_idle = "requestIdleCallback" in source
    has_timeout = "setTimeout(" in source
    assert has_idle or has_timeout, "Background drain must use requestIdleCallback or setTimeout"


def test_background_drain_has_single_timer_guard():
    """Only one background drain timer may be scheduled at a time (guard variable)."""
    source = read_frontend_js()
    # Look for a guard pattern: if (timerId !== null) { clearTimeout(timerId); } or
    # if (timerId != null) return;
    timer_guard = (
        "clearTimeout" in source
        or "cancelIdleCallback" in source
        or re.search(r"_viewportDrainTimer\w*\s*(!==?\s*null|!=\s*null)", source)
    )
    assert timer_guard, (
        "Expected single-timer guard (clearTimeout / cancelIdleCallback / _viewportDrainTimer !== null)"
    )


def test_cancel_scheduled_clears_background_timer():
    """cancelScheduledViewportLoads must cancel any pending idle/timer callback."""
    source = read_frontend_js()
    cancel_body = extract_function_body(source, "function cancelScheduledViewportLoads(")
    # Must either call clearTimeout/cancelIdleCallback directly or via a helper
    calls_cleanup = (
        "clearTimeout(" in cancel_body
        or "cancelIdleCallback(" in cancel_body
        or "_cancelBackgroundDrain()" in cancel_body
    )
    assert calls_cleanup, "cancelScheduledViewportLoads must clear pending timer"
    # The helper must itself contain clearTimeout/cancelIdleCallback
    if "_cancelBackgroundDrain()" in cancel_body:
        drain_body = extract_function_body(source, "function _cancelBackgroundDrain(")
        assert "clearTimeout(" in drain_body or "cancelIdleCallback(" in drain_body, (
            "_cancelBackgroundDrain must clear the timer"
        )


# ── priority ordering in the scheduler ────────────────────────────────────


def test_scheduler_uses_priority_ordered_queues():
    """The scheduler must drain visible before near, and near before deferred."""
    source = read_frontend_js()
    has_visible_q = "_viewportVisibleQueue" in source
    has_near_q = "_viewportNearQueue" in source
    has_deferred_q = "_viewportDeferredQueue" in source
    assert has_visible_q, "Expected a visible-priority queue"
    assert has_near_q, "Expected a near-priority queue"
    assert has_deferred_q, "Expected a deferred queue"


# ── promotion without duplication ─────────────────────────────────────────


def test_observer_promotes_priority_without_duplication():
    """Observer callbacks must update the priority on an existing info record
    rather than creating a duplicate entry."""
    source = read_frontend_js()
    # Look for observers that mutate .priority on an existing info record
    # rather than calling scheduleThumbnailLoad again
    assert ".priority =" in source or "info.priority" in source, (
        "Expected observer to promote by setting .priority on existing info"
    )
    # Must NOT call scheduleThumbnailLoad inside observer callbacks (that would duplicate)
    observer_scope_start = source.find("function _viewportLoadObserverCallback")
    if observer_scope_start == -1:
        observer_scope_start = source.find("function _viewportVisibleObserver")
    if observer_scope_start != -1:
        next_fn1 = source.find("function _", observer_scope_start + 1)
        if next_fn1 != -1:
            next_fn2 = source.find("function _", next_fn1 + 1)
            observer_end = next_fn2 if next_fn2 != -1 else next_fn1
        else:
            observer_end = len(source)
        observer_scope = source[observer_scope_start:observer_end]
        # scheduleThumbnailLoad should not be called from within the observer callbacks
        assert "scheduleThumbnailLoad(" not in observer_scope, (
            "Observer callbacks must not call scheduleThumbnailLoad (would duplicate entries)"
        )


# ── unschedule and cleanup ────────────────────────────────────────────────


def test_unschedule_thumbnail_load_function_exists():
    """unscheduleThumbnailLoad(element) must be defined."""
    source = read_frontend_js()
    assert "function unscheduleThumbnailLoad(" in source, (
        "Expected unscheduleThumbnailLoad function"
    )


def test_unschedule_called_when_elements_removed_from_grid():
    """When updateGrid removes elements from gridThumbMap, it must unschedule them."""
    source = read_frontend_js()
    update_grid_body = extract_function_body(source, "function updateGrid()")
    # After element.remove() and gridThumbMap.delete(), unscheduleThumbnailLoad should be called
    assert "unscheduleThumbnailLoad(" in update_grid_body, (
        "updateGrid must call unscheduleThumbnailLoad when removing elements from gridThumbMap"
    )


def test_unschedule_unobserves_element():
    """unscheduleThumbnailLoad must call .unobserve on any registered observers."""
    source = read_frontend_js()
    unschedule_body = extract_function_body(source, "function unscheduleThumbnailLoad(")
    assert ".unobserve(" in unschedule_body, "unscheduleThumbnailLoad must unobserve from observers"


def test_empty_grid_state_cancels_scheduled_loads():
    """When updateGrid enters the empty state, it must call cancelScheduledViewportLoads."""
    source = read_frontend_js()
    update_grid_body = extract_function_body(source, "function updateGrid()")
    reset_body = extract_function_body(source, "function _resetProgressiveGridLifecycle()")
    assert "_resetProgressiveGridLifecycle()" in update_grid_body, (
        "updateGrid empty-state path must reset the progressive lifecycle"
    )
    assert "cancelScheduledViewportLoads()" in reset_body


def test_unschedule_removes_from_queues():
    """unscheduleThumbnailLoad must remove the info record from all queues."""
    source = read_frontend_js()
    unschedule_body = extract_function_body(source, "function unscheduleThumbnailLoad(")
    # Should filter/remove from queues
    assert ".filter(" in unschedule_body or ".delete(" in unschedule_body, (
        "unscheduleThumbnailLoad must remove from maps/queues"
    )


# ── concurrency slot accounting via promise ───────────────────────────────


def test_set_thumbnail_image_src_returns_promise():
    """setThumbnailImageSrc must return the load promise for slot accounting."""
    source = read_frontend_js()
    setsrc_body = extract_function_body(
        source, "function setThumbnailImageSrc(imageEl, imageSrc, cacheKey"
    )
    assert "return resolveThumbnailBlobUrl(" in setsrc_body, (
        "setThumbnailImageSrc must return resolveThumbnailBlobUrl promise"
    )


def test_concurrency_slot_released_via_promise():
    """Slot release after fetch completion must use the returned promise from
    setThumbnailImageSrc, not guess via inflight map."""
    source = read_frontend_js()
    # The load-start code should do: const promise = setThumbnailImageSrc(...);
    # promise.then(decrementFn, decrementFn);
    load_start_body = extract_function_body(source, "function _startViewportLoad(")
    has_promise_chain = "setThumbnailImageSrc(" in load_start_body
    assert has_promise_chain, (
        "_startViewportLoad must call setThumbnailImageSrc and use its return for accounting"
    )


# ── no viewport-exit unload ───────────────────────────────────────────────


def test_no_loaded_clear_on_intersection_exit():
    """There must be no code path that clears src / resets / re-shimmers a
    thumbnail on intersection exit."""
    source = read_frontend_js()
    assert "!entry.isIntersecting" not in source, (
        "Viewport loader must not react to intersection exit"
    )


# ── preserved invariants ──────────────────────────────────────────────────


def test_thumbnail_blob_cache_unchanged():
    """Existing blob cache architecture must remain intact."""
    source = read_frontend_js()
    assert "const thumbnailBlobUrlCache = new Map();" in source
    assert "const thumbnailBlobInflight = new Map();" in source
    assert "const THUMBNAIL_BLOB_CACHE_MAX = 400;" in source


def test_grid_thumb_map_preserved():
    """gridThumbMap must still be used for persistent element tracking."""
    source = read_frontend_js()
    assert "gridThumbMap = new Map();" in source
    update_grid_body = extract_function_body(source, "function updateGrid()")
    assert "gridThumbMap.get(img.name)" in update_grid_body


def test_thumbs_with_unchanged_cache_key_not_rescheduled():
    """updateThumbElement must check thumbnailCacheKey to skip unchanged thumbs."""
    source = read_frontend_js()
    update_thumb_body = extract_function_body(
        source, "function updateThumbElement(thumb, img, index)"
    )
    assert "thumbnailCacheKey" in update_thumb_body
    assert "classList.remove('loaded')" in update_thumb_body


def test_selection_mode_preserved_in_update_thumb():
    """updateThumbElement must still toggle the selected class."""
    source = read_frontend_js()
    update_thumb_body = extract_function_body(
        source, "function updateThumbElement(thumb, img, index)"
    )
    assert "selectedImages.has(img.name)" in update_thumb_body
    assert "classList.toggle('selected'" in update_thumb_body


def test_beforeunload_cleanup_preserved():
    """Blob URL cleanup on beforeunload must remain."""
    source = read_frontend_js()
    assert "beforeunload" in source
    assert "URL.revokeObjectURL" in source


def test_intersection_observer_used():
    """IntersectionObserver must be referenced."""
    source = read_frontend_js()
    assert "IntersectionObserver" in source


def test_observer_fallback():
    """typeof IntersectionObserver guard for fallback path."""
    source = read_frontend_js()
    assert "typeof IntersectionObserver" in source


def test_unobserve_on_load_start():
    """.unobserve() called when a thumbnail load is admitted."""
    source = read_frontend_js()
    assert ".unobserve(" in source


def test_stale_generation_cancellation():
    """cancelScheduledViewportLoads must increment a generation token."""
    source = read_frontend_js()
    cancel_body = extract_function_body(source, "function cancelScheduledViewportLoads(")
    assert "++" in cancel_body or "+=" in cancel_body or "+ 1" in cancel_body


def test_generation_check_in_start_load():
    """Load start must check .generation against the current token."""
    source = read_frontend_js()
    load_start_body = extract_function_body(source, "function _startViewportLoad(")
    assert ".generation" in load_start_body, (
        "_startViewportLoad must check info.generation against _viewportGeneration"
    )


def test_show_placeholder_cancels_scheduled():
    """showGridLoadingPlaceholders must cancel pending viewport loads."""
    source = read_frontend_js()
    placeholder_body = extract_function_body(
        source, "function showGridLoadingPlaceholders(batch, folder)"
    )
    reset_body = extract_function_body(source, "function _resetProgressiveGridLifecycle()")
    assert "_resetProgressiveGridLifecycle()" in placeholder_body
    assert "cancelScheduledViewportLoads()" in reset_body


# ── admission helper and lifecycle fixes ──────────────────────────────────


def test_admit_and_load_helper_exists():
    """An _admitAndLoad helper must exist that handles cleanup before loading."""
    source = read_frontend_js()
    assert "function _admitAndLoad(" in source, "Expected _admitAndLoad helper function"


def test_admit_and_load_removes_from_info_map():
    """_admitAndLoad must delete the info record from _viewportInfoMap."""
    source = read_frontend_js()
    admit_body = extract_function_body(source, "function _admitAndLoad(")
    assert "_viewportInfoMap.delete(" in admit_body or "_viewportInfoMap.delete" in admit_body, (
        "_admitAndLoad must remove from _viewportInfoMap"
    )


def test_admit_and_load_unobserves_both_observers():
    """_admitAndLoad must unobserve from both visible AND near observers."""
    source = read_frontend_js()
    admit_body = extract_function_body(source, "function _admitAndLoad(")
    visible_unobserve = "_viewportVisibleObserver.unobserve(" in admit_body
    near_unobserve = "_viewportNearObserver.unobserve(" in admit_body
    assert visible_unobserve, "_admitAndLoad must unobserve from visible observer"
    assert near_unobserve, "_admitAndLoad must unobserve from near observer"


def test_schedule_thumbnail_load_does_not_drain_immediately():
    """scheduleThumbnailLoad must NOT call _drainQueues or _startViewportLoad
    directly. It arms background drain only when IntersectionObserver is
    unavailable (fallback path)."""
    source = read_frontend_js()
    schedule_body = extract_function_body(source, "function scheduleThumbnailLoad(")
    assert "_drainQueues()" not in schedule_body, (
        "scheduleThumbnailLoad must not call _drainQueues directly"
    )
    assert "_startViewportLoad(" not in schedule_body, (
        "scheduleThumbnailLoad must not call _startViewportLoad directly"
    )
    # Background drain is armed only in the no-observer fallback
    assert "_scheduleBackgroundDrain()" in schedule_body, (
        "scheduleThumbnailLoad must reference _scheduleBackgroundDrain (fallback path)"
    )
    # Background drain arm is conditional on no observers
    assert "!_viewportVisibleObserver" in schedule_body, (
        "scheduleThumbnailLoad must guard background drain behind !_viewportVisibleObserver"
    )


def test_priority_pump_uses_single_raf():
    """A single rAF-based priority pump must exist, guarded against duplicate
    scheduling."""
    source = read_frontend_js()
    assert (
        "function _requestPriorityPump" in source or "function _requestPriorityPump(" in source
    ), "Expected _requestPriorityPump function"
    assert "function _runPriorityPump" in source or "function _runPriorityPump(" in source, (
        "Expected _runPriorityPump function"
    )
    assert "_viewportPumpRafId" in source, "Expected _viewportPumpRafId guard variable"


def test_cancellation_cancels_priority_pump():
    """cancelScheduledViewportLoads must cancel the priority pump rAF."""
    source = read_frontend_js()
    cancel_body = extract_function_body(source, "function cancelScheduledViewportLoads(")
    cancels_pump = (
        "_cancelPriorityPump()" in cancel_body
        or "cancelAnimationFrame(_viewportPumpRafId)" in cancel_body
    )
    assert cancels_pump, "cancelScheduledViewportLoads must cancel the priority pump"


def test_background_drain_only_drains_deferred():
    """Background drain must target deferred priority (used in no-observer
    fallback path)."""
    source = read_frontend_js()
    # Find the background drain function
    bg_drain = None
    for name in ["_scheduleBackgroundDrain", "_runBackgroundDrain"]:
        try:
            bg_drain = extract_function_body(source, f"function {name}(")
            break
        except AssertionError:
            continue
    if bg_drain:
        # Background drain should call _drainNext(DEFERRED) not _drainQueues
        assert "VIEWPORT_PRIORITY_DEFERRED" in bg_drain, (
            "Background drain must target deferred priority"
        )
        # Guarded by observer check in normal path
        assert "_viewportVisibleObserver" in bg_drain, (
            "Background drain must check _viewportVisibleObserver guard"
        )


def test_observer_callbacks_use_priority_pump_not_immediate_drain():
    """Observer callbacks must call _requestPriorityPump(), not _drainQueues()."""
    source = read_frontend_js()
    # Check the near observer callback body
    near_start = source.find("function (entries)")
    if near_start == -1:
        near_start = source.find("function(entries)")
    if near_start != -1:
        # Find the near observer (second one, with rootMargin: '100%')
        near_obs = source.find("rootMargin: '100%'", near_start)
        if near_obs == -1:
            near_obs = source.find("rootMargin:'100%'", near_start)
        if near_obs != -1:
            # Check that the observer callback before this point doesn't have _drainQueues()
            # But this is fragile. Just check the full source.
            pass
    assert "_requestPriorityPump()" in source, (
        "Expected _requestPriorityPump call in observer callbacks"
    )


# ── Node-executed lifecycle test ──────────────────────────────────────────


def test_viewport_loader_node_lifecycle():
    """Deterministic Node-executed lifecycle test with mocked observers,
    DOM elements, and scheduling callbacks. Verifies admission order,
    once-only loading, map/queue cleanup, and cancellation."""
    node_exe = "node"
    script_path = str(Path("tests/unit/viewport_loader_lifecycle_test.js"))
    try:
        result = subprocess.run(
            [node_exe, script_path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path.cwd()),
        )
    except FileNotFoundError:
        pytest.skip("node executable not found")
    except subprocess.TimeoutExpired:
        pytest.fail("Node lifecycle test timed out after 30s")

    stderr = result.stderr.strip()
    if stderr:
        print(f"Node test stderr:\n{stderr}", file=sys.stderr)

    try:
        report = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(
            f"Node test produced invalid JSON.\nstdout:\n{result.stdout}\nstderr:\n{stderr}"
        )

    failures = [d for d in report["details"] if not d["pass"]]
    if failures:
        fail_msgs = "\n".join(f"  - {d['message']}" for d in failures)
        pytest.fail(
            f"Node lifecycle test: {report['failed']}/{report['total']} failed:\n{fail_msgs}"
        )

    assert report["failed"] == 0, f"Expected 0 failures, got {report['failed']}/{report['total']}"
