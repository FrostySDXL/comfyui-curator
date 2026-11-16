"""Native paged folders: immutable snapshots, 256-item pages, revision polling."""

from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def test_folder_page_size_and_native_transport_are_defined() -> None:
    state = Path("static/js/state.js").read_text(encoding="utf-8")

    assert "const FOLDER_PAGE_SIZE = 256;" in state
    assert "PAGED_FOLDER_THRESHOLD" not in state
    assert "CURATOR_NATIVE" not in state


def test_folder_loader_always_uses_the_revisioned_paged_path() -> None:
    body = extract_function_body(
        read_frontend_js(), "async function loadCurrentFolderImages(options = {})"
    )

    assert "const snapshot = await _waitForFolderSnapshot(batch, folder, requestToken);" in body
    assert "pagedFolderMode = true;" in body
    assert "ensureFolderPageForIndex(0)" in body
    assert "if (requiresMaterializedNativeFolder()) {" in body
    assert "FOLDER_PAGE_SIZE" in body
    assert "folderCountHint" not in body
    assert "PAGED_FOLDER_THRESHOLD" not in body
    assert "CURATOR_NATIVE" not in body


def test_folder_poll_uses_the_snapshot_revision_only() -> None:
    body = extract_function_body(read_frontend_js(), "async function pollForChanges()")

    assert "if (!folderSnapshot) return;" in body
    assert "apiPollFolderSnapshot(" in body
    assert "folderSnapshot.revision" in body
    assert "loadCurrentFolderImages({preserveScroll: true})" in body
    assert "importSnapshotLoad" not in body
    assert "folderCountHint" not in body
    assert "PAGED_FOLDER_THRESHOLD" not in body
    assert "CURATOR_NATIVE" not in body
