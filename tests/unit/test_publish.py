from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from image_curator import batch_store, publish
from image_curator.media import thumbnail_cache_path


def _make_png(
    path: Path, color: tuple[int, int, int] = (20, 40, 80), metadata: bool = False
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (96, 64), color)
    pnginfo = None
    if metadata:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("prompt", "secret generation prompt")
        pnginfo.add_text("parameters", "Steps: 20, Sampler: Euler")
    image.save(path, pnginfo=pnginfo)


def _make_batch(batches_dir: Path, batch: str = "alpha") -> None:
    batch_store.create_batch(batches_dir, batch)


def test_create_public_copies_strips_metadata_and_preserves_original(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    source = batches_dir / "alpha" / "finals" / "portrait.png"
    _make_png(source, metadata=True)
    original_bytes = source.read_bytes()

    result = publish.create_public_copies(
        batches_dir,
        batch="alpha",
        folder="finals",
        filenames=["portrait.png"],
        strip_metadata=True,
        watermark={"enabled": False},
    )

    assert result["exported"] == 1
    assert result["failed"] == 0
    assert result["files"] == [{"source": "portrait.png", "output": "portrait-public.png"}]
    output = batches_dir / "alpha" / "public" / "portrait-public.png"
    assert output.exists()
    assert source.read_bytes() == original_bytes
    with Image.open(output) as exported:
        assert exported.text == {}


def test_create_public_copies_uses_dash_number_collision_names(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    _make_png(batches_dir / "alpha" / "finals" / "portrait.png")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir()
    (public_dir / "portrait-public.png").write_bytes(b"existing")

    result = publish.create_public_copies(
        batches_dir,
        batch="alpha",
        folder="finals",
        filenames=["portrait.png"],
    )

    assert result["files"] == [{"source": "portrait.png", "output": "portrait-public-2.png"}]
    assert (public_dir / "portrait-public.png").read_bytes() == b"existing"
    assert (public_dir / "portrait-public-2.png").exists()


def test_create_public_copies_rejects_public_as_source_folder(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)

    result = publish.create_public_copies(
        batches_dir,
        batch="alpha",
        folder="public",
        filenames=["portrait.png"],
    )

    assert result["exported"] == 0
    assert result["failed"] == 1
    assert result["files"][0]["error"] == "Invalid source folder"


@pytest.mark.parametrize("filename", ["animation.gif", "clip.mp4", "track.mp3"])
def test_create_public_copies_never_flattens_typed_media(tmp_path, filename):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    source = batches_dir / "alpha" / "finals" / filename
    source.write_bytes(b"original-media")

    result = publish.create_public_copies(
        batches_dir,
        batch="alpha",
        folder="finals",
        filenames=[filename],
    )

    assert result["exported"] == 0
    assert result["failed"] == 1
    assert source.read_bytes() == b"original-media"
    assert list((batches_dir / "alpha" / "public").iterdir()) == []


def test_create_public_copies_applies_text_watermark(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    _make_png(batches_dir / "alpha" / "finals" / "portrait.png", color=(10, 10, 10))

    publish.create_public_copies(
        batches_dir,
        batch="alpha",
        folder="finals",
        filenames=["portrait.png"],
        watermark={
            "enabled": True,
            "text": "FrostySDXL",
            "position": "bottom-right",
            "margin": 4,
            "opacity": 1.0,
            "size_percent": 8,
        },
    )

    source = Image.open(batches_dir / "alpha" / "finals" / "portrait.png").convert("RGB")
    exported = Image.open(batches_dir / "alpha" / "public" / "portrait-public.png").convert("RGB")
    assert list(source.getdata()) != list(exported.getdata())


def test_create_public_copies_can_apply_black_text_watermark(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    source = batches_dir / "alpha" / "finals" / "portrait.png"
    Image.new("RGB", (300, 180), (128, 128, 128)).save(source)

    publish.create_public_copies(
        batches_dir,
        batch="alpha",
        folder="finals",
        filenames=["portrait.png"],
        watermark={
            "enabled": True,
            "text": "FrostySDXL",
            "position": "center",
            "margin": 0,
            "opacity": 1.0,
            "size_percent": 20,
            "color": "black",
        },
    )

    exported = Image.open(batches_dir / "alpha" / "public" / "portrait-public.png").convert("RGB")
    changed_pixels = [pixel for pixel in exported.getdata() if pixel != (128, 128, 128)]
    assert changed_pixels
    assert min(pixel[0] for pixel in changed_pixels) < 128
    assert max(pixel[0] for pixel in changed_pixels) <= 128


def test_list_batch_and_all_public_images(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir, "alpha")
    _make_batch(batches_dir, "beta")
    _make_png(batches_dir / "alpha" / "public" / "a-public.png")
    _make_png(batches_dir / "beta" / "public" / "b-public.png")
    (batches_dir / "beta" / "public" / "notes.txt").write_text("skip")

    assert publish.list_batch_public(batches_dir, "alpha")[0]["name"] == "a-public.png"
    all_public = publish.list_all_public(batches_dir)

    assert [item["batch"] for item in all_public] == ["alpha", "beta"]
    assert [item["folder"] for item in all_public] == ["public", "public"]
    assert [item["name"] for item in all_public] == ["a-public.png", "b-public.png"]


def test_copy_public_items_requires_configured_export_root(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    _make_png(batches_dir / "alpha" / "public" / "portrait-public.png")

    result = publish.copy_public_items(
        batches_dir,
        destination=tmp_path / "exports",
        items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        export_root=None,
    )

    assert result["copied"] == 0
    assert result["failed"] == 1
    assert result["files"][0]["error"] == "Public export root is not configured"


def test_move_public_items_requires_configured_export_root(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    _make_png(batches_dir / "alpha" / "public" / "portrait-public.png")

    result = publish.move_public_items(
        batches_dir,
        destination=tmp_path / "exports",
        items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        export_root=None,
    )

    assert result["moved"] == 0
    assert result["failed"] == 1
    assert result["files"][0]["error"] == "Public export root is not configured"


def test_copy_move_delete_public_items_affect_derivatives_only(tmp_path):
    batches_dir = tmp_path / "batches"
    export_root = tmp_path / "exports"
    destination = export_root / "posting"
    _make_batch(batches_dir)
    original = batches_dir / "alpha" / "finals" / "portrait.png"
    public_copy = batches_dir / "alpha" / "public" / "portrait-public.png"
    _make_png(original)
    _make_png(public_copy)

    copy_result = publish.copy_public_items(
        batches_dir,
        destination=destination,
        items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        export_root=export_root,
    )
    move_result = publish.move_public_items(
        batches_dir,
        destination=destination,
        items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        export_root=export_root,
    )

    assert copy_result["copied"] == 1
    assert move_result["moved"] == 1
    assert original.exists()
    assert not public_copy.exists()
    assert (destination / "portrait-public.png").exists()

    _make_png(public_copy)
    delete_result = publish.delete_public_items(
        batches_dir,
        items=[{"batch": "alpha", "filename": "portrait-public.png"}],
    )
    assert delete_result["deleted"] == 1
    assert original.exists()
    assert not public_copy.exists()


def test_delete_public_items_reports_missing_file(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)

    result = publish.delete_public_items(
        batches_dir,
        items=[{"batch": "alpha", "filename": "missing-public.png"}],
    )

    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert result["files"] == [{"filename": "missing-public.png", "error": "Public file not found"}]


def test_delete_public_items_removes_thumbnail_cache(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    public_copy = batches_dir / "alpha" / "public" / "portrait-public.png"
    _make_png(public_copy)
    cache_path = thumbnail_cache_path(batches_dir, "alpha", "public", "portrait-public.png")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"cached")

    result = publish.delete_public_items(
        batches_dir,
        items=[{"batch": "alpha", "filename": "portrait-public.png"}],
    )

    assert result["deleted"] == 1
    assert not public_copy.exists()
    assert not cache_path.exists()


def test_copy_public_items_reports_missing_file(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)

    result = publish.copy_public_items(
        batches_dir,
        destination=tmp_path / "exports" / "posting",
        items=[{"batch": "alpha", "filename": "nonexistent-public.png"}],
        export_root=tmp_path / "exports",
    )

    assert result["copied"] == 0
    assert result["failed"] == 1
    assert result["files"] == [
        {"filename": "nonexistent-public.png", "error": "Public file not found"}
    ]


def test_move_public_items_reports_missing_file(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)

    result = publish.move_public_items(
        batches_dir,
        destination=tmp_path / "exports" / "posting",
        items=[{"batch": "alpha", "filename": "nonexistent-public.png"}],
        export_root=tmp_path / "exports",
    )

    assert result["moved"] == 0
    assert result["failed"] == 1
    assert result["files"] == [
        {"filename": "nonexistent-public.png", "error": "Public file not found"}
    ]


def test_copy_public_items_reports_unsupported_name(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    (batches_dir / "alpha" / "public").mkdir(parents=True, exist_ok=True)
    (batches_dir / "alpha" / "public" / "notes.txt").write_text("skip")

    result = publish.copy_public_items(
        batches_dir,
        destination=tmp_path / "exports" / "posting",
        items=[{"batch": "alpha", "filename": "notes.txt"}],
        export_root=tmp_path / "exports",
    )

    assert result["copied"] == 0
    assert result["failed"] == 1
    assert result["files"] == [{"filename": "notes.txt", "error": "Unsupported image type"}]


def test_move_public_items_reports_unsupported_name(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    (batches_dir / "alpha" / "public").mkdir(parents=True, exist_ok=True)
    (batches_dir / "alpha" / "public" / "notes.txt").write_text("skip")

    result = publish.move_public_items(
        batches_dir,
        destination=tmp_path / "exports" / "posting",
        items=[{"batch": "alpha", "filename": "notes.txt"}],
        export_root=tmp_path / "exports",
    )

    assert result["moved"] == 0
    assert result["failed"] == 1
    assert result["files"] == [{"filename": "notes.txt", "error": "Unsupported image type"}]


def test_public_destination_must_stay_under_export_root(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    _make_png(batches_dir / "alpha" / "public" / "portrait-public.png")

    result = publish.copy_public_items(
        batches_dir,
        destination=tmp_path / "outside",
        items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        export_root=tmp_path / "exports",
    )

    assert result["copied"] == 0
    assert result["failed"] == 1
    assert "Destination must stay inside" in result["files"][0]["error"]


def test_list_export_directories_requires_configured_root():
    with pytest.raises(ValueError, match="Public export root is not configured"):
        publish.list_export_directories(None)


def test_list_export_directories_returns_safe_relative_directories(tmp_path):
    export_root = tmp_path / "exports"
    (export_root / "posts" / "batch-b").mkdir(parents=True)
    (export_root / "posts" / "batch-a").mkdir(parents=True)
    (export_root / "posts" / "notes.txt").write_text("skip")

    result = publish.list_export_directories(export_root, path="posts")

    assert result == {
        "path": "posts",
        "parent": "",
        "directories": [
            {"name": "batch-a", "path": "posts/batch-a"},
            {"name": "batch-b", "path": "posts/batch-b"},
        ],
    }


def test_list_export_directories_blocks_traversal(tmp_path):
    export_root = tmp_path / "exports"
    export_root.mkdir()

    with pytest.raises(ValueError, match="Destination must stay inside"):
        publish.list_export_directories(export_root, path="../outside")


def test_create_public_copies_rejects_symlinked_source_file(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    source = batches_dir / "alpha" / "finals" / "portrait.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"image-data")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == source else real_is_symlink(path)
    ):
        result = publish.create_public_copies(
            batches_dir,
            batch="alpha",
            folder="finals",
            filenames=["portrait.png"],
            strip_metadata=True,
            watermark={"enabled": False},
        )
    assert result["exported"] == 0
    assert result["failed"] == 1
    assert result["files"][0]["error"] == "Source file is a symlink"


def test_list_batch_public_skips_symlinked_files(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)
    (public_dir / "real.png").write_bytes(b"real")
    (public_dir / "linked.png").write_bytes(b"linked")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path,
        "is_symlink",
        lambda path, _real=real_is_symlink: True if path.name == "linked.png" else _real(path),
    ):
        items = publish.list_batch_public(batches_dir, "alpha")
    assert len(items) == 1
    assert items[0]["name"] == "real.png"


def test_delete_public_items_rejects_symlinked_file(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)
    pub_file = public_dir / "portrait-public.png"
    pub_file.write_bytes(b"data")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == pub_file else real_is_symlink(path)
    ):
        result = publish.delete_public_items(
            batches_dir,
            items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        )
    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert "symlink" in result["files"][0]["error"].lower()
    assert pub_file.exists()


def test_copy_public_items_rejects_symlinked_public_file(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)
    pub_file = public_dir / "portrait-public.png"
    pub_file.write_bytes(b"data")
    export_root = tmp_path / "exports"

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == pub_file else real_is_symlink(path)
    ):
        result = publish.copy_public_items(
            batches_dir,
            destination=export_root / "posting",
            items=[{"batch": "alpha", "filename": "portrait-public.png"}],
            export_root=export_root,
        )
    assert result["copied"] == 0
    assert result["failed"] == 1
    assert "symlink" in result["files"][0]["error"].lower()
    assert pub_file.exists()


def test_get_public_folder_rejects_symlinked_existing_public_dir(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)
    (public_dir / "existing.png").write_bytes(b"data")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == public_dir else real_is_symlink(path)
    ):
        with pytest.raises(ValueError, match="Public folder is a symlink"):
            publish.get_public_folder(batches_dir, "alpha")


def test_list_batch_public_returns_empty_for_symlinked_public_dir(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)
    (public_dir / "real.png").write_bytes(b"data")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == public_dir else real_is_symlink(path)
    ):
        items = publish.list_batch_public(batches_dir, "alpha")
    assert items == []


def test_create_public_copies_rejects_symlinked_public_dir_no_write(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    source = batches_dir / "alpha" / "finals" / "portrait.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    _make_png(source)
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == public_dir else real_is_symlink(path)
    ):
        result = publish.create_public_copies(
            batches_dir,
            batch="alpha",
            folder="finals",
            filenames=["portrait.png"],
            strip_metadata=True,
            watermark={"enabled": False},
        )
    assert result["exported"] == 0
    assert result["failed"] == 1
    assert any("public" in f["error"].lower() for f in result["files"])
    # No derivative files should be created (public dir only has pre-existing content)
    assert not any(
        f.name.endswith(tuple(batch_store.IMAGE_EXTENSIONS)) for f in public_dir.iterdir()
    )


def test_list_all_public_skips_symlinked_public_dirs(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    batch_store.create_batch(batches_dir, "beta")
    (batches_dir / "alpha" / "public").mkdir(parents=True)
    (batches_dir / "alpha" / "public" / "a.png").write_bytes(b"data")
    (batches_dir / "beta" / "public").mkdir(parents=True)
    (batches_dir / "beta" / "public" / "b.png").write_bytes(b"data")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path,
        "is_symlink",
        lambda path, _real=real_is_symlink: (
            True if path.name == "public" and path.parent.name == "beta" else _real(path)
        ),
    ):
        items = publish.list_all_public(batches_dir)
    assert len(items) == 1
    assert items[0]["batch"] == "alpha"
    assert items[0]["name"] == "a.png"


def test_create_public_copies_rejects_missing_batch(tmp_path):
    batches_dir = tmp_path / "batches"

    result = publish.create_public_copies(
        batches_dir,
        batch="nonexistent",
        folder="finals",
        filenames=["portrait.png"],
    )
    assert result["exported"] == 0
    assert result["failed"] == 1
    assert "batch" in result["files"][0]["error"].lower() or (
        "not exist" in result["files"][0]["error"].lower()
    )


def test_create_public_copies_rejects_symlinked_source_folder(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    source_folder = batches_dir / "alpha" / "finals"

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == source_folder else real_is_symlink(path)
    ):
        result = publish.create_public_copies(
            batches_dir,
            batch="alpha",
            folder="finals",
            filenames=["portrait.png"],
            strip_metadata=True,
            watermark={"enabled": False},
        )
    assert result["exported"] == 0
    assert result["failed"] == 1
    assert any(
        "folder" in f["error"].lower() or "symlink" in f["error"].lower() for f in result["files"]
    )


def test_create_public_copies_rejects_non_regular_source_file(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    source = batches_dir / "alpha" / "finals" / "portrait.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"image-data")

    real_is_file = Path.is_file
    from unittest.mock import patch

    with patch.object(
        Path, "is_file", lambda path: False if path == source else real_is_file(path)
    ):
        result = publish.create_public_copies(
            batches_dir,
            batch="alpha",
            folder="finals",
            filenames=["portrait.png"],
            strip_metadata=True,
            watermark={"enabled": False},
        )
    assert result["exported"] == 0
    assert result["failed"] == 1


def test_create_public_copies_rejects_symlinked_batch_dir(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    batch_dir = batches_dir / "alpha"

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == batch_dir else real_is_symlink(path)
    ):
        result = publish.create_public_copies(
            batches_dir,
            batch="alpha",
            folder="finals",
            filenames=["portrait.png"],
            strip_metadata=True,
            watermark={"enabled": False},
        )
    assert result["exported"] == 0
    assert result["failed"] == 1


def test_resolve_export_destination_rejects_symlinked_export_root(tmp_path):
    export_root = tmp_path / "exports"
    export_root.mkdir()
    # Simulate: raw export_root IS a symlink, but resolve() returns a different
    # normalized path. The buggy code resolves FIRST then checks is_symlink on
    # the resolved path — where it is always False.
    resolved_root = export_root / ".real"
    resolved_root.mkdir()

    raw_is_symlink = Path.is_symlink
    raw_resolve = Path.resolve
    symlink_checked_before_resolve = False

    def _mock_is_symlink(path):
        nonlocal symlink_checked_before_resolve
        if path == export_root:
            # Mark that raw is_symlink was called — the caller should
            # reject here before resolving.
            symlink_checked_before_resolve = True
            return True
        return raw_is_symlink(path)

    def _mock_resolve(path, *args, **kwargs):
        if path == export_root:
            return resolved_root  # resolve follows the link to .real
        return raw_resolve(path, *args, **kwargs)

    from unittest.mock import patch

    # The current code does: root = Path(export_root).resolve()
    # then: if root.is_symlink() — but root is resolved_root, not a symlink.
    with patch.object(Path, "is_symlink", _mock_is_symlink):
        with patch.object(Path, "resolve", _mock_resolve):
            with pytest.raises(ValueError, match="symlink"):
                publish._resolve_export_destination(resolved_root / "posting", export_root)

    assert symlink_checked_before_resolve, (
        "Raw export_root must be checked for symlink BEFORE resolve"
    )


def test_resolve_export_browser_path_rejects_symlinked_export_root_before_resolve(tmp_path):
    """Export root symlink must be detected on raw Path before resolve erases it."""
    export_root = tmp_path / "exports"
    export_root.mkdir()
    resolved_root = export_root / ".real"
    resolved_root.mkdir()

    raw_is_symlink = Path.is_symlink
    raw_resolve = Path.resolve
    symlink_checked_before_resolve = False

    def _mock_is_symlink(path):
        nonlocal symlink_checked_before_resolve
        if path == export_root:
            symlink_checked_before_resolve = True
            return True
        return raw_is_symlink(path)

    def _mock_resolve(path, *args, **kwargs):
        if path == export_root:
            return resolved_root
        return raw_resolve(path, *args, **kwargs)

    from unittest.mock import patch

    with patch.object(Path, "is_symlink", _mock_is_symlink):
        with patch.object(Path, "resolve", _mock_resolve):
            with pytest.raises(ValueError, match="symlink"):
                publish._resolve_export_browser_path("", export_root)

    assert symlink_checked_before_resolve, (
        "Raw export_root must be checked for symlink BEFORE resolve in browser path"
    )


def test_resolve_export_destination_rejects_symlinked_path_component(tmp_path):
    export_root = tmp_path / "exports"
    export_root.mkdir()
    middle = export_root / "middle"
    middle.mkdir()

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == middle else real_is_symlink(path)
    ):
        with pytest.raises(ValueError, match="symlink"):
            publish._resolve_export_destination(export_root / "middle" / "posting", export_root)


def test_list_export_directories_omits_symlinked_child_dirs(tmp_path):
    export_root = tmp_path / "exports"
    (export_root / "real-dir").mkdir(parents=True)
    (export_root / "linked-dir").mkdir(parents=True)
    (export_root / "file.txt").write_text("skip")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    def _mock_is_symlink(path):
        if path.name == "linked-dir":
            return True
        return real_is_symlink(path)

    with patch.object(Path, "is_symlink", _mock_is_symlink):
        result = publish.list_export_directories(export_root)
    assert len(result["directories"]) == 1
    assert result["directories"][0]["name"] == "real-dir"


def test_delete_public_items_skips_symlinked_thumbnail_cache(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    public_copy = batches_dir / "alpha" / "public" / "portrait-public.png"
    public_copy.parent.mkdir(parents=True, exist_ok=True)
    _make_png(public_copy)
    cache_path = thumbnail_cache_path(batches_dir, "alpha", "public", "portrait-public.png")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"cached")

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == cache_path else real_is_symlink(path)
    ):
        result = publish.delete_public_items(
            batches_dir,
            items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        )
    assert result["deleted"] == 1
    assert not public_copy.exists()
    assert cache_path.exists()  # symlinked cache untouched


def test_delete_public_items_skips_thumbnail_in_symlinked_thumbs_dir(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    public_copy = batches_dir / "alpha" / "public" / "portrait-public.png"
    public_copy.parent.mkdir(parents=True, exist_ok=True)
    _make_png(public_copy)
    cache_path = thumbnail_cache_path(batches_dir, "alpha", "public", "portrait-public.png")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"cached")

    thumbs_dir = cache_path.parent

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path, "is_symlink", lambda path: True if path == thumbs_dir else real_is_symlink(path)
    ):
        result = publish.delete_public_items(
            batches_dir,
            items=[{"batch": "alpha", "filename": "portrait-public.png"}],
        )
    assert result["deleted"] == 1
    assert not public_copy.exists()
    assert cache_path.exists()  # cache in symlinked .thumbs untouched


def test_public_item_omits_directories_with_image_extension_name(tmp_path):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir, "alpha")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)
    _make_png(public_dir / "real.png")
    (public_dir / "subdir.png").mkdir()  # directory with image extension name

    items = publish.list_batch_public(batches_dir, "alpha")

    assert len(items) == 1
    assert items[0]["name"] == "real.png"


