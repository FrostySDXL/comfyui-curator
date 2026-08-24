"""Background immutable folder snapshots for paged media browsing."""

from __future__ import annotations

import hashlib
import random
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .batch_store import VIEWABLE_MEDIA_EXTENSIONS, media_kind, media_mime

DEFAULT_PAGE_SIZE = 256
MAX_PAGE_SIZE = 512


@dataclass(frozen=True, slots=True)
class FolderItem:
    name: str
    size: int
    modified_ns: int
    media_kind: str
    mime: str

    def payload(self, index: int, favorite: bool = False) -> dict[str, Any]:
        return {
            "index": index,
            "name": self.name,
            "size": self.size,
            "mtime": self.modified_ns,
            "favorite": favorite,
            "media_kind": self.media_kind,
            "mime": self.mime,
        }


@dataclass(frozen=True, slots=True)
class FolderSnapshot:
    revision: str
    items: tuple[FolderItem, ...]
    name_to_index: Mapping[str, int]
    built_at: float


IndexKey = tuple[str, str, str, str]


class FolderIndexService:
    """Build and reconcile immutable folder listings in a bounded worker pool."""

    def __init__(self, *, max_workers: int = 2, reconcile_interval: float = 5.0) -> None:
        self.reconcile_interval = reconcile_interval
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="curator-folder-index"
        )
        self._lock = threading.RLock()
        self._snapshots: dict[IndexKey, FolderSnapshot] = {}
        self._futures: dict[IndexKey, Future[FolderSnapshot]] = {}
        self._directories: dict[IndexKey, Path] = {}
        self._dirty: set[IndexKey] = set()
        self._closed = False

    @staticmethod
    def _key(batch: str, folder: str, sort_by: str, order: str) -> IndexKey:
        return batch, folder, sort_by, order

    def _scan_directory(self, directory: Path, sort_by: str, order: str) -> tuple[FolderItem, ...]:
        items: list[FolderItem] = []
        try:
            entries = directory.iterdir()
        except OSError:
            return ()
        for path in entries:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if path.suffix.lower() not in VIEWABLE_MEDIA_EXTENSIONS:
                    continue
                stat = path.stat()
            except OSError:
                continue
            kind = media_kind(path)
            mime = media_mime(path)
            if kind is None or mime is None:
                continue
            items.append(FolderItem(path.name, stat.st_size, stat.st_mtime_ns, kind, mime))
        reverse = order == "desc"
        if sort_by == "name":
            items.sort(key=lambda item: item.name.lower(), reverse=reverse)
        elif sort_by == "shuffle":
            seed = "\0".join(sorted(item.name for item in items))
            random.Random(seed).shuffle(items)
            if reverse:
                items.reverse()
        else:
            items.sort(key=lambda item: (item.modified_ns, item.name.lower()), reverse=reverse)
        return tuple(items)

    @staticmethod
    def _snapshot_for(items: tuple[FolderItem, ...]) -> FolderSnapshot:
        digest = hashlib.blake2b(digest_size=12)
        for item in items:
            digest.update(item.name.encode("utf-8", errors="surrogatepass"))
            digest.update(b"\0")
            digest.update(str(item.size).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(item.modified_ns).encode("ascii"))
            digest.update(b"\0")
        lookup = MappingProxyType({item.name: index for index, item in enumerate(items)})
        return FolderSnapshot(digest.hexdigest(), items, lookup, time.monotonic())

    def _build(self, directory: Path, sort_by: str, order: str) -> FolderSnapshot:
        return self._snapshot_for(self._scan_directory(directory, sort_by, order))

    def _finish_build(self, key: IndexKey, future: Future[FolderSnapshot]) -> None:
        try:
            snapshot = future.result()
        except Exception:
            with self._lock:
                self._futures.pop(key, None)
            return
        with self._lock:
            if self._futures.get(key) is future:
                self._snapshots[key] = snapshot
                self._futures.pop(key, None)
                if key in self._dirty:
                    self._dirty.discard(key)
                    directory = self._directories.get(key)
                    if directory is not None:
                        self._schedule(key, directory)

    def _schedule(self, key: IndexKey, directory: Path) -> None:
        if self._closed or key in self._futures:
            return
        self._directories[key] = Path(directory)
        future = self._executor.submit(self._build, Path(directory), key[2], key[3])
        self._futures[key] = future
        future.add_done_callback(lambda completed: self._finish_build(key, completed))

    @staticmethod
    def _metadata(snapshot: FolderSnapshot) -> dict[str, Any]:
        return {
            "status": "ready",
            "revision": snapshot.revision,
            "count": len(snapshot.items),
        }

    def request_snapshot(
        self, batch: str, folder: str, directory: Path, sort_by: str, order: str
    ) -> dict[str, Any]:
        key = self._key(batch, folder, sort_by, order)
        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is None:
                self._schedule(key, directory)
                return {"status": "building"}
            if time.monotonic() - snapshot.built_at >= self.reconcile_interval:
                self._schedule(key, directory)
            return self._metadata(snapshot)

    def poll(
        self,
        batch: str,
        folder: str,
        directory: Path,
        sort_by: str,
        order: str,
        revision: str | None,
    ) -> dict[str, Any]:
        result = self.request_snapshot(batch, folder, directory, sort_by, order)
        if result["status"] != "ready":
            return result
        return {
            "status": "ready",
            "changed": result["revision"] != revision,
            "revision": result["revision"],
            "count": result["count"],
        }

    def page(
        self,
        batch: str,
        folder: str,
        sort_by: str,
        order: str,
        revision: str,
        offset: int,
        limit: int = DEFAULT_PAGE_SIZE,
        favorites: set[str] | None = None,
    ) -> dict[str, Any] | None:
        key = self._key(batch, folder, sort_by, order)
        with self._lock:
            snapshot = self._snapshots.get(key)
        if snapshot is None or snapshot.revision != revision:
            return None
        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), MAX_PAGE_SIZE)
        end = min(len(snapshot.items), safe_offset + safe_limit)
        favorite_names = favorites or set()
        return {
            "status": "ready",
            "revision": snapshot.revision,
            "offset": safe_offset,
            "count": len(snapshot.items),
            "items": [
                item.payload(index, item.name in favorite_names)
                for index, item in enumerate(snapshot.items[safe_offset:end], start=safe_offset)
            ],
        }

    def index_of(
        self, batch: str, folder: str, sort_by: str, order: str, revision: str, name: str
    ) -> int | None:
        key = self._key(batch, folder, sort_by, order)
        with self._lock:
            snapshot = self._snapshots.get(key)
        if snapshot is None or snapshot.revision != revision:
            return None
        return snapshot.name_to_index.get(name)

    def names_for_revision(
        self, batch: str, folder: str, sort_by: str, order: str, revision: str
    ) -> tuple[str, ...] | None:
        key = self._key(batch, folder, sort_by, order)
        with self._lock:
            snapshot = self._snapshots.get(key)
        if snapshot is None or snapshot.revision != revision:
            return None
        return tuple(item.name for item in snapshot.items)

    def invalidate(self, batch: str, *folders: str) -> None:
        folder_set = set(folders)
        with self._lock:
            for key in list(self._snapshots):
                if key[0] == batch and (not folder_set or key[1] in folder_set):
                    self._snapshots.pop(key, None)

    def refresh(self, batch: str, *folders: str) -> None:
        """Schedule mutation reconciliation now while keeping the last snapshot readable."""
        folder_set = set(folders)
        with self._lock:
            keys = [
                key
                for key in set(self._directories) | set(self._snapshots)
                if key[0] == batch and (not folder_set or key[1] in folder_set)
            ]
            for key in keys:
                directory = self._directories.get(key)
                if directory is None:
                    continue
                if key in self._futures:
                    self._dirty.add(key)
                else:
                    self._schedule(key, directory)

    def wait_until_ready(
        self,
        batch: str,
        folder: str,
        sort_by: str,
        order: str,
        *,
        timeout: float,
    ) -> bool:
        key = self._key(batch, folder, sort_by, order)
        with self._lock:
            future = self._futures.get(key)
        if future is None:
            with self._lock:
                return key in self._snapshots
        try:
            future.result(timeout=timeout)
        except Exception:
            return False
        self._finish_build(key, future)
        with self._lock:
            return key in self._snapshots

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


@dataclass(frozen=True, slots=True)
class BulkMoveOperation:
    batch: str
    source: str
    destination: str
    names: tuple[str, ...]
    expires_at: float


class BulkMoveOperationStore:
    """Short-lived server-side undo records for revision-selected moves."""

    def __init__(self, ttl: float = 30.0, max_operations: int = 16) -> None:
        self.ttl = ttl
        self.max_operations = max_operations
        self._lock = threading.RLock()
        self._operations: dict[str, BulkMoveOperation] = {}

    def record(self, batch: str, source: str, destination: str, names: list[str]) -> str:
        token = uuid.uuid4().hex
        now = time.monotonic()
        with self._lock:
            self._operations = {
                key: value for key, value in self._operations.items() if value.expires_at > now
            }
            while len(self._operations) >= self.max_operations:
                self._operations.pop(next(iter(self._operations)))
            self._operations[token] = BulkMoveOperation(
                batch, source, destination, tuple(names), now + self.ttl
            )
        return token

    def pop(self, token: str) -> BulkMoveOperation | None:
        with self._lock:
            operation = self._operations.pop(token, None)
        if operation is None or operation.expires_at <= time.monotonic():
            return None
        return operation
