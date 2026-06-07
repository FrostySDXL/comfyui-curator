"""
ai_curate.storage -- Run history persistence for AI curation.

Manages on-disk layout for per-batch run history:
  <batch>/ai-curate/runs/<run-id>.json
  <batch>/ai-curate/latest.json

Cancelled runs are never persisted. Saved runs are immutable history.
"""

import json
import logging
import threading
from pathlib import Path
from typing import List, Optional

from ai_curate.config import BATCHES_DIR, AI_CURATE_DIR, RUNS_SUBDIR, LATEST_FILE
from ai_curate.models import CurationRun, JobState

logger = logging.getLogger(__name__)


class RunStorage:
    """Manages on-disk storage of AI curation run history."""

    def __init__(self, batches_dir: Optional[Path] = None):
        self.batches_dir = Path(batches_dir) if batches_dir is not None else BATCHES_DIR
        self._lock = threading.RLock()

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        """Raise ValueError if run_id contains unsafe characters."""
        if not run_id or not run_id.strip():
            raise ValueError("run_id must not be empty")
        if "\0" in run_id:
            raise ValueError("run_id contains null byte")
        if "/" in run_id or "\\" in run_id:
            raise ValueError("run_id contains path separators")
        if run_id in (".", ".."):
            raise ValueError("run_id is a reserved path component")

    def _ai_curate_dir(self, batch: str) -> Path:
        return self.batches_dir / batch / AI_CURATE_DIR

    def _runs_dir(self, batch: str) -> Path:
        return self._ai_curate_dir(batch) / RUNS_SUBDIR

    def _latest_path(self, batch: str) -> Path:
        return self._ai_curate_dir(batch) / LATEST_FILE

    def _run_path(self, batch: str, run_id: str) -> Path:
        self._validate_run_id(run_id)
        return self._runs_dir(batch) / f"{run_id}.json"

    def save_run(self, run: CurationRun) -> bool:
        """Persist a completed run to disk.

        Cancelled runs are never written. Only completed or failed runs
        are persisted.

        Args:
            run: The CurationRun to save.

        Returns:
            True if saved, False if skipped (e.g. cancelled).
        """
        if run.status == JobState.CANCELLED:
            return False

        with self._lock:
            runs_dir = self._runs_dir(run.batch)
            runs_dir.mkdir(parents=True, exist_ok=True)

            # Write the run file atomically with a temp file
            run_path = self._run_path(run.batch, run.run_id)
            tmp_path = run_path.with_suffix(run_path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(run.to_dict(), indent=2),
                encoding="utf-8",
            )
            # On Windows, Path.replace() raises FileExistsError if target
            # exists; remove the old file first so the rename is cross-platform.
            if run_path.exists():
                run_path.unlink()
            tmp_path.replace(run_path)

            # Update latest pointer atomically (under lock to prevent TOCTOU)
            latest_path = self._latest_path(run.batch)
            latest_tmp = latest_path.with_suffix(latest_path.suffix + ".tmp")
            latest_tmp.write_text(
                json.dumps({"run_id": run.run_id}, indent=2),
                encoding="utf-8",
            )
            if latest_path.exists():
                latest_path.unlink()
            latest_tmp.replace(latest_path)

        return True

    def load_run(self, batch: str, run_id: str) -> Optional[CurationRun]:
        """Load a specific run by batch and run_id.

        Args:
            batch: Batch name.
            run_id: Run identifier.

        Returns:
            CurationRun if found, None otherwise.
        """
        with self._lock:
            run_path = self._run_path(batch, run_id)
            if not run_path.exists():
                return None
            try:
                data = json.loads(run_path.read_text(encoding="utf-8"))
                return CurationRun.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Corrupt run file {run_path}: {e}", flush=True)
                return None

    def list_runs(self, batch: str) -> List[str]:
        """List run IDs for a batch in chronological order (oldest first).

        Args:
            batch: Batch name.

        Returns:
            List of run_id strings.
        """
        with self._lock:
            runs_dir = self._runs_dir(batch)
            if not runs_dir.exists():
                return []
            run_files = list(runs_dir.glob("*.json"))

            # Sort by created_at from inside each run file, falling back to
            # file modification time for backward compatibility.
            def _run_created_at(path: Path) -> float:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    created = data.get("created_at", "")
                    if created:
                        from datetime import datetime, timezone

                        return datetime.fromisoformat(created).timestamp()
                except Exception:
                    pass
                return path.stat().st_mtime

            run_files.sort(key=_run_created_at)
            return [f.stem for f in run_files]

    def load_latest(self, batch: str) -> Optional[CurationRun]:
        """Load the most recent run for a batch via the latest pointer.

        Args:
            batch: Batch name.

        Returns:
            CurationRun if a latest pointer exists and the run file is valid, None otherwise.
        """
        with self._lock:
            latest_path = self._latest_path(batch)
            if not latest_path.exists():
                return None
            try:
                latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
                run_id = latest_data.get("run_id")
                if not isinstance(run_id, str) or not run_id:
                    return None
                return self.load_run(batch, run_id)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Corrupt latest.json {latest_path}: {e}", flush=True)
                return None
