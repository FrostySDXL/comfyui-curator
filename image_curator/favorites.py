"""Favorite image persistence helpers for Image Curator."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from image_curator.batch_store import BATCH_FOLDERS, _validate_name

_LOCK = threading.RLock()


def _favorites_path(batches_dir: Path, batch: str | None = None) -> Path:
    batches_dir = Path(batches_dir)
    if batch is None:
        return batches_dir / ".favorites.json"
    _validate_name(batch, "batch name")
    return batches_dir / batch / ".favorites.json"


def load_favorites(batches_dir: Path, batch: str | None = None) -> list[Any]:
    """Load favorite data for a batch or universal scope."""
    with _LOCK:
        path = _favorites_path(batches_dir, batch)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        images = data.get("images", []) if isinstance(data, dict) else []
        return images if isinstance(images, list) else []


def save_favorites(batches_dir: Path, data: list[Any], batch: str | None = None) -> None:
    """Save favorite data atomically for a batch or universal scope."""
    with _LOCK:
        path = _favorites_path(batches_dir, batch)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"images": data}, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def toggle_favorite(batches_dir: Path, batch: str, filename: str) -> dict[str, bool]:
    """Toggle favorite in both batch and universal scopes."""
    _validate_name(batch, "batch name")
    _validate_name(filename, "file name")
    with _LOCK:
        batch_images = [str(item) for item in load_favorites(batches_dir, batch)]
        if filename in batch_images:
            batch_images = [name for name in batch_images if name != filename]
            batch_state = False
        else:
            batch_images.append(filename)
            batch_state = True
        save_favorites(batches_dir, batch_images, batch)

        universal = [item for item in load_favorites(batches_dir) if isinstance(item, dict)]
        universal = [
            item
            for item in universal
            if not (item.get("batch") == batch and item.get("filename") == filename)
        ]
        if batch_state:
            universal.append(
                {
                    "batch": batch,
                    "filename": filename,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        save_favorites(batches_dir, universal)
        return {"batch": batch_state, "universal": batch_state}


def get_batch_favorite_filenames(batches_dir: Path, batch: str) -> set[str]:
    """Return favorite filenames for one batch."""
    return {str(item) for item in load_favorites(batches_dir, batch) if isinstance(item, str)}


def _find_file_folder(batches_dir: Path, batch: str, filename: str) -> str | None:
    _validate_name(batch, "batch name")
    _validate_name(filename, "file name")
    batch_dir = Path(batches_dir) / batch
    for folder in BATCH_FOLDERS:
        if (batch_dir / folder / filename).exists():
            return folder
    return None


def resolve_universal_favorites(batches_dir: Path) -> list[dict[str, str]]:
    """Resolve universal favorites to existing files and their current folder."""
    resolved = []
    for item in load_favorites(batches_dir):
        if not isinstance(item, dict):
            continue
        batch = str(item.get("batch") or "")
        filename = str(item.get("filename") or "")
        try:
            folder = _find_file_folder(batches_dir, batch, filename)
        except ValueError:
            continue
        if not folder:
            continue
        file_path = Path(batches_dir) / batch / folder / filename
        try:
            size = file_path.stat().st_size
        except OSError:
            size = 0
        resolved.append(
            {
                "batch": batch,
                "filename": filename,
                "folder": folder,
                "size": size,
                "added_at": str(item.get("added_at") or ""),
            }
        )
    return resolved
