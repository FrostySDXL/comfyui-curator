from pathlib import Path

import pytest


@pytest.mark.integration
def test_import_all_moves_available_images(client, app_module, make_file):
    app_module.create_batch("alpha")
    make_file(app_module.COMFYUI_OUTPUT / "one.png")
    make_file(app_module.COMFYUI_OUTPUT / "two.jpg")
    make_file(app_module.COMFYUI_OUTPUT / "skip.txt")
    response = client.post("/api/import-all", json={"batch": "alpha"})

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "count": 2,
        "failed_count": 0,
        "renamed_count": 0,
        "pending_count": 0,
        "status": "completed",
    }
    assert (app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png").exists()
    assert (app_module.BATCHES_DIR / "alpha" / "inbox" / "two.jpg").exists()
    assert not (app_module.COMFYUI_OUTPUT / "one.png").exists()
    assert not (app_module.COMFYUI_OUTPUT / "two.jpg").exists()
    assert (app_module.COMFYUI_OUTPUT / "skip.txt").exists()


@pytest.mark.integration
def test_import_all_requires_batch_name(client):
    response = client.post("/api/import-all", json={"batch": ""})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Batch required"


@pytest.mark.integration
def test_import_all_rejects_missing_batch_without_creating_phantom(client, app_module, make_file):
    make_file(app_module.COMFYUI_OUTPUT / "pending.png")

    response = client.post("/api/import-all", json={"batch": "missing"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "Batch does not exist"}
    assert (app_module.COMFYUI_OUTPUT / "pending.png").exists()
    assert not (app_module.BATCHES_DIR / "missing").exists()


@pytest.mark.integration
def test_import_all_rejects_inbox_resolved_outside_before_mutation(
    client, app_module, make_file, monkeypatch
):
    app_module.create_batch("alpha")
    make_file(app_module.COMFYUI_OUTPUT / "pending.png")
    inbox = app_module.BATCHES_DIR / "alpha" / "inbox"
    outside = app_module.BATCHES_DIR.parent / "outside-inbox"
    outside.mkdir()
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == inbox:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    response = client.post("/api/import-all", json={"batch": "alpha"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid import destination"}
    assert (app_module.COMFYUI_OUTPUT / "pending.png").exists()


@pytest.mark.integration
def test_import_all_reports_partial_move_outcome(client, app_module, make_file, monkeypatch):
    app_module.create_batch("alpha")
    make_file(app_module.COMFYUI_OUTPUT / "good.png")
    make_file(app_module.COMFYUI_OUTPUT / "failed.jpg")
    original_move = app_module.batch_store.move_image

    def fail_one(src, dst, **kwargs):
        if Path(src).name == "failed.jpg":
            return False
        return original_move(src, dst, **kwargs)

    monkeypatch.setattr(app_module.batch_store, "move_image", fail_one)

    response = client.post("/api/import-all", json={"batch": "alpha"})

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
    client, app_module, monkeypatch, error_type
):
    app_module.create_batch("alpha")

    def fail_after_validation(batch_name):
        raise error_type("import destination changed")

    monkeypatch.setattr(app_module, "import_all_pending_detailed", fail_after_validation)

    response = client.post("/api/import-all", json={"batch": "alpha"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "import destination changed"}
