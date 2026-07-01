"""Public derivative helpers for Image Curator.

The functions in this module operate only on generated public copies under a
batch-local ``public/`` folder. They never modify source review-folder images.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from image_curator.batch_store import BATCH_FOLDERS, IMAGE_EXTENSIONS, _validate_name, get_batches
from image_curator.media import thumbnail_cache_path

PUBLIC_FOLDER = "public"
MIN_WATERMARK_SIZE_PERCENT = 1.0
MAX_WATERMARK_SIZE_PERCENT = 20.0
WATERMARK_FONT_CANDIDATES = (
    "arial.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
WATERMARK_POSITIONS = {
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "bottom-center",
    "center",
}


def get_public_folder(batches_dir: Path, batch: str, *, create: bool = False) -> Path:
    """Return the batch-local public output folder."""
    _validate_name(batch, "batch name")
    folder = Path(batches_dir) / batch / PUBLIC_FOLDER
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def _is_supported_image_name(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _public_output_name(dest_dir: Path, source_name: str) -> str:
    stem = Path(source_name).stem
    suffix = Path(source_name).suffix
    candidate = f"{stem}-public{suffix}"
    counter = 2
    while (dest_dir / candidate).exists():
        candidate = f"{stem}-public-{counter}{suffix}"
        counter += 1
    return candidate


def _collision_safe_dest_name(dest_dir: Path, filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    counter = 2
    while (dest_dir / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _load_font(image_width: int, size_percent: float) -> ImageFont.ImageFont:
    clamped_percent = min(
        MAX_WATERMARK_SIZE_PERCENT,
        max(MIN_WATERMARK_SIZE_PERCENT, size_percent),
    )
    size = max(8, int(image_width * clamped_percent / 100))
    for font_path in WATERMARK_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _watermark_xy(
    image_size: tuple[int, int],
    text_size: tuple[int, int],
    position: str,
    margin: int,
) -> tuple[int, int]:
    width, height = image_size
    text_width, text_height = text_size
    x_left = margin
    x_center = max(margin, (width - text_width) // 2)
    x_right = max(margin, width - text_width - margin)
    y_top = margin
    y_center = max(margin, (height - text_height) // 2)
    y_bottom = max(margin, height - text_height - margin)
    positions = {
        "top-left": (x_left, y_top),
        "top-right": (x_right, y_top),
        "bottom-left": (x_left, y_bottom),
        "bottom-right": (x_right, y_bottom),
        "bottom-center": (x_center, y_bottom),
        "center": (x_center, y_center),
    }
    return positions.get(position, positions["bottom-right"])


def _apply_text_watermark(image: Image.Image, options: dict[str, Any] | None) -> Image.Image:
    if not options or not options.get("enabled"):
        return image
    text = str(options.get("text") or "").strip()
    if not text:
        return image
    position = str(options.get("position") or "bottom-right")
    if position not in WATERMARK_POSITIONS:
        position = "bottom-right"
    margin = max(0, int(options.get("margin") or 32))
    opacity = min(1.0, max(0.0, float(options.get("opacity") or 0.55)))
    size_percent = float(options.get("size_percent") or 4)

    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font = _load_font(base.width, size_percent)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    xy = _watermark_xy(base.size, text_size, position, margin)
    draw.text(xy, text, fill=(255, 255, 255, int(255 * opacity)), font=font)
    return Image.alpha_composite(base, overlay)


def _save_derivative(
    source: Path,
    output: Path,
    *,
    watermark: dict[str, Any] | None,
) -> None:
    with Image.open(source) as image:
        derivative = _apply_text_watermark(image, watermark)
        save_image = derivative
        if output.suffix.lower() in {".jpg", ".jpeg"} and save_image.mode in {"RGBA", "LA"}:
            save_image = save_image.convert("RGB")
        save_image.save(output)


def create_public_copies(
    batches_dir: Path,
    *,
    batch: str,
    folder: str,
    filenames: list[str],
    strip_metadata: bool = True,
    watermark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create public derivatives from selected source images."""
    del strip_metadata  # Saving through Pillow without metadata strips it.
    files: list[dict[str, str]] = []
    exported = 0
    failed = 0
    try:
        _validate_name(batch, "batch name")
    except ValueError as exc:
        return {
            "success": False,
            "exported": 0,
            "failed": len(filenames),
            "files": [{"source": name, "error": str(exc)} for name in filenames],
        }
    if folder not in BATCH_FOLDERS:
        return {
            "success": False,
            "exported": 0,
            "failed": len(filenames),
            "files": [{"source": name, "error": "Invalid source folder"} for name in filenames],
        }
    source_dir = Path(batches_dir) / batch / folder
    public_dir = get_public_folder(batches_dir, batch, create=True)
    for filename in filenames:
        try:
            _validate_name(filename, "file name")
        except ValueError as exc:
            failed += 1
            files.append({"source": filename, "error": str(exc)})
            continue
        if not _is_supported_image_name(filename):
            failed += 1
            files.append({"source": filename, "error": "Unsupported image type"})
            continue
        source = source_dir / filename
        if not source.exists():
            failed += 1
            files.append({"source": filename, "error": "Source file not found"})
            continue
        output_name = _public_output_name(public_dir, filename)
        output = public_dir / output_name
        try:
            _save_derivative(source, output, watermark=watermark)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            failed += 1
            files.append({"source": filename, "error": str(exc)})
            continue
        exported += 1
        files.append({"source": filename, "output": output_name})
    return {"success": failed == 0, "exported": exported, "failed": failed, "files": files}


