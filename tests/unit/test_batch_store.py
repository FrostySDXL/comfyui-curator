"""Unit tests for image_curator.batch_store."""

from pathlib import Path

import pytest

from image_curator import batch_store


def test_media_extension_sets_and_kinds_preserve_still_image_boundary():
    assert batch_store.STILL_IMAGE_EXTENSIONS == {".png", ".jpg", ".jpeg", ".webp"}
    assert batch_store.IMAGE_EXTENSIONS == batch_store.STILL_IMAGE_EXTENSIONS
    assert batch_store.ANIMATED_IMAGE_EXTENSIONS == {".gif"}
    assert batch_store.VIDEO_EXTENSIONS == {".mp4"}
    assert batch_store.AUDIO_EXTENSIONS == {".mp3"}
    assert batch_store.VIEWABLE_MEDIA_EXTENSIONS == {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".mp4",
        ".mp3",
    }
    assert [batch_store.media_kind(name) for name in ("a.PNG", "b.gif", "c.mp4", "d.MP3")] == [
        "image",
        "animated_image",
        "video",
        "audio",
    ]
    assert batch_store.media_kind("notes.txt") is None


def test_batch_listing_counts_and_import_include_all_viewable_media(tmp_path):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    for name in (
        "still.png",
        "photo.jpg",
        "photo.jpeg",
        "web.webp",
        "loop.gif",
        "clip.mp4",
        "sound.mp3",
    ):
        (output_dir / name).write_bytes(b"media")
    (output_dir / "skip.txt").write_text("skip")

    assert batch_store.get_pending_count(output_dir) == 7
    assert batch_store.import_all_pending(output_dir, batches_dir, "alpha") == 7
    listed = batch_store.get_images(batches_dir / "alpha" / "inbox", sort_by="name", order="asc")
    assert [item.name for item in listed] == [
        "clip.mp4",
        "loop.gif",
        "photo.jpeg",
        "photo.jpg",
        "sound.mp3",
        "still.png",
        "web.webp",
    ]
    assert batch_store.get_batch_counts(batches_dir, "alpha")["inbox"] == 7


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


def test_import_all_pending_detailed_reports_failures_collisions_and_remaining_media(
    tmp_path, monkeypatch
):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    inbox = batches_dir / "alpha" / "inbox"
    (inbox / "duplicate.png").write_bytes(b"existing")
    (output_dir / "duplicate.png").write_bytes(b"new")
    (output_dir / "good.jpg").write_bytes(b"good")
    (output_dir / "failed.webp").write_bytes(b"failed")
    (output_dir / "ignored.txt").write_text("ignored", encoding="utf-8")
    (output_dir / "nested").mkdir()

    original_move = batch_store.move_image

    def fail_one(src, dst, **kwargs):
        if Path(src).name == "failed.webp":
            return False
        return original_move(src, dst, **kwargs)

    monkeypatch.setattr(batch_store, "move_image", fail_one)

    result = batch_store.import_all_pending_detailed(output_dir, batches_dir, "alpha")

    assert result.imported_count == 2
    assert result.failed_count == 1
    assert result.renamed_count == 1
    assert result.pending_count == 1
    assert result.status == "partial"


def test_import_detailed_rejects_missing_batch_before_source_mutation(tmp_path):
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    pending = output_dir / "pending.png"
    pending.write_bytes(b"pending")

    with pytest.raises(ValueError, match="Invalid import destination"):
        batch_store.import_all_pending_detailed(output_dir, tmp_path / "batches", "missing")

    assert pending.exists()
    assert not (tmp_path / "batches" / "missing").exists()


