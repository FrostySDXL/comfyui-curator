"""Prompt history indexing for PNG generation metadata."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from image_curator.batch_store import BATCH_FOLDERS, _validate_name, get_batches
from image_curator.png_metadata import LORA_RE, extract_png_metadata

_LOCK = threading.RLock()


def _normalize_prompt(text: str | None) -> str:
    stripped = LORA_RE.sub("", text or "")
    return " ".join(stripped.split()).lower()


def _prompt_hash(prompt: str, negative: str) -> str:
    return hashlib.sha256(f"{prompt}|||{negative}".encode("utf-8")).hexdigest()[:12]


def _cache_path(batches_dir: Path, batch: str) -> Path:
    _validate_name(batch, "batch name")
    return Path(batches_dir) / batch / "prompt-history.json"


def _save_cache(batches_dir: Path, batch: str, data: dict[str, Any]) -> None:
    with _LOCK:
        path = _cache_path(batches_dir, batch)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def count_prompt_index_images(batches_dir: Path, batch: str) -> int:
    """Return the current count of PNG files eligible for prompt indexing."""
    _validate_name(batch, "batch name")
    batch_dir = Path(batches_dir) / batch
    count = 0
    for folder in BATCH_FOLDERS:
        folder_dir = batch_dir / folder
        if not folder_dir.is_dir():
            continue
        for path in folder_dir.iterdir():
            if path.suffix.lower() == ".png":
                count += 1
    return count


def build_prompt_index(batches_dir: Path, batch: str) -> dict[str, Any]:
    """Build and cache a prompt index for one batch."""
    _validate_name(batch, "batch name")
    batch_dir = Path(batches_dir) / batch
    files = []
    for folder in BATCH_FOLDERS:
        folder_dir = batch_dir / folder
        if not folder_dir.is_dir():
            continue
        for path in folder_dir.iterdir():
            if path.suffix.lower() != ".png":
                continue
            try:
                files.append((path.stat().st_mtime, folder, path))
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
    """Load a cached prompt index."""
    with _LOCK:
        path = _cache_path(batches_dir, batch)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None


def load_all_prompt_indices(batches_dir: Path) -> dict[str, Any]:
    """Load cached prompt indices for every batch."""
    batches = {}
    total = 0
    for batch in get_batches(batches_dir):
        index = load_prompt_index(batches_dir, batch)
        if index is None:
            continue
        batches[batch] = index
        total += int(index.get("prompt_count") or 0)
    return {"batches": batches, "total_prompts": total}
