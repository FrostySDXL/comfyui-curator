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


def test_import_all_pending_skips_symlink_source_entries(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    pending = output_dir / "linked.png"
    pending.write_bytes(b"outside")
    real_is_symlink = batch_store.Path.is_symlink
    monkeypatch.setattr(
        batch_store.Path,
        "is_symlink",
        lambda path: True if path == pending else real_is_symlink(path),
    )

    count = batch_store.import_all_pending(output_dir, batches_dir, "alpha")

    assert count == 0
    assert pending.read_bytes() == b"outside"
    assert not (batches_dir / "alpha" / "inbox" / "linked.png").exists()


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


def test_validate_name_null_byte():
    """_validate_name raises ValueError for names containing null byte."""
    with pytest.raises(ValueError, match="null byte"):
        batch_store._validate_name("batch\0name")


def test_get_batch_folder_rejects_nonstandard_folder(tmp_path):
    """get_batch_folder raises ValueError for folders not in BATCH_FOLDERS."""
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "alpha")
    with pytest.raises(ValueError, match="Invalid folder"):
        batch_store.get_batch_folder(batches_dir, "alpha", "not-a-real-folder")


def test_import_all_pending_handles_duplicate_filenames(tmp_path):
    """duplicate filenames get collision-safe names instead of overwriting."""
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    # Pre-populate inbox with a file of the same name
    (batches_dir / "alpha" / "inbox" / "dup.png").write_bytes(b"existing")
    (output_dir / "dup.png").write_bytes(b"new-import")
    (output_dir / "unique.jpg").write_bytes(b"unique-file")

    count = batch_store.import_all_pending(output_dir, batches_dir, "alpha")

    # The existing file must still contain the original content
    assert (batches_dir / "alpha" / "inbox" / "dup.png").read_bytes() == b"existing"
    # A collision-safe file must exist for the duplicate name
    collision_files = list((batches_dir / "alpha" / "inbox").glob("dup_*.png"))
    assert len(collision_files) >= 1
    # The collision-safe file must contain the new content
    assert collision_files[0].read_bytes() == b"new-import"
    # The unique file is imported normally
    assert (batches_dir / "alpha" / "inbox" / "unique.jpg").exists()
    assert count == 2


# ---------------------------------------------------------------------------
# get_images tests
# ---------------------------------------------------------------------------


def test_get_images_returns_supported_files(tmp_path):
    """get_images returns only supported image files in a directory."""
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.jpg").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")

    result = batch_store.get_images(tmp_path, sort_by="name", order="asc")
    assert [p.name for p in result] == ["a.png", "b.jpg"]


def test_get_images_tolerates_file_deleted_between_iterdir_and_sort(tmp_path, monkeypatch):
    """get_images must not crash if a file vanishes between iterdir and sort.

    Regression: a previous version of the function called
    ``x.stat().st_mtime`` inside the sort key. If the file was deleted
    between ``iterdir()`` and the sort, the ``/api/images/...`` endpoint
    raised ``FileNotFoundError``.
    """
    kept = tmp_path / "kept.png"
    kept.write_bytes(b"x")
    deleted = tmp_path / "deleted.png"
    deleted.write_bytes(b"x")

    # Make ``Path.stat()`` for the ``deleted`` file raise, as if the
    # file had been removed between ``iterdir()`` and the sort key call.
    real_stat = batch_store.Path.stat

    def fake_stat(self, *args, **kwargs):
        if self.name == "deleted.png":
            raise FileNotFoundError(self)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(batch_store.Path, "stat", fake_stat)

    # Must not raise.
    result = batch_store.get_images(tmp_path, sort_by="date", order="desc")

    # The surviving file is present in the result. The missing file may
    # either be skipped (preferred) or listed but unstatable; we only
    # require that we got a result without raising.
    names = [p.name for p in result]
    assert "kept.png" in names
    # ``deleted.png`` should be filtered out because its stat() raised.
    assert "deleted.png" not in names


# ---------------------------------------------------------------------------
# move_image / move_images tests
# ---------------------------------------------------------------------------


def test_move_image_succeeds(tmp_path):
    """move_image moves a file from src to dst and returns True."""
    src = tmp_path / "src.png"
    dst = tmp_path / "dst.png"
    src.write_bytes(b"payload")
    assert batch_store.move_image(src, dst) is True
    assert not src.exists()
    assert dst.read_bytes() == b"payload"


def test_move_image_missing_src_returns_false(tmp_path):
    """move_image returns False (does not raise) if the source is missing."""
    src = tmp_path / "missing.png"
    dst = tmp_path / "dst.png"
    assert batch_store.move_image(src, dst) is False
    assert not dst.exists()


def test_move_image_creates_parent_dirs(tmp_path):
    """move_image creates missing parent directories for the destination."""
    src = tmp_path / "src.png"
    src.write_bytes(b"x")
    dst = tmp_path / "nested" / "deeper" / "dst.png"
    assert batch_store.move_image(src, dst) is True
    assert dst.read_bytes() == b"x"


def test_move_images_reports_moved_and_skipped(tmp_path):
    """move_images returns (moved_count, skipped_count) for a batch."""
    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "b.png").write_bytes(b"b")
    (tmp_path / "c.png").write_bytes(b"c")

    moved, skipped = batch_store.move_images(
        source_dir=tmp_path,
        names=["a.png", "b.png", "missing.png", "c.png"],
        dest_dir=tmp_path / "dest",
    )
    assert moved == 3
    assert skipped == 1
    assert sorted(p.name for p in (tmp_path / "dest").iterdir()) == ["a.png", "b.png", "c.png"]


# ---------------------------------------------------------------------------
# Defense-in-depth validation tests (H4, H5)
# ---------------------------------------------------------------------------


def test_get_batch_metadata_validates_batch_name(tmp_path):
    """get_batch_metadata raises ValueError for path-traversal batch names.

    Regression: a previous version of get_batch_metadata constructed
    ``Path(batches_dir) / batch_name`` directly with no validation,
    while every other public batch_store function called _validate_name.
    """
    with pytest.raises(ValueError, match="path separators"):
        batch_store.get_batch_metadata(tmp_path, "../escape")


def test_move_images_skips_names_with_path_separators(tmp_path):
    """move_images treats names containing path separators as skipped.

    Defense-in-depth: the API route already validates names via _safe_path,
    but move_images itself should reject unsafe names so any direct caller
    cannot trigger a path traversal.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "valid.png").write_bytes(b"x")
    (src / "ok_again.png").write_bytes(b"y")

    dest = tmp_path / "dest"
    dest.mkdir()

    moved, skipped = batch_store.move_images(
        source_dir=src,
        names=["valid.png", "../escape.png", "subdir/file.png", "ok_again.png"],
        dest_dir=dest,
    )

    assert moved == 2
    assert skipped == 2
    # The valid names actually landed in dest.
    assert (dest / "valid.png").exists()
    assert (dest / "ok_again.png").exists()
    # No traversal directory was created inside dest.
    assert not (dest / "subdir").exists()
    assert not (dest / "escape.png").exists()


def test_move_images_skips_dotfile_names(tmp_path):
    """move_images rejects dotfile names like '.hidden' or '..'."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "valid.png").write_bytes(b"x")

    dest = tmp_path / "dest"
    dest.mkdir()

    moved, skipped = batch_store.move_images(
        source_dir=src,
        names=["valid.png", ".hidden", ".."],
        dest_dir=dest,
    )

    assert moved == 1
    assert skipped == 2
    assert (dest / "valid.png").exists()
