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

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_focus_trap_handler_is_named_and_removable():
    """The keydown handler registered in _trapFocus must be a named function."""
    source = read_frontend_js()
    # The handler must be declared with a name so it can be referenced
    # by removeEventListener. Anonymous function expressions leak.
    assert "function _modalKey(" in source, (
        "Expected a named function `_modalKey` for the focus-trap handler "
        "so it can be removed in _releaseFocusTrap. Anonymous handlers "
        "cannot be unregistered."
    )


def test_focus_trap_uses_named_handler_in_add_event_listener():
    """_trapFocus must pass the named handler to addEventListener."""
    source = read_frontend_js()
    trap_body = extract_function_body(source, "function _trapFocus(")
    assert "addEventListener('keydown', _modalKey)" in trap_body, (
        "_trapFocus must addEventListener('keydown', _modalKey) using the "
        "named handler reference, not an inline function."
    )


def test_focus_trap_releases_named_handler():
    """_releaseFocusTrap must call removeEventListener with the named handler."""
    source = read_frontend_js()
    release_body = extract_function_body(source, "function _releaseFocusTrap(")
    assert "removeEventListener('keydown', _modalKey)" in release_body, (
        "_releaseFocusTrap must call removeEventListener('keydown', _modalKey) "
        "to unregister the handler that _trapFocus added. Without this, "
        "every modal open cycle leaks a listener."
    )
