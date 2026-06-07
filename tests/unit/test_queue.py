"""Unit tests for ai_curate.queue -- single-worker queue manager."""

import pytest
from unittest.mock import MagicMock, patch
from ai_curate.queue import QueueManager
from ai_curate.models import CurationRun, JobState, ImageResult, RunTotals


@pytest.fixture
def qm():
    """Create a fresh QueueManager for each test."""
    return QueueManager()


def _make_job(batch="test-batch", prompt="test prompt", **kwargs):
    """Helper to create a job submission dict."""
    job = {
        "batch": batch,
        "prompt": prompt,
        "source_folder": "inbox",
        "model": "vl-scorer",
        "top_n": 15,
        "move_enabled": False,
        "elements": None,
    }
    job.update(kwargs)
    return job


class TestQueueManagerSubmit:
    def test_first_job_runs_immediately(self, qm):
        """First submitted job goes to running state."""
        run = qm.submit(_make_job())
        assert run.status == JobState.RUNNING
        assert run.run_id

    def test_second_job_goes_to_queued(self, qm):
        """Second job while first is running goes to queued state."""
        qm.submit(_make_job(batch="batch1"))
        run2 = qm.submit(_make_job(batch="batch2"))
        assert run2.status == JobState.QUEUED

    def test_queued_job_gets_id(self, qm):
        """Queued jobs still get a run_id immediately."""
        qm.submit(_make_job())
        run2 = qm.submit(_make_job())
        assert run2.run_id
        assert len(run2.run_id) == 12


class TestQueueManagerGetJob:
    def test_get_running_job(self, qm):
        """get_job returns the running job."""
        submitted = qm.submit(_make_job())
        retrieved = qm.get_job(submitted.run_id)
        assert retrieved is not None
        assert retrieved.run_id == submitted.run_id
        assert retrieved.status == JobState.RUNNING

    def test_get_queued_job(self, qm):
        """get_job returns a queued job."""
        qm.submit(_make_job(batch="batch1"))
        run2 = qm.submit(_make_job(batch="batch2"))
        retrieved = qm.get_job(run2.run_id)
        assert retrieved is not None
        assert retrieved.status == JobState.QUEUED

    def test_get_nonexistent_job(self, qm):
        """get_job returns None for unknown run_id."""
        assert qm.get_job("nonexistent") is None


class TestQueueManagerCancel:
    def test_cancel_queued_job(self, qm):
        """Cancelling a queued job sets it to cancelled."""
        qm.submit(_make_job(batch="batch1"))
        run2 = qm.submit(_make_job(batch="batch2"))
        result = qm.cancel(run2.run_id)
        assert result is True
        assert qm.get_job(run2.run_id).status == JobState.CANCELLED

    def test_cancel_running_job_during_scoring(self, qm):
        """Cancelling a running job during scoring sets it to cancelling."""
        run = qm.submit(_make_job())
        result = qm.cancel(run.run_id)
        # During scoring phase, cancel sets state to cancelling
        assert result is True
        job = qm.get_job(run.run_id)
        assert job.status in (JobState.CANCELLING, JobState.CANCELLED)

    def test_cancel_nonexistent_job(self, qm):
        """Cancelling a nonexistent job returns False."""
        assert qm.cancel("nonexistent") is False


class TestQueueManagerListJobs:
    def test_list_jobs_returns_all(self, qm):
        """list_jobs returns both running and queued jobs."""
        qm.submit(_make_job(batch="batch1"))
        qm.submit(_make_job(batch="batch2"))
        jobs = qm.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_empty(self, qm):
        """list_jobs returns empty list when no jobs."""
        assert qm.list_jobs() == []


