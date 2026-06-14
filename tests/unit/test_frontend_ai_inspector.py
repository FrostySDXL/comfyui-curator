from pathlib import Path

from tests.unit.frontend_source import read_frontend_css, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def test_ai_sidebar_contains_contextual_image_inspector() -> None:
    html = read_index_html()
    css = read_frontend_css()

    assert 'id="ai-review-section"' in html
    assert 'class="ai-review-section"' in html
    assert 'id="ai-image-inspector"' in html
    assert 'class="ai-image-inspector ai-image-inspector-empty"' in html
    assert "Review inspector" in html
    assert ".ai-review-section" in css
    assert ".ai-image-inspector" in css
    assert ".ai-image-inspector-empty" in css


def test_ai_inspector_renders_score_details_without_api_calls() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "let aiInspectedImageName = null;" in js
    assert "function aiSetInspectedImage(img)" in js
    assert "function aiRenderImageInspector(img = null)" in js
    assert "const result = aiGetImageScore(target.name);" in js
    assert "detailChip.className = `ai-inspector-detail ${matched ? 'matched' : 'missing'}`;" in js
    assert "detailChip.textContent = `${matched ? 'YES' : 'NO'} · ${element}`;" in js
    assert "No AI score for this image" in js
    assert ".ai-inspector-score" in css
    assert ".ai-inspector-detail.matched" in css
    assert ".ai-inspector-detail.missing" in css


def test_grid_and_lightbox_update_ai_inspected_image() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert (
        "if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(images[index]);" in js
    )
    assert "if (typeof aiSetInspectedImage === 'function') aiSetInspectedImage(img);" in js
    assert (
        "thumb.classList.toggle('inspected', typeof aiInspectedImageName !== 'undefined' && aiInspectedImageName === img.name);"
        in js
    )
    assert ".thumb.inspected" in css
    assert ".thumb.inspected::before" in css


def test_ai_run_changes_refresh_inspector_context() -> None:
    js = read_frontend_js()

    assert "aiRenderImageInspector();" in js
    assert "aiInspectedImageName = null;" in js
    assert "function aiGetInspectedImage()" in js
