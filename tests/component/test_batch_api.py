import threading
import time

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
    (rejects_dir / "bad1.png.json").write_text('{"reason":"duplicate"}', encoding="utf-8")

    response = client.post("/api/delete-rejects/test-batch")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 2
    assert not (rejects_dir / "bad1.png").exists()
    assert not (rejects_dir / "bad2.webp").exists()
    assert not (rejects_dir / "bad1.png.json").exists()


@pytest.mark.component
def test_delete_rejects_removes_namespaced_thumbnail_cache(client, app_module, make_file):
    app_module.create_batch("test-batch")
    rejects_dir = app_module.BATCHES_DIR / "test-batch" / "rejects"
    thumbs_dir = app_module.BATCHES_DIR / "test-batch" / ".thumbs"

    make_file(rejects_dir / "bad1.png")
    make_file(thumbs_dir / "rejects__bad1--png.webp")

    response = client.post("/api/delete-rejects/test-batch")

    assert response.status_code == 200
    assert not (rejects_dir / "bad1.png").exists()
    assert not (thumbs_dir / "rejects__bad1--png.webp").exists()


@pytest.mark.component
def test_delete_rejects_nonexistent_batch(client):
    response = client.post("/api/delete-rejects/no-such-batch")
    assert response.status_code == 404


@pytest.mark.component
def test_import_status_is_lightweight_and_reports_active_batch(client, app_module, make_file):
    app_module.create_batch("focus")
    app_module.save_state({"active_batch": "focus"})
    make_file(app_module.COMFYUI_OUTPUT / "waiting.mp4")

    response = client.get("/api/import-status")

    assert response.status_code == 200
    assert response.get_json() == {"active_batch": "focus", "pending_count": 1}


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
def test_serve_thumbnail_applies_configured_delay(client, app_module, monkeypatch):
    app_module.create_batch("batch")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "inbox" / "test.png")
    monkeypatch.setenv("IMAGE_CURATOR_THUMBNAIL_DELAY_MS", "150")

    started = time.perf_counter()
    response = client.get("/thumb/batch/inbox/test.png")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed >= 0.15


@pytest.mark.component
def test_serve_thumbnail_does_not_sleep_when_delay_unset(client, app_module, monkeypatch):
    app_module.create_batch("batch")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "inbox" / "test.png")
    monkeypatch.delenv("IMAGE_CURATOR_THUMBNAIL_DELAY_MS", raising=False)

    client.get("/thumb/batch/inbox/test.png")  # warm the cache before timing

    started = time.perf_counter()
    response = client.get("/thumb/batch/inbox/test.png")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.14


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
    assert data[0]["mtime"] > 0


@pytest.mark.component
def test_api_images_adds_media_kind_and_mime_without_changing_still_items(
    client, app_module, make_file
):
    app_module.create_batch("media")
    inbox = app_module.BATCHES_DIR / "media" / "inbox"
    for name in (
        "still.png",
        "photo.jpg",
        "legacy.jpeg",
        "web.webp",
        "loop.gif",
        "clip.mp4",
        "sound.mp3",
    ):
        make_file(inbox / name)

    response = client.get("/api/images/media/inbox?sort=name&order=asc")

    assert response.status_code == 200
    items = {item["name"]: item for item in response.get_json()}
    assert items["still.png"]["media_kind"] == "image"
    assert items["still.png"]["mime"] == "image/png"
    assert items["photo.jpg"]["media_kind"] == "image"
    assert items["legacy.jpeg"]["mime"] == "image/jpeg"
    assert items["web.webp"]["mime"] == "image/webp"
    assert items["loop.gif"]["size"] == 1
    assert items["loop.gif"]["favorite"] is False
    assert items["loop.gif"]["media_kind"] == "animated_image"
    assert items["loop.gif"]["mime"] == "image/gif"
    assert items["loop.gif"]["mtime"] > 0
    assert items["clip.mp4"]["mime"] == "video/mp4"
    assert items["sound.mp3"]["mime"] == "audio/mpeg"