def test_import_detailed_rejects_inbox_outside_root_before_source_mutation(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    pending = output_dir / "pending.png"
    pending.write_bytes(b"pending")
    inbox = batches_dir / "alpha" / "inbox"
    outside = tmp_path / "outside-inbox"
    outside.mkdir()
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == inbox:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    with pytest.raises(ValueError, match="Invalid import destination"):
        batch_store.import_all_pending_detailed(output_dir, batches_dir, "alpha")

    assert pending.exists()
    assert not list(outside.iterdir())


def test_import_detailed_allows_configured_root_symlink(tmp_path):
    real_root = tmp_path / "real-batches"
    configured_root = tmp_path / "configured-batches"
    output_dir = tmp_path / "comfyui-outputs"
    real_root.mkdir()
    output_dir.mkdir()
    try:
        configured_root.symlink_to(real_root, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation unavailable")
    batch_store.create_batch(real_root, "alpha")
    (output_dir / "pending.png").write_bytes(b"pending")

    result = batch_store.import_all_pending_detailed(output_dir, configured_root, "alpha")

    assert result.imported_count == 1
    assert (real_root / "alpha" / "inbox" / "pending.png").exists()


def test_get_pending_count_ignores_directories_symlinks_and_stat_errors(tmp_path, monkeypatch):
    output_dir = tmp_path / "comfyui-outputs"
    output_dir.mkdir()
    (output_dir / "good.png").write_bytes(b"good")
    (output_dir / "nested").mkdir()
    linked = output_dir / "linked.png"
    linked.write_bytes(b"linked")
    real_is_symlink = Path.is_symlink

    def is_symlink(path):
        if path == linked:
            return True
        return real_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    real_is_file = Path.is_file

    def is_file(path):
        if path.name == "good.png":
            raise OSError("vanished")
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", is_file)

    assert batch_store.get_pending_count(output_dir) == 0


def test_import_renames_media_when_its_json_sidecar_destination_collides(tmp_path):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "incoming"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    inbox = batches_dir / "alpha" / "inbox"
    (inbox / "favorite.json").write_text('{"existing": true}', encoding="utf-8")
    (output_dir / "favorite.png").write_bytes(b"image")
    (output_dir / "favorite.json").write_text('{"rating": 5}', encoding="utf-8")

    assert batch_store.import_all_pending(output_dir, batches_dir, "alpha") == 1

    assert (inbox / "favorite_1.png").read_bytes() == b"image"
    assert (inbox / "favorite_1.json").read_text(encoding="utf-8") == '{"rating": 5}'
    assert (inbox / "favorite.json").read_text(encoding="utf-8") == '{"existing": true}'


def test_import_detailed_counts_media_sidecar_failure_as_failed_and_pending(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    output_dir = tmp_path / "incoming"
    output_dir.mkdir()
    batch_store.create_batch(batches_dir, "alpha")
    media = output_dir / "clip.mp4"
    sidecar = output_dir / "clip.mp4.json"
    media.write_bytes(b"video")
    sidecar.write_text('{"source": "test"}', encoding="utf-8")
    original_move = batch_store.shutil.move

    def fail_sidecar(src, dst):
        if Path(src) == sidecar:
            raise OSError("simulated sidecar failure")
        return original_move(src, dst)

    monkeypatch.setattr(batch_store.shutil, "move", fail_sidecar)

    result = batch_store.import_all_pending_detailed(output_dir, batches_dir, "alpha")

    assert result.imported_count == 0
    assert result.failed_count == 1
    assert result.renamed_count == 0
    assert result.pending_count == 1
    assert result.status == "partial"
    assert media.exists()
    assert sidecar.exists()


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


def test_move_image_carries_filename_preserving_json_sidecar(tmp_path):
    src = tmp_path / "source" / "clip.mp4"
    src.parent.mkdir()
    src.write_bytes(b"video")
    sidecar = src.with_name("clip.mp4.json")
    sidecar.write_text('{"rating": 5}', encoding="utf-8")
    dst = tmp_path / "dest" / "renamed.mp4"

    assert batch_store.move_image(src, dst) is True

    assert dst.read_bytes() == b"video"
    assert dst.with_name("renamed.mp4.json").read_text(encoding="utf-8") == '{"rating": 5}'
    assert not sidecar.exists()


def test_move_image_no_overwrite_uses_exclusive_transfer_and_rolls_back_pair(tmp_path, monkeypatch):
    """No-overwrite moves must not call overwrite-capable shutil.move.

    If the paired sidecar transfer fails after the media has been installed,
    both destination entries are removed and both source entries remain.
    """
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    media = source / "clip.mp4"
    sidecar = source / "clip.mp4.json"
    media.write_bytes(b"video")
    sidecar.write_bytes(b"metadata")

    def fail_shutil(*_args, **_kwargs):
        raise AssertionError("no-overwrite must not use shutil.move")

    monkeypatch.setattr(batch_store.shutil, "move", fail_shutil)
    real_link = batch_store.os.link

    def fail_sidecar(src, dst, *args, **kwargs):
        if str(src).endswith("clip.mp4.json"):
            raise OSError("injected sidecar collision")
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(batch_store.os, "link", fail_sidecar)

    assert batch_store.move_image(media, destination / media.name, no_overwrite=True) is False
    assert media.read_bytes() == b"video"
    assert sidecar.read_bytes() == b"metadata"
    assert not (destination / media.name).exists()
    assert not (destination / sidecar.name).exists()


def test_move_image_no_overwrite_rejects_existing_media_and_sidecar(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    media = source / "clip.mp4"
    sidecar = source / "clip.mp4.json"
    media.write_bytes(b"source")
    sidecar.write_bytes(b"source-sidecar")
    (destination / media.name).write_bytes(b"destination")
    (destination / sidecar.name).write_bytes(b"destination-sidecar")

    assert batch_store.move_image(media, destination / media.name, no_overwrite=True) is False
    assert media.read_bytes() == b"source"
    assert sidecar.read_bytes() == b"source-sidecar"
    assert (destination / media.name).read_bytes() == b"destination"
    assert (destination / sidecar.name).read_bytes() == b"destination-sidecar"


def test_move_images_reports_moved_and_skipped(tmp_path):
    """move_images returns (moved_count, skipped_count) for a batch."""
    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "b.png").write_bytes(b"b")
    (tmp_path / "c.png").write_bytes(b"c")

    moved, skipped, moved_names = batch_store.move_images(
        source_dir=tmp_path,
        names=["a.png", "b.png", "missing.png", "c.png"],
        dest_dir=tmp_path / "dest",
    )
    assert moved == 3
    assert skipped == 1
    assert moved_names == ["a.png", "b.png", "c.png"]
    assert sorted(p.name for p in (tmp_path / "dest").iterdir()) == ["a.png", "b.png", "c.png"]


def test_move_images_returns_only_exact_successful_names(tmp_path):
    """Partial failures must never enter a snapshot undo record."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "moved.png").write_bytes(b"moved")
    (source / "also-moved.png").write_bytes(b"also")

    moved, skipped, moved_names = batch_store.move_images(
        source_dir=source,
        names=["moved.png", "missing.png", "also-moved.png"],
        dest_dir=tmp_path / "dest",
    )

    assert moved == 2
    assert skipped == 1
    assert moved_names == ["moved.png", "also-moved.png"]


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

    moved, skipped, moved_names = batch_store.move_images(
        source_dir=src,
        names=["valid.png", "../escape.png", "subdir/file.png", "ok_again.png"],
        dest_dir=dest,
    )

    assert moved == 2
    assert skipped == 2
    assert moved_names == ["valid.png", "ok_again.png"]
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

    moved, skipped, moved_names = batch_store.move_images(
        source_dir=src,
        names=["valid.png", ".hidden", ".."],
        dest_dir=dest,
    )

    assert moved == 1
    assert skipped == 2
    assert moved_names == ["valid.png"]
    assert (dest / "valid.png").exists()


# ---------------------------------------------------------------------------
# State-file safety tests
# ---------------------------------------------------------------------------


def test_load_state_rejects_symlinked_target(tmp_path):
    """load_state returns default dict when state file is a symlink."""
    state_file = tmp_path / "state.json"
    outside = tmp_path / "outside.json"
    outside.write_text('{"active_batch": "escaped"}', encoding="utf-8")
    try:
        state_file.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation unavailable")

    result = batch_store.load_state(state_file)
    assert result == {"active_batch": None}


def test_save_state_rejects_symlinked_target(tmp_path):
    """save_state rejects when the state file is a symlink (no mutation)."""
    state_file = tmp_path / "state.json"
    outside = tmp_path / "outside.json"
    outside.write_text('{"active_batch": "original"}', encoding="utf-8")
    try:
        state_file.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation unavailable")

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "new"})

    assert outside.read_text(encoding="utf-8") == '{"active_batch": "original"}'


def test_save_state_rejects_symlinked_tmp_target(tmp_path):
    """save_state rejects when the temp file is a symlink (no mutation)."""
    state_dir = tmp_path / "state-dir"
    state_dir.mkdir()
    state_file = state_dir / "state.json"
    tmp_path_file = state_dir / "state.json.tmp"
    outside = tmp_path / "outside.json"
    outside.write_text("external", encoding="utf-8")
    # Create the symlink to the temp target before calling save_state
    try:
        tmp_path_file.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation unavailable")

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "after"})

    assert outside.read_text(encoding="utf-8") == "external"
    assert not state_file.exists()


def test_save_state_rejects_non_regular_target(tmp_path):
    """save_state rejects when the state file target exists as a directory."""
    state_file = tmp_path / "state.json"
    state_file.mkdir()

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "test"})


def test_save_state_rejects_resolved_escape(tmp_path, monkeypatch):
    """save_state rejects when the state file resolves outside its parent."""
    state_file = tmp_path / "state.json"
    state_file.write_text('{"active_batch": "before"}', encoding="utf-8")
    truly_outside = tmp_path.parent / "outside"  # above tmp_path
    truly_outside.mkdir(exist_ok=True)
    real_resolve = Path.resolve

    def patched_resolve(path):
        if path == state_file:
            return truly_outside / "state.json"
        return real_resolve(path)

    monkeypatch.setattr(Path, "resolve", patched_resolve)

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "after"})

    assert state_file.read_text(encoding="utf-8") == '{"active_batch": "before"}'


def test_save_state_safe_atomic_roundtrip(tmp_path):
    """Ordinary atomic roundtrip saves and loads correctly."""
    state_file = tmp_path / "state.json"
    batch_store.save_state(state_file, {"active_batch": "alpha"})
    result = batch_store.load_state(state_file)
    assert result == {"active_batch": "alpha"}


def test_save_state_cleans_tmp_on_rejection(tmp_path, monkeypatch):
    """A rejected save must not leave a newly created temp file."""
    state_file = tmp_path / "state.json"
    state_file.write_text('{"active_batch": "original"}', encoding="utf-8")
    # Simulate a validation failure by making Path.is_file return False
    # when inspecting the state file (which triggers the non-regular check).
    real_is_file = Path.is_file

    def patched_is_file(path):
        if path == state_file:
            return False
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", patched_is_file)

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "new"})

    # Tmp file must not exist
    tmp_file = state_file.with_suffix(state_file.suffix + ".tmp")
    assert not tmp_file.exists()
    # Original content preserved
    assert state_file.read_text(encoding="utf-8") == '{"active_batch": "original"}'


# ---------------------------------------------------------------------------
# State-file validator ordering tests (dangling symlink, raw parent chain)
# ---------------------------------------------------------------------------


def test_load_state_rejects_dangling_state_symlink(tmp_path, monkeypatch):
    """load_state returns default when state.json is a dangling symlink
    (exists()=False but is_symlink()=True)."""
    state_file = tmp_path / "state.json"
    real_is_symlink = Path.is_symlink
    real_exists = Path.exists

    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == state_file else real_is_symlink(path),
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if path == state_file else real_exists(path),
    )

    result = batch_store.load_state(state_file)
    assert result == {"active_batch": None}


def test_save_state_rejects_dangling_state_symlink_no_mutation(tmp_path, monkeypatch):
    """save_state rejects a dangling state.json symlink without creating files."""
    state_file = tmp_path / "state.json"
    real_is_symlink = Path.is_symlink
    real_exists = Path.exists

    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == state_file else real_is_symlink(path),
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if path == state_file else real_exists(path),
    )

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "new"})

    assert not (state_file.with_suffix(state_file.suffix + ".tmp")).exists()


def test_save_state_rejects_dangling_temp_symlink(tmp_path, monkeypatch):
    """save_state rejects a dangling state.json.tmp symlink without mutation."""
    state_dir = tmp_path / "state-dir"
    state_dir.mkdir()
    state_file = state_dir / "state.json"
    tmp_path_file = state_dir / "state.json.tmp"
    real_is_symlink = Path.is_symlink
    real_exists = Path.exists

    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == tmp_path_file else real_is_symlink(path),
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if path == tmp_path_file else real_exists(path),
    )

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "after"})

    assert not state_file.exists()


def test_save_state_rejects_intermediate_raw_parent_symlink(tmp_path, monkeypatch):
    """save_state rejects when a raw (lexical) parent component appears
    as a symlink, even when .resolve() would return a safe path."""
    state_dir = tmp_path / "safe" / "state"
    state_dir.parent.mkdir(parents=True)
    state_file = state_dir / "state.json"

    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == state_dir.parent else real_is_symlink(path),
    )

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "new"})

    assert not state_file.exists()


def test_save_state_rejects_raw_parent_symlink_even_when_resolve_erases_identity(
    tmp_path, monkeypatch
):
    """save_state rejects a raw parent symlink even when monkeypatched
    .resolve() would return a path under a different, safe parent.  The
    raw lexical chain rules, not the resolved one."""
    state_dir = tmp_path / "lexical" / "state"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "state.json"
    state_file.write_text('{"active_batch": "original"}', encoding="utf-8")

    # The raw parent "lexical" appears as a symlink (monkeypatch).
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == state_dir.parent else real_is_symlink(path),
    )

    # Monkeypatch .resolve() so the state file appears to live directly
    # under tmp_path, erasing the symlink identity at resolve time.
    real_resolve = Path.resolve

    def patched_resolve(path):
        if path == state_file or path == state_file.parent:
            return tmp_path / path.name if path == state_file else tmp_path
        return real_resolve(path)

    monkeypatch.setattr(Path, "resolve", patched_resolve)

    with pytest.raises(ValueError):
        batch_store.save_state(state_file, {"active_batch": "new"})

    assert state_file.read_text(encoding="utf-8") == '{"active_batch": "original"}'


def test_state_validation_checks_relative_leaf_symlink(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path):
        if Path(path) == tmp_path / "state.json":
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(ValueError, match="State path is unsafe"):
        batch_store._validate_state_target(Path("state.json"))
