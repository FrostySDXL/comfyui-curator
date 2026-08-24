"""Adjacent JSON sidecar discovery and metadata helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .png_metadata import extract_png_metadata


SIDECAR_MAX_BYTES = 2 * 1024 * 1024


def json_sidecar_candidates(media_path: Path) -> tuple[Path, ...]:
    """Return supported sidecar names in deterministic preference order."""
    media_path = Path(media_path)
    candidates = [media_path.with_name(f"{media_path.name}.json"), media_path.with_suffix(".json")]
    return tuple(dict.fromkeys(candidates))


def find_json_sidecar(media_path: Path) -> Path | None:
    """Return the first regular, non-symlinked adjacent JSON sidecar."""
    for candidate in json_sidecar_candidates(media_path):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
        except OSError:
            continue
        return candidate
    return None


def sidecar_destination(media_source: Path, media_destination: Path, sidecar: Path) -> Path:
    """Map a source sidecar naming style to a renamed media destination."""
    media_source = Path(media_source)
    media_destination = Path(media_destination)
    sidecar = Path(sidecar)
    if sidecar.name == f"{media_source.name}.json":
        return media_destination.with_name(f"{media_destination.name}.json")
    return media_destination.with_suffix(".json")


def inspect_json_sidecar(media_path: Path) -> dict[str, Any] | None:
    """Return a bounded, display-ready sidecar payload for *media_path*."""
    for candidate in json_sidecar_candidates(media_path):
        try:
            if candidate.is_symlink():
                return {
                    "name": candidate.name,
                    "size": None,
                    "mtime": None,
                    "text": None,
                    "error": "JSON sidecar is not a regular file.",
                }
            if not candidate.is_file():
                continue
            stat = candidate.stat()
            payload: dict[str, Any] = {
                "name": candidate.name,
                "size": stat.st_size,
                "mtime": stat.st_mtime_ns,
                "text": None,
                "error": None,
            }
            if stat.st_size > SIDECAR_MAX_BYTES:
                payload["error"] = (
                    f"JSON sidecar is too large to display ({stat.st_size} bytes; "
                    f"limit {SIDECAR_MAX_BYTES} bytes)."
                )
                return payload
            try:
                value = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                payload["error"] = "JSON sidecar could not be read as valid JSON."
                return payload
            payload["data"] = value
            payload["text"] = json.dumps(value, ensure_ascii=False, indent=2)
            return payload
        except OSError:
            return {
                "name": candidate.name,
                "size": None,
                "mtime": None,
                "text": None,
                "error": "JSON sidecar could not be inspected.",
            }
    return None


def extract_media_metadata(media_path: Path) -> dict[str, Any]:
    """Combine PNG generation metadata with an optional JSON sidecar."""
    metadata = extract_png_metadata(media_path)
    has_png_metadata = bool(metadata.get("has_metadata"))
    sidecar = inspect_json_sidecar(media_path)
    metadata["has_png_metadata"] = has_png_metadata
    metadata["has_sidecar"] = sidecar is not None
    metadata["sidecar"] = sidecar
    metadata["has_metadata"] = has_png_metadata or sidecar is not None
    return metadata


def delete_json_sidecar(media_path: Path) -> bool:
    """Delete the selected adjacent sidecar, returning False on an I/O failure."""
    sidecar = find_json_sidecar(media_path)
    if sidecar is None:
        return True
    try:
        sidecar.unlink()
    except OSError:
        return False
    return True
