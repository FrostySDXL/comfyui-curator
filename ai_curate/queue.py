"""
ai_curate.queue -- Single-worker queue manager for AI curation jobs.

Supports:
- One running job at a time
- FIFO queue for additional jobs
- Cancellation of queued or running jobs
- Two-phase execution: scoring phase then optional move phase
- Cancelled runs are never persisted to history
"""

import logging
import threading
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from ai_curate.models import CurationRun, ImageResult, JobState, RunTotals
from ai_curate.config import DEFAULT_MODEL, DEFAULT_TOP_N
from ai_curate.storage import RunStorage

logger = logging.getLogger(__name__)


class QueueManager:
    """Manages the lifecycle of AI curation jobs.

    Only one job runs at a time. Additional submissions are queued.
    Cancellation during scoring discards partial results and does not
    persist history. Cancellation of running jobs is supported in both
    the scoring and move phases.
    """

    def __init__(
        self,
        storage: Optional[RunStorage] = None,
        on_promote: Optional[Callable[[str], None]] = None,
    ):
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, CurationRun] = OrderedDict()
        self._queue_order: deque[str] = deque()
        self._running_id: Optional[str] = None
        self._storage = storage  # May be None for testing
        self._on_promote = on_promote  # Callback when a queued job starts running

    def submit(self, job_params: Dict) -> CurationRun:
        """Submit a new curation job.

        If no job is currently running, the job starts immediately.
        Otherwise, it is placed in the queue.

        Args:
            job_params: Dict with batch, prompt, source_folder, model,
                        top_n, move_enabled, elements, destination_folder.

        Returns:
            The CurationRun with its assigned run_id and initial status.
        """
        run = CurationRun(
            batch=job_params.get("batch", ""),
            source_folder=job_params.get("source_folder", "inbox"),
            destination_folder=job_params.get("destination_folder"),
            move_enabled=job_params.get("move_enabled", False),
            prompt=job_params.get("prompt", ""),
            elements=job_params.get("elements") or [],
            model=job_params.get("model") or DEFAULT_MODEL or "",
            top_n=job_params.get("top_n", DEFAULT_TOP_N),
        )

        with self._lock:
            self._jobs[run.run_id] = run
            if self._running_id is None:
                run.status = JobState.RUNNING
                self._running_id = run.run_id
            else:
                run.status = JobState.QUEUED
                self._queue_order.append(run.run_id)

        return run

    def get_job(self, run_id: str) -> Optional[CurationRun]:
        """Retrieve a job by run_id.

        Args:
            run_id: The job identifier.

        Returns:
            CurationRun if found, None otherwise.
        """
        with self._lock:
            return self._jobs.get(run_id)

    def list_jobs(self) -> List[CurationRun]:
        """List all known jobs (running, queued, completed, etc.).

        Returns:
            List of CurationRun objects.
        """
        with self._lock:
            return list(self._jobs.values())

    def prune(self, keep_last: int = 100) -> int:
        """Remove old completed, failed, and cancelled jobs from memory.

        Running and queued jobs are never pruned. Keeps the most recent
        ``keep_last`` completed/failed/cancelled jobs plus all active ones.

        Args:
            keep_last: Number of most-recent terminal jobs to retain.

        Returns:
            Number of jobs removed.
        """
        with self._lock:
            # Collect terminal job IDs ordered by insertion (oldest first)
            terminal_ids = [
                run_id
                for run_id, run in self._jobs.items()
                if run.status in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)
            ]
            # Keep the most recent keep_last; remove the rest
            to_remove = terminal_ids[:-keep_last] if len(terminal_ids) > keep_last else []
            for run_id in to_remove:
                del self._jobs[run_id]
                if run_id in self._queue_order:
                    self._queue_order.remove(run_id)
            return len(to_remove)

    def cancel(self, run_id: str) -> bool:
        """Request cancellation of a job.

        - Queued jobs: immediately set to CANCELLED.
        - Running jobs: set to CANCELLING (caller must finalize after
          scoring loop exits). Cancellation is accepted during both the
          scoring and move phases; callers are responsible for stopping
          their work and calling finalize_cancelled().

        Args:
            run_id: The job to cancel.

        Returns:
            True if cancellation was accepted, False otherwise.
        """
        with self._lock:
            run = self._jobs.get(run_id)
            if run is None:
                return False

            if run.status == JobState.QUEUED:
                run.status = JobState.CANCELLED
                if run_id in self._queue_order:
                    self._queue_order.remove(run_id)
                return True

            if run.status == JobState.RUNNING:
                # During scoring phase, set to CANCELLING
                # The scoring loop must check and stop
                run.status = JobState.CANCELLING
                return True

            # Cannot cancel completed, failed, or already cancelled jobs
            return False

    def finalize_cancelled(
        self,
        run_id: str,
        results: Optional[list] = None,
        totals: Optional[object] = None,
    ) -> bool:
        """Finalize a cancelling job after the scoring loop has stopped.

        Discards partial results and does NOT persist history by default.
        If results and totals are provided, they are retained on the cancelled
        run record (e.g., for partial move audit trails).

        Args:
            run_id: The job to finalize as cancelled.
            results: Optional partial results to retain on the cancelled run.
            totals: Optional partial totals to retain on the cancelled run.

        Returns:
            True if finalized, False if not in CANCELLING state.
        """
        with self._lock:
            run = self._jobs.get(run_id)
            if run is None or run.status != JobState.CANCELLING:
                return False

            run.status = JobState.CANCELLED
            if results is not None:
                run.results = results
            else:
                run.results = []  # Discard partial results
            if totals is not None:
                run.totals = totals
            run.completed_at = datetime.now(timezone.utc).isoformat()

            # Clear the running slot and promote next queued job
            promoted_id = None
            if self._running_id == run_id:
                self._running_id = None
                promoted_id = self._promote_next()

        self._notify_promote(promoted_id)
        self.prune()
        return True

    def complete_job(
        self,
        run_id: str,
        results: List[ImageResult],
        totals: RunTotals,
    ) -> bool:
        """Mark a running job as completed and persist history.

        After completion, promotes the next queued job to running.

        Args:
            run_id: The job to complete.
            results: List of ImageResult objects.
            totals: Aggregate RunTotals.

        Returns:
            True if completed, False if not in RUNNING state.
        """
        with self._lock:
            run = self._jobs.get(run_id)
            if run is None or run.status != JobState.RUNNING:
                return False

            run.status = JobState.COMPLETED
            run.results = results
            run.totals = totals
            run.completed_at = datetime.now(timezone.utc).isoformat()

            # Clear the running slot and promote next queued job
            promoted_id = None
            if self._running_id == run_id:
                self._running_id = None
                promoted_id = self._promote_next()

        # Persist to storage outside the lock to avoid blocking queue
        # operations during disk I/O.
        if self._storage:
            self._storage.save_run(run)

        self._notify_promote(promoted_id)
        self.prune()
        return True

    def fail_job(self, run_id: str, error_message: str = "") -> bool:
        """Mark a running job as failed.

        Args:
            run_id: The job that failed.
            error_message: Description of the failure.

        Returns:
            True if failed, False if not in RUNNING state.
        """
        with self._lock:
            run = self._jobs.get(run_id)
            if run is None or run.status != JobState.RUNNING:
                return False

            run.status = JobState.FAILED
            run.completed_at = datetime.now(timezone.utc).isoformat()

            promoted_id = None
            if self._running_id == run_id:
                self._running_id = None
                promoted_id = self._promote_next()

        # Persist to storage outside the lock to avoid blocking queue
        # operations during disk I/O.
        if self._storage:
            self._storage.save_run(run)

        self._notify_promote(promoted_id)
        self.prune()
        return True

    def _notify_promote(self, promoted_id: Optional[str]) -> None:
        """Invoke the on_promote callback for a promoted job, swallowing errors."""
        if promoted_id and self._on_promote:
            try:
                self._on_promote(promoted_id)
            except Exception:
                import traceback

                traceback.print_exc()

    def is_cancel_requested(self, run_id: str) -> bool:
        """Check if cancellation has been requested for a running job.

        The scoring loop should call this before each image.

        Args:
            run_id: The job to check.

        Returns:
            True if the job is in CANCELLING state.
        """
        with self._lock:
            run = self._jobs.get(run_id)
            return run is not None and run.status == JobState.CANCELLING

    def _promote_next(self) -> Optional[str]:
        """Promote the next queued job to running. Must be called under lock.

        Returns:
            The run_id of the promoted job, or None if no job was promoted.
            Callers must invoke the ``_on_promote`` callback **outside** the
            lock to avoid deadlock.
        """
        while self._queue_order:
            next_id = self._queue_order.popleft()
            next_run = self._jobs.get(next_id)
            if next_run and next_run.status == JobState.QUEUED:
                next_run.status = JobState.RUNNING
                self._running_id = next_id
                return next_id

        # No more queued jobs
        self._running_id = None
        return None
