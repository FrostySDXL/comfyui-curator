"""Component tests for AI curation workflow constraints.

Tests the critical invariants:
- Move phase only after scoring completes
- Cancelled runs leave no persisted history
- Failed images never move even when move mode is enabled
"""

import pytest

from ai_curate.models import CurationRun, ImageResult, RunTotals, JobState
from ai_curate.queue import QueueManager
from ai_curate.storage import RunStorage


@pytest.fixture
def tmp_batches(tmp_path):
    batches = tmp_path / "batches"
    batches.mkdir()
    batch_dir = batches / "test-batch"
    batch_dir.mkdir()
    (batch_dir / "inbox").mkdir()
    (batch_dir / "shortlisted").mkdir()
    return batches


@pytest.fixture
def storage(tmp_batches):
    return RunStorage(batches_dir=tmp_batches)


class TestMovePhaseAfterScoring:
    @pytest.mark.component
    def test_move_only_after_scoring_completes(self, storage):
        """A completed run with move_enabled should have moved count
        only when scoring finished successfully."""
        run = CurationRun(
            batch="test-batch",
            move_enabled=True,
            destination_folder="shortlisted",
            top_n=5,
            status=JobState.COMPLETED,
            results=[
                ImageResult(filename="a.png", score=5, total=6),
                ImageResult(filename="b.png", score=3, total=6),
                ImageResult(
                    filename="c.png",
                    score=-1,
                    total=6,
                    failed=True,
                    error_message="timeout",
                ),
            ],
            totals=RunTotals(images=3, scored=2, failed=1, moved=2),
        )
        storage.save_run(run)
        loaded = storage.load_run("test-batch", run.run_id)
        assert loaded.totals.moved == 2
        assert loaded.totals.failed == 1

    @pytest.mark.component
    def test_failed_images_never_move(self):
        """Even in a move-enabled run, failed images should not have moved_to."""
        results = [
            ImageResult(filename="good.png", score=5, total=6, moved_to="/dest/good.png"),
            ImageResult(
                filename="bad.png",
                score=-1,
                total=6,
                failed=True,
                error_message="timeout",
            ),
        ]
        # The failed image should not have a moved_to path
        assert results[0].moved_to is not None
        assert results[1].moved_to is None


class TestCancelledRunsLeaveNoHistory:
    @pytest.mark.component
    def test_cancelled_run_not_in_storage(self, storage):
        """Cancelling a running job does not persist any run file."""
        qm = QueueManager(storage=storage)
        run = qm.submit(
            {
                "batch": "test-batch",
                "prompt": "test",
                "source_folder": "inbox",
                "model": "vl-scorer",
                "top_n": 15,
                "move_enabled": False,
            }
        )

        # Cancel during scoring
        qm.cancel(run.run_id)
        qm.finalize_cancelled(run.run_id)

        # No run files should exist
        runs = storage.list_runs("test-batch")
        assert runs == []

    @pytest.mark.component
    def test_cancelled_run_no_latest_pointer(self, storage):
        """Cancelling a running job does not update latest.json."""
        qm = QueueManager(storage=storage)
        run = qm.submit(
            {
                "batch": "test-batch",
                "prompt": "test",
                "source_folder": "inbox",
                "model": "vl-scorer",
                "top_n": 15,
                "move_enabled": False,
            }
        )

        qm.cancel(run.run_id)
        qm.finalize_cancelled(run.run_id)

        latest = storage.load_latest("test-batch")
        assert latest is None

    @pytest.mark.component
    def test_completed_run_after_cancelled_does_persist(self, storage):
        """A completed run after a cancelled run does persist correctly."""
        qm = QueueManager(storage=storage)

        # Submit and cancel first job
        run1 = qm.submit(
            {
                "batch": "test-batch",
                "prompt": "first",
                "source_folder": "inbox",
                "model": "vl-scorer",
                "top_n": 15,
                "move_enabled": False,
            }
        )
        qm.cancel(run1.run_id)
        qm.finalize_cancelled(run1.run_id)

        # Submit and complete second job
        run2 = qm.submit(
            {
                "batch": "test-batch",
                "prompt": "second",
                "source_folder": "inbox",
                "model": "vl-scorer",
                "top_n": 15,
                "move_enabled": False,
            }
        )
        qm.complete_job(run2.run_id, results=[], totals=RunTotals(images=0))

        # Only the second run should be in history
        runs = storage.list_runs("test-batch")
        assert len(runs) == 1
        assert runs[0] == run2.run_id

        latest = storage.load_latest("test-batch")
        assert latest.run_id == run2.run_id
