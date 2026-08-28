from pathlib import Path

import image_curator.move_history as move_history
from image_curator import batch_store
from image_curator.move_history import MoveHistory
import pytest


def test_move_history_records_and_undoes_across_new_instance(tmp_path):
    root = tmp_path / "batches"
    source = root / "b" / "inbox"
    destination = root / "b" / "shortlisted"
    source.mkdir(parents=True)
    (source / "a.png").write_bytes(b"stable")

    history = MoveHistory(root)
    result = history.move("b", "inbox", "shortlisted", ["a.png"])
    assert result.moved == 1
    assert result.operation_id
    assert (destination / "a.png").exists()

    restarted = MoveHistory(root)
    operations = restarted.list_operations()
    assert operations[0]["id"] == result.operation_id
    assert operations[0]["can_undo"] is True
    undone = restarted.undo(result.operation_id)
    assert undone.moved == 1
    assert (source / "a.png").read_bytes() == b"stable"


def test_move_history_undo_is_newest_first_and_collision_is_partial(tmp_path):
    root = tmp_path / "batches"
    source = root / "b" / "inbox"
    source.mkdir(parents=True)
    (source / "a.png").write_bytes(b"a")
    (source / "b.png").write_bytes(b"b")
    history = MoveHistory(root)
    first = history.move("b", "inbox", "shortlisted", ["a.png"])
    second = history.move("b", "inbox", "shortlisted", ["b.png"])

    blocked = history.undo(first.operation_id)
    assert blocked.moved == 0
    assert blocked.status == "blocked"
    assert history.undo(second.operation_id).moved == 1

    # Replacing a moved file is detected by its content fingerprint.
    (source / "a.png").write_bytes(b"new")
    # The older operation remains unavailable until it is newest.
    assert history.list_operations()[0]["id"] == second.operation_id


