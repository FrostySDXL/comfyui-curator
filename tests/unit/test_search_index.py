import json
import os

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from image_curator import batch_store
from image_curator import search_index
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
    assert result["index_statuses"] == [
        {
            "batch": "external-favorites",
            "status": "ready",
            "built_at": built["built_at"],
            "item_count": 1,
        }
    ]


def test_search_index_rebuild_reuses_unchanged_media_without_extracting(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "incremental")
    media = batches_dir / "incremental" / "inbox" / "subject.jpg"
    media.write_bytes(b"image")

    build_search_index(batches_dir, "incremental")

    def fail_extract(*_args, **_kwargs):
        raise AssertionError("unchanged media should be reused from the prior index")

    monkeypatch.setattr(search_index, "extract_media_metadata", fail_extract)
    rebuilt = build_search_index(batches_dir, "incremental")

    assert rebuilt["item_count"] == 1
    assert rebuilt["reused_count"] == 1
    assert rebuilt["scanned_count"] == 0


def test_search_index_manifest_does_not_rescan_through_batch_store(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "fast-manifest")
    (batches_dir / "fast-manifest" / "inbox" / "subject.jpg").write_bytes(b"image")

    def fail_get_images(*_args, **_kwargs):
        raise AssertionError("incremental manifest should use one scandir pass per stage")

    monkeypatch.setattr(batch_store, "get_images", fail_get_images)
    built = build_search_index(batches_dir, "fast-manifest")

    assert built["item_count"] == 1


def test_search_index_reuses_files_with_identical_stat_tuples(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "fast-identical-stats")
    inbox = batches_dir / "fast-identical-stats" / "inbox"
    for number in range(3):
        path = inbox / f"same-{number}.jpg"
        path.write_bytes(b"same")
        os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    build_search_index(batches_dir, "fast-identical-stats")

    def fail_extract(*_args, **_kwargs):
        raise AssertionError("unique filenames should disambiguate unchanged files")

    monkeypatch.setattr(search_index, "extract_media_metadata", fail_extract)
    rebuilt = build_search_index(batches_dir, "fast-identical-stats")

    assert rebuilt["reused_count"] == 3
    assert rebuilt["scanned_count"] == 0


def test_search_index_case_folded_sidecar_changes_invalidate_reuse(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "case-sidecar")
    media = batches_dir / "case-sidecar" / "inbox" / "asset.jpg"
    media.write_bytes(b"image")
    sidecar = media.with_name("ASSET.JPG.JSON")
    sidecar.write_text(json.dumps({"tags": "old"}), encoding="utf-8")
    monkeypatch.setattr(search_index.os.path, "normcase", lambda value: str(value).casefold())
    candidate = media.with_name("asset.jpg.json")
    monkeypatch.setattr(search_index, "json_sidecar_candidates", lambda _path: (candidate,))

    calls = []

    def fake_extract(path):
        calls.append(path.name)
        return {
            "has_png_metadata": False,
            "parameters": {},
            "loras": [],
            "sidecar": {"error": None, "data": {"tags": sidecar.read_text()}},
        }

    monkeypatch.setattr(search_index, "extract_media_metadata", fake_extract)
    build_search_index(batches_dir, "case-sidecar")

    calls.clear()
    sidecar.write_text(json.dumps({"tags": "new"}), encoding="utf-8")
    build_search_index(batches_dir, "case-sidecar")

    assert calls == ["asset.jpg"]


def test_search_index_rebuild_scans_only_media_with_changed_sidecar(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "incremental-sidecar")
    inbox = batches_dir / "incremental-sidecar" / "inbox"
    first = inbox / "first.jpg"
    second = inbox / "second.jpg"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    sidecar = first.with_name("first.jpg.json")
    sidecar.write_text(json.dumps({"tags": "old"}), encoding="utf-8")
    build_search_index(batches_dir, "incremental-sidecar")

    calls = []
    original_extract = search_index.extract_media_metadata

    def counted_extract(path):
        calls.append(path.name)
        return original_extract(path)

    monkeypatch.setattr(search_index, "extract_media_metadata", counted_extract)
    sidecar.write_text(json.dumps({"tags": "new"}), encoding="utf-8")
    rebuilt = build_search_index(batches_dir, "incremental-sidecar")

    assert calls == ["first.jpg"]
    assert rebuilt["reused_count"] == 1
    assert rebuilt["scanned_count"] == 1
    assert query_search_indices(batches_dir, "new", batch="incremental-sidecar")["total"] == 1


def test_search_index_rebuild_reuses_move_and_removes_deleted_media(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "incremental-move")
    inbox = batches_dir / "incremental-move" / "inbox"
    moved = inbox / "moved.jpg"
    deleted = inbox / "deleted.jpg"
    moved.write_bytes(b"move")
    deleted.write_bytes(b"delete")
    build_search_index(batches_dir, "incremental-move")
    assert batch_store.move_image(
        moved, batches_dir / "incremental-move" / "shortlisted" / moved.name
    )
    deleted.unlink()

    def fail_extract(*_args, **_kwargs):
        raise AssertionError("moved unchanged media should be reused")

    monkeypatch.setattr(search_index, "extract_media_metadata", fail_extract)
    rebuilt = build_search_index(batches_dir, "incremental-move")

    assert rebuilt["item_count"] == 1
    assert rebuilt["items"][0]["name"] == "moved.jpg"
    assert rebuilt["items"][0]["folder"] == "shortlisted"
    assert rebuilt["reused_count"] == 1
    assert query_search_indices(batches_dir, "moved", batch="incremental-move")["total"] == 1
    assert query_search_indices(batches_dir, "deleted", batch="incremental-move")["total"] == 0


