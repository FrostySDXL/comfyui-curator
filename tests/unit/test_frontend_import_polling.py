from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_lightweight_import_status_poll_updates_visible_disabled_control() -> None:
    js = read_frontend_js()
    update = extract_function_body(js, "function updatePendingImportUi(pendingCount, activeBatch)")
    poll = extract_function_body(js, "async function pollImportAvailability()")

    assert "pendingInfo.style.display = activeBatch ? 'flex' : 'none'" in update
    assert "importBtn.disabled = importInFlight || normalizedCount < 1" in update
    assert "ccApiPath('/api/import-status')" in poll
    assert "updatePendingImportUi(data.pending_count, data.active_batch)" in poll


def test_bootstrap_polls_import_status_and_native_batch_summaries_separately() -> None:
    js = read_frontend_js()

    assert "pollImportAvailability" in js
    assert "}, 1000);" in js
    assert "pollNativeBatchSummaries" in js
    assert "}, 10000);" in js
