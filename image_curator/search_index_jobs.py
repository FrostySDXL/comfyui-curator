"""Shared cancellable lifecycle for asynchronous media search-index builds."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import batch_store, search_index


SEARCH_INDEX_FILENAME = search_index.SEARCH_INDEX_FILENAME
ACTIVE_STATES = frozenset({"queued", "running", "cancelling"})
TERMINAL_STATES = frozenset({"cancelled", "completed", "failed"})
MAX_RETAINED_JOBS = 100
CLOSE_JOIN_TIMEOUT_SECONDS = 5.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _SearchIndexJob:
    job_id: str
    batch: str
    batches_dir: Path
    temp_path: Path
    status: str = "queued"
    completed: int = 0
    total: int = 0
    detail: str = "Queued"
    error: str = ""
    result: str = ""
    built_at: str | None = None
    item_count: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    completed_at: str | None = None
    cancel_accepted: bool | None = None
    committing: bool = field(default=False, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def payload(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "batch": self.batch,
            "status": self.status,
            "completed": self.completed,
            "total": self.total,
            "detail": self.detail,
            "error": self.error,
            "result": self.result,
            "built_at": self.built_at,
            "item_count": self.item_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "cancel_accepted": self.cancel_accepted,
        }


class ActiveSearchIndexJob(Exception):
    """Raised when a batch already has a queued or running build."""

    def __init__(self, job: dict[str, object]) -> None:
        super().__init__("A search-index build is already active for this batch")
        self.job = job


class SearchIndexJobManager:
    """Run one cancellable search-index build per batch in daemon threads."""

    def __init__(self, batches_dir: Path | Callable[[], Path]) -> None:
        self._batches_dir = batches_dir
        self._lock = threading.RLock()
        self._jobs: dict[str, _SearchIndexJob] = {}
        self._active_by_batch: dict[tuple[Path, str], str] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._closed = False

    def _root(self) -> Path:
        root = self._batches_dir() if callable(self._batches_dir) else self._batches_dir
        return Path(root)

    def submit(self, batch: str) -> dict[str, object]:
        batch_store._validate_name(batch, "batch name")
        batches_dir = self._root().resolve()
        with self._lock:
            if self._closed:
                raise RuntimeError("Search-index job manager is closed")
            self._prune_terminal_jobs(reserve=1)
            active_id = self._active_by_batch.get((batches_dir, batch))
            if active_id:
                active = self._jobs.get(active_id)
                if active and active.status in ACTIVE_STATES:
                    raise ActiveSearchIndexJob(active.payload())
            job_id = uuid.uuid4().hex
            job = _SearchIndexJob(
                job_id=job_id,
                batch=batch,
                batches_dir=batches_dir,
                temp_path=batches_dir / batch / f"{SEARCH_INDEX_FILENAME}.{job_id}.tmp",
            )
            self._jobs[job.job_id] = job
            worker = threading.Thread(
                target=self._run,
                args=(job,),
                name=f"search-index-{batch}-{job.job_id[:8]}",
                daemon=True,
            )
            self._active_by_batch[(batches_dir, batch)] = job.job_id
            self._workers[job.job_id] = worker
            worker.start()
            return job.payload()

    def get(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.payload() if job else None

    def cancel(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in TERMINAL_STATES:
                job.cancel_accepted = False
                return job.payload()
            if job.committing:
                job.cancel_accepted = False
                job.detail = "Build is being committed"
                job.updated_at = _now()
                return job.payload()
            job.cancel_event.set()
            job.status = "cancelling"
            job.detail = "Cancellation requested"
            job.cancel_accepted = True
            job.updated_at = _now()
            return job.payload()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for job in self._jobs.values():
                if job.status in ACTIVE_STATES:
                    job.cancel_event.set()
                    job.status = "cancelling"
                    job.detail = "Cancellation requested during shutdown"
                    job.cancel_accepted = True
                    job.updated_at = _now()
            workers = list(self._workers.values())
        end = time.monotonic() + CLOSE_JOIN_TIMEOUT_SECONDS
        for worker in workers:
            if worker is threading.current_thread():
                continue
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)

    def _prune_terminal_jobs(self, *, reserve: int = 0) -> None:
        terminal_ids = [job.job_id for job in self._jobs.values() if job.status in TERMINAL_STATES]
        excess = len(terminal_ids) - MAX_RETAINED_JOBS + reserve
        for job_id in terminal_ids[: max(0, excess)]:
            self._jobs.pop(job_id, None)

    def _set_terminal(
        self,
        job: _SearchIndexJob,
        status: str,
        *,
        detail: str,
        error: str = "",
        result: str = "",
    ) -> None:
        with self._lock:
            job.status = status
            job.detail = detail
            job.error = error
            job.result = result
            job.completed_at = _now()
            job.updated_at = job.completed_at
            if self._active_by_batch.get((job.batches_dir, job.batch)) == job.job_id:
                self._active_by_batch.pop((job.batches_dir, job.batch), None)
            self._workers.pop(job.job_id, None)
            self._prune_terminal_jobs()

    def _cleanup_temp(self, job: _SearchIndexJob) -> None:
        try:
            root = job.batches_dir.resolve()
            batch_dir = job.batches_dir / job.batch
            if batch_dir.is_symlink() or not batch_dir.is_dir():
                return
            resolved_batch = batch_dir.resolve()
            job.temp_path.relative_to(batch_dir)
            resolved_temp = job.temp_path.resolve()
            resolved_temp.relative_to(root)
            resolved_temp.relative_to(resolved_batch)
            if job.temp_path.is_file() and not job.temp_path.is_symlink():
                job.temp_path.unlink()
        except (OSError, ValueError):
            return

    def _run(self, job: _SearchIndexJob) -> None:
        with self._lock:
            if job.cancel_event.is_set():
                should_run = False
            else:
                job.status = "running"
                job.detail = "Scanning media…"
                job.updated_at = _now()
                should_run = True
        if not should_run:
            self._cleanup_temp(job)
            self._set_terminal(job, "cancelled", detail="Build cancelled", error="Build cancelled")
            return

        def progress(completed: int, total: int) -> None:
            if job.cancel_event.is_set():
                raise search_index.SearchIndexBuildCancelled
            with self._lock:
                job.completed = completed
                job.total = total
                job.detail = "Scanning media…"
                job.updated_at = _now()

        def before_commit() -> None:
            with self._lock:
                if job.cancel_event.is_set():
                    raise search_index.SearchIndexBuildCancelled
                job.committing = True
                job.detail = "Saving search index…"
                job.updated_at = _now()

        try:
            summary = search_index.build_search_index(
                job.batches_dir,
                job.batch,
                cancel_check=job.cancel_event.is_set,
                progress_callback=progress,
                commit_check=before_commit,
                temp_path=job.temp_path,
            )
        except search_index.SearchIndexBuildCancelled:
            self._cleanup_temp(job)
            self._set_terminal(job, "cancelled", detail="Build cancelled", error="Build cancelled")
            return
        except Exception:
            self._cleanup_temp(job)
            self._set_terminal(
                job,
                "failed",
                detail="Search index build failed",
                error="Search index build failed",
            )
            return

        with self._lock:
            job.completed = int(summary.get("item_count", job.completed))
            job.total = max(job.total, job.completed)
            job.built_at = str(summary.get("built_at") or "") or None
            job.item_count = job.completed
        self._set_terminal(
            job,
            "completed",
            detail="Search index ready",
            result="Search index built",
        )
