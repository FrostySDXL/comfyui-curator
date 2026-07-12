"""
ai_curate.storage -- Run history persistence for AI curation.

Manages on-disk layout for per-batch run history:
  <batch>/ai-curate/runs/<run-id>.json
  <batch>/ai-curate/latest.json

Cancelled runs are never persisted. Saved runs are immutable history.
All read/write operations validate filesystem containment against the
configured batches directory and reject symlinked or escaping paths.
"""

import json
import logging
import threading
from pathlib import Path
from typing import List, Optional

from .config import BATCHES_DIR, AI_CURATE_DIR, RUNS_SUBDIR, LATEST_FILE
from .models import CurationRun, JobState

logger = logging.getLogger(__name__)


class RunStorage:
    """Manages on-disk storage of AI curation run history."""

    def __init__(self, batches_dir: Optional[Path] = None):
        self.batches_dir = Path(batches_dir) if batches_dir is not None else BATCHES_DIR
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # String-level validation (defence layer 1)
    # ------------------------------------------------------------------

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

    @staticmethod
    def _validate_batch(batch: str) -> None:
        """Raise ValueError if ``batch`` contains unsafe characters.

        Mirrors ``_validate_run_id`` so neither input can escape the
        configured ``batches_dir``. Defence in depth: callers should
        already restrict batches to known-good names, but storage methods
        must not silently trust that.
        """
        if not batch or not batch.strip():
            raise ValueError("batch must not be empty")
        if "\0" in batch:
            raise ValueError("batch contains null byte")
        if "/" in batch or "\\" in batch:
            raise ValueError("batch contains path separators")
        if batch in (".", ".."):
            raise ValueError("batch is a reserved path component")
        if batch.startswith("."):
            raise ValueError("batch starts with a dot")

    # ------------------------------------------------------------------
    # Filesystem-level containment (defence layer 2)
    # ------------------------------------------------------------------

    def _validate_path_for_write(self, path: Path, batch: str) -> None:
        """Validate *before* writing that ``path`` is safely contained.

        Checks:
        - The path is not an existing symlink.
        - If the path exists, it is a regular file.
        - The resolved path is within ``self.batches_dir``.
        - The resolved path is within the resolved batch directory.
        - No parent directory that already exists is a symlink.

        Raises ValueError on any violation.  The caller must perform this
        check **before** any write (including ``mkdir``) to guarantee
        rejected saves do not mutate the filesystem.
        """
        real_root = self.batches_dir.resolve()
        _validate_containment_root(self.batches_dir, real_root)

        # Check the batch directory exists, is a dir, and is not a symlink.
        batch_dir = self.batches_dir / batch
        self._validate_batch(batch)
        try:
            if not batch_dir.exists():
                raise ValueError("batch directory does not exist")
            if batch_dir.is_symlink():
                raise ValueError("batch path is a symlink")
            if not batch_dir.is_dir():
                raise ValueError("batch path is not a directory")
        except OSError as exc:
            raise ValueError("invalid batch path") from exc

        # Resolve batch for containment: must resolve within real_root.
        try:
            real_batch = batch_dir.resolve()
            real_batch.relative_to(real_root)
        except (OSError, ValueError) as exc:
            raise ValueError("batch path escapes batch root") from exc

        # Validate parent chain: every existing parent must not be a symlink.
        _validate_parent_chain_no_symlinks(self.batches_dir, path)

        # Validate the target path itself.
        try:
            if path.exists():
                if path.is_symlink():
                    raise ValueError("target path is a symlink")
                if not path.is_file():
                    raise ValueError("target path exists but is not a regular file")
            real_path = path.resolve()
            real_path.relative_to(real_root)
            real_path.relative_to(real_batch)
        except (OSError, ValueError) as exc:
            raise ValueError("target path escapes containment") from exc

    def _validate_path_for_read(self, path: Path, batch: str) -> None:
        """Validate *before* reading that ``path`` is safely contained.

        Similar to ``_validate_path_for_write`` but also requires the file
        to be a regular file (not a directory or symlink).
        """
        real_root = self.batches_dir.resolve()
        _validate_containment_root(self.batches_dir, real_root)

        batch_dir = self.batches_dir / batch
        self._validate_batch(batch)
        try:
            if batch_dir.is_symlink() or not batch_dir.is_dir():
                raise ValueError("invalid batch path")
            real_batch = batch_dir.resolve()
            real_batch.relative_to(real_root)
        except (OSError, ValueError) as exc:
            raise ValueError("batch path escapes batch root") from exc

        _validate_parent_chain_no_symlinks(self.batches_dir, path)

        # Must exist and be a regular file.
        try:
            if not path.exists():
                return  # not-found is not a safety violation
            if path.is_symlink():
                raise ValueError("path is a symlink")
            if not path.is_file():
                raise ValueError("path is not a regular file")
            real_path = path.resolve()
            real_path.relative_to(real_root)
            real_path.relative_to(real_batch)
        except (OSError, ValueError) as exc:
            raise ValueError("path escapes containment") from exc

    def _validate_dir_for_listing(self, runs_dir: Path, batch: str) -> None:
        """Validate that ``runs_dir`` is a safe directory for listing."""
        real_root = self.batches_dir.resolve()
        _validate_containment_root(self.batches_dir, real_root)

        batch_dir = self.batches_dir / batch
        self._validate_batch(batch)
        try:
            if batch_dir.is_symlink() or not batch_dir.is_dir():
                raise ValueError("invalid batch path")
            real_batch = batch_dir.resolve()
            real_batch.relative_to(real_root)
        except (OSError, ValueError) as exc:
            raise ValueError("batch path escapes batch root") from exc

        if not runs_dir.exists():
            return

        try:
            _validate_parent_chain_no_symlinks(self.batches_dir, runs_dir / "placeholder")
            if runs_dir.is_symlink():
                raise ValueError("runs dir is a symlink")
            if not runs_dir.is_dir():
                raise ValueError("runs dir is not a directory")
            real_runs = runs_dir.resolve()
            real_runs.relative_to(real_root)
            real_runs.relative_to(real_batch)
        except (OSError, ValueError) as exc:
            raise ValueError("runs dir escapes containment") from exc

    # ------------------------------------------------------------------
    # Path builders
    # ------------------------------------------------------------------

    def _ai_curate_dir(self, batch: str) -> Path:
        self._validate_batch(batch)
        return self.batches_dir / batch / AI_CURATE_DIR

    def _runs_dir(self, batch: str) -> Path:
        self._validate_batch(batch)
        return self._ai_curate_dir(batch) / RUNS_SUBDIR

    def _latest_path(self, batch: str) -> Path:
        self._validate_batch(batch)
        return self._ai_curate_dir(batch) / LATEST_FILE

    def _run_path(self, batch: str, run_id: str) -> Path:
        self._validate_batch(batch)
        self._validate_run_id(run_id)
        return self._runs_dir(batch) / f"{run_id}.json"

    # ------------------------------------------------------------------
    # Public I/O operations
    # ------------------------------------------------------------------

    def save_run(self, run: CurationRun, allow_cancelled: bool = False) -> bool:
        """Persist a completed run to disk.

        Cancelled runs are normally not persisted. The exception is the
        partial-move audit-trail case: the queue's ``finalize_cancelled``
        calls this with ``allow_cancelled=True`` when partial results
        were supplied, so the operator can see which files were moved
        before the cancellation.

        All target paths (run JSON, .tmp, latest.json, latest.json.tmp)
        are validated for filesystem containment BEFORE any write.
        Rejected saves never create or mutate files.

        Args:
            run: The CurationRun to save.
            allow_cancelled: When True, persist CANCELLED runs (used for
                partial-move audit trails). When False (default), cancelled
                runs are skipped.

        Returns:
            True if saved, False if skipped (e.g. cancelled).
        """
        if run.status == JobState.CANCELLED and not allow_cancelled:
            return False

        run_path = self._run_path(run.batch, run.run_id)
        tmp_path = run_path.with_suffix(run_path.suffix + ".tmp")
        latest_path = self._latest_path(run.batch)
        latest_tmp = latest_path.with_suffix(latest_path.suffix + ".tmp")

        with self._lock:
            # Validate ALL paths before any write — if any fail, nothing is created.
            self._validate_path_for_write(run_path, run.batch)
            self._validate_path_for_write(tmp_path, run.batch)
            self._validate_path_for_write(latest_path, run.batch)
            self._validate_path_for_write(latest_tmp, run.batch)

            runs_dir = run_path.parent
            runs_dir.mkdir(parents=True, exist_ok=True)

            # ------------------------------------------------------------------
            # Post-creation revalidation: after mkdir the parent chain and
            # every target may have transitioned to a symlink, non-regular
            # file, or resolved escape.  Re-check before any write so a
            # rejected save never mutates the filesystem.
            # ------------------------------------------------------------------
            self._validate_path_for_write(run_path, run.batch)
            self._validate_path_for_write(tmp_path, run.batch)
            self._validate_path_for_write(latest_path, run.batch)
            self._validate_path_for_write(latest_tmp, run.batch)
            _validate_parent_chain_no_symlinks(self.batches_dir, runs_dir)

            # Write the run file atomically via a temp file.
            tmp_path.write_text(
                json.dumps(run.to_dict(), indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(run_path)

            # Update latest pointer atomically.
            latest_tmp.write_text(
                json.dumps({"run_id": run.run_id}, indent=2),
                encoding="utf-8",
            )
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
            try:
                self._validate_path_for_read(run_path, batch)
            except ValueError:
                return None
            if not run_path.exists():
                return None
            try:
                data = json.loads(run_path.read_text(encoding="utf-8"))
                return CurationRun.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("Corrupt run file: %s", e)
                return None

    def list_runs(self, batch: str) -> List[str]:
        """List run IDs for a batch in chronological order (oldest first).

        Unsafe entries (symlinks, escaping paths, non-regular files) are
        silently excluded.

        Args:
            batch: Batch name.

        Returns:
            List of run_id strings.
        """
        with self._lock:
            runs_dir = self._runs_dir(batch)
            try:
                self._validate_dir_for_listing(runs_dir, batch)
            except ValueError:
                return []
            if not runs_dir.exists():
                return []

            all_files = list(runs_dir.glob("*.json"))
            safe_files: list[Path] = []
            for f in all_files:
                try:
                    if f.is_symlink():
                        continue
                    if not f.is_file():
                        continue
                    real_f = f.resolve()
                    real_root = self.batches_dir.resolve()
                    real_batch = (self.batches_dir / batch).resolve()
                    real_f.relative_to(real_root)
                    real_f.relative_to(real_batch)
                except (OSError, ValueError):
                    continue
                safe_files.append(f)

            # Sort by created_at from inside each run file, falling back to
            # file modification time for backward compatibility.
            def _run_created_at(path: Path) -> float:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    created = data.get("created_at", "")
                    if created:
                        from datetime import datetime

                        return datetime.fromisoformat(created).timestamp()
                except Exception:
                    pass
                try:
                    return path.stat().st_mtime
                except OSError:
                    return 0.0

            safe_files.sort(key=_run_created_at)
            return [f.stem for f in safe_files]

    def load_latest(self, batch: str) -> Optional[CurationRun]:
        """Load the most recent run for a batch via the latest pointer.

        Args:
            batch: Batch name.

        Returns:
            CurationRun if a latest pointer exists and the run file is valid, None otherwise.
        """
        with self._lock:
            latest_path = self._latest_path(batch)
            try:
                self._validate_path_for_read(latest_path, batch)
            except ValueError:
                return None
            if not latest_path.exists():
                return None
            try:
                latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
                run_id = latest_data.get("run_id")
                if not isinstance(run_id, str) or not run_id:
                    return None
                return self.load_run(batch, run_id)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("Corrupt latest.json: %s", e)
                return None


# ------------------------------------------------------------------
# Module-level path safety helpers
# ------------------------------------------------------------------


def _validate_containment_root(raw_root: Path, real_root: Path) -> None:
    """Ensure the configured batches_dir resolves to a real directory."""
    try:
        if raw_root.is_symlink():
            raise ValueError("configured batch root is a symlink")
        if not real_root.is_dir():
            raise ValueError("configured batch root is not a directory")
    except (OSError, ValueError) as exc:
        raise ValueError("invalid batch root") from exc


def _validate_parent_chain_no_symlinks(base_dir: Path, final_path: Path) -> None:
    """Check that no parent of ``final_path`` (up to and including ``base_dir``) is a symlink.

    Traverses the directory chain from ``base_dir`` to the parent of
    ``final_path``, rejecting any existing directory that is a symlink.
    Non-existent intermediate directories are silently skipped (OSError
    from ``is_symlink()`` is caught) because they will be created by
    ``mkdir`` at a later stage and then revalidated.
    """
    parts = final_path.relative_to(base_dir).parts
    current = base_dir
    # Check every ancestor directory except the final leaf.
    for part in parts[:-1]:
        current = current / part
        try:
            if current.is_symlink():
                raise ValueError(f"symlink in path: {current}")
        except OSError:
            pass
