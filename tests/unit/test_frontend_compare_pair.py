"""Source contracts for the Phase 1 compare/pair-walk foundation."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
INDEX = ROOT / "templates" / "index.html"
CURATOR = ROOT / "templates" / "curator.html"
LIGHTBOX_JS = ROOT / "static" / "js" / "lightbox.js"
KEYBOARD_JS = ROOT / "static" / "js" / "keyboard.js"
EVENTS_JS = ROOT / "static" / "js" / "events.js"
LIGHTBOX_CSS = ROOT / "static" / "css" / "lightbox.css"


def test_compare_template_exposes_sync_split_pin_and_pair_controls() -> None:
    html = INDEX.read_text(encoding="utf-8")
    for control_id in (
        "lightbox-compare-sync-btn",
        "lightbox-compare-split-btn",
        "lightbox-compare-pair-btn",
        "lightbox-pin-compare-btn",
    ):
        assert f'id="{control_id}"' in html
    assert "Sync Pan/Zoom" in html
    assert "A/B Split" in html
    assert "Advance pair" in html
    assert "Pin A" in html


def test_compare_controls_are_wired_and_expose_explicit_state() -> None:
    lightbox = LIGHTBOX_JS.read_text(encoding="utf-8")
    events = EVENTS_JS.read_text(encoding="utf-8")
    keyboard = KEYBOARD_JS.read_text(encoding="utf-8")

    for function_name in (
        "setLightboxCompareSync",
        "toggleLightboxCompareSplit",
        "clearStickyComparePin",
        "advanceComparePair",
    ):
        assert f"function {function_name}(" in lightbox
    assert "lightboxCompareSync" in lightbox
    assert "lightboxCompareSplitMode" in lightbox
    assert "lightboxCompareCandidateIndex" in lightbox
    assert "getStillLightboxImages" in lightbox
    assert "isStillLightboxImage" in lightbox
    assert "Still images only" in lightbox
    sticky_start = lightbox.index("function navigateStickyCompare(delta)")
    sticky_end = lightbox.index("function advanceComparePair(delta)", sticky_start)
    assert "currentIndex = nextIndex" not in lightbox[sticky_start:sticky_end]
    assert "lightbox-compare-sync-btn" in events
    assert "lightbox-compare-split-btn" in events
    assert "lightbox-compare-pair-btn" in events
    assert "lightbox-pin-compare-btn" in events
    assert "advanceComparePair" in keyboard
    assert "getCompareSplitPaneIndex" in lightbox
    assert "handleLightboxCompareSplitKeydown" in events
    assert "aria-valuenow" in lightbox
    assert "lightboxCompareSplitDragging" in lightbox
    assert "lightboxCompareSplitDragging || divider" in lightbox
    assert "lightboxCompareSplitDragging || !lightboxComparePanState" in lightbox
    assert "if (lightboxCompareSync)" in lightbox


def test_compare_split_separator_is_keyboard_operable_and_aria_labeled() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="lightbox-compare-divider"' in html
    assert 'role="separator"' in html
    assert 'aria-orientation="vertical"' in html
    assert 'aria-valuemin="8"' in html
    assert 'aria-valuemax="92"' in html
    assert 'aria-valuenow="50"' in html


def test_compare_css_supports_split_mode_and_responsive_reduced_motion() -> None:
    css = LIGHTBOX_CSS.read_text(encoding="utf-8")
    assert ".lightbox-compare.split-mode" in css
    assert ".lightbox-compare-divider" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 900px)" in css


def test_native_compare_template_keeps_the_two_transform_parity() -> None:
    index = INDEX.read_text(encoding="utf-8")
    expected = index.replace("/static/", "/curator_static/")
    marker = '<script src="/curator_static/js/'
    expected = expected.replace(
        marker,
        "<script>window.CURATOR_NATIVE = true;</script>\n    " + marker,
        1,
    )
    assert CURATOR.read_text(encoding="utf-8") == expected
