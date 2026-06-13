"""Flask-adjacent validation helpers for batch web routes."""

from collections.abc import Callable
from pathlib import Path


def safe_path(base: Path, *parts: str) -> tuple[Path | None, str | None]:
    """Resolve a path within a base directory, blocking traversal."""
    try:
        resolved = (base / Path(*parts)).resolve()
    except (ValueError, OSError, TypeError):
        return None, "Invalid path"
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        return None, "Invalid path"
    return resolved, None


def require_existing_batch(
    batch_name: str,
    get_batches: Callable[[], list[str]],
) -> tuple[str | None, tuple[dict[str, str], int] | None]:
    """Validate that a batch name refers to an existing batch."""
    if not batch_name or batch_name not in get_batches():
        return None, ({"error": "Batch does not exist"}, 404)
    return batch_name, None