@pytest.mark.component
def test_audio_original_supports_mime_ranges_and_fallback_poster(client, app_module, make_file):
    app_module.create_batch("batch")
    track = app_module.BATCHES_DIR / "batch" / "inbox" / "track.mp3"
    make_file(track, b"0123456789")

    original = client.get(
        "/image/batch/inbox/track.mp3",
        headers={"Range": "bytes=2-5"},
    )
    poster = client.get("/thumb/batch/inbox/track.mp3")

    assert original.status_code == 206
    assert original.mimetype == "audio/mpeg"
    assert original.data == b"2345"
    assert poster.status_code == 200
    assert poster.mimetype == "image/webp"


@pytest.mark.component
def test_hover_preview_missing_ffmpeg_is_stable_unavailable_response(
    client, app_module, make_file, monkeypatch, tmp_path
):
    app_module.create_batch("batch")
    make_file(app_module.BATCHES_DIR / "batch" / "inbox" / "loop.gif", b"bad-gif")
    monkeypatch.setenv("IMAGE_CURATOR_FFMPEG", str(tmp_path / "missing-ffmpeg.exe"))

    response = client.get("/preview/batch/inbox/loop.gif")

    assert response.status_code == 503
    assert response.get_json() == {"error": "Hover preview unavailable"}


@pytest.mark.component
def test_api_images_nonexistent_batch(client):
    """GET /api/images returns 404 for nonexistent batch."""
    response = client.get("/api/images/nope/inbox")
    assert response.status_code == 404


@pytest.mark.component
def test_v2_folder_snapshot_is_paged_revision_bound_and_poll_is_lightweight(
    client, app_module, make_file
):
    app_module.create_batch("paged")
    inbox = app_module.BATCHES_DIR / "paged" / "inbox"
    for index in range(5):
        make_file(inbox / f"item-{index}.png", bytes([index]))

    first = client.get("/api/v2/folders/paged/inbox/snapshot?sort=name&order=asc")
    assert first.status_code in {200, 202}
    assert app_module._folder_index.wait_until_ready("paged", "inbox", "name", "asc", timeout=2)
    snapshot = client.get("/api/v2/folders/paged/inbox/snapshot?sort=name&order=asc")
    metadata = snapshot.get_json()
    revision = metadata["revision"]

    page = client.get(
        f"/api/v2/folders/paged/inbox/items?sort=name&order=asc&revision={revision}&offset=1&limit=2"
    )
    poll = client.get(f"/api/v2/folders/paged/inbox/poll?sort=name&order=asc&revision={revision}")
    stale = client.get(
        "/api/v2/folders/paged/inbox/items?sort=name&order=asc&revision=stale&offset=0&limit=2"
    )
    lookup = client.get(
        f"/api/v2/folders/paged/inbox/lookup?sort=name&order=asc&revision={revision}&name=item-3.png"
    )

    assert metadata == {"status": "ready", "revision": revision, "count": 5}
    assert [item["name"] for item in page.get_json()["items"]] == [
        "item-1.png",
        "item-2.png",
    ]
    assert poll.get_json() == {
        "status": "ready",
        "changed": False,
        "revision": revision,
        "count": 5,
    }
    assert stale.status_code == 409
    assert lookup.status_code == 200
    assert lookup.get_json() == {"revision": revision, "index": 3}
    assert "items" not in poll.get_json()


@pytest.mark.component
def test_v2_folder_shuffle_seed_rotates_a_stable_paged_order(client, app_module, make_file):
    app_module.create_batch("shuffle")
    inbox = app_module.BATCHES_DIR / "shuffle" / "inbox"
    for index in range(20):
        make_file(inbox / f"item-{index:02}.png", bytes([index]))

    def names_for_seed(seed):
        query = f"sort=shuffle&order=asc&shuffle_seed={seed}"
        client.get(f"/api/v2/folders/shuffle/inbox/snapshot?{query}")
        assert app_module._folder_index.wait_until_ready(
            "shuffle", "inbox", "shuffle", "asc", seed, timeout=2
        )
        snapshot = client.get(f"/api/v2/folders/shuffle/inbox/snapshot?{query}").get_json()
        page = client.get(
            f"/api/v2/folders/shuffle/inbox/items?{query}"
            f"&revision={snapshot['revision']}&offset=0&limit=256"
        )
        assert page.status_code == 200
        return snapshot["revision"], [item["name"] for item in page.get_json()["items"]]

    first_revision, first_names = names_for_seed("one")
    second_revision, second_names = names_for_seed("two")

    assert second_revision != first_revision
    assert second_names != first_names
    assert set(second_names) == set(first_names)
    too_long = client.get(
        "/api/v2/folders/shuffle/inbox/snapshot?sort=shuffle&shuffle_seed=" + "x" * 65
    )
    assert too_long.status_code == 400
    moved = client.post(
        "/api/move-batch",
        json={
            "batch": "shuffle",
            "source": "inbox",
            "destination": "finals",
            "selection": {
                "type": "snapshot",
                "revision": second_revision,
                "sort": "shuffle",
                "order": "asc",
                "shuffle_seed": "two",
                "excluded": [],
            },
        },
    )
    assert moved.status_code == 200
    assert moved.get_json()["moved"] == 20


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
    assert response.get_json()["success"] is True
    assert len(response.get_json()["operation_id"]) == 32
    assert not (app_module.BATCHES_DIR / "batch" / "inbox" / "pic.png").exists()
    assert (app_module.BATCHES_DIR / "batch" / "shortlisted" / "pic.png").exists()


