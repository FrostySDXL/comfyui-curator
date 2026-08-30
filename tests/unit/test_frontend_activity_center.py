import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


INDEX_HTML = Path("templates/index.html")
CURATOR_HTML = Path("templates/curator.html")


def test_activity_center_markup_is_shared_and_accessible() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="activity-center-toggle"' in html
    assert 'aria-controls="activity-center-panel"' in html
    assert 'id="activity-center-panel"' in html
    assert 'role="log"' in html
    assert 'id="activity-center-list"' in html
    assert 'aria-live="polite"' in html


def test_native_template_preserves_activity_center_and_mode_transform() -> None:
    index = INDEX_HTML.read_text(encoding="utf-8")
    curator = CURATOR_HTML.read_text(encoding="utf-8")

    assert 'id="activity-center-toggle"' in curator
    assert 'id="activity-center-panel"' in curator
    assert "/static/js/activity-center.js" not in curator
    assert "/curator_static/js/activity-center.js" in curator
    assert "window.CURATOR_NATIVE = true;" in curator
    transformed = index.replace("/static/", "/curator_static/").splitlines()
    native = curator.replace(
        "    <script>window.CURATOR_NATIVE = true;</script>\n", "", 1
    ).splitlines()
    assert [line for line in transformed if line.strip()] == [
        line for line in native if line.strip()
    ]


def test_activity_center_normalizes_truthful_states_and_ages_successes() -> None:
    js = read_frontend_js()
    css = read_frontend_css()

    for name in (
        "activityRegister",
        "activityUpdate",
        "activityComplete",
        "activityRemove",
        "activityRender",
        "activityToggle",
    ):
        assert f"function {name}(" in js
    render = extract_function_body(js, "function activityRender(")
    for state in ("queued", "running", "partial", "failed", "completed", "cancelled"):
        assert state in js
    assert "completedAt" in js
    assert "ACTIVITY_SUCCESS_TTL" in js
    assert "aria-busy" in render
    assert "prefers-reduced-motion" in css


def test_activity_adapters_cover_import_indexes_public_export_and_ai_cancel() -> None:
    js = read_frontend_js()

    import_body = extract_function_body(js, "async function importAll()")
    search_body = extract_function_body(js, "async function _buildMediaSearchIndexes(batches)")
    prompt_source_start = js.index("async function buildSinglePromptIndex(batch, options = {})")
    prompt_body = js[prompt_source_start : prompt_source_start + 5000]
    publish_body = extract_function_body(js, "async function submitPublicExport()")
    ai_body = extract_function_body(js, "function aiShowJobStatus(job)")

    assert "activityRegister" in import_body
    assert "activityUpdate" in import_body
    assert "activityComplete" in import_body
    assert "activityRegister" in search_body
    assert "activityUpdate" in search_body
    assert "activityComplete" in search_body
    assert "activityRegister" in prompt_body
    assert "activityUpdate" in prompt_body
    assert "activityComplete" in prompt_body
    assert "activityRegister" in publish_body
    assert "activityComplete" in publish_body
    assert "activityUpdate" in ai_body
    assert "cancel" in ai_body
    assert "activityGetLatest(`folder-view:${currentBatch}:${currentFolder}`)" in js
    assert "Loading visible thumbnails…" in js
    assert "No active work · ${records.length} recent" in js


def test_import_activity_uses_backend_outcome_and_preserves_pending_count() -> None:
    js = read_frontend_js()
    import_body = extract_function_body(js, "async function importAll()")

    assert "data.failed_count" in import_body
    assert "data.renamed_count" in import_body
    assert "data.pending_count" in import_body
    assert "activityComplete(activityId, importStatus" in import_body
    assert "updatePendingImportUi(pendingCount, batch)" in import_body
    assert "data.error || 'Import failed'" in import_body
    assert "throw error" not in import_body


def test_import_finally_repaints_button_before_offline_poll() -> None:
    js = read_frontend_js()
    import_body = extract_function_body(js, "async function importAll()")
    finally_body = import_body[import_body.rfind("finally {") :]

    clear_index = finally_body.index("importInFlight = false;")
    repaint_index = finally_body.index("updatePendingImportUi(")
    poll_index = finally_body.index("pollImportAvailability()")

    assert clear_index < repaint_index < poll_index
    assert "document.getElementById('pending-count')?.textContent" in finally_body
    assert "document.getElementById('active-batch-select')?.value" in finally_body


def test_activity_center_is_loaded_before_runtime_bootstrap_in_both_templates() -> None:
    index = INDEX_HTML.read_text(encoding="utf-8")
    curator = CURATOR_HTML.read_text(encoding="utf-8")

    for html, prefix in ((index, "/static/"), (curator, "/curator_static/")):
        activity = html.index(f"{prefix}js/activity-center.js")
        bootstrap = html.index(f"{prefix}js/bootstrap.js")
        assert activity < bootstrap


def test_async_adapters_cancel_superseded_attempts_without_reusing_ids() -> None:
    js = read_frontend_js()
    grid_start = js.index("async function loadCurrentFolderImages(options = {})")
    grid_body = js[grid_start : grid_start + 9000]
    prompt_start = js.index("async function buildSinglePromptIndex(batch, options = {})")
    prompt_body = js[prompt_start : prompt_start + 5000]

    assert "activityAttemptId(activityGroup, requestToken)" in grid_body
    assert "if (requestToken !== folderRequestToken)" in grid_body
    assert "activityRemove(activityId)" in grid_body
    assert "activityAttemptId(activityGroup, token)" in prompt_body
    assert "activityCancel(activityId)" in prompt_body


def test_activity_center_node_lifecycle() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node executable not found")
    completed = subprocess.run(
        [node, "tests/unit/activity_center_lifecycle_test.js"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Activity Center lifecycle assertions passed" in completed.stdout
