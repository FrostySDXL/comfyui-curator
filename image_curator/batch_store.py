"""Batch filesystem and state helpers for Image Curator.

This module owns reusable non-AI batch behavior so the Flask entrypoint can
stay focused on route wiring and operator-facing service concerns.
"""

import json
import logging
import random
import shutil
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
BATCH_FOLDERS = ("inbox", "shortlisted", "finals", "rejects")


def _validate_name(name: str, label: str = "name") -> None:
    """Raise ValueError if a name looks like a path traversal attempt."""
    if not name or not name.strip():
        raise ValueError(f"empty {label}")
    if "\0" in name:
        raise ValueError(f"{label} contains null byte")
    if "/" in name or "\\" in name:
        raise ValueError(f"{label} contains path separators")
    if name in (".", ".."):
        raise ValueError(f"{label} is a reserved path component")
    if name.startswith("."):
        raise ValueError(f"{label} starts with a dot")


def load_state(state_file: Path) -> dict:
    """Load persistent state from a JSON file.

    Returns a default state dict if the file is missing or corrupt.
    """
    state_file = Path(state_file)
    if state_file.exists():
        try:
            with state_file.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print(
                f"Warning: state file {state_file} is corrupt, using defaults",
                flush=True,
            )
    return {"active_batch": None}


def save_state(state_file: Path, state: dict) -> None:
    """Save persistent state to a JSON file atomically.

    Writes to a temporary file then renames to avoid corruption on crash.
    """
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state), encoding="utf-8")
    tmp_path.replace(state_file)


def get_batches(batches_dir: Path) -> list[str]:
    """Return all batch directory names sorted alphabetically."""
    batches_dir = Path(batches_dir)
    if not batches_dir.exists():
        return []
    return sorted([d.name for d in batches_dir.iterdir() if d.is_dir()])


def create_batch(batches_dir: Path, name: str) -> bool:
    """Create a batch with the standard folder structure."""
    _validate_name(name, "batch name")
    batch_dir = Path(batches_dir) / name
    if batch_dir.exists():
        return False
    for folder in BATCH_FOLDERS:
        (batch_dir / folder).mkdir(parents=True, exist_ok=True)
    return True


def get_batch_folder(batches_dir: Path, batch_name: str, folder: str) -> Path:
    """Return a path to a batch subfolder."""
    _validate_name(batch_name, "batch name")
    _validate_name(folder, "folder name")
    if folder not in BATCH_FOLDERS:
        raise ValueError(f"Invalid folder '{folder}'. Must be one of: {', '.join(BATCH_FOLDERS)}")
    return Path(batches_dir) / batch_name / folder


def _is_supported_image(path: Path, extensions: Iterable[str] = IMAGE_EXTENSIONS) -> bool:
    return path.suffix.lower() in extensions


def get_images(directory: Path, sort_by: str = "date", order: str = "desc") -> list[Path]:
    """Return supported image files in a directory with configurable sorting."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    images = [f for f in directory.iterdir() if not f.is_symlink() and _is_supported_image(f)]
    reverse = order == "desc"
    if sort_by == "name":
        images.sort(key=lambda x: x.name.lower(), reverse=reverse)
    elif sort_by == "shuffle":
        random.shuffle(images)
    else:
        images.sort(key=lambda x: x.stat().st_mtime, reverse=reverse)
    return images


def get_batch_counts(batches_dir: Path, batch_name: str) -> dict[str, int]:
    """Return supported image counts for all standard folders in a batch."""
    counts = {}
    for folder in BATCH_FOLDERS:
        folder_path = get_batch_folder(batches_dir, batch_name, folder)
        if folder_path.exists():
            counts[folder] = len([f for f in folder_path.iterdir() if _is_supported_image(f)])
        else:
            counts[folder] = 0
    return counts


def get_batch_metadata(batches_dir: Path, batch_name: str) -> dict[str, float]:
    """Return lightweight metadata for batch-list sorting."""
    batch_dir = Path(batches_dir) / batch_name
    if not batch_dir.exists():
        return {"modified_at": 0}
    max_mtime = batch_dir.stat().st_mtime
    for f in batch_dir.rglob("*"):
        if f.is_file():
            max_mtime = max(max_mtime, f.stat().st_mtime)
    return {"modified_at": max_mtime}


def get_all_counts(batches_dir: Path) -> dict[str, dict[str, int]]:
    """Return folder counts for all batches."""
    return {batch: get_batch_counts(batches_dir, batch) for batch in get_batches(batches_dir)}


def get_all_batch_metadata(batches_dir: Path) -> dict[str, dict[str, float]]:
    """Return sortable metadata for all batches."""
    return {batch: get_batch_metadata(batches_dir, batch) for batch in get_batches(batches_dir)}


def get_pending_count(comfyui_output: Path) -> int:
    """Return supported image count waiting in the ComfyUI output directory."""
    comfyui_output = Path(comfyui_output)
    if not comfyui_output.exists():
        return 0
    return len([f for f in comfyui_output.iterdir() if _is_supported_image(f)])


def _collision_safe_name(dest_dir: Path, name: str) -> str:
    """Return a filename that doesn't conflict with existing files in dest_dir."""
    stem = Path(name).stem
    suffix = Path(name).suffix
    candidate = name
    counter = 1
    while (dest_dir / candidate).exists():
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def import_all_pending(comfyui_output: Path, batches_dir: Path, batch_name: str) -> int:
    """Move all pending supported images into a batch inbox."""
    comfyui_output = Path(comfyui_output)
    if not comfyui_output.exists():
        return 0

    dest_inbox = get_batch_folder(batches_dir, batch_name, "inbox")
    dest_inbox.mkdir(parents=True, exist_ok=True)

    count = 0
    for path in comfyui_output.iterdir():
        if _is_supported_image(path):
            safe_name = _collision_safe_name(dest_inbox, path.name)
            dst = dest_inbox / safe_name
            try:
                shutil.move(str(path), str(dst))
                count += 1
            except (OSError, shutil.Error) as exc:
                print(f"Failed to import {path.name}: {exc}")
    return count