@pytest.mark.component
def test_move_history_routes_retain_receipt_and_idempotent_undo(client, app_module, make_file):
    app_module.create_batch("batch")
    source = app_module.BATCHES_DIR / "batch" / "inbox" / "pic.png"
    make_file(source, b"original")
    moved = client.post(
        "/api/move",
        json={"batch": "batch", "filename": "pic.png", "source": "inbox", "destination": "finals"},
    ).get_json()
    listing = client.get("/api/move-history").get_json()
    assert listing["operations"][0]["id"] == moved["operation_id"]
    assert listing["operations"][0]["can_undo"]
    assert listing["max_operations"] == 100 and listing["retention_days"] == 30
    batches = client.get("/api/batches")
    assert batches.status_code == 200
    assert batches.get_json()["batches"] == ["batch"]
    for expected_moved in (1, 0):
        response = client.post("/api/move-batch/undo", json={"operation_id": moved["operation_id"]})
        assert response.status_code == 200
        assert response.get_json()["success"]
        assert response.get_json()["status"] == "undone"
        assert response.get_json()["moved"] == expected_moved
    assert source.read_bytes() == b"original"


@pytest.mark.component
@pytest.mark.parametrize(
    "endpoint,body",
    [
        ("move-history", None),
        (
            "move",
            {"batch": "batch", "filename": "pic.png", "source": "inbox", "destination": "finals"},
        ),
        (
            "move-batch",
            {
                "batch": "batch",
                "filenames": ["pic.png"],
                "source": "inbox",
                "destination": "finals",
            },
        ),
        ("move-batch/undo", {"operation_id": "unknown"}),
    ],
)
def test_move_history_storage_errors_are_json_and_fail_closed(
    client, app_module, make_file, monkeypatch, endpoint, body
):
    from image_curator.move_history import MoveHistory

    app_module.create_batch("batch")
    source = app_module.BATCHES_DIR / "batch" / "inbox" / "pic.png"
    make_file(source, b"original")

    def fail_load(_self):
        raise OSError("private path must not be returned")

    monkeypatch.setattr(MoveHistory, "_load", fail_load)
    response = (
        client.get(f"/api/{endpoint}")
        if body is None
        else client.post(f"/api/{endpoint}", json=body)
    )
    assert response.status_code == 500
    assert response.is_json
    assert "private path" not in response.get_json()["error"]
    assert source.read_bytes() == b"original"


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
def test_snapshot_bulk_move_uses_revision_and_operation_token_for_undo(
    client, app_module, make_file
):
    app_module.create_batch("batch")
    inbox = app_module.BATCHES_DIR / "batch" / "inbox"
    for name in ("one.png", "two.gif", "three.mp4"):
        make_file(inbox / name)
    client.get("/api/v2/folders/batch/inbox/snapshot?sort=name&order=asc")
    assert app_module._folder_index.wait_until_ready("batch", "inbox", "name", "asc", timeout=2)
    metadata = client.get("/api/v2/folders/batch/inbox/snapshot?sort=name&order=asc").get_json()

    moved = client.post(
        "/api/move-batch",
        json={
            "batch": "batch",
            "source": "inbox",
            "destination": "finals",
            "selection": {
                "type": "snapshot",
                "revision": metadata["revision"],
                "sort": "name",
                "order": "asc",
                "excluded": ["two.gif"],
            },
        },
    )

    assert moved.status_code == 200
    payload = moved.get_json()
    assert payload["moved"] == 2
    assert payload["operation_id"]
    assert (inbox / "two.gif").exists()
    restored = client.post("/api/move-batch/undo", json={"operation_id": payload["operation_id"]})
    assert restored.status_code == 200
    assert restored.get_json()["moved"] == 2
    assert all((inbox / name).exists() for name in ("one.png", "two.gif", "three.mp4"))


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


