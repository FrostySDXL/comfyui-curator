import os

from PIL import Image

from image_curator.media import generate_thumbnail, thumbnail_cache_path, thumbnail_is_fresh


def test_thumbnail_cache_path_namespaces_by_folder(tmp_path):
    path = thumbnail_cache_path(tmp_path, "batch", "inbox", "sample.png")

    assert path == tmp_path / "batch" / ".thumbs" / "inbox__sample.webp"


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


def test_thumbnail_is_fresh_returns_false_for_missing_cache(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")

    assert thumbnail_is_fresh(tmp_path / "missing.webp", source) is False


def test_generate_thumbnail_writes_valid_webp(tmp_path):
    source = tmp_path / "source.png"
    cache = tmp_path / "thumbs" / "source.webp"
    Image.new("RGB", (20, 20), color="red").save(str(source), format="PNG")

    generate_thumbnail(source, cache, (8, 8))

    with Image.open(cache) as img:
        assert img.format == "WEBP"
        assert img.size[0] <= 8
        assert img.size[1] <= 8
