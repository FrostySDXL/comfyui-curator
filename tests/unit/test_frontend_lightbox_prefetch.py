"""Source and executable tests for lightbox navigation and adjacent-image prefetch.

The Node lifecycle harness executes the production lightbox script with controllable
browser-like image load/decode completion. Source invariants cover the bounded
registry and compare path.

Source-invariant coverage includes lightbox adjacent-image prefetch and
sticky-compare candidate-replacement smoothness.

Verifies a bounded Map-based registry with:
- Reconciliation against the desired adjacent URL set (max two candidates)
- Identity-safe completion (entry identity, not URL alone)
- Internal imageToken stale-guard
- Image-object retention for cancellation
- closeLightbox cleanup that detaches handlers and clears registry
- Display-order adjacency, wrapping, compare skip, URL helper usage,
  no current-image mutation, and onload integration

Also verifies compare-pane replacement uses off-DOM load-then-swap:
- Replacement loaded via new Image() off-DOM, not by mutating visible imgEl.src
- Visible imgEl is never blanked (no opacity:0, no loading class)
- Token guard on swap; per-pane bounded pending-loader registry
- Cleanup on close and on superseding navigation
- Error path preserves old visible image
"""

import json
import subprocess
from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_lightbox_navigation_node_lifecycle() -> None:
    completed = subprocess.run(
        ["node", "tests/unit/lightbox_navigation_lifecycle_test.js"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.stdout, completed.stderr
    report = json.loads(completed.stdout)
    failures = [detail["message"] for detail in report["details"] if not detail["pass"]]
    assert completed.returncode == 0, "\n".join(failures) + "\n" + completed.stderr
    assert report["failed"] == 0


def test_grid_open_uses_separate_prepare_before_activation_path() -> None:
    """A grid-open session must not reuse preserve-current-image navigation."""
    js = read_frontend_js()
    open_body = extract_function_body(js, "function openLightbox(")
    prepare_body = extract_function_body(js, "function _prepareLightboxOpen(")

    assert "_prepareLightboxOpen(" in open_body
    assert "showCurrentImage(" not in open_body
    assert "classList.add('active')" in prepare_body
    assert prepare_body.index("capturePreparedLightboxBaseSize()") < prepare_body.index(
        "classList.add('active')"
    )


def test_grid_open_measures_untransformed_layout_dimensions() -> None:
    """Preparation must avoid transform-scaled client rectangles."""
    js = read_frontend_js()
    prepare_body = extract_function_body(js, "function _prepareLightboxOpen(")
    capture_body = extract_function_body(js, "function capturePreparedLightboxBaseSize(")

    assert "capturePreparedLightboxBaseSize()" in prepare_body
    assert "offsetWidth" in capture_body
    assert "offsetHeight" in capture_body
    assert "getBoundingClientRect()" not in capture_body


def test_new_session_open_has_token_and_pending_loader_identity_guards() -> None:
    """Close/reopen races require both monotonic token and entry identity checks."""
    js = read_frontend_js()
    prepare_body = extract_function_body(js, "function _prepareLightboxOpen(")
    close_body = extract_function_body(js, "function closeLightbox(")

    assert "++lightboxOpenToken" in prepare_body
    assert "_pendingLightboxOpen !== pending" in prepare_body
    assert "openToken !== lightboxOpenToken" in prepare_body
    assert "++lightboxOpenToken" in close_body
    assert "_cancelPendingLightboxOpen()" in close_body


# ── Registry structure ──────────────────────────────────────────────────────


def test_prefetch_registry_is_module_scoped_map() -> None:
    """Registry must be a module-scoped Map storing preloader Image entries."""
    js = read_frontend_js()
    assert "const _prefetchRegistry" in js or "let _prefetchRegistry" in js
    # Must use a Map (not a Set) to store entry objects
    assert "_prefetchRegistry = new Map(" in js


def test_prefetch_registry_stores_image_objects() -> None:
    """Each entry must hold a live Image reference and the captured token."""
    js = read_frontend_js()
    body = extract_function_body(js, "function _prefetchAdjacentImages(")
    loader_body = extract_function_body(js, "function _createLightboxImageLoader(")
    assert "new Image()" in loader_body
    assert "_createLightboxImageLoader(" in body
    assert "_prefetchRegistry.set(" in body


# ── Desired-set reconciliation ──────────────────────────────────────────────


def test_prefetch_builds_desired_url_set() -> None:
    """Reconciliation must build a Set of desired adjacent URLs before
    removing obsolete entries or adding missing ones."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "new Set(" in body


def test_prefetch_reconciles_obsolete_entries() -> None:
    """Registry entries whose URL is no longer desired must be removed
    (cancel preloader, delete from registry)."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "_prefetchRegistry.delete(" in body


def test_prefetch_adjacency_is_bounded_to_two_candidates() -> None:
    """Only prev and next indices enter the desired set.  No speculative
    depth beyond immediately adjacent."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "currentIndex - 1" in body
    assert "currentIndex + 1" in body


# ── Identity-safe completion ────────────────────────────────────────────────


def test_prefetch_completion_checks_entry_identity() -> None:
    """Completion handlers must compare their own entry object against the
    current registry value (identity check), not just test URL membership.
    This prevents an old completion from deleting a newer preloader."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "_prefetchRegistry.get(" in body
    assert "=== entry" in body


# ── Internal stale-token guard ──────────────────────────────────────────────


def test_prefetch_token_used_internally() -> None:
    """imageToken must be meaningfully used inside the function as an
    additional stale guard, not only by the caller."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    # Token is compared against the module-level lightboxImageToken
    assert "imageToken !== lightboxImageToken" in body


# ── Eligibility cleanup (early-return guards) ───────────────────────────────
# Every ineligible scheduling state must actively call _cleanupPrefetch before
# returning, so stale registry entries from a prior eligible state cannot
# survive (e.g. entering sticky compare from single-image lightbox).
#
# Exception: stale-token return must NOT cleanup, because the ghost invocation
# must not cancel valid prefetches belonging to the newer active image.


def test_prefetch_cleanup_on_compare_mode() -> None:
    """Compare-mode early return must call _cleanupPrefetch before exiting."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    idx = body.find("lightboxCompareMode")
    assert idx != -1
    ret_idx = body.find("return", idx)
    assert ret_idx != -1
    assert "_cleanupPrefetch()" in body[idx:ret_idx]


def test_prefetch_cleanup_on_single_or_zero_images() -> None:
    """When <=1 lightbox images exist, cleanup before returning."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    idx = body.find("<= 1")
    assert idx != -1
    ret_idx = body.find("return", idx)
    assert ret_idx != -1
    assert "_cleanupPrefetch()" in body[idx:ret_idx]


def test_prefetch_cleanup_on_inactive_lightbox() -> None:
    """When lightbox is not active, cleanup before returning (lifecycle defense)."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    idx = body.find("classList.contains(")
    assert idx != -1
    ret_idx = body.find("return", idx)
    assert ret_idx != -1
    assert "_cleanupPrefetch()" in body[idx:ret_idx]


def test_prefetch_no_cleanup_on_stale_token() -> None:
    """Stale-token return must NOT cleanup — it must not cancel valid prefetches
    belonging to the newer active navigation."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    idx = body.find("imageToken !== lightboxImageToken")
    assert idx != -1
    ret_idx = body.find("return", idx)
    assert ret_idx != -1
    assert "_cleanupPrefetch" not in body[idx:ret_idx]


# ── Close/cleanup ───────────────────────────────────────────────────────────


def test_prefetch_cleanup_function_exists() -> None:
    """Dedicated cleanup function must detach handlers and clear registry."""
    js = read_frontend_js()
    assert "function _cleanupPrefetch(" in js


def test_prefetch_cleanup_detaches_handlers() -> None:
    """Cleanup must null preloader onload/onerror to prevent callbacks
    after close."""
    js = read_frontend_js()
    body = extract_function_body(js, "function _cleanupPrefetch(")
    dispose_body = extract_function_body(js, "function _disposeLightboxImageLoader(")
    assert "_disposeLightboxImageLoader(entry)" in body
    assert ".onload = null" in dispose_body or ".onload=null" in dispose_body
    assert ".onerror = null" in dispose_body or ".onerror=null" in dispose_body


def test_prefetch_cleanup_clears_registry() -> None:
    """Cleanup must empty the registry after detaching handlers."""
    body = extract_function_body(read_frontend_js(), "function _cleanupPrefetch(")
    assert "_prefetchRegistry.clear()" in body


def test_prefetch_close_lightbox_calls_cleanup() -> None:
    """closeLightbox must actively cancel pending prefetch work."""
    body = extract_function_body(read_frontend_js(), "function closeLightbox(")
    assert "_cleanupPrefetch()" in body


# ── Navigation compatibility ────────────────────────────────────────────────


def test_prefetch_uses_display_order() -> None:
    """Adjacency must follow getLightboxImages() (the canonical display order)."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "getLightboxImages()" in body


def test_prefetch_uses_url_helpers() -> None:
    """Must use ccImageUrl and getImageBatchAndFolder for dual-mode URLs."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "ccImageUrl(" in body
    assert "getImageBatchAndFolder(" in body


def test_prefetch_never_mutates_current_image() -> None:
    """Must NOT reference the active lightbox image element."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "lightbox-img" not in body


def test_prefetch_wraps_at_boundaries() -> None:
    """Modulo wrapping must match existing navigation."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert ".length)" in body


def test_prefetch_skips_compare_mode() -> None:
    """Compare mode has its own image loading path."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "lightboxCompareMode" in body


def test_prefetch_checks_lightbox_active() -> None:
    """Must return early when lightbox is not visible."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "classList.contains(" in body


# ── Integration with showCurrentImage ───────────────────────────────────────


def test_prefetch_called_from_show_current_image_onload() -> None:
    """Prefetch triggers after the current full-resolution image loads."""
    show_body = extract_function_body(read_frontend_js(), "function showCurrentImage(")
    assert "_prefetchAdjacentImages(" in show_body


# ── Sticky compare candidate-replacement smoothness ──────────────────────────
# The original updateComparePaneImage mutated the visible imgEl directly
# (opacity=0, loading class, imgEl.src assignment), blanking the old
# candidate before the replacement was loaded.  The fix loads the
# replacement off-DOM via new Image(), calls loader.decode() for decode
# readiness, and swaps imgEl.src + label only after the decode promise
# resolves and the per-pane registry entry is still identity-current.
# Errors leave the old image visible and do not update the label.


def test_compare_pane_uses_off_dom_loader() -> None:
    """Replacement must be loaded via new Image() off-DOM."""
    body = extract_function_body(read_frontend_js(), "function updateComparePaneImage(")
    assert "new Image()" in body


def test_compare_pane_does_not_blank_visible_image() -> None:
    """Visible imgEl must never be hidden: no opacity=0, no loading class."""
    body = extract_function_body(read_frontend_js(), "function updateComparePaneImage(")
    assert "imgEl.style.opacity = '0'" not in body
    assert "imgEl.classList.add('loading')" not in body


def test_compare_pane_pending_loader_registry_exists() -> None:
    """Per-pane bounded pending-loader storage must exist."""
    js = read_frontend_js()
    assert "_pendingCompareLoaders" in js


def test_compare_pane_loader_identity_safe() -> None:
    """Swap and error paths must use identity comparison against the stored
    registry entry, not a bare token check, so a stale completion cannot
    act on a replacement entry."""
    body = extract_function_body(read_frontend_js(), "function updateComparePaneImage(")
    assert "!== entry" in body or "=== entry" in body


def test_compare_pane_loader_calls_decode() -> None:
    """After loader.onload, call loader.decode() before committing the swap
    so the image is fully decoded when painted."""
    body = extract_function_body(read_frontend_js(), "function updateComparePaneImage(")
    assert ".decode()" in body


def test_compare_pane_loader_cancel_function_exists() -> None:
    """A cancel/detach function must exist for pending compare loaders."""
    js = read_frontend_js()
    assert "function _cancelComparePaneLoader(" in js


def test_compare_pane_cleanup_on_close() -> None:
    """closeLightbox must cancel pending compare loaders."""
    body = extract_function_body(read_frontend_js(), "function closeLightbox(")
    assert "_cancelComparePaneLoader" in body or "_cleanupCompareLoaders" in body


def test_compare_pane_error_path_avoids_visible_mutation() -> None:
    """The error/load-failure path must NOT assign imgEl.src or
    label.textContent.  Only the successful swap path may do so.
    Count occurrences: exactly one imgEl.src = and one label.textContent =
    proves the error path (which has neither) is clean."""
    body = extract_function_body(read_frontend_js(), "function updateComparePaneImage(")
    assert body.count("imgEl.src =") == 1
    assert body.count("label.textContent") == 1
