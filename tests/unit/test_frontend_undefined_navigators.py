"""Regression test: app.js event bindings must not reference undefined functions.

Two functions are referenced in ``_bindDelegatedEvents`` but never defined:
  - ``navigateLightbox`` (real function is ``navigate``)
  - ``navigateLightboxToScored`` (real function is ``navigateScored``)

A third function, ``aiToggleRunDiff``, is referenced for an element id
``ai-diff-select`` that does not exist in the HTML template. The real
``ai-compare-run-select`` element is already wired to ``aiSetCompareRun``.

The lightbox prev/next buttons and the scored-image nav buttons would
throw ``ReferenceError`` on click in production.
"""

from pathlib import Path

APP_JS = Path("static/js/app.js")


def test_no_undefined_navigate_lightbox_calls():
    """No call site in app.js may reference the undefined navigateLightbox function."""
    source = APP_JS.read_text(encoding="utf-8")
    # navigateLightbox must not appear as an identifier. We allow the substring
    # "navigateLightbox" only inside a function-name definition `function navigateLightbox`,
    # which would itself be unused. Either way the surface must be clean.
    assert "navigateLightbox" not in source, (
        "navigateLightbox is referenced but not defined. "
        "Rename call sites to `navigate` (the actual function name)."
    )


def test_no_undefined_navigate_lightbox_to_scored_calls():
    """No call site in app.js may reference the undefined navigateLightboxToScored function."""
    source = APP_JS.read_text(encoding="utf-8")
    assert "navigateLightboxToScored" not in source, (
        "navigateLightboxToScored is referenced but not defined. "
        "Rename call sites to `navigateScored` (the actual function name)."
    )


def test_no_undefined_ai_toggle_run_diff_calls():
    """No call site in app.js may reference the undefined aiToggleRunDiff function."""
    source = APP_JS.read_text(encoding="utf-8")
    assert "aiToggleRunDiff" not in source, (
        "aiToggleRunDiff is referenced but not defined. "
        "The element id `ai-diff-select` is not in the HTML either — "
        "remove the dead binding or wire it to the real handler."
    )


def test_navigate_and_navigate_scored_are_defined():
    """The two real functions must still be defined after renaming."""
    source = APP_JS.read_text(encoding="utf-8")
    assert "function navigate(" in source, "function navigate must still be defined"
    assert "function navigateScored(" in source, "function navigateScored must still be defined"
