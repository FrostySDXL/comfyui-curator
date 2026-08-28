"""Durable, filesystem-safe history for operator initiated moves."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from . import batch_store
from .sidecar_metadata import json_sidecar_candidates, sidecar_destination

MAX_OPERATIONS = 100
RETENTION_DAYS = 30
# Native snapshot selections can contain tens of thousands of media members.
# This bounded parser guard remains large enough for those valid journals.
MAX_HISTORY_BYTES = 256 * 1024 * 1024
MAX_ITEMS_PER_OPERATION = 100_000
_VALID_STATUSES = {"pending", "available", "undo_pending", "partial", "undone", "blocked"}
_OPERATION_KEYS = {
    "id",
    "batch",
    "source",
    "destination",
    "created_at",
    "status",
    "count",
    "items",
    "error",
    "restored",
}
_ITEM_KEYS = {"name", "src_hash", "sidecar", "sidecar_hash"}


@dataclass(frozen=True)
class MoveResult:
    operation_id: str | None
    moved: int
    skipped: int
    remaining: int = 0
    status: str = "available"
    error: str | None = None
    names: tuple[str, ...] = ()


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _root_lock(root: Path) -> threading.RLock:
    key = str(Path(root).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_hash(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class MoveHistory:
    """Persist and undo manual moves under one batches-root hidden directory."""

    def __init__(
        self,
        batches_root: Path,
        *,
        max_operations: int = MAX_OPERATIONS,
        retention_days: int = RETENTION_DAYS,
    ) -> None:
        self.root = Path(batches_root)
        self.dir = self.root / ".curator-undo"
        self.path = self.dir / "history.json"
        self.max_operations = max_operations
        self.retention_days = retention_days
        self._lock = _root_lock(self.root)

    def _validate_storage(self, *, create: bool = False) -> None:
        root = self.root.absolute()
        # Check lexical ancestors, not only resolved paths, to prevent a
        # symlinked parent from redirecting mkdir/open operations.
        for parent in (root, *root.parents):
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise OSError("Unsafe move history storage")
        if not root.exists() and not create:
            return
        if create and not root.exists():
            root.mkdir(parents=True)
        if root.is_symlink() or not root.is_dir():
            raise OSError("Unsafe move history storage")
        if self.dir.exists() or self.dir.is_symlink():
            if self.dir.is_symlink() or not self.dir.is_dir():
                raise OSError("Unsafe move history storage")
        elif create:
            self.dir.mkdir()
        elif self.path.exists() or self.path.is_symlink():
            raise OSError("Unsafe move history storage")
        if self.dir.exists() and (self.dir.is_symlink() or not self.dir.is_dir()):
            raise OSError("Unsafe move history storage")
        if self.path.exists() or self.path.is_symlink():
            if self.path.is_symlink() or not self.path.is_file():
                raise OSError("Unsafe move history storage")

    @staticmethod
    def _validate_item(item: object) -> None:
        if not isinstance(item, dict) or set(item) != _ITEM_KEYS:
            raise OSError("Invalid move history")
        if not isinstance(item["name"], str):
            raise OSError("Invalid move history")
        try:
            batch_store._validate_name(item["name"], "file name")
        except (TypeError, ValueError) as exc:
            raise OSError("Invalid move history") from exc
        if not _is_hash(item["src_hash"]):
            raise OSError("Invalid move history")
        sidecar, sidecar_hash = item["sidecar"], item["sidecar_hash"]
        if sidecar is None:
            if sidecar_hash is not None:
                raise OSError("Invalid move history")
        elif not isinstance(sidecar, str) or not _is_hash(sidecar_hash):
            raise OSError("Invalid move history")
        else:
            try:
                batch_store._validate_name(sidecar, "sidecar name")
            except (TypeError, ValueError) as exc:
                raise OSError("Invalid move history") from exc
            if sidecar not in {f"{item['name']}.json", f"{Path(item['name']).stem}.json"}:
                raise OSError("Invalid move history")

    @classmethod
    def _validate_operation(cls, item: object) -> None:
        required = {
            "id",
            "batch",
            "source",
            "destination",
            "created_at",
            "status",
            "count",
            "items",
        }
        if (
            not isinstance(item, dict)
            or not _OPERATION_KEYS.issuperset(item)
            or not required.issubset(item)
        ):
            raise OSError("Invalid move history")
        if not isinstance(item["items"], list):
            raise OSError("Invalid move history")
        for key in ("id", "batch", "source", "destination", "created_at", "status"):
            if not isinstance(item[key], str) or not item[key] or len(item[key]) > 512:
                raise OSError("Invalid move history")
        try:
            batch_store._validate_name(item["batch"], "batch name")
            batch_store._validate_name(item["source"], "source folder")
            batch_store._validate_name(item["destination"], "destination folder")
        except (TypeError, ValueError) as exc:
            raise OSError("Invalid move history") from exc
        if (
            item["source"] not in batch_store.BATCH_FOLDERS
            or item["destination"] not in batch_store.BATCH_FOLDERS
        ):
            raise OSError("Invalid move history")
        if item["status"] not in _VALID_STATUSES or not _is_int(item["count"]):
            raise OSError("Invalid move history")
        if item["count"] < 0 or len(item["items"]) > MAX_ITEMS_PER_OPERATION:
            raise OSError("Invalid move history")
        if "restored" in item and (not _is_int(item["restored"]) or item["restored"] < 0):
            raise OSError("Invalid move history")
        restored = item.get("restored", 0)
        if restored + len(item["items"]) != item["count"]:
            raise OSError("Invalid move history")
        if item["status"] == "available" and restored != 0:
            raise OSError("Invalid move history")
        if item["status"] == "undone" and item["items"]:
            raise OSError("Invalid move history")
        if item.get("error") is not None and (
            not isinstance(item["error"], str) or len(item["error"]) > 2048
        ):
            raise OSError("Invalid move history")
        try:
            created = datetime.fromisoformat(item["created_at"])
        except ValueError as exc:
            raise OSError("Invalid move history") from exc
        if created.tzinfo is None or created.utcoffset() is None:
            raise OSError("Invalid move history")
        for member in item["items"]:
            cls._validate_item(member)

    def _load(self) -> list[dict]:
        self._validate_storage()
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size > MAX_HISTORY_BYTES:
            raise OSError("Invalid move history")
        with self.path.open("rb") as stream:
            payload = stream.read(MAX_HISTORY_BYTES + 1)
        if len(payload) > MAX_HISTORY_BYTES:
            raise OSError("Invalid move history")
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OSError("Invalid move history") from exc
        if not isinstance(data, list) or len(data) > self.max_operations * 2:
            raise OSError("Invalid move history")
        for item in data:
            self._validate_operation(item)
        return data

    def _save(self, operations: list[dict]) -> None:
        self._validate_storage(create=True)
        if len(operations) > self.max_operations * 2:
            raise OSError("Move history has too many operations")
        for operation in operations:
            self._validate_operation(operation)
        payload = json.dumps(operations, indent=2, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_HISTORY_BYTES:
            raise OSError("Move history is too large")
        temporary: Path | None = None
        fd: int | None = None
        try:
            for _ in range(8):
                candidate = self.dir / f".history-{uuid.uuid4().hex}.tmp"
                try:
                    fd = os.open(str(candidate), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    continue
                temporary = candidate
                break
            if fd is None or temporary is None:
                raise OSError("Could not create move history temporary file")
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(self.path))
            temporary = None
            try:
                dir_fd = os.open(str(self.dir), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        finally:
            if fd is not None:
                os.close(fd)
            if temporary is not None:
                try:
                    if not temporary.is_symlink() and temporary.exists():
                        temporary.unlink()
                except OSError:
                    pass

    def _prune(self, operations: list[dict]) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        kept = []
        for item in operations:
            try:
                created = datetime.fromisoformat(item["created_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if created >= cutoff:
                kept.append(item)
        return kept[: self.max_operations]

    def _operation_dirs(
        self, op: dict, *, allow_missing_destination: bool = False
    ) -> tuple[Path, Path, Path]:
        try:
            batch_store._validate_name(op["batch"], "batch name")
            batch_store._validate_name(op["source"], "source folder")
            batch_store._validate_name(op["destination"], "destination folder")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Unsafe path") from exc
        if (
            op["source"] not in batch_store.BATCH_FOLDERS
            or op["destination"] not in batch_store.BATCH_FOLDERS
        ):
            raise ValueError("Unsafe path")
        root = self.root.absolute()
        batch = root / op["batch"]
        source_dir, destination_dir = batch / op["source"], batch / op["destination"]
        for path in (root, batch, source_dir):
            if path.is_symlink() or not path.is_dir():
                raise ValueError("Unsafe path")
            try:
                path.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError("Unsafe path") from exc
        if (
            destination_dir.is_symlink()
            or (not destination_dir.exists() and not allow_missing_destination)
            or (destination_dir.exists() and not destination_dir.is_dir())
        ):
            raise ValueError("Unsafe path")
        if destination_dir.exists():
            try:
                destination_dir.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError("Unsafe path") from exc
        return batch, source_dir, destination_dir

    def _validate_paths(
        self, batch: str, source: str, destination: str, name: str
    ) -> tuple[Path, Path]:
        _batch, source_dir, destination_dir = self._operation_dirs(
            {"batch": batch, "source": source, "destination": destination},
            allow_missing_destination=True,
        )
        try:
            batch_store._validate_name(name, "file name")
        except (TypeError, ValueError) as exc:
            raise ValueError("Unsafe path") from exc
        src, dst = source_dir / name, destination_dir / name
        if src.is_symlink() or not src.is_file() or dst.is_symlink() or dst.exists():
            raise ValueError("Source unavailable or destination occupied")
        return src, dst

    def _validate_undo_paths(self, op: dict, name: str) -> tuple[Path, Path]:
        _batch, original_dir, current_dir = self._operation_dirs(op)
        try:
            batch_store._validate_name(name, "file name")
        except (TypeError, ValueError) as exc:
            raise ValueError("Unsafe path") from exc
        return current_dir / name, original_dir / name

    @staticmethod
    def _sidecar_path(media: Path, name: str | None) -> Path | None:
        return media.with_name(name) if name else None

    @classmethod
    def _member_exact(
        cls,
        media: Path,
        digest: str,
        sidecar_name: str | None,
        sidecar_hash: str | None,
        *,
        allow_unselected_sidecar: bool = False,
    ) -> bool:
        try:
            if media.is_symlink() or not media.is_file() or _digest(media) != digest:
                return False
            expected = cls._sidecar_path(media, sidecar_name)
            for candidate in json_sidecar_candidates(media):
                if candidate == expected:
                    if (
                        candidate.is_symlink()
                        or not candidate.is_file()
                        or _digest(candidate) != sidecar_hash
                    ):
                        return False
                elif not allow_unselected_sidecar and (
                    candidate.exists() or candidate.is_symlink()
                ):
                    return False
            return True
        except OSError:
            return False

    @classmethod
    def _member_absent(cls, media: Path, selected_sidecar: str | None = None) -> bool:
        try:
            if media.exists() or media.is_symlink():
                return False
            if selected_sidecar is None:
                return all(
                    not candidate.exists() and not candidate.is_symlink()
                    for candidate in json_sidecar_candidates(media)
                )
            return all(
                candidate.name != selected_sidecar
                or (not candidate.exists() and not candidate.is_symlink())
                for candidate in json_sidecar_candidates(media)
            )
        except OSError:
            return False

    @staticmethod
    def _remaining_error(items: list[dict], reason: str) -> str:
        names = [item["name"] for item in items[:3]]
        detail = ", ".join(names)
        if len(items) > len(names):
            detail += f" (+{len(items) - len(names)} more)"
        return f"{reason}: {detail}"[:2048]

    def _reconcile(self, operations: list[dict]) -> bool:
        """Reconcile interrupted intents using exact media+sidecar identity."""
        changed = False
        for op in operations:
            before = json.dumps(op, sort_keys=True)
            try:
                _batch, source_dir, destination_dir = self._operation_dirs(
                    op, allow_missing_destination=op["status"] == "pending"
                )
            except (OSError, ValueError):
                # Preserve the receipt and its members. A transient symlink,
                # missing stage, or operator conflict must remain retryable;
                # a status GET must never discard recovery evidence.
                continue
            if op["status"] == "pending":
                kept: list[dict] = []
                moved = 0
                ambiguous = False
                for item in op["items"]:
                    source = source_dir / item["name"]
                    destination = destination_dir / item["name"]
                    src_exact = self._member_exact(
                        source,
                        item["src_hash"],
                        item["sidecar"],
                        item["sidecar_hash"],
                        allow_unselected_sidecar=True,
                    )
                    dst_exact = self._member_exact(
                        destination, item["src_hash"], item["sidecar"], item["sidecar_hash"]
                    )
                    if dst_exact and self._member_absent(source, item["sidecar"]):
                        kept.append(item)
                        moved += 1
                    elif src_exact and self._member_absent(destination, item["sidecar"]):
                        continue
                    else:
                        kept.append(item)
                        ambiguous = True
                op["items"] = kept
                op["count"] = len(kept)
                if moved:
                    op["status"] = "partial" if ambiguous else "available"
                    op["error"] = (
                        self._remaining_error(kept, "Move interrupted; verify remaining members")
                        if ambiguous
                        else None
                    )
                else:
                    op["status"] = "blocked"
                    op["error"] = "Move did not finish"
            elif op["status"] == "undo_pending":
                remaining: list[dict] = []
                for item in op["items"]:
                    source = source_dir / item["name"]
                    destination = destination_dir / item["name"]
                    source_exact = self._member_exact(
                        source,
                        item["src_hash"],
                        item["sidecar"],
                        item["sidecar_hash"],
                        allow_unselected_sidecar=True,
                    )
                    if source_exact and self._member_absent(destination, item["sidecar"]):
                        continue
                    remaining.append(item)
                op["items"] = remaining
                op["restored"] = op["count"] - len(remaining)
                op["status"] = "undone" if not remaining else "partial"
                op["error"] = (
                    None
                    if not remaining
                    else self._remaining_error(remaining, "Some files could not be restored")
                )
            changed |= before != json.dumps(op, sort_keys=True)
        return changed

    def move(self, batch: str, source: str, destination: str, names: list[str]) -> MoveResult:
        with self._lock:
            if source == destination:
                return MoveResult(
                    None,
                    0,
                    len(names),
                    status="blocked",
                    error="Source and destination are identical",
                )
            operations = self._prune(self._load())
            if self._reconcile(operations):
                self._save(operations)
            valid: list[dict] = []
            skipped = 0
            seen: set[str] = set()
            for name in names:
                try:
                    if name in seen:
                        raise ValueError("Duplicate filename")
                    seen.add(name)
                    src, dst = self._validate_paths(batch, source, destination, name)
                    sidecar = next(
                        (
                            p
                            for p in json_sidecar_candidates(src)
                            if p.is_file() and not p.is_symlink()
                        ),
                        None,
                    )
                    side_dst = sidecar_destination(src, dst, sidecar) if sidecar else None
                    if side_dst and (side_dst.exists() or side_dst.is_symlink()):
                        raise ValueError("Sidecar destination occupied")
                    valid.append(
                        {
                            "name": name,
                            "src_hash": _digest(src),
                            "sidecar": sidecar.name if sidecar else None,
                            "sidecar_hash": _digest(sidecar) if sidecar else None,
                        }
                    )
                except (OSError, ValueError):
                    skipped += 1
            if not valid:
                return MoveResult(None, 0, skipped, status="blocked")
            operation = {
                "id": uuid.uuid4().hex,
                "batch": batch,
                "source": source,
                "destination": destination,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                "count": len(valid),
                "items": valid,
            }
            self._save(self._prune([operation] + operations))
            moved_items: list[dict] = []
            uncertain_items: list[dict] = []
            for item in valid:
                src = self.root / batch / source / item["name"]
                dst = self.root / batch / destination / item["name"]
                if batch_store.move_image(src, dst, no_overwrite=True):
                    moved_items.append(item)
                else:
                    skipped += 1
                    # A false return can still mean a pair transfer failed
                    # after one member was installed. Keep such an uncertain
                    # member in the journal rather than claiming it never
                    # moved; only a fully intact source + empty destination
                    # is a safe no-op to omit.
                    if not self._member_exact(
                        src,
                        item["src_hash"],
                        item["sidecar"],
                        item["sidecar_hash"],
                        allow_unselected_sidecar=True,
                    ) or not self._member_absent(dst, item["sidecar"]):
                        uncertain_items.append(item)
            recorded_items = moved_items + uncertain_items
            operation["items"] = recorded_items
            operation["count"] = len(recorded_items)
            operation["status"] = (
                "partial"
                if moved_items and uncertain_items
                else "available"
                if moved_items
                else "blocked"
            )
            operation["error"] = (
                self._remaining_error(uncertain_items, "Move failed after a partial transfer")
                if uncertain_items
                else None
                if moved_items
                else "Move failed"
            )
            operations = [operation] + [x for x in operations if x.get("id") != operation["id"]]
            self._save(self._prune(operations))
            return MoveResult(
                cast(str, operation["id"]) if recorded_items else None,
                len(moved_items),
                skipped,
                status=cast(str, operation["status"]),
                error=cast(str | None, operation["error"]),
                names=tuple(x["name"] for x in moved_items),
            )

    def list_operations(self) -> list[dict]:
        with self._lock:
            operations = self._prune(self._load())
            self._reconcile(operations)
            newest_available = next(
                (
                    x.get("id")
                    for x in operations
                    if x.get("status") in {"available", "partial"}
                    or (
                        x.get("status") in {"pending", "undo_pending", "blocked"} and x.get("items")
                    )
                ),
                None,
            )
            result = []
            for op in operations:
                remaining = len(op.get("items", []))
                status = op.get("status", "blocked")
                result.append(
                    {
                        "id": op.get("id"),
                        "batch": op.get("batch"),
                        "source": op.get("source"),
                        "destination": op.get("destination"),
                        "count": op.get("count", remaining),
                        "created_at": op.get("created_at"),
                        "status": status,
                        "restored": op.get("restored", 0),
                        "remaining": remaining,
                        "can_undo": status in {"available", "partial"}
                        and op.get("id") == newest_available,
                        "error": op.get("error"),
                    }
                )
            return result

    def undo(self, operation_id: str) -> MoveResult:
        with self._lock:
            operations = self._prune(self._load())
            if self._reconcile(operations):
                self._save(operations)
            op = next((x for x in operations if x.get("id") == operation_id), None)
            if op is None:
                return MoveResult(
                    operation_id,
                    0,
                    0,
                    status="blocked",
                    error="Undo operation expired or not found",
                )
            if op.get("status") == "undone":
                return MoveResult(operation_id, 0, 0, status="undone")
            newest = next(
                (
                    x
                    for x in operations
                    if x.get("status") != "undone"
                    and (x.get("status") in {"available", "partial"} or x.get("items"))
                ),
                None,
            )
            if newest is not op:
                return MoveResult(
                    operation_id,
                    0,
                    len(op.get("items", [])),
                    len(op.get("items", [])),
                    "blocked",
                    "Only newest move can be undone",
                )
            if op.get("status") in {"pending", "undo_pending", "blocked"}:
                return MoveResult(
                    operation_id,
                    0,
                    len(op.get("items", [])),
                    len(op.get("items", [])),
                    "blocked",
                    "Move did not finish",
                )
            op["status"] = "undo_pending"
            self._save(operations)
            moved = skipped = 0
            remaining = []
            failure_reasons: list[str] = []
            for item in op.get("items", []):
                try:
                    current, original = self._validate_undo_paths(op, item["name"])
                    if not self._member_exact(
                        current, item["src_hash"], item["sidecar"], item["sidecar_hash"]
                    ) or not self._member_absent(original, item["sidecar"]):
                        raise ValueError("Moved pair changed or original destination occupied")
                    if not batch_store.move_image(current, original, no_overwrite=True):
                        raise ValueError("Could not restore file")
                    moved += 1
                except (OSError, ValueError):
                    skipped += 1
                    remaining.append(item)
                    failure_reasons.append(item["name"])
            op["items"] = remaining
            op["restored"] = op["count"] - len(remaining)
            op["status"] = "undone" if not remaining else "partial"
            op["error"] = (
                None
                if not remaining
                else self._remaining_error(
                    [{"name": name} for name in failure_reasons],
                    "Some files could not be restored",
                )
            )
            self._save(operations)
            return MoveResult(
                operation_id, moved, skipped, len(remaining), op["status"], op.get("error")
            )
