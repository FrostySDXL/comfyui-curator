import json

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from image_curator import batch_store
from image_curator.search_index import build_search_index, query_search_indices


def test_search_index_matches_nested_sidecar_keys_and_values(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "external-favorites")
    media = batches_dir / "external-favorites" / "inbox" / "saved-post.jpg"
    media.write_bytes(b"not-decoded-during-sidecar-search")
    media.with_name("saved-post.jpg.json").write_text(
        json.dumps(
            {
                "category": "external_favorites",
                "subcategory": "favorite",
                "favorite_id": 81,
                "tags": "frosty_sky blue_hair",
                "source": {"website": "Example Gallery", "post_id": "17590127"},
            }
        ),
        encoding="utf-8",
    )

    built = build_search_index(batches_dir, "external-favorites")
    result = query_search_indices(batches_dir, "blue hair", batch="external-favorites")

    assert built["item_count"] == 1
    assert result["total"] == 1
    item = result["items"][0]
    assert item["name"] == "saved-post.jpg"
    assert item["batch"] == "external-favorites"
    assert item["folder"] == "inbox"
    assert item["metadata_sources"] == ["sidecar"]
    assert "sidecar" in item["matched_fields"]
    assert item["sidecar_summary"]["category"] == "external_favorites"
    assert item["sidecar_summary"]["subcategory"] == "favorite"
    assert item["sidecar_summary"]["tags"] == "frosty_sky blue_hair"
    assert item["sidecar_summary"]["favorite_id"] == 81
    assert isinstance(item["sidecar_summary"]["favorite_id"], int)


def test_search_index_matches_png_generation_fields_and_loras(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "generated")
    media = batches_dir / "generated" / "finals" / "portrait.png"
    info = PngInfo()
    info.add_text(
        "parameters",
        (
            "cinematic portrait <lora:CrystalDetails:0.8>\n"
            "Negative prompt: blurry, extra fingers\n"
            "Steps: 28, Sampler: DPM++ 2M, CFG scale: 6.5, Seed: 424242, "
            "Model: frosty-sdxl"
        ),
    )
    Image.new("RGB", (8, 8), "navy").save(media, pnginfo=info)

    build_search_index(batches_dir, "generated")
    result = query_search_indices(batches_dir, "crystal details 424242", batch="generated")

    assert result["total"] == 1
    item = result["items"][0]
    assert item["metadata_sources"] == ["png"]
    assert item["prompt"].startswith("cinematic portrait")
    assert item["negative_prompt"] == "blurry, extra fingers"
    assert item["seed"] == 424242
    assert item["model"] == "frosty-sdxl"
    assert item["loras"] == ["CrystalDetails"]
    assert set(item["matched_fields"]) == {"prompt", "seed", "lora"}


def test_search_index_marks_batch_stale_after_media_move(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "moving")
    source = batches_dir / "moving" / "inbox" / "subject.jpg"
    source.write_bytes(b"image")
    source.with_name("subject.jpg.json").write_text(
        json.dumps({"tags": "winter portrait"}), encoding="utf-8"
    )
    build_search_index(batches_dir, "moving")

    assert batch_store.move_image(source, batches_dir / "moving" / "shortlisted" / "subject.jpg")
    result = query_search_indices(batches_dir, "winter", batch="moving")

    assert result["items"] == []
    assert result["stale_batches"] == ["moving"]
    assert result["missing_batches"] == []


def test_search_index_rejects_symlinked_review_stage_without_writing_cache(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "unsafe")
    inbox = batches_dir / "unsafe" / "inbox"
    inbox.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        inbox.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        return

    try:
        build_search_index(batches_dir, "unsafe")
    except ValueError as exc:
        assert "Unsafe search index path" in str(exc)
    else:
        raise AssertionError("symlinked review stage should be rejected")
    assert not (batches_dir / "unsafe" / "search-index.json").exists()


def test_search_index_bounds_sidecar_summary_strings(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "bounded")
    media = batches_dir / "bounded" / "inbox" / "large.jpg"
    media.write_bytes(b"image")
    media.with_name("large.jpg.json").write_text(
        json.dumps({"tags": "needle " + ("x" * 10_000)}),
        encoding="utf-8",
    )

    build_search_index(batches_dir, "bounded")
    result = query_search_indices(batches_dir, "needle", batch="bounded")

    assert result["total"] == 1
    assert len(result["items"][0]["sidecar_summary"]["tags"]) == 4096


def test_search_index_treats_malformed_item_cache_as_missing(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "malformed")
    media = batches_dir / "malformed" / "inbox" / "item.jpg"
    media.write_bytes(b"image")
    built = build_search_index(batches_dir, "malformed")
    cache = batches_dir / "malformed" / "search-index.json"
    cache.write_text(
        json.dumps(
            {
                "version": 1,
                "batch": "malformed",
                "source_state": built["source_state"],
                "items": [None],
            }
        ),
        encoding="utf-8",
    )

    result = query_search_indices(batches_dir, "anything", batch="malformed")

    assert result["items"] == []
    assert result["missing_batches"] == ["malformed"]


def test_search_index_pages_a_stable_snapshot_after_a_review_move(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "large")
    inbox = batches_dir / "large" / "inbox"
    for number in range(5):
        (inbox / f"match-{number}.jpg").write_bytes(b"image")
    build_search_index(batches_dir, "large")

    first = query_search_indices(batches_dir, "match", batch="large", limit=2)
    assert [item["name"] for item in first["items"]] == [
        "match-0.jpg",
        "match-1.jpg",
    ]
    assert first["total"] == 5
    assert first["offset"] == 0
    assert first["next_offset"] == 2
    assert first["has_more"] is True
    assert isinstance(first["snapshot"], str) and first["snapshot"]

    assert batch_store.move_image(
        inbox / "match-0.jpg",
        batches_dir / "large" / "shortlisted" / "match-0.jpg",
    )
    second = query_search_indices(
        batches_dir,
        "match",
        batch="large",
        limit=2,
        offset=first["next_offset"],
        snapshot=first["snapshot"],
    )

    assert [item["name"] for item in second["items"]] == [
        "match-2.jpg",
        "match-3.jpg",
    ]
    assert second["total"] == 5
    assert second["offset"] == 2
    assert second["next_offset"] == 4
    assert second["has_more"] is True
    assert second["snapshot"] == first["snapshot"]
