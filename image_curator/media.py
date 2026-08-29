"""Typed media poster and hover-preview cache helpers."""

import os
import subprocess
import uuid
from pathlib import Path

from PIL import Image, ImageDraw


def thumbnail_cache_path(batches_dir: Path, batch_name: str, folder: str, filename: str) -> Path:
    """Return an extension-safe per-batch WebP poster cache path."""
    cache_dir = batches_dir / batch_name / ".thumbs"
    source = Path(filename)
    extension = source.suffix.lower().lstrip(".") or "none"
    return cache_dir / f"{folder}__{source.stem}--{extension}.webp"


def hover_preview_cache_path(
    batches_dir: Path, batch_name: str, folder: str, filename: str
) -> Path:
    """Return an extension-safe cached MP4 hover-preview path."""
    source = Path(filename)
    extension = source.suffix.lower().lstrip(".") or "none"
    return batches_dir / batch_name / ".previews" / f"{folder}__{source.stem}--{extension}.mp4"


def remove_cached_media_derivatives(
    batches_dir: Path, batch_name: str, folder: str, filename: str
) -> None:
    """Remove regular in-batch poster/preview files without following symlinks."""
    root = Path(batches_dir).resolve()
    batch_dir = Path(batches_dir) / batch_name
    candidates = (
        thumbnail_cache_path(Path(batches_dir), batch_name, folder, filename),
        hover_preview_cache_path(Path(batches_dir), batch_name, folder, filename),
    )
    for candidate in candidates:
        try:
            if batch_dir.is_symlink() or candidate.parent.is_symlink() or candidate.is_symlink():
                continue
            real_batch = batch_dir.resolve()
            real_parent = candidate.parent.resolve()
            real_candidate = candidate.resolve()
            real_batch.relative_to(root)
            real_parent.relative_to(real_batch)
            real_candidate.relative_to(real_batch)
            if candidate.is_file():
                candidate.unlink()
        except (OSError, ValueError):
            continue


def media_cache_is_fresh(cache_path: Path, source_path: Path) -> bool:
    """Return whether a regular cached derivative is at least as new as its source."""
    try:
        return (
            cache_path.is_file()
            and not cache_path.is_symlink()
            and not source_path.is_symlink()
            and cache_path.stat().st_mtime >= source_path.stat().st_mtime
        )
    except OSError:
        return False


def thumbnail_is_fresh(
    cache_path: Path,
    source_path: Path,
    thumb_size: tuple[int, int] | None = None,
) -> bool:
    """Return True when a cached thumbnail exists and is newer than its source."""
    if not media_cache_is_fresh(cache_path, source_path):
        return False
    if thumb_size is None:
        return True
    try:
        with Image.open(source_path) as source, Image.open(cache_path) as cached:
            scale = min(thumb_size[0] / source.width, thumb_size[1] / source.height, 1)
            expected_width = max(1, int(source.width * scale))
            expected_height = max(1, int(source.height * scale))
            return cached.width >= expected_width and cached.height >= expected_height
    except (OSError, ValueError, ZeroDivisionError):
        return False


def _atomic_temp_path(cache_path: Path) -> Path:
    return cache_path.with_name(f".{cache_path.stem}.{uuid.uuid4().hex}.tmp{cache_path.suffix}")


def _safe_cache_target(source_path: Path, cache_path: Path) -> None:
    if source_path.is_symlink() or cache_path.is_symlink() or cache_path.parent.is_symlink():
        raise ValueError("Unsafe media cache path")
    if not source_path.is_file():
        raise ValueError("Media source is not a regular file")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.parent.is_symlink():
        raise ValueError("Unsafe media cache path")


