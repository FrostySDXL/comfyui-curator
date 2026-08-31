import threading
import time

import pytest

from image_curator import batch_store
from image_curator import search_index_jobs
from image_curator.search_index import SearchIndexBuildCancelled, build_search_index


def _wait_for_status(manager, job_id, status, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job and job["status"] == status:
            return job
        time.sleep(0.005)
    pytest.fail(f"job {job_id} did not reach {status!r}: {manager.get(job_id)!r}")


def test_cancelled_build_preserves_existing_index_and_cleans_temp(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    batch_store.create_batch(batches, "alpha")
    index_path = batches / "alpha" / search_index_jobs.SEARCH_INDEX_FILENAME
    index_path.write_text('{"version": 1, "prior": true}', encoding="utf-8")
    started = threading.Event()
    owned_temp_paths = []

    def blocked_build(
        root,
        batch,
        *,
        cancel_check=None,
        progress_callback=None,
        commit_check=None,
        temp_path=None,
    ):
        started.set()
        while not cancel_check():
            time.sleep(0.005)
        owned_temp_paths.append(temp_path)
        temp_path.write_text("partial", encoding="utf-8")
        raise search_index_jobs.search_index.SearchIndexBuildCancelled

    monkeypatch.setattr(search_index_jobs.search_index, "build_search_index", blocked_build)
    manager = search_index_jobs.SearchIndexJobManager(batches)
    try:
        job = manager.submit("alpha")
        _wait_for_status(manager, job["job_id"], "running")
        assert started.wait(1)
        cancelled = manager.cancel(job["job_id"])
        assert cancelled["status"] == "cancelling"
        terminal = _wait_for_status(manager, job["job_id"], "cancelled")
        assert terminal["error"] == "Build cancelled"
        assert index_path.read_text(encoding="utf-8") == '{"version": 1, "prior": true}'
        assert not owned_temp_paths[0].exists()
    finally:
        manager.close()


def test_only_one_active_build_is_allowed_per_batch(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    batch_store.create_batch(batches, "alpha")
    started = threading.Event()
    release = threading.Event()

    def blocked_build(
        root,
        batch,
        *,
        cancel_check=None,
        progress_callback=None,
        commit_check=None,
        temp_path=None,
    ):
        started.set()
        release.wait(1)
        return {"item_count": 0, "built_at": "now"}

    monkeypatch.setattr(search_index_jobs.search_index, "build_search_index", blocked_build)
    manager = search_index_jobs.SearchIndexJobManager(batches)
    try:
        first = manager.submit("alpha")
        assert started.wait(1)
        with pytest.raises(search_index_jobs.ActiveSearchIndexJob) as exc_info:
            manager.submit("alpha")
        assert exc_info.value.job["job_id"] == first["job_id"]
        release.set()
        _wait_for_status(manager, first["job_id"], "completed")
    finally:
        release.set()
        manager.close()


def test_scan_cancellation_stops_before_commit_and_preserves_prior_index(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    batch_store.create_batch(batches, "alpha")
    inbox = batches / "alpha" / "inbox"
    (inbox / "first.jpg").write_bytes(b"first")
    (inbox / "second.jpg").write_bytes(b"second")
    index_path = batches / "alpha" / search_index_jobs.SEARCH_INDEX_FILENAME
    prior = '{"version": 1, "prior": true}'
    index_path.write_text(prior, encoding="utf-8")
    cancelled = threading.Event()

    monkeypatch.setattr(
        search_index_jobs.search_index,
        "_build_item",
        lambda batch, folder, path: {"batch": batch, "folder": folder, "name": path.name},
    )

    def progress(completed, _total):
        if completed == 1:
            cancelled.set()

    with pytest.raises(SearchIndexBuildCancelled):
        build_search_index(
            batches,
            "alpha",
            cancel_check=cancelled.is_set,
            progress_callback=progress,
        )

    assert index_path.read_text(encoding="utf-8") == prior
    assert not index_path.with_suffix(index_path.suffix + ".tmp").exists()


def test_cancel_cleanup_does_not_delete_foreign_legacy_temp(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    batch_store.create_batch(batches, "alpha")
    index_path = batches / "alpha" / search_index_jobs.SEARCH_INDEX_FILENAME
    index_path.write_text('{"version": 1, "prior": true}', encoding="utf-8")
    started = threading.Event()
    foreign_done = threading.Event()

    def blocked_build(
        root,
        batch,
        *,
        cancel_check=None,
        progress_callback=None,
        commit_check=None,
        temp_path=None,
    ):
        started.set()
        while not cancel_check():
            time.sleep(0.005)

        def legacy_writer():
            legacy_temp = index_path.with_suffix(index_path.suffix + ".tmp")
            legacy_temp.write_text("foreign legacy writer", encoding="utf-8")
            foreign_done.set()

        foreign_thread = threading.Thread(target=legacy_writer)
        foreign_thread.start()
        assert foreign_done.wait(1)
        foreign_thread.join()
        raise search_index_jobs.search_index.SearchIndexBuildCancelled

    monkeypatch.setattr(search_index_jobs.search_index, "build_search_index", blocked_build)
    manager = search_index_jobs.SearchIndexJobManager(batches)
    try:
        job = manager.submit("alpha")
        _wait_for_status(manager, job["job_id"], "running")
        assert started.wait(1)
        manager.cancel(job["job_id"])
        _wait_for_status(manager, job["job_id"], "cancelled")
        assert index_path.with_suffix(index_path.suffix + ".tmp").read_text(encoding="utf-8") == (
            "foreign legacy writer"
        )
    finally:
        manager.close()


def test_job_pins_batch_root_at_submission(tmp_path, monkeypatch):
    first_root = tmp_path / "first"
    roots = [first_root, tmp_path / "second"]
    for root in roots:
        batch_store.create_batch(root, "alpha")
    started = threading.Event()
    release = threading.Event()
    seen_roots = []

    def blocked_build(root, batch, **_kwargs):
        seen_roots.append(root)
        started.set()
        release.wait(1)
        return {"item_count": 0, "built_at": "now"}

    monkeypatch.setattr(search_index_jobs.search_index, "build_search_index", blocked_build)
    manager = search_index_jobs.SearchIndexJobManager(lambda: roots[0])
    try:
        job = manager.submit("alpha")
        assert started.wait(1)
        roots[0] = roots[1]
        release.set()
        _wait_for_status(manager, job["job_id"], "completed")
        assert seen_roots == [first_root.resolve()]
    finally:
        release.set()
        manager.close()


def test_close_waits_for_cancelled_worker_before_return(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    batch_store.create_batch(batches, "alpha")
    started = threading.Event()
    finished = threading.Event()

    def slow_cancel_build(root, batch, *, cancel_check=None, commit_check=None, **_kwargs):
        started.set()
        while not cancel_check():
            time.sleep(0.005)
        time.sleep(0.1)
        finished.set()
        commit_check()
        return {"item_count": 0, "built_at": "late"}

    monkeypatch.setattr(search_index_jobs.search_index, "build_search_index", slow_cancel_build)
    manager = search_index_jobs.SearchIndexJobManager(batches)
    job = manager.submit("alpha")
    assert started.wait(1)
    manager.close()
    assert finished.is_set()
    assert manager.get(job["job_id"])["status"] == "cancelled"


def test_cancel_during_commit_reports_not_accepted(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    batch_store.create_batch(batches, "alpha")
    commit_started = threading.Event()
    release = threading.Event()

    def committing_build(root, batch, *, commit_check=None, **_kwargs):
        commit_check()
        commit_started.set()
        release.wait(1)
        return {"item_count": 0, "built_at": "now"}

    monkeypatch.setattr(search_index_jobs.search_index, "build_search_index", committing_build)
    manager = search_index_jobs.SearchIndexJobManager(batches)
    try:
        job = manager.submit("alpha")
        assert commit_started.wait(1)
        result = manager.cancel(job["job_id"])
        assert result["status"] == "running"
        assert result["cancel_accepted"] is False
        release.set()
        assert _wait_for_status(manager, job["job_id"], "completed")
    finally:
        release.set()
        manager.close()


def test_cancellation_is_checked_during_initial_enumeration(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    batch_store.create_batch(batches, "alpha")
    cancelled = threading.Event()

    def cancel_check():
        cancelled.set()
        return True

    with pytest.raises(SearchIndexBuildCancelled):
        build_search_index(batches, "alpha", cancel_check=cancel_check)
    assert cancelled.is_set()


def test_terminal_jobs_are_retained_within_bounded_history(tmp_path, monkeypatch):
    batches = tmp_path / "batches"
    for number in range(search_index_jobs.MAX_RETAINED_JOBS + 2):
        batch_store.create_batch(batches, f"batch-{number}")

    monkeypatch.setattr(
        search_index_jobs.search_index,
        "build_search_index",
        lambda root, batch, **_kwargs: {"item_count": 0, "built_at": "now"},
    )
    manager = search_index_jobs.SearchIndexJobManager(batches)
    job_ids = []
    try:
        for number in range(search_index_jobs.MAX_RETAINED_JOBS + 2):
            job = manager.submit(f"batch-{number}")
            job_ids.append(job["job_id"])
            _wait_for_status(manager, job["job_id"], "completed")
        retained = [job_id for job_id in job_ids if manager.get(job_id) is not None]
        assert len(retained) <= search_index_jobs.MAX_RETAINED_JOBS
        assert manager.get(job_ids[0]) is None
    finally:
        manager.close()
