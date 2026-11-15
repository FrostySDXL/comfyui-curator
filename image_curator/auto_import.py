"""Process-local serialized imports and background stability tracking."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import batch_store
from .sidecar_metadata import find_json_sidecar

logger = logging.getLogger(__name__)


def _fingerprint(path: Path) -> tuple:
    if path.is_symlink() or not path.is_file():
        raise OSError("Unsafe source media")
    stat = path.stat()
    sidecar = find_json_sidecar(path)
    side_stat = sidecar.stat() if sidecar else None
    return (
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        sidecar.name if sidecar else None,
        side_stat.st_ino if side_stat else None,
        side_stat.st_size if side_stat else None,
        side_stat.st_mtime_ns if side_stat else None,
    )


def _validate_source(source: Path, root: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Import source is unavailable or unsafe.")
    real_source = source.resolve(strict=True)
    real_root = root.resolve(strict=True)
    if real_source.is_relative_to(real_root) or real_root.is_relative_to(real_source):
        raise ValueError("Import source and library must not overlap.")


class AutoImport:
    """One worker per server; mutations share its lock with manual imports."""

    def __init__(
        self, paths: Callable[[], tuple[Path, Path, Path, bool]], refresh: Callable[[str], None]
    ):
        self.paths = paths
        self.refresh = refresh
        self.lock = threading.RLock()
        self._status_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.observed: dict[str, tuple] = {}
        self.context = None
        self.error = ""
        self.retry_after = 0.0
        self.paused = False
        self.failure = None
        self.failure_id = 0

    def _set_error(self, message: str, *, paused: bool):
        with self._status_lock:
            if message and (message != self.error or paused != self.paused):
                self.failure_id += 1
                self.failure = {"id": self.failure_id, "message": message[:240], "paused": paused}
            self.error, self.paused = message, paused

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread = threading.Thread(
                    target=self._run, daemon=True, name="curator-auto-import"
                )
                self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        return not self.thread or not self.thread.is_alive()

    def _run(self):
        while not self.stop_event.wait(1):
            try:
                self.poll()
            except Exception:
                logger.exception("Automatic import failed")
                self._set_error("Automatic import failed; check server logs.", paused=False)
                self.stop_event.wait(10)

    def poll(self):
        with self.lock:
            source, root, state_path, enabled = self.paths()
            state = batch_store.load_state(state_path)
            batch = state.get("active_batch")
            context = (source, root, batch, enabled)
            if context != self.context:
                self.context, self.observed = context, {}
                self._set_error("", paused=False)
                self.retry_after = 0.0
            if not context[-1]:
                self._set_error("", paused=False)
                return
            try:
                if not batch:
                    raise ValueError("Select an import destination batch.")
                batch_store._resolve_import_destination(root, batch)
                _validate_source(source, root)
                current = {}
                stable = set()
                for path in batch_store._iter_pending_media(source):
                    try:
                        fingerprint = _fingerprint(path)
                        current[path.name] = fingerprint
                        if self.observed.get(path.name) == fingerprint:
                            stable.add(path.name)
                    except OSError:
                        continue
                self.observed = current
                if stable and time.monotonic() >= self.retry_after:

                    def ready(path):
                        if self.stop_event.is_set():
                            return False
                        try:
                            return _fingerprint(path) == current.get(path.name)
                        except OSError:
                            return False

                    result = batch_store.import_all_pending_detailed(
                        source, root, batch, names=stable, ready=ready
                    )
                    if result.imported_count:
                        self.refresh(batch)
                    self._set_error(
                        f"{result.failed_count} files could not be imported; retrying."
                        if result.failed_count
                        else "",
                        paused=False,
                    )
                    self.retry_after = time.monotonic() + 10 if result.failed_count else 0.0
                elif not current:
                    self._set_error("", paused=False)
            except (OSError, ValueError) as exc:
                self.observed = {}
                self._set_error(str(exc) or "Automatic import paused.", paused=True)

    def manual(self, batch: str):
        with self.lock:
            source, root, _, _ = self.paths()
            _validate_source(source, root)
            result = batch_store.import_all_pending_detailed(source, root, batch)
            if result.imported_count:
                self.refresh(batch)
            return result

    def status(self):
        # Status uses a separate short-held lock, never the transfer lock.
        _, _, _, enabled = self.paths()
        with self._status_lock:
            return {
                "auto_import_enabled": enabled,
                "auto_import_error": self.error,
                "auto_import_paused": self.paused,
                "auto_import_failure": self.failure,
            }
