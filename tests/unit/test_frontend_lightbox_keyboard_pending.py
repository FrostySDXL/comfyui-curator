"""Source-invariant tests for lightbox-keyboard pending-open shortcut guard.

Confirm that keyboard.js detects a pending lightbox open before dispatching
grid/global/modal shortcuts, so Escape cancels the pending session and every
other key/shortcut is suppressed while the lightbox prepares invisibly.
"""

from pathlib import Path

from tests.unit.frontend_source import extract_function_body

KEYBOARD_JS = Path("static/js/keyboard.js")
LIGHTBOX_JS = Path("static/js/lightbox.js")


def _read_keyboard() -> str:
    return KEYBOARD_JS.read_text(encoding="utf-8")


def _read_lightbox() -> str:
    return LIGHTBOX_JS.read_text(encoding="utf-8")


# ── isLightboxOpenPending helper ────────────────────────────────────────────


def test_is_lightbox_open_pending_function_exists() -> None:
    """A named function must expose the pending-open state."""
    source = _read_lightbox()
    assert "function isLightboxOpenPending(" in source, (
        "lightbox.js must define function isLightboxOpenPending()"
    )


def test_is_lightbox_open_pending_checks_pending_lightbox_open() -> None:
    """The helper must truthfully report _pendingLightboxOpen !== null."""
    body = extract_function_body(_read_lightbox(), "function isLightboxOpenPending(")
    assert "_pendingLightboxOpen !== null" in body, (
        "isLightboxOpenPending must return _pendingLightboxOpen !== null"
    )


# ── Keyboard guard ordering ─────────────────────────────────────────────────


def test_keyboard_checks_pending_before_any_grid_shortcut() -> None:
    """The pending guard must be evaluated BEFORE the first shortcut branch."""
    source = _read_keyboard()
    add_listener_idx = source.find("addEventListener('keydown'")
    assert add_listener_idx != -1, "keydown listener is registered"

    pending_idx = source.find("isLightboxOpenPending", add_listener_idx)
    first_shortcut_idx = source.find('if (e.key === "/"', add_listener_idx)

    assert pending_idx != -1, "keyboard.js must check isLightboxOpenPending"
    assert first_shortcut_idx != -1, '"/" shortcut must be present'

    assert pending_idx < first_shortcut_idx, (
        f"pending guard at offset {pending_idx} must appear before "
        f'"/" search shortcut at offset {first_shortcut_idx}'
    )


def test_pending_guard_escape_calls_close_lightbox_and_prevents_default() -> None:
    """Escape during a pending open must cancel and preventDefault."""
    body = extract_function_body(
        _read_keyboard(),
        "if (typeof isLightboxOpenPending === 'function' && isLightboxOpenPending())",
    )
    assert "e.key === 'Escape'" in body, "pending guard must check for Escape key"
    assert "closeLightbox()" in body, "Escape during pending must call closeLightbox()"
    assert "e.preventDefault()" in body, "Escape during pending must call preventDefault()"
    assert "return;" in body, "pending guard must return after handling Escape"


def test_pending_guard_returns_before_any_shortcut_execution() -> None:
    """Non-Escape keys must return without executing any shortcut action."""
    body = extract_function_body(
        _read_keyboard(),
        "if (typeof isLightboxOpenPending === 'function' && isLightboxOpenPending())",
    )
    # After the Escape conditional, there must be a return; that exits the
    # keydown handler entirely.
    lines = body.splitlines()
    found_escape_return = False
    for line in lines:
        stripped = line.strip()
        if "e.key === 'Escape'" in stripped:
            found_escape_return = True
            continue
        if found_escape_return and stripped == "return;":
            break
    else:
        raise AssertionError(
            "pending guard must have a top-level return; after Escape handling "
            "to suppress all other shortcuts"
        )


def test_space_toggles_visible_lightbox_video_before_native_controls_have_focus() -> None:
    """Space must be owned by the active lightbox even when BODY still has focus."""
    source = _read_keyboard()
    body = extract_function_body(
        source,
        "if (lightboxActive && e.code === 'Space' && toggleLightboxVideoPlayback())",
    )

    assert "e.preventDefault()" in body
    assert "return;" in body
    assert source.index("e.code === 'Space'") < source.index("isLightboxCompareMode")
