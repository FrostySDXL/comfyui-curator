"""Source-invariant tests for lightbox adjacent-image prefetch.

Verifies a bounded Map-based registry with:
- Reconciliation against the desired adjacent URL set (max two candidates)
- Identity-safe completion (entry identity, not URL alone)
- Internal imageToken stale-guard
- Image-object retention for cancellation
- closeLightbox cleanup that detaches handlers and clears registry
- Display-order adjacency, wrapping, compare skip, URL helper usage,
  no current-image mutation, and onload integration.
"""

from tests.unit.frontend_source import extract_function_body, read_frontend_js


# ── Registry structure ──────────────────────────────────────────────────────


def test_prefetch_registry_is_module_scoped_map() -> None:
    """Registry must be a module-scoped Map storing preloader Image entries."""
    js = read_frontend_js()
    assert "const _prefetchRegistry" in js or "let _prefetchRegistry" in js
    # Must use a Map (not a Set) to store entry objects
    assert "_prefetchRegistry = new Map(" in js


def test_prefetch_registry_stores_image_objects() -> None:
    """Each entry must hold a live Image reference and the captured token."""
    body = extract_function_body(read_frontend_js(), "function _prefetchAdjacentImages(")
    assert "new Image()" in body
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
    body = extract_function_body(read_frontend_js(), "function _cleanupPrefetch(")
    assert ".onload = null" in body or ".onload=null" in body
    assert ".onerror = null" in body or ".onerror=null" in body


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
