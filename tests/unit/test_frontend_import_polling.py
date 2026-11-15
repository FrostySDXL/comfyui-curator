import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.frontend_source import extract_function_body, read_frontend_css, read_frontend_js


def test_lightweight_import_status_poll_updates_visible_disabled_control() -> None:
    js = read_frontend_js()
    update = extract_function_body(js, "function updatePendingImportUi(pendingCount, activeBatch)")
    poll = extract_function_body(js, "async function pollImportAvailability()")

    assert "importBtn.disabled = importInFlight || normalizedCount < 1 || !activeBatch" in update
    assert "data.auto_import_enabled" in poll
    assert "data.auto_import_error" in poll
    assert "data.auto_import_failure" in poll
    assert "failureKey !== lastAutoImportFailureKey" in poll
    assert "failure.paused ? 'failed' : 'partial'" in poll
    assert "ccApiPath('/api/import-status')" in poll
    assert "updatePendingImportUi(data.pending_count, data.active_batch)" in poll


def test_import_controls_share_existing_header_and_destination_lives_in_settings() -> None:
    html = Path("templates/index.html").read_text(encoding="utf-8")
    css = read_frontend_css()
    header = html.split('<div class="header">', 1)[1].split(
        '<section id="activity-center-panel"', 1
    )[0]
    settings = html.split('id="settings-modal"', 1)[1].split("<!-- Toast -->", 1)[0]
    assert 'id="auto-import-status"' in header
    assert 'id="pending-count"' in header
    assert 'class="help-btn import-btn"' in header
    assert 'id="active-batch-input"' not in header
    assert 'id="set-auto-import-btn" class="help-btn hidden"' in header
    assert header.index('id="pending-info"') < header.index('class="help-btn import-btn"')
    assert header.index('class="help-btn import-btn"') < header.index(
        'id="batch-sidebar-toggle-btn"'
    )
    assert 'class="import-workspace"' not in html
    assert 'id="active-batch-input"' in settings
    assert 'id="active-batch-select"' in settings
    assert "Destination changes save immediately" in settings
    assert ".header-import-status" in css
    assert ".header .import-btn:disabled" in css
    assert ".set-auto-import-btn" not in css
    for source in ("static/js/favorites.js", "static/js/publish.js"):
        assert "updateAutoImportQuickAction(" in Path(source).read_text(encoding="utf-8")


def test_bootstrap_polls_import_status_and_native_batch_summaries_separately() -> None:
    js = read_frontend_js()

    assert "pollImportAvailability" in js
    assert "}, 1000);" in js
    assert "pollNativeBatchSummaries" in js
    assert "}, 10000);" in js


def test_shuffle_import_refresh_executes_real_scripts() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    subprocess.run([node, "tests/unit/shuffle_import_refresh_test.js"], check=True, timeout=15)
