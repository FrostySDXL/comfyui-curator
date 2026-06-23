from pathlib import Path

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