def _public_item(batch: str, path: Path) -> dict[str, Any] | None:
    if not _is_supported_image_name(path.name):
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "batch": batch,
        "folder": PUBLIC_FOLDER,
        "name": path.name,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
    }


def list_batch_public(batches_dir: Path, batch: str) -> list[dict[str, Any]]:
    """List generated public images for one batch."""
    public_dir = get_public_folder(batches_dir, batch)
    if not public_dir.is_dir():
        return []
    items = [
        _public_item(batch, path)
        for path in sorted(public_dir.iterdir(), key=lambda p: p.name.lower())
    ]
    return [item for item in items if item is not None]


def list_all_public(batches_dir: Path) -> list[dict[str, Any]]:
    """Aggregate generated public images from every batch."""
    items: list[dict[str, Any]] = []
    for batch in get_batches(batches_dir):
        items.extend(list_batch_public(batches_dir, batch))
    return items


def _resolve_export_destination(destination: Path | str, export_root: Path | str | None) -> Path:
    if export_root is None:
        raise ValueError("Public export root is not configured")
    root = Path(export_root).resolve()
    dest = Path(destination)
    if not dest.is_absolute():
        dest = root / dest
    resolved = dest.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Destination must stay inside {root}") from exc
    return resolved


def _resolve_public_file(batches_dir: Path, item: dict[str, Any]) -> Path:
    batch = str(item.get("batch") or "")
    filename = str(item.get("filename") or item.get("name") or "")
    _validate_name(batch, "batch name")
    _validate_name(filename, "file name")
    return get_public_folder(batches_dir, batch) / filename


def _transfer_public_items(
    batches_dir: Path,
    *,
    destination: Path | str,
    items: list[dict[str, Any]],
    export_root: Path | str | None,
    move: bool,
) -> dict[str, Any]:
    action = "moved" if move else "copied"
    try:
        dest_dir = _resolve_export_destination(destination, export_root)
    except ValueError as exc:
        return {
            "success": False,
            action: 0,
            "failed": len(items),
            "files": [
                {"filename": str(item.get("filename") or item.get("name") or ""), "error": str(exc)}
                for item in items
            ],
        }
    dest_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, str]] = []
    completed = 0
    failed = 0
    for item in items:
        filename = str(item.get("filename") or item.get("name") or "")
        try:
            source = _resolve_public_file(batches_dir, item)
        except ValueError as exc:
            failed += 1
            files.append({"filename": filename, "error": str(exc)})
            continue
        if not source.exists():
            failed += 1
            files.append({"filename": filename, "error": "Public file not found"})
            continue
        if not _is_supported_image_name(source.name):
            failed += 1
            files.append({"filename": filename, "error": "Unsupported image type"})
            continue
        output_name = _collision_safe_dest_name(dest_dir, source.name)
        output = dest_dir / output_name
        try:
            if move:
                shutil.move(str(source), str(output))
            else:
                shutil.copy2(source, output)
        except OSError as exc:
            failed += 1
            files.append({"filename": filename, "error": str(exc)})
            continue
        completed += 1
        files.append({"filename": filename, "output": output_name})
    return {"success": failed == 0, action: completed, "failed": failed, "files": files}


def copy_public_items(
    batches_dir: Path,
    *,
    destination: Path | str,
    items: list[dict[str, Any]],
    export_root: Path | str | None,
) -> dict[str, Any]:
    """Copy generated public derivatives to a configured export destination."""
    return _transfer_public_items(
        batches_dir,
        destination=destination,
        items=items,
        export_root=export_root,
        move=False,
    )


def move_public_items(
    batches_dir: Path,
    *,
    destination: Path | str,
    items: list[dict[str, Any]],
    export_root: Path | str | None,
) -> dict[str, Any]:
    """Move generated public derivatives to a configured export destination."""
    return _transfer_public_items(
        batches_dir,
        destination=destination,
        items=items,
        export_root=export_root,
        move=True,
    )


def delete_public_items(batches_dir: Path, *, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Delete generated public derivatives only."""
    files: list[dict[str, str]] = []
    deleted = 0
    failed = 0
    for item in items:
        filename = str(item.get("filename") or item.get("name") or "")
        try:
            source = _resolve_public_file(batches_dir, item)
        except ValueError as exc:
            failed += 1
            files.append({"filename": filename, "error": str(exc)})
            continue
        if not source.exists() or not _is_supported_image_name(source.name):
            failed += 1
            files.append({"filename": filename, "error": "Public file not found"})
            continue
        try:
            source.unlink()
        except OSError as exc:
            failed += 1
            files.append({"filename": filename, "error": str(exc)})
            continue
        cache_path = thumbnail_cache_path(
            batches_dir, item.get("batch", ""), PUBLIC_FOLDER, filename
        )
        if cache_path.exists():
            try:
                cache_path.unlink()
            except OSError:
                pass
        deleted += 1
        files.append({"filename": filename})
    return {"success": failed == 0, "deleted": deleted, "failed": failed, "files": files}
