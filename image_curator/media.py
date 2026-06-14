"""Media cache helpers for web image serving."""

from pathlib import Path

from PIL import Image


def thumbnail_cache_path(batches_dir: Path, batch_name: str, folder: str, filename: str) -> Path:
    """Return the per-batch WebP thumbnail cache path for an image."""
    cache_dir = batches_dir / batch_name / ".thumbs"
    return cache_dir / f"{folder}__{Path(filename).stem}.webp"


def thumbnail_is_fresh(
    cache_path: Path,
    source_path: Path,
    thumb_size: tuple[int, int] | None = None,
) -> bool:
    """Return True when a cached thumbnail exists and is newer than its source."""
    if not cache_path.exists() or cache_path.stat().st_mtime < source_path.stat().st_mtime:
        return False
    if thumb_size is None:
        return True
    with Image.open(source_path) as source, Image.open(cache_path) as cached:
        scale = min(thumb_size[0] / source.width, thumb_size[1] / source.height, 1)
        expected_width = max(1, int(source.width * scale))
        expected_height = max(1, int(source.height * scale))
        return cached.width >= expected_width and cached.height >= expected_height


def generate_thumbnail(source_path: Path, cache_path: Path, thumb_size: tuple[int, int]) -> None:
    """Generate a WebP thumbnail at cache_path from source_path."""
    with Image.open(source_path) as img:
        img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(cache_path), format="WEBP", quality=85, method=6)
