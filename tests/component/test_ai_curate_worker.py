"""Component tests for ``app._run_scoring_worker_inner``.

The full AI scoring orchestration has three pieces of behavior that are
not exercised by the API integration tests (which only patch out the
worker entirely):

1. Cancellation during the scoring phase discards all results and never
   persists a run record.
2. Cancellation during the move phase, **after** at least one file has
   been moved, must persist a cancelled run with the partial results so
   the operator has an audit trail of what was moved.
3. If cancellation is requested between the worker's final cancel check
   and the ``complete_job`` call (a tight race), the worker must land on
   ``finalize_cancelled`` instead of completing.

These tests live in ``tests/component/`` because they pull in the Flask
app module to access module-level state, but they do not need a live
Flask client.
"""

import pytest
from unittest.mock import MagicMock

from ai_curate.models import ImageResult, JobState
from ai_curate.queue import QueueManager
from ai_curate.storage import RunStorage
from image_curator import batch_store

pytestmark = pytest.mark.component


def _setup_batch(app_module, batch_name="test-batch", num_images=3):
    """Create a batch with ``num_images`` images in inbox + standard folders."""
    batches_dir = app_module.BATCHES_DIR
    inbox = batches_dir / batch_name / "inbox"
    shortlisted = batches_dir / batch_name / "shortlisted"
    finals = batches_dir / batch_name / "finals"
    rejects = batches_dir / batch_name / "rejects"
    for folder in (inbox, shortlisted, finals, rejects):
        folder.mkdir(parents=True, exist_ok=True)
    for i in range(num_images):
        (inbox / f"img_{i}.png").write_bytes(b"x")
    return batches_dir / batch_name


def _install_queue_and_client(app_module, batches_dir):
    """Install a real QueueManager + stubbed VisionClient on the app module."""
    storage = RunStorage(batches_dir=batches_dir)
    queue = QueueManager(storage=storage)
    app_module._ai_storage = storage
    app_module._ai_queue = queue
    # Stub the vision client. Tests drive behaviour via ``is_cancel_requested``.
    app_module._ai_client = MagicMock()


def _submit_run(queue, app_module, batch_name, move_enabled=False):
    """Submit a move-enabled (or not) job and return its ``CurationRun``."""
    run = queue.submit(
        {
            "batch": batch_name,
            "source_folder": "inbox",
            "destination_folder": "shortlisted" if move_enabled else None,
            "move_enabled": move_enabled,
            "prompt": "test prompt",
            "elements": ["blue sky", "red dress"],  # explicit → no extract_elements call
            "model": "vl-scorer",
            "top_n": 5,
        }
    )
    # The CurationRun model stores elements in its constructor only; the
    # worker overwrites them with build_element_list(...). For our tests
    # we just need the run to exist and be RUNNING.
    return run


def _patch_scoring_to_succeed(monkeypatch, results):
    """Replace ``app_module.score_images`` with a stub that returns ``results``."""
    monkeypatch.setattr(
        "app.score_images",
        lambda **kwargs: (results, len(results)),
    )


def _patch_get_batch_folder(monkeypatch, batches_dir):
    """Make ``app.get_batch_folder`` resolve against the temp batches dir."""

    def _get(folder_path_str):
        # ``app.get_batch_folder`` takes (batch_name, folder). We accept
        # whatever it returns and return the Path as-is — by the time the
        # tests run, BATCHES_DIR is monkeypatched on app_module, so
        # ``get_batch_folder`` already resolves to the temp dir.
        return folder_path_str

    monkeypatch.setattr("app.get_batch_folder", lambda batch, folder: batches_dir / batch / folder)


