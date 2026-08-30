"""Standalone large-folder paging: revisioned paged path replaces full-listing refetches."""

from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def _function_body(source: str, signature: str) -> str:
    start = source.find(signature)
    assert start != -1, f"Could not locate {signature}"
    paren_close = source.find(")", start)
    assert paren_close != -1, f"Could not locate parameter list end for {signature}"
    brace_start = source.find("{", paren_close)
    assert brace_start != -1, f"Could not locate function body for {signature}"
    depth = 0
    in_string = None
    in_line_comment = False
    in_block_comment = False
    index = brace_start
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == in_string:
                in_string = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        if char in {'"', "'", "`"}:
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"Could not find end of function body for {signature}")


def test_paged_folder_threshold_constant_defined_in_state() -> None:
    state = Path("static/js/state.js").read_text(encoding="utf-8")

    assert "const PAGED_FOLDER_THRESHOLD = 2000;" in state


def test_standalone_large_folders_use_paged_path_in_folder_loader() -> None:
    body = _function_body(
        read_frontend_js(), "async function loadCurrentFolderImages(options = {})"
    )

    assert "const folderCountHint = allCounts[batch]?.[folder];" in body
    assert "folderCountHint >= PAGED_FOLDER_THRESHOLD" in body
    assert "if (usePagedFolder) {" in body
    assert "_waitForFolderSnapshot(batch, folder, requestToken)" in body
    assert "pagedFolderMode = true;" in body
    assert "ensureFolderPageForIndex(0)" in body
    assert "if (requiresMaterializedNativeFolder()) {" in body
    assert "if (CURATOR_NATIVE) {" not in body


def test_standalone_paged_folders_use_revision_poll() -> None:
    body = extract_function_body(read_frontend_js(), "async function pollForChanges()")

    assert "const folderCountHint = allCounts[currentBatch]?.[currentFolder];" in body
    assert "const usesPagedFolderTransport = Boolean(folderSnapshot)" in body
    assert "folderCountHint >= PAGED_FOLDER_THRESHOLD" in body
    assert "if (usesPagedFolderTransport) {" in body
    assert "if (!folderSnapshot) return;" in body
    assert "apiPollFolderSnapshot(" in body
    assert "if (CURATOR_NATIVE && folderSnapshot)" not in body
    assert "/api/images/${currentBatch}/${currentFolder}" in body
    assert "if (!CURATOR_NATIVE) await loadBatches();" in body
