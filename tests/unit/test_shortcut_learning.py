from pathlib import Path


ROOT = Path(__file__).parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_contextual_shortcut_strip_exposes_four_truthful_contexts() -> None:
    js = read("static/js/shortcut-learning.js")
    html = read("templates/index.html")

    assert "function updateShortcutLearningContext" in js
    assert "shortcutLearningObserver.observe(grid, {childList: true});" in js
    for context in ("grid", "selection", "lightbox", "compare"):
        assert f"{context}:" in js
    assert 'id="shortcut-learning-strip"' in html
    assert 'id="shortcut-learning-dismiss"' in html
    assert 'aria-label="Dismiss shortcut hint"' in html


def test_contextual_shortcut_strip_is_dismissible_and_keyboard_safe() -> None:
    js = read("static/js/shortcut-learning.js")
    html = read("templates/index.html")
    css = read("static/css/layout.css")

    assert "SHORTCUT_LEARNING_DISMISSED_KEY" in js
    assert "localStorage" in js
    assert "shortcut-learning-dismiss" in js
    assert '.shortcut-learning-strip[data-context="lightbox"]' in css
    assert "z-index: 1004" in css
    assert "button" in html.split('id="shortcut-learning-dismiss"', 1)[1].split(">", 1)[0]
    assert "Escape" not in js


def test_lightbox_hint_measures_control_clearance_instead_of_using_a_fixed_offset() -> None:
    js = read("static/js/shortcut-learning.js")
    css = read("static/css/layout.css")

    assert "function syncShortcutLearningLightboxOffset()" in js
    assert "document.getElementById('lightbox-actions')" in js
    assert "window.innerHeight - rect.top + 10" in js
    assert "window.addEventListener('resize', syncShortcutLearningLightboxOffset)" in js
    assert "var(--shortcut-learning-lightbox-bottom, 96px)" in css


def test_help_modal_matches_contextual_shortcut_copy() -> None:
    html = read("templates/index.html")

    assert "Browse: click an image to open" in html
    assert "Selection: Ctrl/Cmd+A select all" in html
    assert "Lightbox: Left / Right navigate" in html
    assert "Compare: Alt+Left/Right advance the pair" in html


def test_native_template_keeps_shortcut_learning_markup_in_parity() -> None:
    index = read("templates/index.html").replace("/static/", "/curator_static/")
    index = index.replace('<script src="/curator_static/', '<script src="/curator_static/', 1)
    curator = read("templates/curator.html")

    assert "window.CURATOR_NATIVE = true;" in curator
    assert 'id="shortcut-learning-strip"' in curator
    assert 'id="shortcut-learning-dismiss"' in curator
    assert "Browse: click an image to open" in curator
