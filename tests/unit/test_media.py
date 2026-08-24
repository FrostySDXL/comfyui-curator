import os
from pathlib import Path

from PIL import Image

from image_curator.media import (
    generate_media_poster,
    generate_thumbnail,
    hover_preview_cache_path,
    thumbnail_cache_path,
    thumbnail_is_fresh,
)


def test_thumbnail_cache_path_namespaces_by_folder(tmp_path):
    path = thumbnail_cache_path(tmp_path, "batch", "inbox", "sample.png")

    assert path == tmp_path / "batch" / ".thumbs" / "inbox__sample--png.webp"


def test_thumbnail_cache_path_namespaces_same_stem_by_source_extension(tmp_path):
    png = thumbnail_cache_path(tmp_path, "batch", "inbox", "sample.png")
    gif = thumbnail_cache_path(tmp_path, "batch", "inbox", "sample.gif")

    assert png != gif
    assert gif.name == "inbox__sample--gif.webp"


def test_thumbnail_is_fresh_compares_cache_and_source_mtime(tmp_path):
    source = tmp_path / "source.png"
    cache = tmp_path / "cache.webp"
    source.write_bytes(b"source")
    cache.write_bytes(b"cache")

    source_time = source.stat().st_mtime
    os.utime(cache, (source_time + 10, source_time + 10))
    assert thumbnail_is_fresh(cache, source) is True

    os.utime(cache, (source_time - 10, source_time - 10))
    assert thumbnail_is_fresh(cache, source) is False


def test_thumbnail_is_fresh_rejects_stale_thumbnail_size(tmp_path):
    source = tmp_path / "source.png"
    cache = tmp_path / "cache.webp"
    Image.new("RGB", (500, 500), color="red").save(str(source), format="PNG")
    Image.new("RGB", (200, 200), color="red").save(str(cache), format="WEBP")
    source_time = source.stat().st_mtime
    os.utime(cache, (source_time + 10, source_time + 10))

    assert thumbnail_is_fresh(cache, source, (320, 320)) is False


def test_thumbnail_is_fresh_accepts_current_thumbnail_size(tmp_path):
    source = tmp_path / "source.png"
    cache = tmp_path / "cache.webp"
    Image.new("RGB", (500, 500), color="red").save(str(source), format="PNG")
    Image.new("RGB", (320, 320), color="red").save(str(cache), format="WEBP")
    source_time = source.stat().st_mtime
    os.utime(cache, (source_time + 10, source_time + 10))

    assert thumbnail_is_fresh(cache, source, (320, 320)) is True


def test_thumbnail_is_fresh_returns_false_for_missing_cache(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")

    assert thumbnail_is_fresh(tmp_path / "missing.webp", source) is False


def test_thumbnail_is_fresh_returns_false_for_non_image_source(tmp_path):
    source = tmp_path / "track.mp3"
    cache = tmp_path / "track.webp"
    source.write_bytes(b"audio")
    Image.new("RGB", (320, 320)).save(str(cache), format="WEBP")
    source_time = source.stat().st_mtime
    os.utime(cache, (source_time + 10, source_time + 10))

    assert thumbnail_is_fresh(cache, source, (320, 320)) is False


def test_generate_thumbnail_writes_valid_webp(tmp_path):
    source = tmp_path / "source.png"
    cache = tmp_path / "thumbs" / "source.webp"
    Image.new("RGB", (20, 20), color="red").save(str(source), format="PNG")

    generate_thumbnail(source, cache, (8, 8))

    with Image.open(cache) as img:
        assert img.format == "WEBP"
        assert img.size[0] <= 8
        assert img.size[1] <= 8


def test_generate_thumbnail_uses_high_quality_webp(tmp_path):
    source = Path("image_curator/media.py").read_text(encoding="utf-8")

    assert "quality=85" in source
    assert "method=6" in source


def test_audio_poster_has_stable_fallback_when_ffmpeg_is_missing(tmp_path):
    source = tmp_path / "track.mp3"
    cache = tmp_path / "track.webp"
    source.write_bytes(b"not-real-audio")

    generated = generate_media_poster(
        source,
        cache,
        (320, 320),
        media_kind="audio",
        ffmpeg_path=str(tmp_path / "missing-ffmpeg.exe"),
    )

    assert generated is True
    with Image.open(cache) as poster:
        assert poster.format == "WEBP"
        assert poster.size == (320, 320)


def test_hover_preview_cache_path_is_extension_safe(tmp_path):
    gif = hover_preview_cache_path(tmp_path, "batch", "inbox", "sample.gif")
    mp4 = hover_preview_cache_path(tmp_path, "batch", "inbox", "sample.mp4")

    assert gif != mp4
    assert gif.name == "inbox__sample--gif.mp4"
