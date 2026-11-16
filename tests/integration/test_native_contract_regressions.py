"""Small native HTTP contracts retained from the removed standalone adapter."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

pytest.importorskip("aiohttp")

from image_curator import native_routes

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("surface", ["image", "thumb"])
def test_missing_media_returns_json_404(client, create_batch, surface):
    create_batch("alpha")

    response = client.get(f"/curator/{surface}/alpha/inbox/missing.png")

    assert response.status_code == 404
    assert response.get_json() == {"error": "File not found"}


def test_batch_summary_reports_real_folder_and_pending_counts(
    client, create_batch, native_settings
):
    batch = create_batch("alpha")
    (batch / "inbox" / "one.png").write_bytes(b"review media")
    (native_settings.import_source / "pending.mp4").write_bytes(b"pending media")

    response = client.get("/api/curator/batches")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["counts"]["alpha"] == {
        "inbox": 1,
        "shortlisted": 0,
        "finals": 0,
        "rejects": 0,
    }
    assert payload["pending_count"] == 1


@pytest.mark.parametrize(
    ("extension", "mime"),
    [("jpeg", "image/jpeg"), ("webp", "image/webp"), ("mp4", "video/mp4")],
)
def test_original_media_preserves_mime_and_bytes(client, create_batch, extension, mime):
    batch = create_batch("alpha")
    content = b"original bytes served without decoding"
    (batch / "inbox" / f"asset.{extension}").write_bytes(content)

    response = client.get(f"/curator/image/alpha/inbox/asset.{extension}")

    assert response.status_code == 200
    assert response.mimetype == mime
    assert response.data == content


def test_thumbnail_does_not_sleep_without_delay_setting(client, create_batch, monkeypatch):
    batch = create_batch("alpha")
    Image.new("RGB", (8, 8), "blue").save(batch / "inbox" / "one.png")
    monkeypatch.delenv("IMAGE_CURATOR_THUMBNAIL_DELAY_MS", raising=False)
    sleep = AsyncMock()
    # Replace only this adapter's asyncio reference, not aiohttp's event loop.
    monkeypatch.setattr(
        native_routes, "asyncio", SimpleNamespace(to_thread=asyncio.to_thread, sleep=sleep)
    )

    response = client.get("/curator/thumb/alpha/inbox/one.png")

    assert response.status_code == 200
    assert response.mimetype == "image/webp"
    sleep.assert_not_awaited()
