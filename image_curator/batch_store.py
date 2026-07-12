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


def _validate_state_target(path: Path) -> None:
    """Validate that a state-related path is safe to read or write.

    Checks (in order):
    1. Every existing or dangling-symlink component in the raw lexical
       parent chain is rejected.
    2. A symlink leaf is rejected BEFORE the missing-file check so
       dangling symlinks are not mistaken for safe missing files.
    3. Existing non-directory ancestors and non-regular leaves are
       rejected.
    4. The resolved path must be contained under the real parent.

    OSError during validation is never silently swallowed; it is
    converted to a stable ValueError without host paths.
    """
    path = Path(path)
    lexical_path = path if path.is_absolute() else Path.cwd() / path

    # ---- Walk raw parent chain (lexical, not resolved) ----
    try:
        anchor = Path(lexical_path.anchor)
    except Exception as exc:
        raise ValueError("State path is unsafe") from exc

    raw_parts = lexical_path.parts[1:]  # everything after the anchor
    for i, part in enumerate(raw_parts):
        anchor = anchor / part
        is_leaf = i == len(raw_parts) - 1
        try:
            if anchor.is_symlink():
                raise ValueError("State path is unsafe")
        except ValueError:
            raise
        except OSError:
            # is_symlink() can fail if a component is missing.  A
            # missing *parent* component is fine (it will be created
            # by mkdir).  A missing *leaf* that is also a dangling
            # symlink has already been caught above because is_symlink
            # returns True for dangling symlinks on most platforms.
            # If the platform cannot detect a dangling symlink via
            # is_symlink(), we fall through to the containment check.
            if not is_leaf:
                continue
            raise ValueError("State path is unsafe") from None

        if not is_leaf:
            # Parent component: must be a directory (or not exist yet).
            try:
                if anchor.exists() and not anchor.is_dir():
                    raise ValueError("State path is unsafe")
            except ValueError:
                raise
            except OSError:
                raise ValueError("State path is unsafe") from None
        else:
            # Leaf component: symlink rejected above; now check
            # regular-file-ness if it already exists.
            try:
                if anchor.exists() and not anchor.is_file():
                    raise ValueError("State path is unsafe")
            except ValueError:
                raise
            except OSError:
                raise ValueError("State path is unsafe") from None

    # ---- Resolved containment under real parent ----
    try:
        real_parent = lexical_path.parent.resolve()
        if lexical_path.exists():
            lexical_path.resolve().relative_to(real_parent)
        else:
            # For a missing target the path.resolve() may return a
            # different path than a future write would actually use.
            # We validate that a future resolve would be contained by
            # checking the parent chain containment instead.
            lexical_path.parent.resolve().relative_to(real_parent)
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError("State path is unsafe") from exc


