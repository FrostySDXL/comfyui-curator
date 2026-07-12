"""Prompt history indexing for PNG generation metadata."""

from __future__ import annotations

import hashlib
import json
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


def count_prompt_index_images(batches_dir: Path, batch: str) -> int:
    """Return the current count of PNG files eligible for prompt indexing."""
    _validate_name(batch, "batch name")
    root, batch_dir, resolved_batch = _resolved_batch(batches_dir, batch)
    count = 0
    for folder in BATCH_FOLDERS:
        folder_dir = _safe_stage(root, batch_dir, resolved_batch, folder)
        if folder_dir is None:
            continue
        for path in folder_dir.iterdir():
            if path.suffix.lower() == ".png":
                try:
                    if path.is_symlink() or not path.is_file():
                        raise ValueError("Unsafe prompt history path")
                    resolved_path = path.resolve()
                    resolved_path.relative_to(folder_dir)
                    if resolved_path.parent != folder_dir:
                        raise ValueError("Unsafe prompt history path")
                except (OSError, ValueError) as exc:
                    raise ValueError("Unsafe prompt history path") from exc
                count += 1
    return count


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
    files = []
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
                files.append((path.stat().st_mtime, folder, resolved_path))
            except ValueError as exc:
                raise ValueError("Unsafe prompt history path") from exc
            except OSError:
                continue
    files.sort(key=lambda item: item[0])

    groups: dict[str, dict[str, Any]] = {}
    for _mtime, folder, path in files:
        meta = extract_png_metadata(path)
        params = meta.get("parameters", {}) or {}
        prompt = (params.get("prompt") or "").strip()
        negative = (params.get("negative_prompt") or "").strip()
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

    prompts = sorted(groups.values(), key=lambda item: item["count"], reverse=True)
    index = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "batch": batch,
        "image_count": len(files),
        "prompt_count": len(prompts),
        "prompts": prompts,
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
