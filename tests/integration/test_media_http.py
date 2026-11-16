"""Real-HTTP media contract checks migrated from the old Flask component suite."""

from PIL import Image

import pytest

pytestmark = pytest.mark.integration


def _write_png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), color="blue").save(path)


def test_audio_original_supports_mime_ranges_and_fallback_poster(
    client, create_batch, native_settings, make_file
):
    create_batch("batch")
    track = native_settings.batch_root / "batch" / "inbox" / "track.mp3"
    make_file(track, b"0123456789")

    original = client.get(
        "/curator/image/batch/inbox/track.mp3",
        headers={"Range": "bytes=2-5"},
    )
    poster = client.get("/curator/thumb/batch/inbox/track.mp3")

    assert original.status_code == 206
    assert original.mimetype == "audio/mpeg"
    assert original.data == b"2345"
    assert poster.status_code == 200
    assert poster.mimetype == "image/webp"


def test_hover_preview_missing_ffmpeg_is_stable_unavailable_response(
    client, create_batch, native_settings, make_file, monkeypatch, tmp_path
):
    create_batch("batch")
    make_file(native_settings.batch_root / "batch" / "inbox" / "loop.gif", b"bad-gif")
    monkeypatch.setenv("IMAGE_CURATOR_FFMPEG", str(tmp_path / "missing-ffmpeg.exe"))

    response = client.get("/curator/preview/batch/inbox/loop.gif")

    assert response.status_code == 503
    assert response.get_json() == {"error": "Hover preview unavailable"}


def test_thumbnail_cache_keys_are_namespaced_by_folder(client, create_batch, native_settings):
    create_batch("batch")
    _write_png(native_settings.batch_root / "batch" / "inbox" / "shared.png")
    _write_png(native_settings.batch_root / "batch" / "shortlisted" / "shared.png")

    inbox_response = client.get("/curator/thumb/batch/inbox/shared.png")
    shortlisted_response = client.get("/curator/thumb/batch/shortlisted/shared.png")

    assert inbox_response.status_code == 200
    assert shortlisted_response.status_code == 200

    cache_dir = native_settings.batch_root / "batch" / ".thumbs"
    cache_files = sorted(path.name for path in cache_dir.glob("*.webp"))
    assert len(cache_files) == 2, f"expected 2 distinct cache files, got {cache_files}"
    assert cache_files[0] != cache_files[1]
    assert any("inbox" in name for name in cache_files)
    assert any("shortlisted" in name for name in cache_files)
