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
    assert "AI Review" in html
    assert 'id="ai-panel-tab-inspect"' in html
    assert 'id="ai-panel-tab-score"' in html
    assert 'id="ai-panel-tab-runs"' in html
    assert ".ai-review-section" in css
    assert ".ai-image-inspector" in css
    assert ".ai-image-inspector-empty" in css


def test_ai_inspector_renders_score_details_without_api_calls() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "let aiInspectedImageName = null;" in js
    assert "function aiSetInspectedImage(img)" in js
    assert "function aiRenderImageInspector(img = null)" in js
    assert "function aiRenderSelectionInspector()" in js
    assert "if (selectedImages.size > 1)" in js
    assert "if (selectedImages.size === 0)" in js
    assert "function aiGetSingleSelectedImage()" in js
    assert "Common missing" in js
    assert "ai-selection-image-list" in js
    assert "toggleAiSelectionImageCard" in js
    assert "const result = aiGetImageScore(target.name);" in js
    assert "detailChip.className = `ai-inspector-detail ${matched ? 'matched' : 'missing'}`;" in js
    assert "detailChip.textContent = `${matched ? 'YES' : 'NO'} · ${element}`;" in js
    assert "No AI score for this image" in js
    assert ".ai-inspector-score" in css
    assert ".ai-inspector-detail.matched" in css
    assert ".ai-inspector-detail.missing" in css
    assert ".ai-selection-summary" in css
    assert ".ai-selection-image-card" in css
    assert ".ai-selection-image-card.expanded" in css


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
    assert ".thumb.inspected::before" not in css


def test_ai_run_changes_refresh_inspector_context() -> None:
    js = read_frontend_js()

    assert "aiRenderImageInspector();" in js
    assert "aiInspectedImageName = null;" in js
    assert "function aiGetInspectedImage()" in js


def test_ai_runs_tab_owns_run_history_visibility() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "historySection.classList.remove('hidden');" in js
    assert "aiSetPanelTab(aiActivePanelTab);" in js
    assert "section.dataset.aiPanelSection === aiActivePanelTab" in js
    assert "historySection.style.display = 'block';" not in js
    assert ".ai-run-brief" in css
    assert ".ai-run-kpis" in css
    assert ".ai-stat-card" not in css


def test_lightbox_has_visible_ai_inspector_opposite_metadata_panel() -> None:
    html = read_index_html()
    js = read_frontend_js()
    css = read_frontend_css()

    assert 'id="lightbox-ai-panel"' in html
    assert 'id="lightbox-ai-toggle-btn"' in html
    assert "function toggleLightboxAiPanel()" in js
    assert "function renderLightboxAiPanel()" in js
    assert "lightboxAiOpen" in js
    assert "case 'i': e.preventDefault(); toggleLightboxAiPanel(); break;" in js
    assert ".lightbox-ai-panel" in css
    assert "right: 20px;" in css
    assert ".lightbox-metadata-panel" in css
    assert "left: 20px;" in css


def test_ai_sidebar_removes_internal_whole_panel_collapse() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'id="ai-curate-toggle"' not in html
    assert "function toggleAiCuratePanel()" not in js
    assert "AI_PANEL_OPEN_KEY" not in js


def test_ai_job_status_uses_running_indicator_not_progress_bar() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    assert "ai-progress-bar" not in js
    assert "ai-progress-fill" not in js
    assert "Scoring in progress" in js
    assert ".ai-status-dot" in css
    assert ".ai-progress-bar" not in css
