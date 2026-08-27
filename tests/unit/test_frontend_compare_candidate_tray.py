"""Source contracts for the optional compare candidate tray."""

from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


ROOT = Path(__file__).parents[2]
INDEX = ROOT / "templates" / "index.html"
CURATOR = ROOT / "templates" / "curator.html"
LIGHTBOX = ROOT / "static" / "js" / "lightbox.js"
SELECTION = ROOT / "static" / "js" / "selection.js"
GRID_CSS = ROOT / "static" / "css" / "grid.css"


def test_candidate_tray_markup_is_compact_accessible_and_dismissible() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="compare-candidate-tray"' in html
    assert 'role="region"' in html
    assert 'aria-label="Compare candidates"' in html
    assert 'id="compare-candidate-list"' in html
    assert 'id="compare-candidate-dismiss"' in html
    assert 'id="compare-candidate-launch"' in html
    assert 'id="compare-candidate-status"' in html


def test_candidate_tray_uses_selection_as_source_and_orders_only_stills() -> None:
    js = read_frontend_js()
    lightbox = LIGHTBOX.read_text(encoding="utf-8")
    selection = SELECTION.read_text(encoding="utf-8")
    for function_name in (
        "syncCompareCandidateOrder",
        "renderCompareCandidateTray",
        "removeCompareCandidate",
        "moveCompareCandidate",
    ):
        assert f"function {function_name}(" in js
    assert "isStillLightboxImage" in lightbox
    assert "compareCandidateOrder" in js
    assert "selectedImages.has(img.name)" in js
    assert "Compare supports still images only" in selection
    assert "compare-candidate-launch" in js
    assert "launchCompareCandidateTray();" in js


def test_candidate_tray_allows_two_or_more_stills_and_surfaces_skipped_media() -> None:
    js = read_frontend_js()
    tray = extract_function_body(js, "function renderCompareCandidateTray()")
    assert "stillCandidates.length < 2" in tray
    assert "skippedCount" in tray
    assert "non-still" in tray
    assert "disabled" in tray
    assert "first two" in tray
    assert "getVisibleCompareCandidates" in tray
    assert "more not shown" in tray


def test_candidate_tray_caps_rendered_candidates_without_changing_launch_order() -> None:
    js = read_frontend_js()
    assert "const COMPARE_CANDIDATE_VISIBLE_LIMIT = 6;" in js
    visible = extract_function_body(js, "function getVisibleCompareCandidates(candidates)")
    assert "candidates.slice(0, COMPARE_CANDIDATE_VISIBLE_LIMIT)" in visible
    launch = extract_function_body(js, "function launchCompareCandidateTray()")
    assert "syncCompareCandidateOrder()" in launch
    assert "stillCandidates.slice(0, 2)" in launch


def test_candidate_tray_reorder_and_remove_preserve_canonical_selection() -> None:
    js = read_frontend_js()
    remove = extract_function_body(js, "function removeCompareCandidate(name)")
    move = extract_function_body(js, "function moveCompareCandidate(name, delta)")
    reset = extract_function_body(js, "function resetSelectionState()")
    assert "selectedImages.delete(name);" in remove
    assert "updateSelectionVisuals();" in remove
    assert "compareCandidateOrder" in move
    assert "updateActionBar();" in move
    assert "compareCandidateOrder = [];" in reset


def test_candidate_tray_css_is_responsive_and_above_action_bar() -> None:
    css = GRID_CSS.read_text(encoding="utf-8")
    assert ".compare-candidate-tray" in css
    assert "var(--action-bar-safe-area" in css
    assert "@media (max-width: 900px)" in css


def test_native_template_keeps_candidate_tray_parity() -> None:
    index = INDEX.read_text(encoding="utf-8")
    expected = index.replace("/static/", "/curator_static/")
    marker = '<script src="/curator_static/js/'
    expected = expected.replace(
        marker,
        "<script>window.CURATOR_NATIVE = true;</script>\n    " + marker,
        1,
    )
    assert CURATOR.read_text(encoding="utf-8") == expected


def test_tray_launch_uses_explicit_pair_and_restores_focus_to_launch_control() -> None:
    js = read_frontend_js()
    lightbox = LIGHTBOX.read_text(encoding="utf-8")
    launch = extract_function_body(js, "function launchCompareCandidateTray()")
    assert "stillCandidates.slice(0, 2)" in launch
    assert "compare-candidate-launch" in launch
    assert "openCompareLightboxWithSelection(stillCandidates.slice(0, 2)" in launch
    compare = extract_function_body(lightbox, "function openCompareLightboxWithSelection(")
    assert "explicitSelection" in compare
    assert "rememberLightboxReturnFocus(focusElement || document.activeElement);" in compare
    assert "isVirtualCollectionView() || isPublicView()" in compare
