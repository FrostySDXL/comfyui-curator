import pytest

from image_curator import batch_store


@pytest.mark.unit
def test_batch_store_creates_batches_and_counts_supported_images(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "alpha")
    (batches_dir / "alpha" / "inbox" / "one.png").write_bytes(b"x")
    (batches_dir / "alpha" / "inbox" / "ignore.txt").write_text("x")
    (batches_dir / "alpha" / "finals" / "two.webp").write_bytes(b"x")

    assert batch_store.get_batches(batches_dir) == ["alpha"]
    assert batch_store.get_batch_counts(batches_dir, "alpha") == {
        "inbox": 1,
        "shortlisted": 0,
        "finals": 1,
        "rejects": 0,
    }


@pytest.mark.unit
def test_batch_store_imports_pending_images(tmp_path):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    (output_dir / "one.png").write_bytes(b"x")
    (output_dir / "two.jpg").write_bytes(b"x")
    (output_dir / "skip.txt").write_text("x")

    count = batch_store.import_all_pending(output_dir, batches_dir, "alpha")

    assert count == 2
    assert (batches_dir / "alpha" / "inbox" / "one.png").exists()
    assert (batches_dir / "alpha" / "inbox" / "two.jpg").exists()
    assert (output_dir / "skip.txt").exists()


@pytest.mark.unit
def test_batch_store_import_all_pending_continues_after_move_failure(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    (output_dir / "fails.png").write_bytes(b"x")
    (output_dir / "moves.jpg").write_bytes(b"x")

    original_move = batch_store.shutil.move

    def fail_one_move(src, dst):
        if src.endswith("fails.png"):
            raise OSError("simulated move failure")
        return original_move(src, dst)

    monkeypatch.setattr(batch_store.shutil, "move", fail_one_move)

    count = batch_store.import_all_pending(output_dir, batches_dir, "alpha")

    assert count == 1
    assert (output_dir / "fails.png").exists()
    assert (batches_dir / "alpha" / "inbox" / "moves.jpg").exists()