# ---------------------------------------------------------------------------
# Thumbnail cache key (C1)
# ---------------------------------------------------------------------------


@pytest.mark.component
def test_thumbnail_cache_keys_are_namespaced_by_folder(client, app_module):
    """Two same-stem files in different folders cache to separate files.

    Regression: the previous cache key was ``{stem}.webp``, so
    ``inbox/shared.png`` and ``shortlisted/shared.png`` collided on the
    same cache file and the second folder would serve the first
    folder's thumbnail.
    """
    app_module.create_batch("batch")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "inbox" / "shared.png")
    _write_test_png(app_module.BATCHES_DIR / "batch" / "shortlisted" / "shared.png")

    inbox_resp = client.get("/thumb/batch/inbox/shared.png")
    short_resp = client.get("/thumb/batch/shortlisted/shared.png")

    assert inbox_resp.status_code == 200
    assert short_resp.status_code == 200

    cache_dir = app_module.BATCHES_DIR / "batch" / ".thumbs"
    cache_files = sorted(p.name for p in cache_dir.glob("*.webp"))
    assert len(cache_files) == 2, f"expected 2 distinct cache files, got {cache_files}"
    # The folder is now part of the cache key, so the two files have
    # distinct names and are not overwritten by the second request.
    assert cache_files[0] != cache_files[1]
    assert any("inbox" in name for name in cache_files)
    assert any("shortlisted" in name for name in cache_files)


# ---------------------------------------------------------------------------
# Folder snapshot invalidation after move/undo (stale-revision regression)
# ---------------------------------------------------------------------------


def _warm_folder_snapshot(client, app_module, batch, folder, sort="name", order="asc"):
    """Build and return the ready snapshot for a folder's paged view."""
    client.get(f"/api/v2/folders/{batch}/{folder}/snapshot?sort={sort}&order={order}")
    assert app_module._folder_index.wait_until_ready(batch, folder, sort, order, timeout=2)
    response = client.get(f"/api/v2/folders/{batch}/{folder}/snapshot?sort={sort}&order={order}")
    assert response.status_code == 200
    return response.get_json()


def _block_folder_index_rebuild(app_module, monkeypatch):
    """Hold subsequent folder-index rebuilds in flight until released.

    This makes the mutation-triggered rebuild deterministically still-running
    when the snapshot endpoint is inspected, so the test can prove the route
    never serves the pre-mutation revision as a final ``ready`` result.
    """
    release = threading.Event()
    original_scan = app_module._folder_index._scan_directory

    def blocking_scan(directory, sort_by, order, shuffle_seed=""):
        release.wait(timeout=5)
        return original_scan(directory, sort_by, order, shuffle_seed)

    monkeypatch.setattr(app_module._folder_index, "_scan_directory", blocking_scan)
    return release


def _assert_snapshot_reflects_mutation(
    client,
    app_module,
    release,
    batch,
    folder,
    pre_revision,
    expected_count,
    sort="name",
    order="asc",
):
    """Assert the snapshot endpoint does not serve ``pre_revision`` as final.

    Accepts either an immediate ``202`` "building" response (then releases the
    blocked rebuild and awaits a new ready revision) or an immediate ``200``
    whose revision differs and whose count reflects the mutation.
    """
    response = client.get(f"/api/v2/folders/{batch}/{folder}/snapshot?sort={sort}&order={order}")
    assert response.status_code in {200, 202}
    payload = response.get_json()
    if response.status_code == 200:
        release.set()
        assert payload["status"] == "ready"
        assert payload["revision"] != pre_revision
        assert payload["count"] == expected_count
        return payload
    assert payload == {"status": "building"}
    release.set()
    assert app_module._folder_index.wait_until_ready(batch, folder, sort, order, timeout=5)
    ready = client.get(f"/api/v2/folders/{batch}/{folder}/snapshot?sort={sort}&order={order}")
    assert ready.status_code == 200
    body = ready.get_json()
    assert body["status"] == "ready"
    assert body["revision"] != pre_revision
    assert body["count"] == expected_count
    return body


