"""Independent acceptance checks for persistent manual-move recovery."""

from pathlib import Path

import pytest

from image_curator.move_history import MoveHistory


@pytest.fixture
def library(tmp_path):
    for stage in ("inbox", "shortlisted", "finals", "rejects"):
        (tmp_path / "batch" / stage).mkdir(parents=True)
    return tmp_path


def media(root: Path, stage: str, name: str = "a.png") -> Path:
    return root / "batch" / stage / name


def test_partial_move_records_only_actual_members_and_preserves_collision(library):
    media(library, "inbox").write_bytes(b"original")
    media(library, "inbox", "b.mp4").write_bytes(b"video")
    media(library, "shortlisted").write_bytes(b"existing destination")
    history = MoveHistory(library)
    result = history.move("batch", "inbox", "shortlisted", ["a.png", "b.mp4"])
    assert (result.moved, result.skipped) == (1, 1)
    assert history.list_operations()[0]["count"] == 1
    assert history.undo(result.operation_id).moved == 1
    assert media(library, "inbox").read_bytes() == b"original"
    assert media(library, "shortlisted").read_bytes() == b"existing destination"
    assert media(library, "inbox", "b.mp4").read_bytes() == b"video"


def test_partial_undo_retries_only_remaining_files_after_restart(library):
    for name in ("a.png", "b.mp4"):
        media(library, "inbox", name).write_bytes(name.encode())
    history = MoveHistory(library)
    receipt = history.move("batch", "inbox", "shortlisted", ["a.png", "b.mp4"])
    media(library, "inbox").write_bytes(b"conflict")
    first = history.undo(receipt.operation_id)
    assert (first.moved, first.remaining, first.status) == (1, 1, "partial")
    assert media(library, "inbox").read_bytes() == b"conflict"
    # Explicitly remove only this test's conflict, never library media.
    media(library, "inbox").unlink()
    restarted = MoveHistory(library)
    assert restarted.list_operations()[0]["can_undo"]
    second = restarted.undo(receipt.operation_id)
    assert (second.moved, second.remaining, second.status) == (1, 0, "undone")
    assert restarted.list_operations()[0]["restored"] == 2
    assert restarted.undo(receipt.operation_id).moved == 0


@pytest.mark.parametrize("sidecar_name", ["a.png.json", "a.json"])
def test_exact_sidecar_moves_and_restores_without_changing_bytes(library, sidecar_name):
    media(library, "inbox").write_bytes(b"image")
    sidecar = media(library, "inbox", sidecar_name)
    sidecar.write_bytes(b'{"original_type":"123"}')
    history = MoveHistory(library)
    receipt = history.move("batch", "inbox", "shortlisted", ["a.png"])
    assert not sidecar.exists()
    assert history.undo(receipt.operation_id).moved == 1
    assert sidecar.read_bytes() == b'{"original_type":"123"}'


def test_unrecorded_new_sidecar_blocks_undo_without_moving_it(library):
    media(library, "inbox").write_bytes(b"image")
    history = MoveHistory(library)
    receipt = history.move("batch", "inbox", "shortlisted", ["a.png"])
    media(library, "shortlisted", "a.png.json").write_bytes(b"new auxiliary file")
    result = history.undo(receipt.operation_id)
    assert result.moved == 0
    assert result.remaining == 1
    assert not media(library, "inbox").exists()
    assert media(library, "shortlisted", "a.png.json").read_bytes() == b"new auxiliary file"


def test_new_preferred_sidecar_blocks_old_fallback_receipt(library):
    media(library, "inbox").write_bytes(b"image")
    media(library, "inbox", "a.json").write_bytes(b"old fallback")
    history = MoveHistory(library)
    receipt = history.move("batch", "inbox", "shortlisted", ["a.png"])
    media(library, "shortlisted", "a.png.json").write_bytes(b"new preferred")
    assert history.undo(receipt.operation_id).moved == 0
    assert media(library, "shortlisted", "a.json").read_bytes() == b"old fallback"
    assert not media(library, "inbox").exists()


def test_preferred_sidecar_undo_preserves_unselected_fallback(library):
    media(library, "inbox").write_bytes(b"image")
    media(library, "inbox", "a.png.json").write_bytes(b"preferred")
    media(library, "inbox", "a.json").write_bytes(b"unselected fallback")
    history = MoveHistory(library)
    receipt = history.move("batch", "inbox", "shortlisted", ["a.png"])
    assert media(library, "inbox", "a.json").read_bytes() == b"unselected fallback"
    assert history.undo(receipt.operation_id).moved == 1
    assert media(library, "inbox", "a.png.json").read_bytes() == b"preferred"
    assert media(library, "inbox", "a.json").read_bytes() == b"unselected fallback"


def test_same_image_chain_undo_is_lifo_across_instances(library):
    media(library, "inbox").write_bytes(b"original")
    history = MoveHistory(library)
    first = history.move("batch", "inbox", "shortlisted", ["a.png"])
    second = history.move("batch", "shortlisted", "finals", ["a.png"])
    assert history.undo(first.operation_id).status == "blocked"
    assert MoveHistory(library).undo(second.operation_id).moved == 1
    assert MoveHistory(library).undo(first.operation_id).moved == 1
    assert media(library, "inbox").read_bytes() == b"original"


def test_failed_noop_does_not_block_previous_valid_history(library):
    media(library, "inbox").write_bytes(b"image")
    history = MoveHistory(library)
    receipt = history.move("batch", "inbox", "shortlisted", ["a.png"])
    noop = history.move("batch", "inbox", "inbox", ["a.png"])
    missing = history.move("batch", "inbox", "finals", ["missing.png"])
    assert noop.operation_id is None and missing.operation_id is None
    assert history.list_operations()[0]["id"] == receipt.operation_id
    assert history.undo(receipt.operation_id).moved == 1


def test_final_move_save_failure_is_recoverable_not_just_listed(library, monkeypatch):
    media(library, "inbox").write_bytes(b"image")
    history = MoveHistory(library)
    save = history._save
    calls = 0

    def fail_final(operations):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected final-save failure")
        save(operations)

    monkeypatch.setattr(history, "_save", fail_final)
    with pytest.raises(OSError):
        history.move("batch", "inbox", "shortlisted", ["a.png"])
    restarted = MoveHistory(library)
    operation = restarted.list_operations()[0]
    assert operation["can_undo"]
    assert restarted.undo(operation["id"]).moved == 1
    assert media(library, "inbox").read_bytes() == b"image"


def test_final_undo_save_failure_reconciles_as_undone(library, monkeypatch):
    media(library, "inbox").write_bytes(b"image")
    history = MoveHistory(library)
    receipt = history.move("batch", "inbox", "shortlisted", ["a.png"])
    save = history._save
    calls = 0

    def fail_final(operations):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected undo-save failure")
        save(operations)

    monkeypatch.setattr(history, "_save", fail_final)
    with pytest.raises(OSError):
        history.undo(receipt.operation_id)
    assert media(library, "inbox").read_bytes() == b"image"
    restarted = MoveHistory(library)
    assert restarted.list_operations()[0]["status"] == "undone"
    assert restarted.undo(receipt.operation_id).status == "undone"
