from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

pytestmark = pytest.mark.integration


def _write_png(path: Path, metadata: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (12, 8), color="blue")
    pnginfo = None
    if metadata:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("prompt", "private prompt")
    image.save(path, pnginfo=pnginfo)


def test_publish_export_creates_public_copy_and_preserves_original(client, app_module):
    app_module.create_batch("alpha")
    source = app_module.BATCHES_DIR / "alpha" / "finals" / "portrait.png"
    _write_png(source, metadata=True)
    original_bytes = source.read_bytes()

    response = client.post(
        "/api/publish/export",
        json={
            "batch": "alpha",
            "folder": "finals",
            "filenames": ["portrait.png"],
            "strip_metadata": True,
            "watermark": {"enabled": False},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["exported"] == 1
    assert payload["files"] == [{"source": "portrait.png", "output": "portrait-public.png"}]
    assert source.read_bytes() == original_bytes
    assert (app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png").exists()


def test_publish_export_api_applies_text_watermark(client, app_module):
    app_module.create_batch("alpha")
    source = app_module.BATCHES_DIR / "alpha" / "finals" / "portrait.png"
    _write_png(source)
    original_bytes = source.read_bytes()

    response = client.post(
        "/api/publish/export",
        json={
            "batch": "alpha",
            "folder": "finals",
            "filenames": ["portrait.png"],
            "strip_metadata": True,
            "watermark": {
                "enabled": True,
                "text": "FrostySDXL",
                "position": "bottom-right",
                "margin": 1,
                "opacity": 1.0,
                "size_percent": 20,
            },
        },
    )

    assert response.status_code == 200
    assert source.read_bytes() == original_bytes
    source_pixels = Image.open(source).convert("RGB").getdata()
    output_pixels = (
        Image.open(app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png")
        .convert("RGB")
        .getdata()
    )
    assert list(source_pixels) != list(output_pixels)


def test_public_listing_routes_return_batch_and_all_public_items(client, app_module):
    app_module.create_batch("alpha")
    app_module.create_batch("beta")
    _write_png(app_module.BATCHES_DIR / "alpha" / "public" / "a-public.png")
    _write_png(app_module.BATCHES_DIR / "beta" / "public" / "b-public.png")

    batch_response = client.get("/api/public/alpha")
    all_response = client.get("/api/public")

    assert batch_response.status_code == 200
    assert batch_response.get_json()[0]["name"] == "a-public.png"
    assert all_response.status_code == 200
    assert [item["batch"] for item in all_response.get_json()["public"]] == ["alpha", "beta"]


def test_public_images_can_be_served_and_thumbnailed(client, app_module):
    app_module.create_batch("alpha")
    _write_png(app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png")

    image_response = client.get("/image/alpha/public/portrait-public.png")
    thumb_response = client.get("/thumb/alpha/public/portrait-public.png")

    assert image_response.status_code == 200
    assert thumb_response.status_code == 200
    assert thumb_response.mimetype == "image/webp"


def test_public_copy_move_delete_routes_are_export_root_gated(
    client, app_module, monkeypatch, tmp_path
):
    app_module.create_batch("alpha")
    _write_png(app_module.BATCHES_DIR / "alpha" / "finals" / "portrait.png")
    _write_png(app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png")
    export_root = tmp_path / "exports"
    monkeypatch.setattr(app_module, "PUBLIC_EXPORT_ROOT", export_root)

    copy_response = client.post(
        "/api/public/copy",
        json={
            "destination": str(export_root / "posting"),
            "items": [{"batch": "alpha", "filename": "portrait-public.png"}],
        },
    )
    move_response = client.post(
        "/api/public/move",
        json={
            "destination": str(export_root / "posting"),
            "items": [{"batch": "alpha", "filename": "portrait-public.png"}],
        },
    )

    assert copy_response.status_code == 200
    assert copy_response.get_json()["copied"] == 1
    assert move_response.status_code == 200
    assert move_response.get_json()["moved"] == 1
    assert not (app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png").exists()
    assert (app_module.BATCHES_DIR / "alpha" / "finals" / "portrait.png").exists()

    _write_png(app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png")
    delete_response = client.post(
        "/api/public/delete",
        json={"items": [{"batch": "alpha", "filename": "portrait-public.png"}]},
    )
    assert delete_response.status_code == 200
    assert delete_response.get_json()["deleted"] == 1
    assert (app_module.BATCHES_DIR / "alpha" / "finals" / "portrait.png").exists()


def test_public_copy_disabled_without_export_root(client, app_module, tmp_path):
    app_module.create_batch("alpha")
    _write_png(app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png")

    response = client.post(
        "/api/public/copy",
        json={
            "destination": str(tmp_path / "posting"),
            "items": [{"batch": "alpha", "filename": "portrait-public.png"}],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Public export root is not configured"


def test_public_move_disabled_without_export_root(client, app_module, tmp_path):
    app_module.create_batch("alpha")
    _write_png(app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png")

    response = client.post(
        "/api/public/move",
        json={
            "destination": str(tmp_path / "posting"),
            "items": [{"batch": "alpha", "filename": "portrait-public.png"}],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Public export root is not configured"


def test_public_item_payload_rejects_non_object_items(client, app_module, tmp_path):
    app_module.create_batch("alpha")
    _write_png(app_module.BATCHES_DIR / "alpha" / "public" / "portrait-public.png")

    response = client.post(
        "/api/public/copy",
        json={
            "destination": str(tmp_path / "posting"),
            "items": [{"batch": "alpha", "filename": "portrait-public.png"}, "bad-item"],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "items must be objects"


def test_public_destinations_route_lists_export_root_directories(
    client, app_module, monkeypatch, tmp_path
):
    export_root = tmp_path / "exports"
    (export_root / "posts" / "batch-b").mkdir(parents=True)
    (export_root / "posts" / "batch-a").mkdir(parents=True)
    (export_root / "posts" / "notes.txt").write_text("skip")
    monkeypatch.setattr(app_module, "PUBLIC_EXPORT_ROOT", export_root)

    response = client.get("/api/public/destinations?path=posts")

    assert response.status_code == 200
    assert response.get_json() == {
        "path": "posts",
        "parent": "",
        "directories": [
            {"name": "batch-a", "path": "posts/batch-a"},
            {"name": "batch-b", "path": "posts/batch-b"},
        ],
    }


def test_public_destinations_route_requires_export_root(client):
    response = client.get("/api/public/destinations")

    assert response.status_code == 400
    assert response.get_json()["error"] == "Public export root is not configured"


def test_public_destinations_route_blocks_traversal(client, app_module, monkeypatch, tmp_path):
    export_root = tmp_path / "exports"
    export_root.mkdir()
    monkeypatch.setattr(app_module, "PUBLIC_EXPORT_ROOT", export_root)

    response = client.get("/api/public/destinations?path=../outside")

    assert response.status_code == 400
    assert "Destination must stay inside" in response.get_json()["error"]
