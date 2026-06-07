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
    assert response.status_code == 404


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


# ---------------------------------------------------------------------------
# Uncovered route tests (C10)
# ---------------------------------------------------------------------------


@pytest.mark.component
def test_root_route_returns_ui(client):
    """GET / returns the web UI HTML page."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.mimetype == "text/html"


@pytest.mark.component
def test_api_images_returns_sorted_list(client, app_module, make_file):
    """GET /api/images/<batch>/<folder> returns sorted image list with name/size."""
    app_module.create_batch("batch")
    make_file(app_module.BATCHES_DIR / "batch" / "inbox" / "b.png")
    make_file(app_module.BATCHES_DIR / "batch" / "inbox" / "a.jpg")

    response = client.get("/api/images/batch/inbox?sort=name&order=asc")

    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 2
    assert data[0]["name"] == "a.jpg"
    assert data[1]["name"] == "b.png"
    assert "size" in data[0]


@pytest.mark.component
def test_api_images_nonexistent_batch(client):
    """GET /api/images returns 404 for nonexistent batch."""
    response = client.get("/api/images/nope/inbox")
    assert response.status_code == 404


@pytest.mark.component
def test_api_move_moves_single_file(client, app_module, make_file):
    """POST /api/move moves a single image between folders."""
    app_module.create_batch("batch")
    make_file(app_module.BATCHES_DIR / "batch" / "inbox" / "pic.png")

    response = client.post(
        "/api/move",
        json={
            "batch": "batch",
            "filename": "pic.png",
            "source": "inbox",
            "destination": "shortlisted",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert not (app_module.BATCHES_DIR / "batch" / "inbox" / "pic.png").exists()
    assert (app_module.BATCHES_DIR / "batch" / "shortlisted" / "pic.png").exists()


@pytest.mark.component
def test_api_move_nonexistent_batch(client):
    """POST /api/move returns 404 for nonexistent batch."""
    response = client.post(
        "/api/move",
        json={
            "batch": "nope",
            "filename": "pic.png",
            "source": "inbox",
            "destination": "shortlisted",
        },
    )
    assert response.status_code == 404


@pytest.mark.component
def test_api_move_missing_file(client, app_module):
    """POST /api/move returns 404 when file doesn't exist."""
    app_module.create_batch("batch")

    response = client.post(
        "/api/move",
        json={
            "batch": "batch",
            "filename": "ghost.png",
            "source": "inbox",
            "destination": "shortlisted",
        },
    )

    assert response.status_code == 404


@pytest.mark.component
def test_api_move_batch_bulk_moves_files(client, app_module, make_file):
    """POST /api/move-batch bulk-moves multiple images."""
    app_module.create_batch("batch")
    make_file(app_module.BATCHES_DIR / "batch" / "inbox" / "one.png")
    make_file(app_module.BATCHES_DIR / "batch" / "inbox" / "two.jpg")
    make_file(app_module.BATCHES_DIR / "batch" / "inbox" / "ignore.txt")

    response = client.post(
        "/api/move-batch",
        json={
            "batch": "batch",
            "filenames": ["one.png", "two.jpg", "ignore.txt"],
            "source": "inbox",
            "destination": "finals",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    # only image files should be moved; .txt stays (but route moves all filenames)
    assert not (app_module.BATCHES_DIR / "batch" / "inbox" / "one.png").exists()
    assert not (app_module.BATCHES_DIR / "batch" / "inbox" / "two.jpg").exists()
    assert (app_module.BATCHES_DIR / "batch" / "finals" / "one.png").exists()
    assert (app_module.BATCHES_DIR / "batch" / "finals" / "two.jpg").exists()


@pytest.mark.component
def test_api_move_batch_nonexistent_batch(client):
    """POST /api/move-batch returns 404 for nonexistent batch."""
    response = client.post(
        "/api/move-batch",
        json={
            "batch": "nope",
            "filenames": ["pic.png"],
            "source": "inbox",
            "destination": "shortlisted",
        },
    )
    assert response.status_code == 404


@pytest.mark.component
def test_api_move_batch_missing_params(client, app_module):
    """POST /api/move-batch returns 400 when parameters missing."""
    app_module.create_batch("batch")
    response = client.post("/api/move-batch", json={"batch": "batch"})
    assert response.status_code == 400
