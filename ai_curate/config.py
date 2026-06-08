"""
ai_curate.config -- Configuration defaults for AI curation.

All values can be overridden at runtime via API parameters or
environment variables where noted.
"""

import os
from pathlib import Path
from typing import Optional

# IMAGE_EXTENSIONS is owned by image_curator.batch_store. Re-exported here so
# consumers can still do ``from ai_curate.config import IMAGE_EXTENSIONS``
# without importing the non-AI module directly. Keeping a single source of
# truth prevents the two definitions from drifting.
from image_curator.batch_store import IMAGE_EXTENSIONS  # noqa: F401

# --- Paths ---
BATCHES_DIR = Path(
    os.environ.get(
        "IMAGE_CURATOR_BATCHES",
        str(Path.home() / "image-curator" / "batches"),
    )
)
COMFYUI_OUTPUT = Path(
    os.environ.get(
        "IMAGE_CURATOR_COMFYUI",
        str(Path.home() / "image-curator" / "comfyui-outputs"),
    )
)

# --- Llama-swap / vision model ---
DEFAULT_BASE_URL = os.environ.get("IMAGE_CURATOR_LLM_URL", "http://localhost:8080")
API_KEY = os.environ.get("IMAGE_CURATOR_API_KEY", "") or None
# ^^ Optional API key sent as Bearer token in Authorization header.
# Set to empty string or leave unset to skip authentication.

_raw_model = os.environ.get("IMAGE_CURATOR_MODEL", "")
_models = [m.strip() for m in _raw_model.split(",") if m.strip()]
AVAILABLE_MODELS: list[str] = _models if _models else []
DEFAULT_MODEL: Optional[str] = _models[0] if _models else None
# ^^ IMAGE_CURATOR_MODEL accepts a comma-separated list of model
# names/aliases (e.g. "vl-scorer,qwen-vl,gemini-pro").
# The first entry is the default selection in the UI dropdown.
# Set to a single value (no commas) for backward compatibility.
# Returns None when IMAGE_CURATOR_MODEL is not set to distinguish
# "unset" from an explicit empty string.
try:
    REQUEST_TIMEOUT = int(os.environ.get("IMAGE_CURATOR_TIMEOUT", "120"))
except ValueError:
    REQUEST_TIMEOUT = 120

# --- Scoring defaults ---
DEFAULT_TOP_N = 15
TOP_N_CAP = 100
ELEMENT_CAP = 12

# --- Run history ---
AI_CURATE_DIR = "ai-curate"
RUNS_SUBDIR = "runs"
LATEST_FILE = "latest.json"

# --- Allowed batch folders ---
ALLOWED_SOURCE_FOLDERS = {"inbox", "shortlisted", "finals", "rejects"}
ALLOWED_DEST_FOLDERS = {"inbox", "shortlisted", "finals", "rejects"}

# --- Image extensions ---
# IMAGE_EXTENSIONS is imported at the top of this module from
# image_curator.batch_store (single source of truth).
