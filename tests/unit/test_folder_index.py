import threading
import time

from image_curator.folder_index import FolderIndexService


def test_initial_snapshot_request_never_waits_for_filesystem_scan(tmp_path, monkeypatch):
    service = FolderIndexService(reconcile_interval=60)
    started = threading.Event()
    release = threading.Event()

    def blocking_scan(*_args, **_kwargs):
        started.set()
        release.wait(timeout=2)
        return ()

    monkeypatch.setattr(service, "_scan_directory", blocking_scan)
    before = time.perf_counter()
    result = service.request_snapshot("alpha", "inbox", tmp_path, "name", "asc")
    elapsed = time.perf_counter() - before

    assert result == {"status": "building"}
    assert elapsed < 0.1
    assert started.wait(timeout=1)
    release.set()
    assert service.wait_until_ready("alpha", "inbox", "name", "asc", timeout=2)
    service.close()


def test_refresh_keeps_old_snapshot_readable_then_publishes_new_revision(tmp_path):
    source = tmp_path / "one.png"
    source.write_bytes(b"one")
    service = FolderIndexService(reconcile_interval=60)
    assert service.request_snapshot("alpha", "inbox", tmp_path, "name", "asc") == {
        "status": "building"
    }
    assert service.wait_until_ready("alpha", "inbox", "name", "asc", timeout=2)
    first = service.request_snapshot("alpha", "inbox", tmp_path, "name", "asc")

    (tmp_path / "two.mp4").write_bytes(b"two")
    service.refresh("alpha", "inbox")
    during = service.poll("alpha", "inbox", tmp_path, "name", "asc", first["revision"])
    deadline = time.monotonic() + 2
    changed = during
    while not changed.get("changed") and time.monotonic() < deadline:
        time.sleep(0.01)
        changed = service.poll("alpha", "inbox", tmp_path, "name", "asc", first["revision"])

    assert during["status"] == "ready"
    assert changed["changed"] is True
    assert changed["count"] == 2
    service.close()


def test_folder_page_exposes_nanosecond_mtime_for_thumbnail_cache_identity(tmp_path):
    media = tmp_path / "same-size.png"
    media.write_bytes(b"first")
    expected_mtime = media.stat().st_mtime_ns
    service = FolderIndexService(reconcile_interval=60)
    service.request_snapshot("alpha", "inbox", tmp_path, "name", "asc")
    assert service.wait_until_ready("alpha", "inbox", "name", "asc", timeout=2)
    snapshot = service.request_snapshot("alpha", "inbox", tmp_path, "name", "asc")

    page = service.page("alpha", "inbox", "name", "asc", snapshot["revision"], 0, 256, set())

    assert page is not None
    assert page["items"][0]["mtime"] == expected_mtime
    service.close()


def test_shuffle_sessions_are_stable_within_a_session_and_rotate_between_sessions(tmp_path):
    for index in range(20):
        (tmp_path / f"item-{index:02}.png").write_bytes(bytes([index]))

    service = FolderIndexService(reconcile_interval=60)

    def shuffled_names(shuffle_seed):
        service.request_snapshot(
            "alpha", "inbox", tmp_path, "shuffle", "asc", shuffle_seed=shuffle_seed
        )
        assert service.wait_until_ready(
            "alpha",
            "inbox",
            "shuffle",
            "asc",
            shuffle_seed=shuffle_seed,
            timeout=2,
        )
        snapshot = service.request_snapshot(
            "alpha", "inbox", tmp_path, "shuffle", "asc", shuffle_seed=shuffle_seed
        )
        page = service.page(
            "alpha",
            "inbox",
            "shuffle",
            "asc",
            snapshot["revision"],
            0,
            256,
            shuffle_seed=shuffle_seed,
        )
        assert page is not None
        return snapshot["revision"], [item["name"] for item in page["items"]]

    first_revision, first_names = shuffled_names("session-one")
    repeated_revision, repeated_names = shuffled_names("session-one")
    second_revision, second_names = shuffled_names("session-two")

    assert repeated_revision == first_revision
    assert repeated_names == first_names
    assert second_revision != first_revision
    assert second_names != first_names
    assert set(second_names) == set(first_names)
    for session in ("three", "four", "five"):
        shuffled_names(session)
    assert (
        service.page(
            "alpha",
            "inbox",
            "shuffle",
            "asc",
            first_revision,
            0,
            256,
            shuffle_seed="session-one",
        )
        is None
    )
    service.close()