class TestWorkerCancellation:
    """Cancellation behaviour in the scoring/move worker."""

    def test_cancel_during_scoring_discards_results(self, app_module, monkeypatch):
        """If cancel is requested during scoring, no run is persisted."""
        batches_dir = app_module.BATCHES_DIR  # already created by the fixture
        _setup_batch(app_module)
        _install_queue_and_client(app_module, batches_dir)
        # score_images stub that cancels after the first image.

        def fake_score_images(**kwargs):
            # First invocation: trigger cancel via the queue.
            app_module._ai_queue.cancel(run.run_id)
            return ([ImageResult(filename="img_0.png", score=1, total=2)], 1)

        monkeypatch.setattr("app.score_images", fake_score_images)
        monkeypatch.setattr(
            "app.get_batch_folder",
            lambda batch, folder: batches_dir / batch / folder,
        )

        run = _submit_run(app_module._ai_queue, app_module, "test-batch", move_enabled=False)
        app_module._run_scoring_worker_inner(run.run_id, run)

        job = app_module._ai_queue.get_job(run.run_id)
        assert job.status == JobState.CANCELLED
        # No results, no totals retained.
        assert job.results == []
        # save_run must NOT have been called for a cancelled run.
        # The queue's storage was real; the runs dir should not exist.
        runs_dir = batches_dir / "test-batch" / "ai-curate" / "runs"
        assert not runs_dir.exists() or list(runs_dir.glob("*.json")) == []

    def test_cancel_during_move_persists_partial_results(self, app_module, monkeypatch):
        """Cancellation mid-move after some files moved must persist a partial run."""
        batches_dir = app_module.BATCHES_DIR
        batch_dir = _setup_batch(app_module)
        _install_queue_and_client(app_module, batches_dir)

        # Pre-computed results: three images, all "scored".
        results = [
            ImageResult(filename="img_0.png", score=3, total=3),
            ImageResult(filename="img_1.png", score=2, total=3),
            ImageResult(filename="img_2.png", score=1, total=3),
        ]

        def fake_score_images(**kwargs):
            return (results, len(results))

        # Wrap move_image so that calling it triggers cancel after the first move.
        original_move = batch_store.move_image
        call_count = {"n": 0}

        def hooked_move(src, dst):
            call_count["n"] += 1
            ok = original_move(src, dst)
            if call_count["n"] == 1:
                # After the first successful move, request cancellation.
                app_module._ai_queue.cancel(run.run_id)
            return ok

        monkeypatch.setattr("app.score_images", fake_score_images)
        monkeypatch.setattr("app.batch_store.move_image", hooked_move)
        monkeypatch.setattr(
            "app.get_batch_folder",
            lambda batch, folder: batches_dir / batch / folder,
        )

        run = _submit_run(app_module._ai_queue, app_module, "test-batch", move_enabled=True)
        app_module._run_scoring_worker_inner(run.run_id, run)

        job = app_module._ai_queue.get_job(run.run_id)
        assert job.status == JobState.CANCELLED, (
            f"Expected CANCELLED, got {job.status}. results={job.results}"
        )
        # Partial move results must be retained on the run record.
        assert job.results, "Partial move results should be retained on a cancelled run"
        # The persisted on-disk record must exist with the partial results.
        runs_dir = batches_dir / "test-batch" / "ai-curate" / "runs"
        run_files = list(runs_dir.glob("*.json"))
        assert len(run_files) == 1, f"Expected one persisted run, found {run_files}"
        import json

        persisted = json.loads(run_files[0].read_text(encoding="utf-8"))
        assert persisted["status"] == "cancelled"
        # At least one file must have actually moved.
        moved_files = list((batch_dir / "shortlisted").iterdir())
        assert len(moved_files) >= 1, "At least one file should have been moved before cancel"

    def test_cancel_races_complete_job(self, app_module, monkeypatch):
        """If cancel is requested just before complete_job, finalize_cancelled wins.

        The race window: after the worker finishes the move loop (line 716
        of app.py) and runs its final ``is_cancel_requested`` check (line
        729). If the user calls ``cancel()`` in that window, the worker's
        ``complete_job`` call returns False (status is now CANCELLING) and
        the worker falls back to ``finalize_cancelled``.

        We force the race by issuing a real ``cancel()`` between the move
        loop and complete_job. The worker's mid-loop cancel_check is
        stubbed out via the fake score_images, so cancellation is only
        observed at the final race check.
        """
        batches_dir = app_module.BATCHES_DIR
        _setup_batch(app_module)
        _install_queue_and_client(app_module, batches_dir)

        results = [ImageResult(filename="img_0.png", score=2, total=2)]

        def fake_score_images(**kwargs):
            return (results, len(results))

        # Wrap the queue's complete_job so that the moment the worker
        # tries to complete, we cancel first to simulate the race.
        original_complete = app_module._ai_queue.complete_job

        def racing_complete(run_id, *args, **kwargs):
            # Mark the run as CANCELLING just before complete_job runs.
            # This is the race: cancel happens between the worker's
            # final cancel check and its complete_job call.
            with app_module._ai_queue._lock:
                run = app_module._ai_queue._jobs.get(run_id)
                if run and run.status == JobState.RUNNING:
                    run.status = JobState.CANCELLING
            return original_complete(run_id, *args, **kwargs)

        monkeypatch.setattr("app.score_images", fake_score_images)
        monkeypatch.setattr("app.get_batch_folder", lambda b, f: batches_dir / b / f)
        monkeypatch.setattr(app_module._ai_queue, "complete_job", racing_complete)

        run = _submit_run(app_module._ai_queue, app_module, "test-batch", move_enabled=False)
        app_module._run_scoring_worker_inner(run.run_id, run)

        job = app_module._ai_queue.get_job(run.run_id)
        # When complete_job sees CANCELLING it returns False; the worker
        # then calls finalize_cancelled. The job ends in CANCELLED.
        assert job.status == JobState.CANCELLED, f"Race: expected CANCELLED, got {job.status}"
