import pytest
from PIL import Image


# Helper to create a valid small PNG for thumbnail/image-serving tests
def _write_test_png(path, size=(4, 4)):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color="red")
    img.save(str(path), format="PNG")


@pytest.mark.component
def test_get_batches_returns_counts_active_batch_and_pending_count(client, app_module, make_file):
    app_module.create_batch("alpha")
    app_module.save_state({"active_batch": "alpha"})
    make_file(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png")
    make_file(app_module.COMFYUI_OUTPUT / "pending.png")

    response = client.get("/api/batches")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["batches"] == ["alpha"]
    assert payload["active_batch"] == "alpha"
    assert payload["counts"]["alpha"]["inbox"] == 1
    assert payload["batch_meta"]["alpha"]["modified_at"] > 0
    assert payload["pending_count"] == 1


@pytest.mark.component
def test_create_batch_api_creates_batch(client, app_module):
    response = client.post("/api/batches", json={"name": "new-batch"})

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert (app_module.BATCHES_DIR / "new-batch" / "inbox").is_dir()


@pytest.mark.component
def test_create_batch_api_rejects_blank_name(client):
    response = client.post("/api/batches", json={"name": "   "})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Name required"


@pytest.mark.component
def test_set_active_batch_updates_state_file(client, app_module):
    app_module.create_batch("focus")

    response = client.post("/api/active-batch", json={"batch": "focus"})

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert app_module.load_state() == {"active_batch": "focus"}


@pytest.mark.component
def test_delete_rejects_removes_files(client, app_module, make_file):
    app_module.create_batch("test-batch")
    rejects_dir = app_module.BATCHES_DIR / "test-batch" / "rejects"

    make_file(rejects_dir / "bad1.png")
    make_file(rejects_dir / "bad2.webp")

    response = client.post("/api/delete-rejects/test-batch")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 2
    assert not (rejects_dir / "bad1.png").exists()
    assert not (rejects_dir / "bad2.webp").exists()


@pytest.mark.component
def test_delete_rejects_nonexistent_batch(client):
    response = client.post("/api/delete-rejects/no-such-batch")
    assert response.status_code == 400


@pytest.mark.component
def test_serve_thumbnail_returns_webp(client, app_module):
    app_module.create_batch("batch")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "inbox" / "test.png")

    response = client.get("/thumb/batch/inbox/test.png")

    assert response.status_code == 200
    assert response.mimetype == "image/webp"


@pytest.mark.component
def test_serve_thumbnail_missing_file(client, app_module):
    app_module.create_batch("batch")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "inbox" / "test.png")

    response = client.get("/thumb/batch/inbox/nonexistent.png")

    assert response.status_code == 404


@pytest.mark.component
def test_serve_image_returns_file(client, app_module):
    app_module.create_batch("batch")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "inbox" / "test.png")

    response = client.get("/image/batch/inbox/test.png")

    assert response.status_code == 200


@pytest.mark.component
def test_serve_image_missing_returns_404(client, app_module):
    app_module.create_batch("batch")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "inbox" / "test.png")

    response = client.get("/image/batch/inbox/nonexistent.png")

    assert response.status_code == 404
