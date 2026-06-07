import pytest


@pytest.mark.unit
def test_load_state_defaults_to_no_active_batch(app_module):
    assert app_module.load_state() == {"active_batch": None}


@pytest.mark.unit
def test_save_state_round_trips_state_file(app_module):
    expected = {"active_batch": "test-batch"}

    app_module.save_state(expected)

    assert app_module.load_state() == expected


@pytest.mark.unit
def test_create_batch_creates_expected_folder_structure(app_module):
    created = app_module.create_batch("alpha")

    assert created is True
    for folder in ["inbox", "shortlisted", "finals", "rejects"]:
        assert (app_module.BATCHES_DIR / "alpha" / folder).is_dir()


@pytest.mark.unit
def test_create_batch_returns_false_when_batch_exists(app_module):
    app_module.create_batch("alpha")

    assert app_module.create_batch("alpha") is False


@pytest.mark.unit
def test_get_images_filters_non_images_and_sorts_by_name(app_module, tmp_path, make_file):
    image_dir = tmp_path / "images"
    make_file(image_dir / "b.png")
    make_file(image_dir / "a.jpg")
    make_file(image_dir / "notes.txt")

    images = app_module.get_images(image_dir, sort_by="name", order="asc")

    assert [img.name for img in images] == ["a.jpg", "b.png"]


@pytest.mark.unit
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


@pytest.mark.unit
def test_get_batch_metadata_returns_modified_time(app_module):
    app_module.create_batch("alpha")

    metadata = app_module.get_batch_metadata("alpha")

    assert "modified_at" in metadata
    assert metadata["modified_at"] > 0
