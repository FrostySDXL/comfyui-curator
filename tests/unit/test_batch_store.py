import pytest

from image_curator import batch_store


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


# ---------------------------------------------------------------------------
# _validate_name tests
# ---------------------------------------------------------------------------


def test_validate_name_empty():
    """_validate_name raises ValueError for empty name."""
    with pytest.raises(ValueError, match="empty"):
        batch_store._validate_name("")


def test_validate_name_whitespace_only():
    """_validate_name raises ValueError for whitespace-only name."""
    with pytest.raises(ValueError, match="empty"):
        batch_store._validate_name("   ")


def test_validate_name_forward_slash():
    """_validate_name raises ValueError for names with forward slash."""
    with pytest.raises(ValueError, match="path separators"):
        batch_store._validate_name("foo/bar")


def test_validate_name_backslash():
    """_validate_name raises ValueError for names with backslash."""
    with pytest.raises(ValueError, match="path separators"):
        batch_store._validate_name("foo\\bar")


def test_validate_name_dot():
    """_validate_name raises ValueError for '.' name."""
    with pytest.raises(ValueError, match="reserved path component"):
        batch_store._validate_name(".")


def test_validate_name_dotdot():
    """_validate_name raises ValueError for '..' name."""
    with pytest.raises(ValueError, match="reserved path component"):
        batch_store._validate_name("..")


def test_validate_name_valid_simple():
    """_validate_name returns None for a valid simple name."""
    assert batch_store._validate_name("my-batch") is None


def test_validate_name_valid_with_underscores():
    """_validate_name returns None for a valid name with underscores."""
    assert batch_store._validate_name("batch_2026_v2") is None
