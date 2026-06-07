"""PNG generation metadata extraction for Image Curator."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image


LORA_RE = re.compile(r"<lora:([^:>]+):([^>]+)>")
SETTING_RE = re.compile(r",\s*(?=[A-Za-z][A-Za-z ]+:)")


def _empty_metadata(reason: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "has_metadata": False,
        "source": None,
        "parameters": {},
        "loras": [],
        "raw_keys": [],
        "workflow_available": False,
        "workflow_size": 0,
        "raw_parameters": None,
    }
    if reason:
        data["reason"] = reason
    return data


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_loras(prompt: str | None) -> list[dict[str, Any]]:
    if not prompt:
        return []
    loras = []
    for name, raw_weight in LORA_RE.findall(prompt):
        loras.append(
            {
                "name": name,
                "weight": _to_float(raw_weight.strip()),
                "hash": None,
            }
        )
    return loras


def _parse_settings(settings_line: str) -> dict[str, str]:
    settings: dict[str, str] = {}
    for part in SETTING_RE.split(settings_line.strip()):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        settings[key.strip().lower()] = value.strip()
    return settings


def _parse_size(value: str | None) -> tuple[int | None, int | None]:
    if not value or "x" not in value.lower():
        return None, None
    width, height = value.lower().split("x", 1)
    return _to_int(width.strip()), _to_int(height.strip())


def parse_parameters(parameters: str) -> dict[str, Any]:
    """Parse A1111/ComfyUI-style human-readable parameters text."""
    text = parameters.strip()
    prompt = text
    negative_prompt = None
    settings_line = ""

    if "\nNegative prompt:" in text:
        prompt, remainder = text.split("\nNegative prompt:", 1)
        if "\nSteps:" in remainder:
            negative_prompt, settings_line = remainder.split("\nSteps:", 1)
            settings_line = "Steps:" + settings_line
        else:
            negative_prompt = remainder
    elif "\nSteps:" in text:
        prompt, settings_line = text.split("\nSteps:", 1)
        settings_line = "Steps:" + settings_line

    settings = _parse_settings(settings_line) if settings_line else {}
    width, height = _parse_size(settings.get("size"))

    return {
        "prompt": prompt.strip() or None,
        "negative_prompt": negative_prompt.strip() if negative_prompt else None,
        "steps": _to_int(settings.get("steps")),
        "sampler": settings.get("sampler"),
        "cfg_scale": _to_float(settings.get("cfg scale")),
        "seed": _to_int(settings.get("seed")),
        "width": width,
        "height": height,
        "clip_skip": _to_int(settings.get("clip skip")),
        "model": settings.get("model"),
        "model_hash": settings.get("model hash"),
        "version": settings.get("version"),
    }


def extract_png_metadata(path: Path) -> dict[str, Any]:
    """Extract generation metadata from PNG text chunks.

    The function is intentionally best-effort and returns a stable JSON-ready
    dictionary rather than raising for malformed metadata.
    """
    path = Path(path)
    if path.suffix.lower() != ".png":
        return _empty_metadata("unsupported_extension")

    try:
        with Image.open(path) as image:
            text_chunks = dict(getattr(image, "text", {}) or {})
    except Exception as exc:  # pragma: no cover - defensive for corrupt images
        data = _empty_metadata("image_read_error")
        data["parse_error"] = str(exc)
        return data

    if not text_chunks:
        return _empty_metadata("no_png_text_chunks")

    raw_parameters = text_chunks.get("parameters")
    parsed_parameters = parse_parameters(raw_parameters) if raw_parameters else {}
    workflow_raw = text_chunks.get("workflow") or text_chunks.get("prompt")

    return {
        "has_metadata": True,
        "source": "comfyui_png" if raw_parameters else "png_text",
        "parameters": parsed_parameters,
        "loras": _parse_loras(parsed_parameters.get("prompt")),
        "raw_keys": sorted(text_chunks.keys()),
        "workflow_available": bool(workflow_raw),
        "workflow_size": len(workflow_raw) if workflow_raw else 0,
        "raw_parameters": raw_parameters,
    }