def test_list_all_public_skips_symlinked_batch_directories(tmp_path):
    batches_dir = tmp_path / "batches"
    from image_curator import batch_store

    batch_store.create_batch(batches_dir, "alpha")
    batch_store.create_batch(batches_dir, "beta")
    (batches_dir / "alpha" / "public").mkdir(parents=True)
    (batches_dir / "alpha" / "public" / "a.png").write_bytes(b"data")
    (batches_dir / "beta" / "public").mkdir(parents=True)
    (batches_dir / "beta" / "public" / "b.png").write_bytes(b"data")

    batch_beta = batches_dir / "beta"

    real_is_symlink = Path.is_symlink
    from unittest.mock import patch

    with patch.object(
        Path,
        "is_symlink",
        lambda path, _real=real_is_symlink: True if path == batch_beta else _real(path),
    ):
        items = publish.list_all_public(batches_dir)
    assert len(items) == 1
    assert items[0]["batch"] == "alpha"
    assert items[0]["name"] == "a.png"


def test_get_public_folder_rejects_resolved_escape_outside_batch(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir)
    public_dir = batches_dir / "alpha" / "public"
    outside = tmp_path / "outside-public"
    outside.mkdir()
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == public_dir:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    with pytest.raises(ValueError, match="Invalid public folder path"):
        publish.get_public_folder(batches_dir, "alpha", create=True)

    assert list(outside.iterdir()) == []


