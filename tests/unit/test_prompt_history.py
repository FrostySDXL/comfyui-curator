import json
from pathlib import Path

import pytest
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


def test_build_index_ignores_non_png_typed_media(tmp_path):
    make_batch(tmp_path)
    write_png(tmp_path / "alpha" / "inbox" / "prompt.png", "cat\nSteps: 1")
    for filename in ("animation.gif", "clip.mp4", "track.mp3"):
        (tmp_path / "alpha" / "inbox" / filename).write_bytes(b"media")

    index = build_prompt_index(tmp_path, "alpha")

    assert index["image_count"] == 1
    assert index["prompts"][0]["images"] == [{"filename": "prompt.png", "folder": "inbox"}]


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


# ---------------------------------------------------------------------------
# Safety: symlink and containment escape rejection
# ---------------------------------------------------------------------------


def _symlink_directory_or_skip_unit(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        import pytest

        pytest.skip(f"directory symlink unavailable on this platform or permission set: {exc}")


def _symlink_file_or_skip_unit(link, target):
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        import pytest

        pytest.skip(f"file symlink unavailable on this platform or permission set: {exc}")


def test_build_rejects_symlinked_stage_no_cache(tmp_path):
    """build_prompt_index must reject a symlinked review stage without creating prompt-history.json."""
    make_batch(tmp_path, "alpha")
    real_stage = tmp_path / "alpha" / "inbox"
    real_stage.rmdir()
    outside = tmp_path / "outside-symlink-build"
    outside.mkdir()
    write_png(outside / "escaped.png", "secret\nSteps: 1")
    _symlink_directory_or_skip_unit(real_stage, outside)

    write_png(tmp_path / "alpha" / "shortlisted" / "valid.png", "safe prompt\nSteps: 1")
    with pytest.raises(ValueError, match="Unsafe prompt history path"):
        build_prompt_index(tmp_path, "alpha")

    cache_file = tmp_path / "alpha" / "prompt-history.json"
    assert not cache_file.exists()
    assert not cache_file.with_suffix(".json.tmp").exists()


def test_build_rejects_resolved_escape_stage_no_cache(tmp_path, monkeypatch):
    """build_prompt_index must reject a stage whose resolved path escapes the batch root even when
    is_symlink() returns False."""
    make_batch(tmp_path, "alpha")
    inbox = tmp_path / "alpha" / "inbox"
    outside = tmp_path / "outside-resolve-build"
    outside.mkdir()
    write_png(outside / "escaped.png", "secret\nSteps: 1")
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == inbox:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    with pytest.raises(ValueError, match="Unsafe prompt history path"):
        build_prompt_index(tmp_path, "alpha")

    cache_file = tmp_path / "alpha" / "prompt-history.json"
    assert not cache_file.exists()


def test_count_rejects_symlinked_stage(tmp_path):
    """count_prompt_index_images must not count PNGs reached through a symlinked stage."""
    from image_curator.prompt_history import count_prompt_index_images

    make_batch(tmp_path, "alpha")
    inbox = tmp_path / "alpha" / "inbox"
    inbox.rmdir()
    outside = tmp_path / "outside-symlink-count"
    outside.mkdir()
    write_png(outside / "count-me.png", "secret\nSteps: 1")
    _symlink_directory_or_skip_unit(inbox, outside)

    # Add a valid image in a safe stage
    write_png(tmp_path / "alpha" / "shortlisted" / "safe.png", "ok\nSteps: 1")

    with pytest.raises(ValueError, match="Unsafe prompt history path"):
        count_prompt_index_images(tmp_path, "alpha")


def test_count_rejects_resolved_escape_stage(tmp_path, monkeypatch):
    """count_prompt_index_images must not count PNGs when a stage resolves outside the batch root."""
    from image_curator.prompt_history import count_prompt_index_images

    make_batch(tmp_path, "alpha")
    inbox = tmp_path / "alpha" / "inbox"
    outside = tmp_path / "outside-count-resolve"
    outside.mkdir()
    write_png(outside / "count-me.png", "secret\nSteps: 1")
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == inbox:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    # Also write a valid image in a safe stage
    write_png(tmp_path / "alpha" / "shortlisted" / "safe.png", "ok\nSteps: 1")

    with pytest.raises(ValueError, match="Unsafe prompt history path"):
        count_prompt_index_images(tmp_path, "alpha")


def test_load_rejects_symlinked_cache(tmp_path):
    """load_prompt_index must return None for a symlinked cache file."""
    make_batch(tmp_path, "alpha")
    cache_path = tmp_path / "alpha" / "prompt-history.json"
    outside = tmp_path / "outside-symlink-load"
    outside.mkdir()
    outside_cache = outside / "fake.json"
    outside_cache.write_text('{"batch": "alpha", "image_count": 999}', encoding="utf-8")
    _symlink_file_or_skip_unit(cache_path, outside_cache)

    result = load_prompt_index(tmp_path, "alpha")
    assert result is None, "symlinked cache must not be loaded"


def test_load_rejects_non_regular_cache(tmp_path):
    """load_prompt_index must return None when the cache path is a directory."""
    make_batch(tmp_path, "alpha")
    cache_path = tmp_path / "alpha" / "prompt-history.json"
    cache_path.mkdir()

    result = load_prompt_index(tmp_path, "alpha")
    assert result is None, "non-regular cache entry must not be loaded"


def test_load_all_skips_unsafe_batch_cache(tmp_path):
    """load_all_prompt_indices must skip batches with unsafe caches while returning safe indices."""
    make_batch(tmp_path, "alpha")
    make_batch(tmp_path, "beta")
    write_png(tmp_path / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
    write_png(tmp_path / "beta" / "inbox" / "two.png", "dog\nSteps: 1")
    build_prompt_index(tmp_path, "alpha")
    build_prompt_index(tmp_path, "beta")

    # Make beta's cache symlinked
    beta_cache = tmp_path / "beta" / "prompt-history.json"
    outside = tmp_path / "outside-aggregate"
    outside.mkdir()
    fake_cache = outside / "fake.json"
    fake_cache.write_text('{"batch": "beta", "image_count": 9999, "prompts": []}', encoding="utf-8")
    _symlink_file_or_skip_unit(beta_cache, fake_cache)

    result = load_all_prompt_indices(tmp_path)
    # alpha is safe, beta is not
    assert "alpha" in result["batches"], "safe batch must be included"
    assert "beta" not in result["batches"], "batch with symlinked cache must be excluded"
    assert result["total_prompts"] == 1


def test_build_with_preexisting_symlinked_cache_does_not_read_or_mutate(tmp_path):
    """build_prompt_index must not read through a symlinked cache to build its index."""
    make_batch(tmp_path, "alpha")
    write_png(tmp_path / "alpha" / "inbox" / "real.png", "real prompt\nSteps: 1")

    # Pre-create a symlinked cache
    cache_path = tmp_path / "alpha" / "prompt-history.json"
    outside = tmp_path / "outside-pre-existing"
    outside.mkdir()
    craft = outside / "crafted.json"
    craft.write_text(
        '{"batch": "alpha", "image_count": 9999, "prompt_count": 1, '
        '"prompts": [{"hash": "abc", "prompt": "INJECTED", "count": 9999}]}',
        encoding="utf-8",
    )
    _symlink_file_or_skip_unit(cache_path, craft)

    original = craft.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe prompt history path"):
        build_prompt_index(tmp_path, "alpha")

    assert cache_path.is_symlink()
    assert craft.read_text(encoding="utf-8") == original


def test_build_rejects_symlinked_tmp_cache_without_external_write(tmp_path):
    make_batch(tmp_path, "alpha")
    write_png(tmp_path / "alpha" / "inbox" / "real.png", "real prompt\nSteps: 1")
    cache_path = tmp_path / "alpha" / "prompt-history.json"
    tmp_cache = cache_path.with_suffix(".json.tmp")
    outside = tmp_path / "outside-tmp.json"
    outside.write_text("unchanged", encoding="utf-8")
    _symlink_file_or_skip_unit(tmp_cache, outside)

    with pytest.raises(ValueError, match="Unsafe prompt history path"):
        build_prompt_index(tmp_path, "alpha")

    assert outside.read_text(encoding="utf-8") == "unchanged"
    assert tmp_cache.is_symlink()
    assert not cache_path.exists()


def test_build_rejects_symlinked_png_entry_without_cache(tmp_path):
    make_batch(tmp_path, "alpha")
    outside = tmp_path / "outside-image.png"
    write_png(outside, "secret prompt\nSteps: 1")
    linked = tmp_path / "alpha" / "inbox" / "linked.png"
    _symlink_file_or_skip_unit(linked, outside)

    with pytest.raises(ValueError, match="Unsafe prompt history path"):
        build_prompt_index(tmp_path, "alpha")

    assert not (tmp_path / "alpha" / "prompt-history.json").exists()


def test_load_rejects_cache_resolved_into_another_batch(tmp_path, monkeypatch):
    make_batch(tmp_path, "alpha")
    make_batch(tmp_path, "beta")
    alpha_cache = tmp_path / "alpha" / "prompt-history.json"
    beta_cache = tmp_path / "beta" / "prompt-history.json"
    alpha_cache.write_text('{"batch": "alpha"}', encoding="utf-8")
    beta_cache.write_text('{"batch": "beta", "prompt_count": 99}', encoding="utf-8")
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == alpha_cache:
            return beta_cache
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert load_prompt_index(tmp_path, "alpha") is None