def test_undo_rejects_parent_symlink_and_restart_reconciles_pending(tmp_path, monkeypatch):
    root = tmp_path / "batches"
    source = root / "b" / "inbox"
    destination = root / "b" / "shortlisted"
    source.mkdir(parents=True)
    (source / "a.png").write_bytes(b"stable")
    history = MoveHistory(root)
    original_save = history._save
    calls = 0

    def fail_final(operations):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated persistence failure")
        return original_save(operations)

    monkeypatch.setattr(history, "_save", fail_final)
    with pytest.raises(OSError):
        history.move("b", "inbox", "shortlisted", ["a.png"])
    assert (destination / "a.png").exists()
    restarted = MoveHistory(root)
    assert restarted.list_operations()[0]["status"] == "available"

    # Parent symlinks are rejected before any restore filesystem operation.
    (root / "b" / "inbox").rmdir()
    try:
        (root / "b" / "inbox").symlink_to(tmp_path / "escape", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    result = restarted.undo(restarted.list_operations()[0]["id"])
    assert result.moved == 0


def test_configured_root_symlink_uses_target_for_move_and_restart_undo(tmp_path, monkeypatch):
    target = tmp_path / "external-library"
    batch = target / "batch"
    (batch / "inbox").mkdir(parents=True)
    (batch / "shortlisted").mkdir()
    media = batch / "inbox" / "image.png"
    media.write_bytes(b"image")
    alias = tmp_path / "library-alias"
    real_resolve = Path.resolve
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *args, **kwargs: (
            target if path == alias else real_resolve(path, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == alias else real_is_symlink(path),
    )

    history = MoveHistory(alias)
    result = history.move("batch", "inbox", "shortlisted", [media.name])
    assert result.moved == 1
    assert (batch / "shortlisted" / media.name).is_file()

    restarted = MoveHistory(alias)
    assert restarted.undo(result.operation_id).status == "undone"
    assert media.is_file()


def test_symlink_loop_root_fails_on_use_not_constructor(tmp_path, monkeypatch):
    root = tmp_path / "loop"
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == root:
            raise RuntimeError("symlink loop")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    real_lexists = move_history.os.path.lexists
    monkeypatch.setattr(
        move_history.os.path,
        "lexists",
        lambda path: True if Path(path) == root else real_lexists(path),
    )
    history = MoveHistory(root)
    with pytest.raises(OSError, match="Unsafe move history storage"):
        history.list_operations()


def test_history_save_ignores_stale_fixed_tmp_and_cleans_failed_unique_tmp(tmp_path, monkeypatch):
    root = tmp_path / "batches"
    history = MoveHistory(root)
    history.dir.mkdir(parents=True)
    stale = history.dir / "history.json.tmp"
    stale.write_text("stale", encoding="utf-8")

    history._save([])
    assert history.path.read_text(encoding="utf-8") == "[]"
    assert stale.read_text(encoding="utf-8") == "stale"

    real_open = move_history.os.open

    def fail_open(path, *args, **kwargs):
        if Path(path).parent == history.dir and Path(path).name.startswith(".history-"):
            raise OSError("injected write failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(move_history.os, "open", fail_open)
    with pytest.raises(OSError):
        history._save([])
    assert not any(item.name.startswith(".history-") for item in history.dir.iterdir())


def test_history_load_rejects_oversized_and_strictly_malformed_records(tmp_path, monkeypatch):
    root = tmp_path / "batches"
    history = MoveHistory(root)
    history.dir.mkdir(parents=True)
    monkeypatch.setattr(move_history, "MAX_HISTORY_BYTES", 1024)
    history.path.write_bytes(b"[" + b" " * 2048 + b"]")
    with pytest.raises(OSError, match="Invalid move history"):
        history._load()

    history.path.write_text(
        '[{"id":"bad","batch":"../escape","source":"inbox",'
        '"destination":"shortlisted","created_at":"2026-01-01T00:00:00",'
        '"status":"available","count":1,"items":[]}]',
        encoding="utf-8",
    )
    with pytest.raises(OSError, match="Invalid move history"):
        history._load()


def test_selected_sidecar_moves_while_unselected_fallback_remains_paired(tmp_path):
    root = tmp_path / "batches"
    source = root / "b" / "inbox"
    destination = root / "b" / "shortlisted"
    source.mkdir(parents=True)
    (source / "a.png").write_bytes(b"image")
    (source / "a.png.json").write_bytes(b"preferred")
    (source / "a.json").write_bytes(b"fallback")
    history = MoveHistory(root)

    receipt = history.move("b", "inbox", "shortlisted", ["a.png"])
    assert (destination / "a.png.json").read_bytes() == b"preferred"
    assert (source / "a.json").read_bytes() == b"fallback"
    assert history.undo(receipt.operation_id).moved == 1
    assert (source / "a.png.json").read_bytes() == b"preferred"
    assert (source / "a.json").read_bytes() == b"fallback"


def test_failed_partial_pair_transfer_remains_in_history_with_zero_moved(tmp_path, monkeypatch):
    root = tmp_path / "batches"
    source = root / "b" / "inbox"
    destination = root / "b" / "shortlisted"
    source.mkdir(parents=True)
    media = source / "clip.mp4"
    sidecar = source / "clip.mp4.json"
    media.write_bytes(b"video")
    sidecar.write_bytes(b"metadata")

    def leave_media_only(src, dst, *, no_overwrite=False):
        assert no_overwrite is True
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return False

    monkeypatch.setattr(batch_store, "move_image", leave_media_only)
    result = MoveHistory(root).move("b", "inbox", "shortlisted", [media.name])

    assert result.moved == 0
    assert result.skipped == 1
    assert result.operation_id is not None
    operation = MoveHistory(root).list_operations()[0]
    assert operation["count"] == 1
    assert operation["status"] in {"partial", "blocked"}
    assert "clip.mp4" in operation["error"]
    assert (destination / media.name).exists()
    assert sidecar.exists()


@pytest.mark.parametrize("leftover", ["destination", "source"])
def test_restart_reconciliation_never_declares_undo_complete_with_leftover_sidecar(
    tmp_path, leftover
):
    root = tmp_path / "batches"
    source = root / "b" / "inbox"
    destination = root / "b" / "shortlisted"
    source.mkdir(parents=True)
    (source / "a.png").write_bytes(b"stable")
    (source / "a.png.json").write_bytes(b"meta")
    history = MoveHistory(root)
    receipt = history.move("b", "inbox", "shortlisted", ["a.png"])
    # Undo journal is intentionally left pending, simulating a crash during
    # the pair transfer. Recreate one exact media side and one orphan side.
    if leftover == "destination":
        (destination / "a.png.json").write_bytes(b"orphan")
    else:
        (source / "a.png.json").write_bytes(b"orphan")
    operations = history._load()
    operations[0]["status"] = "undo_pending"
    history._save(operations)
    restarted = MoveHistory(root)
    assert restarted.list_operations()[0]["status"] != "undone"
    assert restarted.undo(receipt.operation_id).status != "undone"
