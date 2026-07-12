import pytest


@pytest.mark.integration
def test_import_all_moves_available_images(client, app_module, make_file):
    app_module.create_batch("alpha")
    make_file(app_module.COMFYUI_OUTPUT / "one.png")
    make_file(app_module.COMFYUI_OUTPUT / "two.jpg")
    make_file(app_module.COMFYUI_OUTPUT / "skip.txt")
    response = client.post("/api/import-all", json={"batch": "alpha"})

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "count": 2}
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
