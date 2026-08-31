"""Prompt history indexing for PNG generation metadata."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .batch_store import BATCH_FOLDERS, _validate_name, get_batches
from .png_metadata import LORA_RE, extract_png_metadata

_LOCK = threading.RLock()


def _normalize_prompt(text: str | None) -> str:
    stripped = LORA_RE.sub("", text or "")
    return " ".join(stripped.split()).lower()


def _prompt_hash(prompt: str, negative: str) -> str:
    return hashlib.sha256(f"{prompt}|||{negative}".encode("utf-8")).hexdigest()[:12]


def _cache_path(batches_dir: Path, batch: str) -> Path:
    _validate_name(batch, "batch name")
    return Path(batches_dir) / batch / "prompt-history.json"


def _resolved_batch(batches_dir: Path, batch: str) -> tuple[Path, Path, Path]:
    root = Path(batches_dir).resolve()
    batch_dir = Path(batches_dir) / batch
    if batch_dir.is_symlink() or not batch_dir.is_dir():
        raise ValueError("Unsafe prompt history path")
    resolved_batch = batch_dir.resolve()
    try:
        resolved_batch.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("Unsafe prompt history path") from exc
    return root, batch_dir, resolved_batch


def _safe_stage(root: Path, batch_dir: Path, resolved_batch: Path, folder: str) -> Path | None:
    stage = batch_dir / folder
    if not stage.exists() and not stage.is_symlink():
        return None
    try:
        if stage.is_symlink() or not stage.is_dir():
            raise ValueError("Unsafe prompt history path")
        resolved = stage.resolve()
        resolved.relative_to(root)
        resolved.relative_to(resolved_batch)
    except (OSError, ValueError) as exc:
        raise ValueError("Unsafe prompt history path") from exc
    return resolved


def _cache_is_safe(root: Path, resolved_batch: Path, cache_path: Path) -> bool:
    """Check a cache path is regular and resolves within its real batch."""
    try:
        if cache_path.is_symlink():
            return False
        # Walk parent chain for intermediate symlinks
        current = cache_path.parent
        while current != root and current != current.parent:
            if current.is_symlink():
                return False
            current = current.parent
        # If the path already exists it must be a regular file
        if cache_path.exists() and not cache_path.is_file():
            return False
        resolved = cache_path.resolve()
        resolved.relative_to(root)
        resolved.relative_to(resolved_batch)
        return True
    except (OSError, ValueError):
        return False


def _png_fingerprint(path: Path) -> dict[str, int | str]:
    """Return a conservative identity/size/mtime fingerprint for a PNG."""
    stat = path.stat()
    return {
        "name": path.name,
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _png_fingerprint_from_entry(entry: os.DirEntry[str]) -> dict[str, int | str]:
    stat = entry.stat(follow_symlinks=False)
    return {
        "name": entry.name,
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _png_fingerprint_key(fingerprint: Any) -> str | None:
    if not isinstance(fingerprint, dict):
        return None
    if not isinstance(fingerprint.get("name"), str) or not all(
        isinstance(fingerprint.get(key), int) for key in ("device", "inode", "size", "mtime_ns")
    ):
        return None
    return json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))


def _enumerate_pngs(
    batches_dir: Path, batch: str
) -> list[tuple[int, str, Path, dict[str, int | str]]]:
    """Enumerate safe PNGs and capture their fingerprints before extraction."""
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    files: list[tuple[int, str, Path, dict[str, int | str]]] = []
    for folder in BATCH_FOLDERS:
        folder_dir = _safe_stage(root, batch_dir, resolved_batch, folder)
        if folder_dir is None:
            continue
        try:
            with os.scandir(folder_dir) as iterator:
                entries = list(iterator)
        except OSError:
            raise ValueError("Unsafe prompt history path") from None
        for entry in entries:
            if Path(entry.name).suffix.lower() != ".png":
                continue
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    raise ValueError("Unsafe prompt history path")
                fingerprint = _png_fingerprint_from_entry(entry)
                resolved_path = folder_dir / entry.name
            except ValueError as exc:
                raise ValueError("Unsafe prompt history path") from exc
            except OSError:
                continue
            files.append((int(fingerprint["mtime_ns"]), folder, resolved_path, fingerprint))
    files.sort(key=lambda item: item[0])
    return files


def _png_stage_mtimes(batches_dir: Path, batch: str) -> dict[str, int | None]:
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    mtimes: dict[str, int | None] = {}
    for folder in BATCH_FOLDERS:
        folder_dir = _safe_stage(root, batch_dir, resolved_batch, folder)
        mtimes[folder] = None if folder_dir is None else folder_dir.stat().st_mtime_ns
    return mtimes


def _png_manifest_signature(
    files: list[tuple[int, str, Path, dict[str, int | str]]],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (folder, path.name, _png_fingerprint_key(fingerprint) or "")
            for _mtime, folder, path, fingerprint in files
        )
    )


def _save_cache(batches_dir: Path, batch: str, data: dict[str, Any]) -> None:
    with _LOCK:
        path = _cache_path(batches_dir, batch)
        root, _batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        if not _cache_is_safe(root, resolved_batch, path) or not _cache_is_safe(
            root, resolved_batch, tmp_path
        ):
            raise ValueError("Unsafe prompt history path")
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def count_prompt_index_folders(batches_dir: Path, batch: str) -> dict[str, int]:
    """Return the current per-folder PNG counts eligible for prompt indexing."""
    _validate_name(batch, "batch name")
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    counts = {folder: 0 for folder in BATCH_FOLDERS}
    for folder in BATCH_FOLDERS:
        folder_dir = _safe_stage(root, batch_dir, resolved_batch, folder)
        if folder_dir is None:
            continue
        for path in folder_dir.iterdir():
            if path.suffix.lower() != ".png":
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Unsafe prompt history path")
                resolved_path = path.resolve()
                resolved_path.relative_to(folder_dir)
                if resolved_path.parent != folder_dir:
                    raise ValueError("Unsafe prompt history path")
            except (OSError, ValueError) as exc:
                raise ValueError("Unsafe prompt history path") from exc
            counts[folder] += 1
    return counts


def count_prompt_index_images(batches_dir: Path, batch: str) -> int:
    """Return the current count of PNG files eligible for prompt indexing."""
    return sum(count_prompt_index_folders(batches_dir, batch).values())


def prompt_index_is_stale(index: dict[str, Any], current_counts: dict[str, int]) -> bool:
    """Return whether a cached index no longer matches current per-folder counts.

    Compares the index's recorded per-folder counts against the filesystem so a
    same-total move between folders is detected as stale. Legacy indexes without
    ``folder_counts`` fall back to the recorded total image count.
    """
    stored = index.get("folder_counts")
    if stored is None:
        return sum(current_counts.values()) != index.get("image_count")
    return current_counts != stored


def build_prompt_index(batches_dir: Path, batch: str) -> dict[str, Any]:
    """Build and cache a prompt index for one batch."""
    _validate_name(batch, "batch name")
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    cache_path = _cache_path(batches_dir, batch)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    if not _cache_is_safe(root, resolved_batch, cache_path) or not _cache_is_safe(
        root, resolved_batch, tmp_path
    ):
        raise ValueError("Unsafe prompt history path")
    files = _enumerate_pngs(batches_dir, batch)
    initial_stage_mtimes = _png_stage_mtimes(batches_dir, batch)
    prior = load_prompt_index(batches_dir, batch)
    prior_by_fingerprint: dict[str, list[dict[str, Any]]] = {}
    if prior is not None:
        for record in prior.get("files", []):
            if not isinstance(record, dict):
                continue
            key = _png_fingerprint_key(record.get("fingerprint"))
            if (
                key is not None
                and isinstance(record.get("filename"), str)
                and record.get("folder") in BATCH_FOLDERS
                and isinstance(record.get("prompt"), str)
                and isinstance(record.get("negative_prompt"), str)
            ):
                prior_by_fingerprint.setdefault(key, []).append(record)
    current_counts: dict[str, int] = {}
    for _mtime, _folder, _path, fingerprint in files:
        key = _png_fingerprint_key(fingerprint)
        if key is not None:
            current_counts[key] = current_counts.get(key, 0) + 1

    groups: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    reused_count = 0
    scanned_count = 0
    for _mtime, folder, path, fingerprint in files:
        key = _png_fingerprint_key(fingerprint)
        candidates = prior_by_fingerprint.get(key, []) if key is not None else []
        if key is not None and len(candidates) == 1 and current_counts.get(key) == 1:
            record = dict(candidates[0])
            record["filename"] = path.name
            record["folder"] = folder
            record["fingerprint"] = fingerprint
            prompt = record["prompt"]
            negative = record["negative_prompt"]
            reused_count += 1
        else:
            try:
                meta = extract_png_metadata(path)
            except OSError:
                raise ValueError("Prompt history source changed during build") from None
            params = meta.get("parameters", {}) or {}
            prompt = (params.get("prompt") or "").strip()
            negative = (params.get("negative_prompt") or "").strip()
            record = {
                "filename": path.name,
                "folder": folder,
                "fingerprint": fingerprint,
                "prompt": prompt,
                "negative_prompt": negative,
            }
            scanned_count += 1
        records.append(record)
        if not prompt:
            continue
        normalized = _normalize_prompt(prompt)
        normalized_negative = _normalize_prompt(negative)
        key = _prompt_hash(normalized, normalized_negative)
        image_entry = {"filename": path.name, "folder": folder}
        if key not in groups:
            groups[key] = {
                "hash": key,
                "prompt": prompt,
                "normalized": normalized,
                "negative_prompt": negative,
                "count": 0,
                "images": [],
                "first_image": image_entry,
            }
        groups[key]["count"] += 1
        groups[key]["images"].append(image_entry)

    final_files = _enumerate_pngs(batches_dir, batch)
    if _png_manifest_signature(files) != _png_manifest_signature(
        final_files
    ) or initial_stage_mtimes != _png_stage_mtimes(batches_dir, batch):
        raise ValueError("Prompt history source changed during build")

    prompts = sorted(groups.values(), key=lambda item: item["count"], reverse=True)
    folder_counts = {folder: 0 for folder in BATCH_FOLDERS}
    for _mtime, folder, _path, _fingerprint in files:
        folder_counts[folder] = folder_counts.get(folder, 0) + 1
    index = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "batch": batch,
        "image_count": len(files),
        "prompt_count": len(prompts),
        "folder_counts": folder_counts,
        "prompts": prompts,
        "files": records,
        "reused_count": reused_count,
        "scanned_count": scanned_count,
        "changed_count": scanned_count,
    }
    _save_cache(batches_dir, batch, index)
    return index


def load_prompt_index(batches_dir: Path, batch: str) -> dict[str, Any] | None:
    """Load a cached prompt index.

    Safety: rejects symlinked cache files, non-regular cache entries, and
    cache paths whose resolved location escapes the batch root.
    """
    with _LOCK:
        _validate_name(batch, "batch name")
        path = _cache_path(batches_dir, batch)
        try:
            root, _batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
        except ValueError:
            return None
        if not _cache_is_safe(root, resolved_batch, path):
            return None
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None


def load_all_prompt_indices(batches_dir: Path) -> dict[str, Any]:
    """Load cached prompt indices for every batch.

    Safety: batches whose caches fail the safety checks are silently omitted.
    """
    batches = {}
    total = 0
    for batch in get_batches(batches_dir):
        index = load_prompt_index(batches_dir, batch)
        if index is None:
            continue
        batches[batch] = index
        total += int(index.get("prompt_count") or 0)
    return {"batches": batches, "total_prompts": total}