def test_search_index_legacy_cache_upgrades_after_full_scan(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "incremental-legacy")
    media = batches_dir / "incremental-legacy" / "inbox" / "legacy.jpg"
    media.write_bytes(b"legacy")
    built = build_search_index(batches_dir, "incremental-legacy")
    legacy = dict(built)
    legacy["items"] = [
        {key: value for key, value in item.items() if key != "fingerprint"}
        for item in built["items"]
    ]
    (batches_dir / "incremental-legacy" / "search-index.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    search_index._INDEX_CACHE.clear()
    calls = []
    original_extract = search_index.extract_media_metadata
    monkeypatch.setattr(
        search_index,
        "extract_media_metadata",
        lambda path: (calls.append(path.name), original_extract(path))[1],
    )

    rebuilt = build_search_index(batches_dir, "incremental-legacy")

    assert calls == ["legacy.jpg"]
    assert rebuilt["items"][0]["fingerprint"]


def test_search_index_does_not_commit_when_source_changes_at_commit(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "incremental-race")
    media = batches_dir / "incremental-race" / "inbox" / "race.jpg"
    media.write_bytes(b"before")
    original = build_search_index(batches_dir, "incremental-race")

    def mutate_source():
        media.write_bytes(b"after")

    import pytest

    with pytest.raises(ValueError, match="source changed"):
        build_search_index(batches_dir, "incremental-race", commit_check=mutate_source)
    assert (
        search_index.load_search_index(batches_dir, "incremental-race")["built_at"]
        == original["built_at"]
    )


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

    assert [item["name"] for item in result["items"]] == ["subject.jpg"]
    assert result["stale_batches"] == ["moving"]
    assert result["missing_batches"] == []
    assert result["index_statuses"][0]["status"] == "stale"
    assert result["index_statuses"][0]["item_count"] == 1


def test_search_index_query_freshness_does_not_enumerate_media(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "large")
    media = batches_dir / "large" / "inbox" / "subject.jpg"
    media.write_bytes(b"image")
    build_search_index(batches_dir, "large")

    def fail_get_images(*_args, **_kwargs):
        raise AssertionError("query freshness must not enumerate media")

    monkeypatch.setattr(batch_store, "get_images", fail_get_images)
    result = query_search_indices(batches_dir, "subject", batch="large")

    assert result["total"] == 1
    assert result["index_statuses"][0]["status"] == "ready"


def test_search_index_reuses_parsed_cache_between_queries(tmp_path, monkeypatch):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "cached")
    (batches_dir / "cached" / "inbox" / "subject.jpg").write_bytes(b"image")
    build_search_index(batches_dir, "cached")
    query_search_indices(batches_dir, "subject", batch="cached")

    original_loads = search_index.json.loads

    def fail_loads(*_args, **_kwargs):
        raise AssertionError("valid cached index should not be reparsed")

    monkeypatch.setattr(search_index.json, "loads", fail_loads)
    result = query_search_indices(batches_dir, "subject", batch="cached")

    assert result["total"] == 1
    monkeypatch.setattr(search_index.json, "loads", original_loads)


def test_search_index_does_not_query_cached_items_when_stage_becomes_unsafe(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "unsafe-query")
    inbox = batches_dir / "unsafe-query" / "inbox"
    (inbox / "subject.jpg").write_bytes(b"image")
    build_search_index(batches_dir, "unsafe-query")

    (inbox / "subject.jpg").unlink()
    inbox.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        inbox.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        return

    result = query_search_indices(batches_dir, "subject", batch="unsafe-query")

    assert result["items"] == []
    assert result["stale_batches"] == ["unsafe-query"]


def test_search_index_treats_malformed_source_state_as_missing(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "malformed-state")
    (batches_dir / "malformed-state" / "inbox" / "subject.jpg").write_bytes(b"image")
    built = build_search_index(batches_dir, "malformed-state")
    cache = batches_dir / "malformed-state" / "search-index.json"
    cache.write_text(
        json.dumps(
            {
                "version": 1,
                "batch": "malformed-state",
                "source_state": {},
                "items": built["items"],
            }
        ),
        encoding="utf-8",
    )

    result = query_search_indices(batches_dir, "subject", batch="malformed-state")

    assert result["items"] == []
    assert result["missing_batches"] == ["malformed-state"]


def test_search_index_reports_not_built_batches(tmp_path):
    batches_dir = tmp_path / "batches"
    batch_store.create_batch(batches_dir, "unbuilt")

    result = query_search_indices(batches_dir, "anything", batch="unbuilt")

    assert result["index_statuses"] == [
        {
            "batch": "unbuilt",
            "status": "not_built",
            "built_at": None,
            "item_count": 0,
        }
    ]


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
