"""Component tests for the shared AI scoring worker.

These tests exercise ``ai_curate.worker.run_scoring_worker_inner`` directly with
a real ``QueueManager`` and ``RunStorage``. The worker is the shared core used
by both the CLI pipeline and the native ComfyUI lifecycle, so cancellation and
partial-move behavior is covered without importing a web framework.
"""

import json
import logging
from unittest.mock import MagicMock

import pytest

from ai_curate.elements import build_element_list
from ai_curate.models import ImageResult, JobState
from ai_curate.queue import QueueManager
from ai_curate.scoring import find_images
from ai_curate.storage import RunStorage
from ai_curate.worker import run_scoring_worker_inner
from image_curator import batch_store

pytestmark = pytest.mark.component

LOGGER = logging.getLogger("tests.worker")


def _setup_batch(tmp_path, batch_name="test-batch", num_images=3):
    """Create a batch with ``num_images`` images in inbox + standard folders."""
    batches_dir = tmp_path / "batches"
    batch_dir = batches_dir / batch_name
    for folder in ("inbox", "shortlisted", "finals", "rejects"):
        (batch_dir / folder).mkdir(parents=True, exist_ok=True)
    for i in range(num_images):
        (batch_dir / "inbox" / f"img_{i}.png").write_bytes(b"x")
    return batches_dir, batch_dir


def _submit_run(queue, batch_name, move_enabled=False):
    return queue.submit(
        {
            "batch": batch_name,
            "source_folder": "inbox",
            "destination_folder": "shortlisted" if move_enabled else None,
            "move_enabled": move_enabled,
            "prompt": "test prompt",
            "elements": ["blue sky", "red dress"],
            "quality_flags": [],
            "model": "vl-scorer",
            "top_n": 5,
        }
    )


def _run_worker(*, queue, run, batches_dir, score_images_func, move_image_func=None):
    run_scoring_worker_inner(
        run_id=run.run_id,
        run=run,
        queue=queue,
        client=MagicMock(),
        build_element_list_func=build_element_list,
        get_batch_folder=lambda batch, folder: batches_dir / batch / folder,
        find_images_func=find_images,
        score_images_func=score_images_func,
        move_image_func=move_image_func or batch_store.move_image,
        logger=LOGGER,
    )


class TestWorkerCancellation:
    """Cancellation behaviour in the shared scoring/move worker."""

    def test_cancel_during_scoring_discards_results(self, tmp_path):
        """If cancel is requested during scoring, no run is persisted."""
        batches_dir, _ = _setup_batch(tmp_path)
        storage = RunStorage(batches_dir=batches_dir)
        queue = QueueManager(storage=storage)
        run = _submit_run(queue, "test-batch", move_enabled=False)

        def fake_score_images(**kwargs):
            queue.cancel(run.run_id)
            return ([ImageResult(filename="img_0.png", score=1, total=2)], 1)

        _run_worker(
            queue=queue,
            run=run,
            batches_dir=batches_dir,
            score_images_func=fake_score_images,
        )

        job = queue.get_job(run.run_id)
        assert job.status == JobState.CANCELLED
        assert job.results == []
        runs_dir = batches_dir / "test-batch" / "ai-curate" / "runs"
        assert not runs_dir.exists() or list(runs_dir.glob("*.json")) == []

    def test_cancel_during_move_persists_partial_results(self, tmp_path):
        """Cancellation mid-move after some files moved must persist a partial run."""
        batches_dir, batch_dir = _setup_batch(tmp_path)
        storage = RunStorage(batches_dir=batches_dir)
        queue = QueueManager(storage=storage)
        run = _submit_run(queue, "test-batch", move_enabled=True)

        results = [
            ImageResult(filename="img_0.png", score=3, total=3),
            ImageResult(filename="img_1.png", score=2, total=3),
            ImageResult(filename="img_2.png", score=1, total=3),
        ]

        def fake_score_images(**kwargs):
            return (results, len(results))

        original_move = batch_store.move_image
        call_count = {"n": 0}

        def hooked_move(src, dst):
            call_count["n"] += 1
            ok = original_move(src, dst)
            if call_count["n"] == 1:
                queue.cancel(run.run_id)
            return ok

        _run_worker(
            queue=queue,
            run=run,
            batches_dir=batches_dir,
            score_images_func=fake_score_images,
            move_image_func=hooked_move,
        )

        job = queue.get_job(run.run_id)
        assert job.status == JobState.CANCELLED, (
            f"Expected CANCELLED, got {job.status}. results={job.results}"
        )
        assert job.results, "Partial move results should be retained on a cancelled run"
        runs_dir = batches_dir / "test-batch" / "ai-curate" / "runs"
        run_files = list(runs_dir.glob("*.json"))
        assert len(run_files) == 1, f"Expected one persisted run, found {run_files}"

        persisted = json.loads(run_files[0].read_text(encoding="utf-8"))
        assert persisted["status"] == "cancelled"
        moved_files = list((batch_dir / "shortlisted").iterdir())
        assert len(moved_files) >= 1, "At least one file should have been moved before cancel"

    def test_cancel_races_complete_job(self, tmp_path):
        """If cancel is requested just before complete_job, finalize_cancelled wins."""
        batches_dir, _ = _setup_batch(tmp_path)
        storage = RunStorage(batches_dir=batches_dir)
        queue = QueueManager(storage=storage)
        run = _submit_run(queue, "test-batch", move_enabled=False)

        results = [ImageResult(filename="img_0.png", score=2, total=2)]

        def fake_score_images(**kwargs):
            return (results, len(results))

        original_complete = queue.complete_job

        def racing_complete(run_id, *args, **kwargs):
            # Cancel lands between the worker's final cancel check and complete_job.
            with queue._lock:
                current = queue._jobs.get(run_id)
                if current and current.status == JobState.RUNNING:
                    current.status = JobState.CANCELLING
            return original_complete(run_id, *args, **kwargs)

        queue.complete_job = racing_complete

        _run_worker(
            queue=queue,
            run=run,
            batches_dir=batches_dir,
            score_images_func=fake_score_images,
        )

        job = queue.get_job(run.run_id)
        assert job.status == JobState.CANCELLED, f"Race: expected CANCELLED, got {job.status}"
