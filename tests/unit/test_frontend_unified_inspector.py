from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def read_index_html() -> str:
    return Path("templates/index.html").read_text(encoding="utf-8")


def test_unified_inspector_shell_owns_context_tabs_and_active_state() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert 'id="unified-inspector"' in html
    assert 'data-inspector-tab="overview"' in html
    assert 'data-inspector-tab="metadata"' in html
    assert 'data-inspector-tab="ai"' in html
    assert 'id="inspector-overview-section"' in html
    assert 'id="inspector-metadata-section"' in html
    assert 'id="inspector-ai-section"' in html
    assert "let inspectorActiveTab = 'overview';" in js
    assert "function setInspectorTab(tabName)" in js


def test_inspector_metadata_uses_stale_request_guard_and_explicit_empty_states() -> None:
    js = read_frontend_js()

    assert "async function loadInspectorMetadata(target)" in js
    assert "const token = ++inspectorMetadataRequestToken" in js
    assert "if (token !== inspectorMetadataRequestToken) return;" in js
    assert "Metadata unavailable" in js
    assert "No media metadata found" in js
    assert "retry-inspector-metadata" in js


def test_inspector_tabs_preserve_keyboard_focus_and_ai_workflows() -> None:
    html = read_index_html()
    js = read_frontend_js()

    assert "function inspectorHandleTabKeydown(event)" in js
    assert "tab.addEventListener('keydown', inspectorHandleTabKeydown)" in js
    assert "inspectorActiveTab === 'ai'" in js
    assert "aiSetPanelTab(aiActivePanelTab)" in js
    assert 'id="ai-panel-tab-score"' in html
    assert 'id="ai-panel-tab-runs"' in html


def test_inspector_shell_retains_bounded_narrow_overlay() -> None:
    css = Path("static/css/responsive.css").read_text(encoding="utf-8")

    assert ".unified-inspector" in css
    narrow = css.split("@media (max-width: 900px)", 1)[1]
    assert "max-width: 100%;" in narrow
    assert "position: absolute;" in narrow


def test_inspector_uses_effective_server_snapshot_selection_and_zero_fallback() -> None:
    js = read_frontend_js()
    target = extract_function_body(js, "function getInspectorTargetImage()")
    overview = extract_function_body(js, "function renderInspectorOverview()")

    assert "function getInspectorSelectionCount()" in js
    assert "serverSelection.count" in js
    assert "serverSelection.excluded.size" in js
    assert "getInspectorSelectionCount() > 0) return null;" in target
    assert "getInspectorSelectionCount()" in overview
    assert "effective snapshot selection" in js


def test_inspected_image_metadata_load_has_one_lifecycle_owner() -> None:
    js = read_frontend_js()
    inspected = extract_function_body(
        js, "function aiSetInspectedImage(img, sourceOverride = null)"
    )
    render = extract_function_body(js, "function aiRenderImageInspector(img = null)")

    assert "loadInspectorMetadata" not in inspected
    assert render.count("loadInspectorMetadata(typeof getInspectorTargetImage") == 1


def test_header_toggle_uses_inspector_operator_labels() -> None:
    js = read_frontend_js()
    sidebar = extract_function_body(js, "function syncAiSidebarUi(persist = true)")

    assert "headerBtn.textContent = aiSidebarOpen ? 'Hide Inspector' : 'Show Inspector';" in sidebar