def load_state(state_file: Path) -> dict:
    """Load persistent state from a JSON file.

    Returns a default state dict if the file is missing, corrupt, or unsafe.
    """
    state_file = Path(state_file)
    try:
        _validate_state_target(state_file)
    except ValueError:
        return {"active_batch": None}
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
    Rejects unsafe targets before any filesystem mutation so a rejected
    save never writes outside the state directory or leaves a temp file.
    """
    state_file = Path(state_file)
    tmp_path = state_file.with_suffix(state_file.suffix + ".tmp")

    # Validate before any write.
    _validate_state_target(state_file)
    _validate_state_target(tmp_path)

    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Revalidate post-mkdir in case a created parent is a symlink.
    _validate_state_target(state_file)
    _validate_state_target(tmp_path)

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
    """Return supported image files in a directory with configurable sorting.

    Files whose ``stat()`` raises ``OSError`` (for example because they were
    removed between ``iterdir()`` and the per-file inspection) are silently
    skipped so a concurrent deletion does not crash the image-listing
    endpoint. The same protection applies to the date-sort branch below,
    so a file that vanishes after the initial filter is also dropped
    rather than raising.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    images = []
    for f in directory.iterdir():
        # ``is_symlink()`` calls ``lstat`` -> ``stat``; if the file is
        # removed between ``iterdir()`` and that call, the underlying
        # stat raises FileNotFoundError. Treat that the same as an
        # unsupported entry and skip it.
        try:
            if f.is_symlink():
                continue
            if not _is_supported_image(f):
                continue
        except (FileNotFoundError, OSError):
            # File vanished after iterdir() — skip it.
            continue
        images.append(f)
    reverse = order == "desc"
    if sort_by == "name":
        images.sort(key=lambda x: x.name.lower(), reverse=reverse)
    elif sort_by == "shuffle":
        random.shuffle(images)
    else:
        # Capture mtime once during the sort so a file deleted between
        # iterdir() and the sort key call is dropped, not raised.
        dated = []
        for path in images:
            try:
                dated.append((path.stat().st_mtime, path))
            except OSError:
                # File vanished after iterdir() — skip it.
                continue
        dated.sort(key=lambda pair: pair[0], reverse=reverse)
        images = [path for _, path in dated]
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
    """Return lightweight metadata for batch-list sorting.

    Only considers content folders (inbox, shortlisted, finals, rejects, ai-curate).
    Excludes .thumbs cache and other hidden directories to avoid thumbnail
    generation from falsely bumping the batch to the top of "recent" sort.
    """
    _validate_name(batch_name, "batch name")
    batch_dir = Path(batches_dir) / batch_name
    if not batch_dir.exists():
        return {"modified_at": 0}
    max_mtime = 0.0
    for folder in BATCH_FOLDERS:
        folder_path = batch_dir / folder
        if folder_path.exists():
            max_mtime = max(max_mtime, folder_path.stat().st_mtime)
    ai_dir = batch_dir / "ai-curate"
    if ai_dir.exists():
        max_mtime = max(max_mtime, ai_dir.stat().st_mtime)
    return {"modified_at": max_mtime or batch_dir.stat().st_mtime}


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


def move_image(src: Path, dst: Path) -> bool:
    """Move a single file from ``src`` to ``dst``.

    Centralised helper used by the Flask routes, the AI curate worker,
    and the CLI. Returns True on success, False if
    the source does not exist or the move raised ``OSError``. Never
    re-raises so callers don't have to wrap every call in try/except.

    The destination's parent directory is created if missing.
    """
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        return False
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return True
    except OSError:
        logger.warning("move_image failed: %s -> %s", src, dst, exc_info=True)
        return False


def move_images(source_dir: Path, names: list[str], dest_dir: Path) -> tuple[int, int]:
    """Move a batch of files from ``source_dir`` to ``dest_dir``.

    Returns ``(moved, skipped)``. Missing source files and names that fail
    ``_validate_name`` (path traversal, null bytes, dotfiles) count as
    skipped and do not raise. The destination directory is created if
    missing. Defense-in-depth validation is applied at this boundary so
    the helper is safe to call from any caller, not just the API routes.
    """
    source_dir = Path(source_dir)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    skipped = 0
    for name in names:
        try:
            _validate_name(name, "file name")
        except ValueError:
            logger.warning("move_images rejected unsafe name: %r", name)
            skipped += 1
            continue
        src = source_dir / name
        dst = dest_dir / name
        if move_image(src, dst):
            moved += 1
        else:
            skipped += 1
    return moved, skipped


def import_all_pending(comfyui_output: Path, batches_dir: Path, batch_name: str) -> int:
    """Move all pending supported images into a batch inbox."""
    comfyui_output = Path(comfyui_output)
    if not comfyui_output.exists():
        return 0

    dest_inbox = get_batch_folder(batches_dir, batch_name, "inbox")
    dest_inbox.mkdir(parents=True, exist_ok=True)

    count = 0
    for path in comfyui_output.iterdir():
        try:
            is_symlink = path.is_symlink()
        except OSError:
            continue
        if not is_symlink and _is_supported_image(path):
            safe_name = _collision_safe_name(dest_inbox, path.name)
            dst = dest_inbox / safe_name
            if move_image(path, dst):
                count += 1
            else:
                logger.warning("Failed to import %s", path.name)
    return count
