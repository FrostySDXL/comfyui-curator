import os
import pytest
from pathlib import Path


def test_load_state_defaults_to_no_active_batch(app_module):
    assert app_module.load_state() == {"active_batch": None}


def test_save_state_round_trips_state_file(app_module):
    expected = {"active_batch": "test-batch"}

    app_module.save_state(expected)

    assert app_module.load_state() == expected


def test_create_batch_creates_expected_folder_structure(app_module):
    created = app_module.create_batch("alpha")

    assert created is True
    for folder in ["inbox", "shortlisted", "finals", "rejects"]:
        assert (app_module.BATCHES_DIR / "alpha" / folder).is_dir()


def test_create_batch_returns_false_when_batch_exists(app_module):
    app_module.create_batch("alpha")

    assert app_module.create_batch("alpha") is False


def test_get_images_filters_non_images_and_sorts_by_name(app_module, tmp_path, make_file):
    image_dir = tmp_path / "images"
    make_file(image_dir / "b.png")
    make_file(image_dir / "a.jpg")
    make_file(image_dir / "notes.txt")

    images = app_module.get_images(image_dir, sort_by="name", order="asc")

    assert [img.name for img in images] == ["a.jpg", "b.png"]


def test_get_batch_counts_counts_only_supported_image_types(app_module, make_file):
    app_module.create_batch("alpha")
    make_file(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png")
    make_file(app_module.BATCHES_DIR / "alpha" / "inbox" / "ignore.txt")
    make_file(app_module.BATCHES_DIR / "alpha" / "finals" / "two.webp")

    counts = app_module.get_batch_counts("alpha")

    assert counts == {
        "inbox": 1,
        "shortlisted": 0,
        "finals": 1,
        "rejects": 0,
    }


def test_get_batch_metadata_returns_modified_time(app_module):
    app_module.create_batch("alpha")

    metadata = app_module.get_batch_metadata("alpha")

    assert "modified_at" in metadata
    assert metadata["modified_at"] > 0


# ---------------------------------------------------------------------------
# _safe_path tests (path traversal guard)
# ---------------------------------------------------------------------------


def test_safe_path_normal_file(app_module, tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "file.png").write_text("")

    resolved, err = app_module._safe_path(base, "file.png")

    assert err is None
    assert resolved == (base / "file.png").resolve()


def test_safe_path_subdirectory(app_module, tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "sub").mkdir()

    resolved, err = app_module._safe_path(base, "sub", "file.png")

    assert err is None
    assert resolved == (base / "sub" / "file.png").resolve()


def test_safe_path_empty_parts(app_module, tmp_path):
    base = tmp_path / "base"
    base.mkdir()

    resolved, err = app_module._safe_path(base)

    assert err is None
    assert resolved == base.resolve()


def test_safe_path_blocks_single_dotdot(app_module, tmp_path):
    base = tmp_path / "base"
    base.mkdir()

    resolved, err = app_module._safe_path(base, "..", "etc", "passwd")

    assert err is not None
    assert resolved is None


def test_safe_path_blocks_deep_dotdot(app_module, tmp_path):
    base = tmp_path / "base" / "nested"
    base.mkdir(parents=True)

    resolved, err = app_module._safe_path(base, "..", "..", "outside.txt")

    assert err is not None
    assert resolved is None


def test_safe_path_blocks_absolute_path(app_module, tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    abs_path = str(tmp_path / "other" / "file.txt")

    resolved, err = app_module._safe_path(base, abs_path)

    assert err is not None
    assert resolved is None


# ---------------------------------------------------------------------------
# _validate_ai_curate_request tests (AI job submission validation)
# ---------------------------------------------------------------------------


def test_validate_ai_curate_missing_batch(app_module):
    params, err = app_module._validate_ai_curate_request({})
    assert params is None
    assert err[0]["error"] == "batch is required"
    assert err[1] == 400


def test_validate_ai_curate_nonexistent_batch(app_module):
    params, err = app_module._validate_ai_curate_request({"batch": "nope"})
    assert params is None
    assert "does not exist" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_missing_prompt(app_module):
    app_module.create_batch("alpha")
    params, err = app_module._validate_ai_curate_request({"batch": "alpha"})
    assert params is None
    assert err[0]["error"] == "prompt is required"
    assert err[1] == 400


def test_validate_ai_curate_invalid_source_folder(app_module):
    app_module.create_batch("alpha")
    params, err = app_module._validate_ai_curate_request(
        {"batch": "alpha", "prompt": "test", "source_folder": "badfolder"}
    )
    assert params is None
    assert "source_folder" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_elements_not_list(app_module):
    app_module.create_batch("alpha")
    params, err = app_module._validate_ai_curate_request(
        {"batch": "alpha", "prompt": "test", "elements": "not-a-list"}
    )
    assert params is None
    assert "elements must be a list" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_elements_exceed_cap(app_module):
    app_module.create_batch("alpha")
    too_many = [f"element-{i}" for i in range(20)]
    params, err = app_module._validate_ai_curate_request(
        {"batch": "alpha", "prompt": "test", "elements": too_many}
    )
    assert params is None
    assert "too many elements" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_top_n_not_integer(app_module):
    app_module.create_batch("alpha")
    params, err = app_module._validate_ai_curate_request(
        {"batch": "alpha", "prompt": "test", "top_n": "abc"}
    )
    assert params is None
    assert "top_n must be an integer" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_top_n_out_of_range(app_module):
    app_module.create_batch("alpha")
    params, err = app_module._validate_ai_curate_request(
        {"batch": "alpha", "prompt": "test", "top_n": 0}
    )
    assert params is None
    assert "top_n must be between" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_move_without_destination(app_module):
    app_module.create_batch("alpha")
    params, err = app_module._validate_ai_curate_request(
        {"batch": "alpha", "prompt": "test", "move_enabled": True}
    )
    assert params is None
    assert "destination_folder is required" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_move_invalid_destination(app_module):
    app_module.create_batch("alpha")
    params, err = app_module._validate_ai_curate_request(
        {
            "batch": "alpha",
            "prompt": "test",
            "move_enabled": True,
            "destination_folder": "badfolder",
        }
    )
    assert params is None
    assert "destination_folder" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_missing_model(app_module, monkeypatch):
    app_module.create_batch("alpha")
    # Ensure DEFAULT_MODEL is empty
    monkeypatch.setattr(app_module, "DEFAULT_MODEL", "")
    params, err = app_module._validate_ai_curate_request({"batch": "alpha", "prompt": "test"})
    assert params is None
    assert "model is required" in err[0]["error"]
    assert err[1] == 400


def test_validate_ai_curate_valid_minimal_request(app_module, monkeypatch):
    app_module.create_batch("alpha")
    monkeypatch.setattr(app_module, "DEFAULT_MODEL", "vl-scorer")
    params, err = app_module._validate_ai_curate_request(
        {"batch": "alpha", "prompt": "test", "model": "vl-scorer"}
    )
    assert err is None
    assert params["batch"] == "alpha"
    assert params["prompt"] == "test"
    assert params["source_folder"] == "inbox"
    assert params["top_n"] == 15
    assert params["move_enabled"] is False
    assert params["destination_folder"] is None
    assert params["elements"] is None


def test_validate_ai_curate_valid_with_elements_and_move(app_module, monkeypatch):
    app_module.create_batch("alpha")
    monkeypatch.setattr(app_module, "DEFAULT_MODEL", "vl-scorer")
    params, err = app_module._validate_ai_curate_request(
        {
            "batch": "alpha",
            "prompt": "test prompt",
            "model": "vl-scorer",
            "elements": ["sharp focus", "good lighting"],
            "top_n": 5,
            "move_enabled": True,
            "destination_folder": "shortlisted",
            "source_folder": "inbox",
        }
    )
    assert err is None
    assert params["elements"] == ["sharp focus", "good lighting"]
    assert params["top_n"] == 5
    assert params["move_enabled"] is True
    assert params["destination_folder"] == "shortlisted"


# ---------------------------------------------------------------------------
# ImageWatcher tests (background auto-import watcher)
# ---------------------------------------------------------------------------


def test_watcher_start_stop_lifecycle(app_module):
    # Override COMFYUI_OUTPUT in the watcher's constructor scope by patching
    # the module-level COMFYUI_OUTPUT used inside ImageWatcher.__init__
    import app as app_mod

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(app_mod, "COMFYUI_OUTPUT", app_module.COMFYUI_OUTPUT)
        w = app_module.ImageWatcher()

    w.start()
    assert w.running is True
    assert w.thread is not None
    assert w.thread.is_alive()

    w.stop()
    assert w.running is False
    # Thread should have joined within the 3s timeout
    assert not w.thread.is_alive()


def test_watcher_no_active_batch_does_not_import(app_module, tmp_path, make_file):
    """When no active batch is set, the watcher should not move files."""
    import app as app_mod

    comfy_out = tmp_path / "comfy-output"
    comfy_out.mkdir()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(app_mod, "COMFYUI_OUTPUT", comfy_out)
        w = app_module.ImageWatcher()

    # Place a new file in the output directory (not yet seen)
    make_file(comfy_out / "fresh.png")

    # Manually add it to seen_files so the pre-existing scan doesn't catch it,
    # then remove it so _check_for_new_images sees it as new
    w.seen_files = set()

    # Ensure no active batch
    app_module.save_state({"active_batch": None})

    w._check_for_new_images()

    # File should still be in comfy output (not moved)
    assert (comfy_out / "fresh.png").exists()