class TestQueueManagerCompletion:
    def test_complete_running_job(self, qm):
        """Completing a running job sets status and triggers next queued."""
        run1 = qm.submit(_make_job(batch="batch1"))
        run2 = qm.submit(_make_job(batch="batch2"))

        # Complete the first job
        qm.complete_job(run1.run_id, results=[], totals=RunTotals(images=5, scored=5))

        # First job should be completed
        assert qm.get_job(run1.run_id).status == JobState.COMPLETED

        # Second job should now be running
        assert qm.get_job(run2.run_id).status == JobState.RUNNING

    def test_cancelled_run_not_in_history(self, qm):
        """When a running job is cancelled, it should not produce history."""
        mock_storage = MagicMock()
        qm_with_storage = QueueManager(storage=mock_storage)

        run = qm_with_storage.submit(_make_job())
        qm_with_storage.cancel(run.run_id)
        qm_with_storage.finalize_cancelled(run.run_id)

        # Storage save_run should NOT have been called
        mock_storage.save_run.assert_not_called()


class TestQueueManagerStateTransitions:
    def test_state_flow_queued_to_running(self, qm):
        """Queued job transitions to running when slot opens."""
        run1 = qm.submit(_make_job(batch="b1"))
        run2 = qm.submit(_make_job(batch="b2"))
        assert qm.get_job(run2.run_id).status == JobState.QUEUED

        qm.complete_job(run1.run_id, results=[], totals=RunTotals())
        assert qm.get_job(run2.run_id).status == JobState.RUNNING

    def test_state_flow_running_to_completed(self, qm):
        """Running job transitions to completed on finish."""
        run = qm.submit(_make_job())
        qm.complete_job(run.run_id, results=[], totals=RunTotals())
        assert qm.get_job(run.run_id).status == JobState.COMPLETED

    def test_state_flow_running_to_cancelling(self, qm):
        """Running job transitions to cancelling on cancel request."""
        run = qm.submit(_make_job())
        qm.cancel(run.run_id)
        assert qm.get_job(run.run_id).status == JobState.CANCELLING

    def test_state_flow_cancelling_to_cancelled(self, qm):
        """Cancelling job transitions to cancelled on finalize."""
        run = qm.submit(_make_job())
        qm.cancel(run.run_id)
        qm.finalize_cancelled(run.run_id)
        assert qm.get_job(run.run_id).status == JobState.CANCELLED


class TestQueueManagerFail:
    def test_fail_running_job(self, qm):
        """Failing a running job sets it to FAILED."""
        run = qm.submit(_make_job())
        result = qm.fail_job(run.run_id, "scoring error")
        assert result is True
        assert qm.get_job(run.run_id).status == JobState.FAILED

    def test_fail_job_promotes_next(self, qm):
        """Failing the running job promotes the next queued job."""
        run1 = qm.submit(_make_job(batch="b1"))
        run2 = qm.submit(_make_job(batch="b2"))
        assert qm.get_job(run2.run_id).status == JobState.QUEUED

        qm.fail_job(run1.run_id)
        assert qm.get_job(run2.run_id).status == JobState.RUNNING

    def test_fail_job_persists_to_storage(self, qm):
        """Failing a job saves it to storage if provided."""
        mock_storage = MagicMock()
        qm_with_storage = QueueManager(storage=mock_storage)

        run = qm_with_storage.submit(_make_job())
        qm_with_storage.fail_job(run.run_id, "scoring error")

        mock_storage.save_run.assert_called_once()
        saved_run = mock_storage.save_run.call_args[0][0]
        assert saved_run.status == JobState.FAILED

    def test_fail_job_nonexistent(self, qm):
        """Failing a nonexistent job returns False."""
        assert qm.fail_job("nonexistent") is False

    def test_fail_job_not_running(self, qm):
        """Failing a queued (non-running) job returns False."""
        qm.submit(_make_job(batch="b1"))
        run2 = qm.submit(_make_job(batch="b2"))
        # run2 is queued, not running
        assert qm.fail_job(run2.run_id) is False
        assert qm.get_job(run2.run_id).status == JobState.QUEUED

    def test_fail_job_clears_running_id(self, qm):
        """After failing the running job, no job is running."""
        run = qm.submit(_make_job())
        qm.fail_job(run.run_id)
        # Submitting another job should start running immediately
        run2 = qm.submit(_make_job(batch="next"))
        assert qm.get_job(run2.run_id).status == JobState.RUNNING
