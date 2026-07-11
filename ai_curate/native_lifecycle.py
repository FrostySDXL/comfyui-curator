"""Native AI lifecycle manager for the ComfyUI Curator extension.

Owns the QueueManager, RunStorage, VisionClient, and worker thread
lifecycle. Provides startup/shutdown hooks for aiohttp application
lifecycle events.

Lifecycle state machine::

    UNINITIALIZED ── startup() ──> RUNNING
                                      │
                              shutdown() (permanent)
                                      │
                                      v
                                  SHUTDOWN

- startup() is idempotent during RUNNING; it is a no-op when already
  initialised.
- After shutdown, the lifecycle is **permanently closed**. Restart
  (calling startup again after shutdown) is NOT supported and will
  raise ``RuntimeError``.
- The public ``submit_job()`` method replaces direct ``_on_job_promoted``
  calls from route handlers. It atomically checks the submission gate,
  submits to the queue, and starts a worker thread when the job begins
  running immediately.
- All worker threads are tracked; shutdown joins every one of them.
"""

from __future__ import annotations

import enum
import logging
import threading
from pathlib import Path
from typing import Any

from ai_curate.client import VisionClient
from ai_curate.config import DEFAULT_BASE_URL, DEFAULT_MODEL, API_KEY, REQUEST_TIMEOUT
from ai_curate.elements import build_element_list
from ai_curate.models import CurationRun, JobState
from ai_curate.queue import QueueManager
from ai_curate.scoring import find_images, score_images
from ai_curate.storage import RunStorage
from ai_curate.worker import run_scoring_worker_inner
from image_curator import batch_store

logger = logging.getLogger(__name__)


class _LifecycleState(enum.Enum):
    UNINITIALIZED = "uninitialized"
    RUNNING = "running"
    SHUTDOWN = "shutdown"


class LifecycleShutdownError(RuntimeError):
    """Raised when a submission is attempted after shutdown has started."""


