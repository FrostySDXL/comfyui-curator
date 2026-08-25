import json

from image_curator.sidecar_metadata import (
    SIDECAR_MAX_BYTES,
    extract_media_metadata,
    inspect_json_sidecar,
)


def test_filename_preserving_sidecar_wins_and_is_pretty_printed(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    (tmp_path / "clip.json").write_text('{"source":"stem"}', encoding="utf-8")
    (tmp_path / "clip.mp4.json").write_text(
        '{"source":"exact","nested":{"rating":5}}', encoding="utf-8"
    )

    sidecar = inspect_json_sidecar(media)

    assert sidecar is not None
    assert sidecar["name"] == "clip.mp4.json"
    assert sidecar["error"] is None
    assert json.loads(sidecar["text"])["source"] == "exact"
    assert '\n  "nested"' in sidecar["text"]


def test_external_favorite_sidecar_preserves_original_types(tmp_path):
    media = tmp_path / "external_favorite_17590127_hash.jpg"
    media.write_bytes(b"jpg")
    expected = {
        "category": "external_favorites",
        "subcategory": "favorite",
        "favorite_id": 42,
        "id": "17590127",
        "width": "1280",
        "height": "1920",
        "score": "17",
        "tags": "tag1 tag2 tag3",
    }
    media.with_suffix(".json").write_text(json.dumps(expected), encoding="utf-8")

    sidecar = inspect_json_sidecar(media)

    assert sidecar is not None
    assert sidecar["data"] == expected
    assert isinstance(sidecar["data"]["id"], str)
    assert isinstance(sidecar["data"]["favorite_id"], int)


def test_invalid_sidecar_is_reported_as_metadata_instead_of_raising(tmp_path):
    media = tmp_path / "favorite.gif"
    media.write_bytes(b"gif")
    (tmp_path / "favorite.json").write_text("{not-json", encoding="utf-8")

    metadata = extract_media_metadata(media)

    assert metadata["has_metadata"] is True
    assert metadata["has_png_metadata"] is False
    assert metadata["has_sidecar"] is True
    assert metadata["sidecar"]["text"] is None
    assert "valid JSON" in metadata["sidecar"]["error"]


def test_oversized_and_symlink_sidecars_are_not_read(tmp_path):
    media = tmp_path / "large.jpg"
    media.write_bytes(b"jpg")
    sidecar = tmp_path / "large.jpg.json"
    sidecar.write_bytes(b"x" * (SIDECAR_MAX_BYTES + 1))

    result = inspect_json_sidecar(media)
    assert result is not None
    assert result["text"] is None
    assert "too large" in result["error"]

    sidecar.unlink()
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    try:
        sidecar.symlink_to(target)
    except OSError:
        return
    result = inspect_json_sidecar(media)
    assert result is not None
    assert result["text"] is None
    assert "regular file" in result["error"]