@pytest.mark.component
def test_api_move_invalidates_snapshot_revision(client, app_module, make_file, monkeypatch):
    app_module.create_batch("move-single")
    make_file(app_module.BATCHES_DIR / "move-single" / "inbox" / "pic.png")

    pre = _warm_folder_snapshot(client, app_module, "move-single", "inbox")
    release = _block_folder_index_rebuild(app_module, monkeypatch)

    try:
        moved = client.post(
            "/api/move",
            json={
                "batch": "move-single",
                "filename": "pic.png",
                "source": "inbox",
                "destination": "shortlisted",
            },
        )
        assert moved.status_code == 200

        _assert_snapshot_reflects_mutation(
            client, app_module, release, "move-single", "inbox", pre["revision"], 0
        )
    finally:
        release.set()


@pytest.mark.component
def test_api_move_batch_invalidates_snapshot_revision(client, app_module, make_file, monkeypatch):
    app_module.create_batch("move-bulk")
    inbox = app_module.BATCHES_DIR / "move-bulk" / "inbox"
    make_file(inbox / "one.png")
    make_file(inbox / "two.jpg")

    pre = _warm_folder_snapshot(client, app_module, "move-bulk", "inbox")
    release = _block_folder_index_rebuild(app_module, monkeypatch)

    try:
        moved = client.post(
            "/api/move-batch",
            json={
                "batch": "move-bulk",
                "filenames": ["one.png", "two.jpg"],
                "source": "inbox",
                "destination": "finals",
            },
        )
        assert moved.status_code == 200

        _assert_snapshot_reflects_mutation(
            client, app_module, release, "move-bulk", "inbox", pre["revision"], 0
        )
    finally:
        release.set()


@pytest.mark.component
def test_undo_invalidates_snapshot_revision_not_serving_pre_undo(
    client, app_module, make_file, monkeypatch
):
    app_module.create_batch("move-undo")
    make_file(app_module.BATCHES_DIR / "move-undo" / "inbox" / "pic.png")

    pre = _warm_folder_snapshot(client, app_module, "move-undo", "inbox")

    moved = client.post(
        "/api/move",
        json={
            "batch": "move-undo",
            "filename": "pic.png",
            "source": "inbox",
            "destination": "finals",
        },
    )
    assert moved.status_code == 200
    operation_id = moved.get_json()["operation_id"]

    post_move = _assert_snapshot_reflects_mutation(
        client, app_module, threading.Event(), "move-undo", "inbox", pre["revision"], 0
    )

    release = _block_folder_index_rebuild(app_module, monkeypatch)
    try:
        undone = client.post("/api/move-batch/undo", json={"operation_id": operation_id})
        assert undone.status_code == 200

        _assert_snapshot_reflects_mutation(
            client, app_module, release, "move-undo", "inbox", post_move["revision"], 1
        )
    finally:
        release.set()


@pytest.mark.component
def test_thumbnail_route_returns_non_ok_for_corrupt_image(client, app_module):
    app_module.create_batch("alpha")
    inbox = app_module.BATCHES_DIR / "alpha" / "inbox"
    (inbox / "corrupt.png").write_bytes(b"not-a-real-png")

    response = client.get("/thumb/alpha/inbox/corrupt.png")

    assert response.status_code != 200


@pytest.mark.component
def test_thumbnail_route_does_not_cache_fallback_for_corrupt_image(client, app_module):
    app_module.create_batch("alpha")
    inbox = app_module.BATCHES_DIR / "alpha" / "inbox"
    (inbox / "corrupt.png").write_bytes(b"not-a-real-png")

    client.get("/thumb/alpha/inbox/corrupt.png")

    cache = app_module.BATCHES_DIR / "alpha" / ".thumbs" / "inbox__corrupt--png.webp"
    assert not cache.exists()


@pytest.mark.component
def test_thumbnail_route_serves_valid_image(client, app_module):
    app_module.create_batch("alpha")
    _write_test_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "valid.png")

    response = client.get("/thumb/alpha/inbox/valid.png")

    assert response.status_code == 200
    assert response.mimetype == "image/webp"
