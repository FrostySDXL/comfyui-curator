from pathlib import Path


def _source(name: str) -> str:
    return (Path("static/js") / name).read_text(encoding="utf-8")


def test_move_history_source_defines_persistent_history_contract():
    js = _source("moves.js")
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert "function loadMoveHistory" in js
    assert "ccApiPath('/api/move-history')" in js
    assert "function showMoveHistoryModal" in js
    assert "move-batch/undo" in js
    assert "move-history-modal" in template


def test_undo_survives_toast_and_view_transitions():
    moves = _source("moves.js")
    state = _source("state.js")
    dom = _source("dom-utils.js")
    assert "expiresAt" not in moves
    assert (
        "lastAction = null"
        not in state[
            state.index("function beginViewTransition") : state.index("function getViewScopeKey")
        ]
    )
    toast_body = dom[dom.index("function showToast") : dom.index("function hideToast")]
    assert "lastAction = null" not in toast_body


def test_move_history_blocks_duplicate_undo_and_handles_partial_state():
    js = _source("moves.js")
    assert "moveHistoryUndoInflight" in js
    assert "data.status === 'partial'" in js or 'data.status === "partial"' in js
    assert "can_undo" in js


def test_dragging_snapshot_selection_uses_server_selection_operation():
    js = _source("moves.js")
    assert "draggedSnapshotSelection" in js
    assert "if (draggedSnapshotSelection) moveSelected(folder);" in js
    assert "isVirtualCollectionView() || isPublicView()" in js
    assert "const moveBatchScope = getViewScopeKey();" in js
