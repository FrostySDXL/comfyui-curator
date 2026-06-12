import json

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from image_curator.prompt_history import (
    _normalize_prompt,
    _prompt_hash,
    build_prompt_index,
    load_all_prompt_indices,
    load_prompt_index,
)


def make_batch(batches_dir, batch="alpha"):
    for folder in ("inbox", "shortlisted", "finals", "rejects"):
        (batches_dir / batch / folder).mkdir(parents=True, exist_ok=True)


def write_png(path, parameters):
    png_info = PngInfo()
    png_info.add_text("parameters", parameters)
    Image.new("RGB", (1, 1), color="blue").save(path, pnginfo=png_info)


def test_normalize_strips_lora_tags_with_png_metadata_regex():
    assert _normalize_prompt("portrait <lora:name:1.0>  blue hair") == "portrait blue hair"


def test_normalize_collapses_whitespace_and_lowercases():
    assert _normalize_prompt("  Blue\n\tHair   Smile  ") == "blue hair smile"


def test_prompt_hash_is_deterministic():
    assert _prompt_hash("a", "b") == _prompt_hash("a", "b")


def test_prompt_hash_differs_for_different_negative_prompt():
    assert _prompt_hash("a", "b") != _prompt_hash("a", "c")


def test_build_index_collects_png_metadata_and_sorts_by_count(tmp_path):
    make_batch(tmp_path)
    write_png(tmp_path / "alpha" / "inbox" / "one.png", "cat\nNegative prompt: bad\nSteps: 1")
    write_png(tmp_path / "alpha" / "finals" / "two.png", "dog\nSteps: 1")

    index = build_prompt_index(tmp_path, "alpha")

    assert index["batch"] == "alpha"
    assert index["image_count"] == 2
    assert index["prompt_count"] == 2
    assert [entry["count"] for entry in index["prompts"]] == [1, 1]


def test_build_index_dedups_same_normalized_prompt_and_negative(tmp_path):
    make_batch(tmp_path)
    write_png(
        tmp_path / "alpha" / "inbox" / "one.png", "Cat <lora:x:1.0>\nNegative prompt: Bad\nSteps: 1"
    )
    write_png(
        tmp_path / "alpha" / "shortlisted" / "two.png", " cat  \nNegative prompt: bad\nSteps: 1"
    )

    index = build_prompt_index(tmp_path, "alpha")

    assert index["prompt_count"] == 1
    assert index["prompts"][0]["count"] == 2
    assert index["prompts"][0]["first_image"]["filename"] == "one.png"


def test_load_missing_prompt_index_returns_none(tmp_path):
    assert load_prompt_index(tmp_path, "alpha") is None


def test_build_index_cache_roundtrip_matches_original(tmp_path):
    make_batch(tmp_path)
    write_png(tmp_path / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")

    index = build_prompt_index(tmp_path, "alpha")

    loaded = load_prompt_index(tmp_path, "alpha")

    assert loaded == index
    raw = json.loads((tmp_path / "alpha" / "prompt-history.json").read_text(encoding="utf-8"))
    assert raw == index


def test_load_prompt_index_returns_none_for_corrupt_json(tmp_path):
    """Corrupt cache file should be handled gracefully, not raised."""
    make_batch(tmp_path)
    cache = tmp_path / "alpha" / "prompt-history.json"
    cache.write_text("this is not json", encoding="utf-8")

    result = load_prompt_index(tmp_path, "alpha")

    assert result is None


def test_save_cache_leaves_no_tmp_residue(tmp_path):
    """Atomic save via build_prompt_index must not leave .tmp files behind."""
    make_batch(tmp_path)
    write_png(tmp_path / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")

    build_prompt_index(tmp_path, "alpha")

    tmp_mask = tmp_path / "alpha" / "prompt-history.json.tmp"
    assert not tmp_mask.exists()


def test_load_all_prompt_indices_aggregates_batches(tmp_path):
    """Aggregate should collect cached indices across all batches."""
    make_batch(tmp_path, "alpha")
    write_png(tmp_path / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
    build_prompt_index(tmp_path, "alpha")

    make_batch(tmp_path, "beta")
    write_png(tmp_path / "beta" / "inbox" / "two.png", "dog\nSteps: 1")
    build_prompt_index(tmp_path, "beta")

    result = load_all_prompt_indices(tmp_path)

    assert sorted(result["batches"].keys()) == ["alpha", "beta"]
    assert result["total_prompts"] == 2