class NativeAiLifecycle:
    """Owns the AI scoring queue, client, and worker lifecycle for native mode.

    Public API:
        - ``startup(app)`` / ``shutdown(app)`` -- aiohttp lifecycle hooks.
        - ``submit_job(params) → CurationRun`` -- the single entry point for
          route handlers that validates, submits, and launches the worker.
        - ``queue`` / ``storage`` -- read-only access for query routes.

    Route handlers **must not** call ``_on_job_promoted`` directly.
    """

    def __init__(self, settings: Any) -> None:
        from image_curator.native_settings import NativeCuratorSettings  # noqa: F811

        self.settings: NativeCuratorSettings = settings
        self._storage: RunStorage | None = None
        self._queue: QueueManager | None = None
        self._client: VisionClient | None = None

        # Lifecycle state.
        self._state = _LifecycleState.UNINITIALIZED
        self._state_lock = threading.Lock()

        # Submission state is guarded by _state_lock so startup, submission,
        # worker registration, and shutdown form one atomic state machine.
        self._accepting_submissions = False

        # All non-daemon worker threads that are active (set of (thread, run_id)).
        self._workers: set[tuple[threading.Thread, str]] = set()
        self._workers_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle hooks (aiohttp on_startup / on_shutdown)
    # ------------------------------------------------------------------

    async def startup(self, app: Any) -> None:
        """Idempotent initialisation.

        During RUNNING this is a no-op.  After shutdown it raises
        ``RuntimeError`` because the lifecycle is permanently closed.
        """
        with self._state_lock:
            if self._state == _LifecycleState.SHUTDOWN:
                raise RuntimeError("Cannot start NativeAiLifecycle after shutdown")
            if self._state == _LifecycleState.RUNNING:
                return
            self._storage = RunStorage(batches_dir=self.settings.batch_root)
            self._client = VisionClient(
                base_url=DEFAULT_BASE_URL,
                model=DEFAULT_MODEL,
                timeout=REQUEST_TIMEOUT,
                api_key=API_KEY,
            )
            self._queue = QueueManager(storage=self._storage, on_promote=self._on_job_promoted)
            self._accepting_submissions = True
            self._state = _LifecycleState.RUNNING

    async def shutdown(self, app: Any) -> None:
        """Graceful shutdown: atomically stop accepting, cancel jobs, join workers.

        Idempotent -- subsequent calls are no-ops.
        """
        self._cancel_all_and_join()

    # ------------------------------------------------------------------
    # Public submission entry point
    # ------------------------------------------------------------------

    def submit_job(self, params: dict[str, Any]) -> CurationRun:
        """Validate submission gate, submit to queue, and launch worker if needed.

        This is the **single entry point** that route handlers must use to
        start a new curation job.  It replaces calling ``queue.submit()``
        + ``_on_job_promoted()`` directly.

        Raises:
            LifecycleShutdownError: if the lifecycle has started shutdown.
        """
        with self._state_lock:
            if not self._accepting_submissions:
                raise LifecycleShutdownError("AI curation is shutting down; no new jobs accepted")
            if self._queue is None:
                raise LifecycleShutdownError("AI queue not available")
            run = self._queue.submit(params)
            # Register and start the worker before releasing the lifecycle gate,
            # preventing shutdown from interleaving between submit and launch.
            if run.status == JobState.RUNNING:
                self._launch_worker(run.run_id)

        return run

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cancel_all_and_join(self) -> None:
        """Shutdown sequence (idempotent).

        1. Atomically stop accepting new submissions.
        2. Cancel every queued/running/cancelling job.
        3. Join every tracked worker thread (bounded timeout).
        4. Mark state SHUTDOWN.

        Does NOT promote or start any next job during/after shutdown.
        """
        # Step 1: stop acceptance and transition state once.
        should_cancel = False
        with self._state_lock:
            self._accepting_submissions = False
            if self._state != _LifecycleState.SHUTDOWN:
                self._state = _LifecycleState.SHUTDOWN
                should_cancel = True

        if should_cancel and self._queue is not None:
            try:
                for run in self._queue.list_jobs():
                    status = getattr(run, "status", None)
                    if status in (JobState.RUNNING, JobState.QUEUED, JobState.CANCELLING):
                        self._queue.cancel(run.run_id)
            except Exception:
                logger.exception("Error cancelling AI jobs during shutdown")

        # Step 3: join all workers.
        with self._workers_lock:
            workers_snapshot = set(self._workers)

        for t, run_id in workers_snapshot:
            if t.is_alive():
                t.join(timeout=5.0)

        # Clean up any workers that have exited (defensive).
        with self._workers_lock:
            for t, _run_id in workers_snapshot:
                if not t.is_alive():
                    self._workers.discard((t, _run_id))

    def _on_job_promoted(self, run_id: str) -> None:
        """Callback from QueueManager when a queued job is promoted to running.

        During/after shutdown this is a no-op — we do NOT start new workers.
        """
        with self._state_lock:
            if not self._accepting_submissions:
                return
            self._launch_worker(run_id)

    def _launch_worker(self, run_id: str) -> None:
        """Create, track, and start a non-daemon worker thread."""
        t = threading.Thread(target=self._run_worker, args=(run_id,), daemon=False)
        pair = (t, run_id)
        with self._workers_lock:
            self._workers.add(pair)
        t.start()

    def _run_worker(self, run_id: str) -> None:
        """Background thread that executes scoring for a submitted job."""
        try:
            if self._queue is None:
                return
            run = self._queue.get_job(run_id)
            if run is None:
                return
            try:
                self._run_scoring(run_id, run)
            except Exception:
                logger.exception("Unhandled native AI worker error")
                if self._queue is not None:
                    self._queue.fail_job(run_id, error_message="Unhandled worker error")
        finally:
            # Remove self from worker tracking.
            with self._workers_lock:
                for pair in list(self._workers):
                    if pair[1] == run_id:
                        self._workers.discard(pair)

    def _run_scoring(self, run_id: str, run: CurationRun) -> None:
        """Core scoring logic, extracted for exception handling."""
        assert self._queue is not None
        assert self._client is not None
        run_scoring_worker_inner(
            run_id=run_id,
            run=run,
            queue=self._queue,
            client=self._client,
            build_element_list_func=build_element_list,
            get_batch_folder=self._get_batch_folder,
            find_images_func=find_images,
            score_images_func=score_images,
            move_image_func=batch_store.move_image,
            logger=logger,
        )

    def _get_batch_folder(self, batch: str, folder: str) -> Path:
        """Resolve a batch review stage folder with containment validation.

        Rejects symlinked, non-directory, or resolved-escaping paths.
        Never reads/moves outside a real batch contained in batch_root.
        """
        batch_root = self.settings.batch_root
        if batch_root.is_symlink():
            raise ValueError("Batch root is a symlink")
        real_root = batch_root.resolve()

        # Batch directory must not be a symlink.
        batch_dir = batch_root / batch
        try:
            if batch_dir.is_symlink():
                raise ValueError("Batch path is a symlink")
            if not batch_dir.is_dir():
                raise ValueError("Batch is not a directory")
        except OSError as exc:
            raise ValueError("Invalid batch path") from exc

        real_batch = batch_dir.resolve()
        try:
            real_batch.relative_to(real_root)
        except ValueError as exc:
            raise ValueError("Batch escapes batch root") from exc

        # Stage folder must not be a symlink.
        stage_dir = batch_dir / folder
        try:
            if stage_dir.is_symlink():
                raise ValueError("Stage folder is a symlink")
            if not stage_dir.is_dir():
                raise ValueError("Stage folder is not a directory")
        except OSError as exc:
            raise ValueError("Invalid stage path") from exc

        real_stage = stage_dir.resolve()
        try:
            real_stage.relative_to(real_root)
            real_stage.relative_to(real_batch)
        except ValueError as exc:
            raise ValueError("Stage folder escapes batch") from exc

        return real_stage

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def queue(self) -> QueueManager | None:
        return self._queue

    @property
    def storage(self) -> RunStorage | None:
        return self._storage

    @property
    def active_workers(self) -> int:
        """Number of currently-tracked worker threads (for tests)."""
        with self._workers_lock:
            return len(self._workers)