def test_resolve_public_file_rejects_resolved_escape_outside_batch(tmp_path):
    """_resolve_public_file must reject if resolved path escapes the batch root."""
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir, "alpha")
    public_dir = batches_dir / "alpha" / "public"
    public_dir.mkdir(parents=True)
    pub_file = public_dir / "pic-public.png"
    pub_file.write_bytes(b"data")

    outside_target = tmp_path / "outside"
    outside_target.mkdir()
    real_resolve = Path.resolve

    def _mock_resolve(path, *args, **kwargs):
        if path == pub_file:
            return outside_target / "pic-public.png"
        if path == public_dir:
            return outside_target
        return real_resolve(path, *args, **kwargs)

    from unittest.mock import patch

    with patch.object(Path, "resolve", _mock_resolve):
        with pytest.raises(ValueError, match="Invalid"):
            publish._resolve_public_file(
                batches_dir, {"batch": "alpha", "filename": "pic-public.png"}
            )


def test_create_public_copies_rejects_resolved_source_escape(tmp_path):
    """Source file whose resolve escapes the batch must be rejected."""
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir, "alpha")
    source = batches_dir / "alpha" / "finals" / "portrait.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    _make_png(source)
    source_folder = batches_dir / "alpha" / "finals"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_resolve = Path.resolve

    def _mock_resolve(path, *args, **kwargs):
        if path == source:
            return outside / "portrait.png"
        if path == source_folder:
            return outside
        return real_resolve(path, *args, **kwargs)

    from unittest.mock import patch

    with patch.object(Path, "resolve", _mock_resolve):
        result = publish.create_public_copies(
            batches_dir,
            batch="alpha",
            folder="finals",
            filenames=["portrait.png"],
            strip_metadata=True,
            watermark={"enabled": False},
        )
    assert result["exported"] == 0
    assert result["failed"] == 1


def test_delete_public_items_rejects_resolved_escape(tmp_path):
    """Public file whose resolve escapes must be rejected for deletion."""
    batches_dir = tmp_path / "batches"
    _make_batch(batches_dir, "alpha")
    pub_file = batches_dir / "alpha" / "public" / "pic-public.png"
    pub_file.parent.mkdir(parents=True, exist_ok=True)
    _make_png(pub_file)
    public_dir = batches_dir / "alpha" / "public"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_resolve = Path.resolve

    def _mock_resolve(path, *args, **kwargs):
        if path == pub_file:
            return outside / "pic-public.png"
        if path == public_dir:
            return outside
        return real_resolve(path, *args, **kwargs)

    from unittest.mock import patch

    with patch.object(Path, "resolve", _mock_resolve):
        result = publish.delete_public_items(
            batches_dir,
            items=[{"batch": "alpha", "filename": "pic-public.png"}],
        )
    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert pub_file.exists()
