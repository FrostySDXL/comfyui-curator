from pathlib import Path

import pytest

from image_curator import batch_store

pytestmark = pytest.mark.integration


@pytest.mark.integration
def test_import_all_moves_available_images(client, create_batch, native_settings, make_file):
    create_batch("alpha")
    make_file(native_settings.import_source / "one.png")
    make_file(native_settings.import_source / "two.jpg")
    make_file(native_settings.import_source / "skip.txt")
    response = client.post("/api/curator/import-all", json_body={"batch": "alpha"})

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "count": 2,
        "failed_count": 0,
        "renamed_count": 0,
        "pending_count": 0,
        "status": "completed",
    }
    assert (native_settings.batch_root / "alpha" / "inbox" / "one.png").exists()
    assert (native_settings.batch_root / "alpha" / "inbox" / "two.jpg").exists()
    assert not (native_settings.import_source / "one.png").exists()
    assert not (native_settings.import_source / "two.jpg").exists()
    assert (native_settings.import_source / "skip.txt").exists()


@pytest.mark.integration
def test_import_all_requires_batch_name(client):
    response = client.post("/api/curator/import-all", json_body={"batch": ""})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Batch required"


@pytest.mark.integration
def test_import_all_rejects_missing_batch_without_creating_phantom(
    client, create_batch, native_settings, make_file
):
    create_batch("alpha")
    make_file(native_settings.import_source / "pending.png")

    response = client.post("/api/curator/import-all", json_body={"batch": "missing"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "Batch does not exist"}
    assert (native_settings.import_source / "pending.png").exists()
    assert not (native_settings.batch_root / "missing").exists()


@pytest.mark.integration
def test_import_all_rejects_inbox_resolved_outside_before_mutation(
    client, create_batch, native_settings, native_service, make_file, monkeypatch
):
    create_batch("alpha")
    make_file(native_settings.import_source / "pending.png")

    def reject(_batch, _folder):
        raise ValueError("Invalid import destination")

    monkeypatch.setattr(native_service, "resolve_content_directory", reject)

    response = client.post("/api/curator/import-all", json_body={"batch": "alpha"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid import destination"}
    assert (native_settings.import_source / "pending.png").exists()


@pytest.mark.integration
def test_import_all_reports_partial_move_outcome(
    client, create_batch, native_settings, make_file, monkeypatch
):
    create_batch("alpha")
    make_file(native_settings.import_source / "good.png")
    make_file(native_settings.import_source / "failed.jpg")
    original_move = batch_store.move_image

    def fail_one(src, dst, **kwargs):
        if Path(src).name == "failed.jpg":
            return False
        return original_move(src, dst, **kwargs)

    monkeypatch.setattr(batch_store, "move_image", fail_one)

    response = client.post("/api/curator/import-all", json_body={"batch": "alpha"})

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "count": 1,
        "failed_count": 1,
        "renamed_count": 0,
        "pending_count": 1,
        "status": "partial",
    }


@pytest.mark.integration
@pytest.mark.parametrize("error_type", [ValueError, OSError])
def test_import_all_maps_post_validation_failures_to_bad_request(
    client, create_batch, native_service, native_settings, monkeypatch, error_type
):
    create_batch("alpha")

    def fail_after_validation(batch_name):
        raise error_type("import destination changed")

    monkeypatch.setattr(native_service.auto_import, "manual", fail_after_validation)

    response = client.post("/api/curator/import-all", json_body={"batch": "alpha"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "import destination changed"}