def _save_webp_atomic(image: Image.Image, cache_path: Path, thumb_size: tuple[int, int]) -> None:
    image.thumbnail(thumb_size, Image.Resampling.LANCZOS)
    temp_path = _atomic_temp_path(cache_path)
    try:
        image.save(str(temp_path), format="WEBP", quality=85, method=6)
        os.replace(temp_path, cache_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _fallback_tile(cache_path: Path, thumb_size: tuple[int, int], label: str) -> None:
    tile = Image.new("RGB", thumb_size, color=(25, 30, 40))
    draw = ImageDraw.Draw(tile)
    accent = (113, 160, 255)
    cx, cy = thumb_size[0] // 2, thumb_size[1] // 2
    draw.rounded_rectangle((cx - 54, cy - 72, cx + 54, cy + 36), radius=18, fill=(38, 47, 64))
    draw.ellipse((cx - 26, cy - 18, cx + 26, cy + 34), fill=accent)
    draw.rectangle((cx + 17, cy - 70, cx + 29, cy + 9), fill=accent)
    draw.text((20, thumb_size[1] - 38), label, fill=(220, 226, 238))
    _save_webp_atomic(tile, cache_path, thumb_size)


def _run_ffmpeg(command: list[str], timeout: int = 90) -> bool:
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def generate_media_poster(
    source_path: Path,
    cache_path: Path,
    thumb_size: tuple[int, int],
    *,
    media_kind: str,
    ffmpeg_path: str | None = None,
) -> bool:
    """Generate an atomic WebP poster, using a stable tile on decoder failure."""
    source_path = Path(source_path)
    cache_path = Path(cache_path)
    _safe_cache_target(source_path, cache_path)
    if media_kind in {"image", "animated_image"}:
        try:
            with Image.open(source_path) as opened:
                opened.seek(0)
                frame = opened.convert("RGB")
                _save_webp_atomic(frame, cache_path, thumb_size)
            return True
        except (OSError, ValueError):
            return False

    ffmpeg = ffmpeg_path or os.environ.get("IMAGE_CURATOR_FFMPEG", "ffmpeg")
    temp_path = _atomic_temp_path(cache_path)
    label = "AUDIO" if media_kind == "audio" else "VIDEO"
    try:
        command = [ffmpeg, "-y", "-i", str(source_path)]
        if media_kind == "video":
            command.extend(["-frames:v", "1"])
        else:
            command.extend(["-map", "0:v:0", "-frames:v", "1"])
        command.extend(
            [
                "-vf",
                f"scale={thumb_size[0]}:{thumb_size[1]}:force_original_aspect_ratio=decrease",
                "-c:v",
                "libwebp",
                "-quality",
                "90",
                str(temp_path),
            ]
        )
        if _run_ffmpeg(command) and temp_path.is_file() and temp_path.stat().st_size > 0:
            os.replace(temp_path, cache_path)
            return True
    finally:
        temp_path.unlink(missing_ok=True)
    _fallback_tile(cache_path, thumb_size, label)
    return True


def generate_hover_preview(
    source_path: Path,
    cache_path: Path,
    *,
    media_kind: str,
    ffmpeg_path: str | None = None,
) -> bool:
    """Generate a short, muted, quality-first MP4 proxy for GIF/video hover."""
    if media_kind not in {"animated_image", "video"}:
        return False
    source_path = Path(source_path)
    cache_path = Path(cache_path)
    _safe_cache_target(source_path, cache_path)
    ffmpeg = ffmpeg_path or os.environ.get("IMAGE_CURATOR_FFMPEG", "ffmpeg")
    temp_path = _atomic_temp_path(cache_path)
    command = [ffmpeg, "-y"]
    if media_kind == "animated_image":
        command.extend(["-stream_loop", "-1"])
    command.extend(["-i", str(source_path), "-t", "4", "-an"])
    command.extend(
        [
            "-vf",
            "scale=640:640:force_original_aspect_ratio=decrease,fps=24",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temp_path),
        ]
    )
    try:
        if not _run_ffmpeg(command) or not temp_path.is_file() or temp_path.stat().st_size == 0:
            return False
        os.replace(temp_path, cache_path)
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def generate_thumbnail(source_path: Path, cache_path: Path, thumb_size: tuple[int, int]) -> None:
    """Compatibility wrapper for still-image WebP thumbnails."""
    generate_media_poster(
        source_path,
        cache_path,
        thumb_size,
        media_kind="image",
    )
