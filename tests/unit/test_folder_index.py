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
