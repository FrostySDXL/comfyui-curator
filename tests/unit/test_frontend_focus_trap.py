"""Regression test: the modal focus trap must not leak keydown listeners.

The previous implementation of ``_trapFocus`` registered an anonymous
keydown handler on the modal element but ``_releaseFocusTrap`` never
removed it. Because the modals are static elements (not recreated on
open/close), every open/close cycle added another listener to the same
node.

The fix is to hoist the handler to a named, module-scoped function and
pass the same reference to both ``addEventListener`` and
``removeEventListener``.
"""

from pathlib import Path

APP_JS = Path("static/js/app.js")


def test_focus_trap_handler_is_named_and_removable():
    """The keydown handler registered in _trapFocus must be a named function."""
    source = APP_JS.read_text(encoding="utf-8")
    # The handler must be declared with a name so it can be referenced
    # by removeEventListener. Anonymous function expressions leak.
    assert "function _modalKey(" in source, (
        "Expected a named function `_modalKey` for the focus-trap handler "
        "so it can be removed in _releaseFocusTrap. Anonymous handlers "
        "cannot be unregistered."
    )


def test_focus_trap_uses_named_handler_in_add_event_listener():
    """_trapFocus must pass the named handler to addEventListener."""
    source = APP_JS.read_text(encoding="utf-8")
    # Locate the body of _trapFocus and assert it registers _modalKey.
    trap_start = source.find("function _trapFocus(")
    trap_end = source.find("function _releaseFocusTrap(", trap_start)
    assert trap_start != -1 and trap_end != -1, (
        "Could not locate _trapFocus / _releaseFocusTrap in app.js"
    )
    trap_body = source[trap_start:trap_end]
    assert "addEventListener('keydown', _modalKey)" in trap_body, (
        "_trapFocus must addEventListener('keydown', _modalKey) using the "
        "named handler reference, not an inline function."
    )


def test_focus_trap_releases_named_handler():
    """_releaseFocusTrap must call removeEventListener with the named handler."""
    source = APP_JS.read_text(encoding="utf-8")
    release_start = source.find("function _releaseFocusTrap(")
    assert release_start != -1, "Could not locate _releaseFocusTrap"
    # The release body extends until the next "function " declaration.
    next_fn = source.find("function ", release_start + 1)
    release_body = source[release_start : next_fn if next_fn != -1 else None]
    assert "removeEventListener('keydown', _modalKey)" in release_body, (
        "_releaseFocusTrap must call removeEventListener('keydown', _modalKey) "
        "to unregister the handler that _trapFocus added. Without this, "
        "every modal open cycle leaks a listener."
    )
