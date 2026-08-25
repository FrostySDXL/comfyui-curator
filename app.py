"""
Image Curator - Batch-based image organization and curation.
Web UI for reviewing and organizing AI-generated images with optional
AI-assisted scoring.
"""

import atexit
import os
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template, send_file, jsonify, request
from image_curator import batch_store, publish
from image_curator.favorites import (
    get_batch_favorite_filenames,
    resolve_universal_favorites,
    toggle_favorite,
)
from image_curator.sidecar_metadata import delete_json_sidecar, extract_media_metadata
from image_curator.media import (
    generate_hover_preview,
    generate_media_poster,
    hover_preview_cache_path,
    media_cache_is_fresh,
    remove_cached_media_derivatives,
    thumbnail_cache_path,
    thumbnail_is_fresh,
)
from image_curator.folder_index import (
    DEFAULT_PAGE_SIZE,
    BulkMoveOperationStore,
    FolderIndexService,
    normalize_shuffle_seed,
)
from image_curator.prompt_history import (
    build_prompt_index,
    count_prompt_index_images,
    load_all_prompt_indices,
    load_prompt_index,
)
from image_curator.search_index import (
    build_search_index,
    query_search_indices,
    summarize_search_index,
)
from image_curator.web_validation import require_existing_batch, safe_path

logger = logging.getLogger(__name__)

# AI curation imports
from ai_curate.config import (
    BATCHES_DIR,
    COMFYUI_OUTPUT,
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    DEFAULT_TOP_N,
    TOP_N_CAP,
    ELEMENT_CAP,
    ALLOWED_SOURCE_FOLDERS,
    ALLOWED_DEST_FOLDERS,
)
from ai_curate.elements import extract_elements, build_element_list
from ai_curate.job_validation import validate_ai_curate_request
from ai_curate.models import JobState
from ai_curate.client import VisionClient
from ai_curate.scoring import score_images, find_images
from ai_curate.storage import RunStorage
from ai_curate.queue import QueueManager
from ai_curate.routes import AiCurateRouteContext, create_ai_curate_blueprint
from ai_curate.worker import run_scoring_worker_inner

app = Flask(__name__)

# Configuration — paths are imported from ai_curate.config and respect env vars.
# Local overrides on the module-level aliases are removed; use the env vars instead:
#   IMAGE_CURATOR_BATCHES    -> BATCHES_DIR
#   IMAGE_CURATOR_COMFYUI    -> COMFYUI_OUTPUT

STATE_FILE = Path(
    os.environ.get(
        "IMAGE_CURATOR_STATE",
        str(Path.home() / ".config" / "image-curator" / "state.json"),
    )
)
THUMB_SIZE = (320, 320)
IMAGE_EXTENSIONS = batch_store.IMAGE_EXTENSIONS
_PUBLIC_EXPORT_ROOT_RAW = os.environ.get("IMAGE_CURATOR_PUBLIC_EXPORTS", "").strip()
PUBLIC_EXPORT_ROOT = Path(_PUBLIC_EXPORT_ROOT_RAW).expanduser() if _PUBLIC_EXPORT_ROOT_RAW else None
_folder_index = FolderIndexService()
_bulk_move_operations = BulkMoveOperationStore()
atexit.register(_folder_index.close)

# Warn on startup if critical defaults are unlikely to work
if os.environ.get("IMAGE_CURATOR_LLM_URL", "").strip() == "":
    print(
        "Warning: IMAGE_CURATOR_LLM_URL is not set. "
        "AI scoring will fail until configured (see .env.example)."
    )

# Ensure batch directory exists (deferred to __main__ to avoid import side effects)


def load_state():
    """Load persistent state (active batch, etc)."""
    return batch_store.load_state(STATE_FILE)


def save_state(state):
    """Save persistent state."""
    batch_store.save_state(STATE_FILE, state)


def get_batches():
    """Get list of all batch names."""
    return batch_store.get_batches(BATCHES_DIR)


def create_batch(name):
    """Create a new batch with folder structure."""
    return batch_store.create_batch(BATCHES_DIR, name)


def get_batch_folder(batch_name, folder):
    """Get path to a batch's subfolder."""
    return batch_store.get_batch_folder(BATCHES_DIR, batch_name, folder)


def get_batch_content_folder(batch_name, folder):
    """Get path to a review folder or generated public folder."""
    if folder == publish.PUBLIC_FOLDER:
        return publish.get_public_folder(BATCHES_DIR, batch_name)
    return get_batch_folder(batch_name, folder)


def get_images(directory, sort_by="date", order="desc"):
    """Get list of image files in directory with configurable sorting."""
    return batch_store.get_images(directory, sort_by=sort_by, order=order)


def get_batch_counts(batch_name):
    """Get image counts for a batch's folders."""
    return batch_store.get_batch_counts(BATCHES_DIR, batch_name)


def get_batch_metadata(batch_name):
    """Get lightweight metadata for batch list sorting."""
    return batch_store.get_batch_metadata(BATCHES_DIR, batch_name)


def get_all_counts():
    """Get counts for all batches."""
    return batch_store.get_all_counts(BATCHES_DIR)


def get_all_batch_metadata():
    """Get sortable metadata for all batches."""
    return batch_store.get_all_batch_metadata(BATCHES_DIR)


def get_pending_count():
    """Get count of images waiting in comfyui-outputs."""
    return batch_store.get_pending_count(COMFYUI_OUTPUT)


def import_all_pending(batch_name):
    """Import all available images from the configured source into a batch inbox."""
    return batch_store.import_all_pending(COMFYUI_OUTPUT, BATCHES_DIR, batch_name)


@app.route("/")
def index():
    return render_template(
        "index.html",
        available_models=AVAILABLE_MODELS,
        default_model=DEFAULT_MODEL,
        curator_native=False,
    )


def _safe_path(base: Path, *parts: str) -> tuple[Path | None, str | None]:
    """Resolve a path within a base directory, blocking traversal.

    Returns (resolved_path, None) if safe, (None, error_message) if unsafe.
    """
    return safe_path(base, *parts)


def _require_batch(batch_name: str) -> tuple[str | None, tuple | None]:
    """Validate that a batch name refers to an existing batch.

    Returns (batch_name, None) if valid, (None, (error_response, status_code)) if invalid.
    """
    return require_existing_batch(batch_name, get_batches)


def _is_viewable_folder(folder: str) -> bool:
    return folder in batch_store.BATCH_FOLDERS or folder == publish.PUBLIC_FOLDER


@app.route("/api/batches", methods=["GET"])
def api_get_batches():
    state = load_state()
    return jsonify(
        {
            "batches": get_batches(),
            "active_batch": state.get("active_batch"),
            "counts": get_all_counts(),
            "batch_meta": get_all_batch_metadata(),
            "pending_count": get_pending_count(),
        }
    )


@app.route("/api/batches", methods=["POST"])
def api_create_batch():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    if "/" in name or "\\" in name:
        return jsonify({"error": "Invalid batch name"}), 400
    try:
        if create_batch(name):
            return jsonify({"success": True})
        return jsonify({"error": "Batch already exists"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/active-batch", methods=["POST"])
def api_set_active_batch():
    data = request.json or {}
    batch = data.get("batch", "")
    if batch and batch not in get_batches():
        return jsonify({"error": "Batch does not exist"}), 400
    state = load_state()
    state["active_batch"] = batch if batch else None
    save_state(state)
    return jsonify({"success": True})


@app.route("/api/import-all", methods=["POST"])
def api_import_all():
    data = request.json or {}
    batch = data.get("batch", "")
    if not batch:
        return jsonify({"error": "Batch required"}), 400
    count = import_all_pending(batch)
    if count:
        _folder_index.refresh(batch, "inbox")
    return jsonify({"success": True, "count": count})


@app.route("/api/images/<batch>/<folder>")
def api_images(batch, folder):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if folder not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid folder"}), 400
    sort_by = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    if sort_by not in ("date", "name", "shuffle"):
        sort_by = "date"
    if order not in ("asc", "desc"):
        order = "desc"
    folder_path = get_batch_folder(batch_name, folder)
    images = get_images(folder_path, sort_by=sort_by, order=order)
    fav_set = get_batch_favorite_filenames(BATCHES_DIR, batch_name)
    return jsonify(
        [
            {
                "name": img.name,
                "size": img.stat().st_size,
                "mtime": img.stat().st_mtime_ns,
                "favorite": img.name in fav_set,
                "media_kind": batch_store.media_kind(img),
                "mime": batch_store.media_mime(img),
            }
            for img in images
            if img.exists()
        ]
    )


@app.route("/api/image-metadata/<batch>/<folder>/<filename>")
def api_image_metadata(batch, folder, filename):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if not _is_viewable_folder(folder):
        return jsonify({"error": "Invalid folder"}), 400

    filepath, err = _safe_path(get_batch_content_folder(batch_name, folder), filename)
    if err:
        return jsonify({"error": err}), 400
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    return jsonify(extract_media_metadata(filepath))


@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.json or {}
    batch = data.get("batch")
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    filename = data.get("filename")
    source = data.get("source")
    destination = data.get("destination")

    if not all([batch_name, filename, source, destination]):
        return jsonify({"error": "Missing parameters"}), 400

    if source not in batch_store.BATCH_FOLDERS or destination not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid source or destination folder"}), 400

    src_path, err = _safe_path(get_batch_folder(batch_name, source), filename)
    if err:
        return jsonify({"error": err}), 400
    dst_path, err = _safe_path(get_batch_folder(batch_name, destination), filename)
    if err:
        return jsonify({"error": err}), 400

    if not src_path.exists():
        return jsonify({"error": "File not found"}), 404

    if not batch_store.move_image(src_path, dst_path):
        return jsonify({"error": f"Could not move {filename}"}), 500
    _folder_index.refresh(batch_name, source, destination)
    return jsonify({"success": True})


@app.route("/api/move-batch", methods=["POST"])
def api_move_batch():
    data = request.json or {}
    batch = data.get("batch")
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    filenames = data.get("filenames", [])
    selection = data.get("selection")
    source = data.get("source")
    destination = data.get("destination")

    if not batch_name or not source or not destination or (not filenames and not selection):
        return jsonify({"error": "Missing parameters"}), 400

    if source not in batch_store.BATCH_FOLDERS or destination not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid source or destination folder"}), 400

    if selection is not None:
        if not isinstance(selection, dict) or selection.get("type") != "snapshot":
            return jsonify({"error": "Invalid selection"}), 400
        revision = str(selection.get("revision", ""))
        sort_by = str(selection.get("sort", "date"))
        order = str(selection.get("order", "desc"))
        try:
            shuffle_seed = normalize_shuffle_seed(sort_by, selection.get("shuffle_seed", ""))
        except ValueError:
            return jsonify({"error": "Invalid shuffle seed"}), 400
        selected_names = _folder_index.names_for_revision(
            batch_name, source, sort_by, order, revision, shuffle_seed
        )
        if selected_names is None:
            return jsonify({"error": "Snapshot revision is stale"}), 409
        excluded_raw = selection.get("excluded", [])
        if not isinstance(excluded_raw, list) or any(
            not isinstance(name, str) for name in excluded_raw
        ):
            return jsonify({"error": "Invalid selection exclusions"}), 400
        excluded = set(excluded_raw)
        filenames = [name for name in selected_names if name not in excluded]

    moved = 0
    skipped = 0
    moved_names: list[str] = []
    valid_filenames: list[str] = []
    source_dir = get_batch_folder(batch_name, source)
    dest_dir = get_batch_folder(batch_name, destination)
    for filename in filenames:
        src_path, err = _safe_path(source_dir, filename)
        if err:
            skipped += 1
            continue
        dst_path, err = _safe_path(dest_dir, filename)
        if err:
            skipped += 1
            continue
        valid_filenames.append(filename)
    if valid_filenames:
        moved, skipped_in_loop, moved_names = batch_store.move_images(
            source_dir=source_dir,
            names=valid_filenames,
            dest_dir=dest_dir,
        )
        skipped += skipped_in_loop
    _folder_index.refresh(batch_name, source, destination)
    if moved == 0 and filenames:
        # Zero files moved is a legitimate no-op (e.g. all requested files
        # were already in the destination or no longer exist), not a client
        # error. Surface success=False so the UI can show a hint, but keep
        # a 200 status so callers don't treat this as a 4xx failure.
        return jsonify({"success": False, "moved": 0, "skipped": skipped})
    payload = {"success": True, "moved": moved, "skipped": skipped}
    if selection is not None and moved_names:
        payload["operation_id"] = _bulk_move_operations.record(
            batch_name, source, destination, moved_names
        )
    return jsonify(payload)


@app.route("/api/move-batch/undo", methods=["POST"])
def api_undo_snapshot_move():
    data = request.json or {}
    token = data.get("operation_id", "")
    if not isinstance(token, str) or not token:
        return jsonify({"error": "operation_id required"}), 400
    operation = _bulk_move_operations.pop(token)
    if operation is None:
        return jsonify({"error": "Undo operation expired or not found"}), 404
    if operation.batch not in get_batches():
        return jsonify({"error": "Batch does not exist"}), 404
    source_dir = get_batch_folder(operation.batch, operation.destination)
    dest_dir = get_batch_folder(operation.batch, operation.source)
    moved, skipped, _moved_names = batch_store.move_images(
        source_dir, list(operation.names), dest_dir
    )
    _folder_index.refresh(operation.batch, operation.source, operation.destination)
    return jsonify({"success": moved > 0, "moved": moved, "skipped": skipped})


@app.route("/api/import-status", methods=["GET"])
def api_import_status():
    """Return only the inexpensive state needed by the Import All control."""
    return jsonify(
        {
            "active_batch": load_state().get("active_batch"),
            "pending_count": get_pending_count(),
        }
    )


@app.route("/api/delete-rejects/<batch>", methods=["POST"])
def api_delete_rejects(batch):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    rejects_dir = get_batch_folder(batch_name, "rejects")
    if not rejects_dir.exists():
        return jsonify({"error": "No rejects folder"}), 404

    count = 0
    failed = 0
    for f in rejects_dir.iterdir():
        if f.suffix.lower() in batch_store.VIEWABLE_MEDIA_EXTENSIONS:
            try:
                f.unlink()
            except OSError:
                failed += 1
                continue
            sidecar_removed = delete_json_sidecar(f)
            if not sidecar_removed:
                failed += 1
            remove_cached_media_derivatives(BATCHES_DIR, batch_name, "rejects", f.name)
            count += 1
    if count:
        _folder_index.refresh(batch_name, "rejects")
    return jsonify({"success": True, "count": count, "failed": failed})


@app.route("/api/favorites", methods=["GET"])
def api_get_favorites():
    return jsonify({"favorites": resolve_universal_favorites(BATCHES_DIR)})


@app.route("/api/favorites", methods=["POST"])
def api_toggle_universal_favorite():
    data = request.json or {}
    batch = data.get("batch", "")
    filename = data.get("filename", "")
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        return jsonify(toggle_favorite(BATCHES_DIR, batch_name, filename))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/favorites/<batch>", methods=["GET"])
def api_get_batch_favorites(batch):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    return jsonify({"filenames": sorted(get_batch_favorite_filenames(BATCHES_DIR, batch_name))})


@app.route("/api/favorites/<batch>", methods=["POST"])
def api_toggle_batch_favorite(batch):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    data = request.json or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        return jsonify(toggle_favorite(BATCHES_DIR, batch_name, filename))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/publish/export", methods=["POST"])
def api_publish_export():
    data = request.json or {}
    batch = data.get("batch", "")
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    folder = data.get("folder", "")
    filenames = data.get("filenames", [])
    if not isinstance(filenames, list) or not filenames:
        return jsonify({"error": "filenames required"}), 400
    watermark_raw = data.get("watermark")
    result = publish.create_public_copies(
        BATCHES_DIR,
        batch=batch_name,
        folder=folder,
        filenames=[str(name) for name in filenames],
        strip_metadata=bool(data.get("strip_metadata", True)),
        watermark=watermark_raw if isinstance(watermark_raw, dict) else None,
    )
    status = 200 if result.get("exported", 0) > 0 or result.get("failed", 0) == 0 else 400
    return jsonify(result), status


@app.route("/api/public", methods=["GET"])
def api_get_all_public():
    return jsonify({"public": publish.list_all_public(BATCHES_DIR)})


@app.route("/api/public/destinations", methods=["GET"])
def api_public_destinations():
    try:
        result = publish.list_export_directories(
            PUBLIC_EXPORT_ROOT,
            path=request.args.get("path", ""),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc), "directories": []}), 400
    return jsonify(result)


@app.route("/api/public/<batch>", methods=["GET"])
def api_get_batch_public(batch):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    return jsonify(publish.list_batch_public(BATCHES_DIR, batch_name))


def _public_items_payload() -> tuple[list[dict], tuple[dict, int] | None]:
    data = request.json or {}
    items = data.get("items", [])
    if not isinstance(items, list) or not items:
        return [], ({"error": "items required"}, 400)
    if any(not isinstance(item, dict) for item in items):
        return [], ({"error": "items must be objects"}, 400)
    return items, None


def _public_export_root_error_response(result: dict, action_key: str) -> tuple[dict, int] | None:
    if result.get("failed") and not result.get(action_key):
        files = result.get("files") or []
        first_error = files[0].get("error") if files else None
        if first_error == "Public export root is not configured":
            return {"error": first_error, **result}, 400
    return None


def _public_transfer_status(result: dict, action_key: str) -> int:
    if result.get(action_key, 0) == 0 and result.get("failed", 0):
        return 400
    return 200


@app.route("/api/public/copy", methods=["POST"])
def api_copy_public():
    data = request.json or {}
    items, err = _public_items_payload()
    if err:
        return jsonify(err[0]), err[1]
    destination = data.get("destination", "")
    if not destination:
        return jsonify({"error": "destination required"}), 400
    result = publish.copy_public_items(
        BATCHES_DIR,
        destination=destination,
        items=items,
        export_root=PUBLIC_EXPORT_ROOT,
    )
    export_root_error = _public_export_root_error_response(result, "copied")
    if export_root_error:
        return jsonify(export_root_error[0]), export_root_error[1]
    return jsonify(result), _public_transfer_status(result, "copied")


@app.route("/api/public/move", methods=["POST"])
def api_move_public():
    data = request.json or {}
    items, err = _public_items_payload()
    if err:
        return jsonify(err[0]), err[1]
    destination = data.get("destination", "")
    if not destination:
        return jsonify({"error": "destination required"}), 400
    result = publish.move_public_items(
        BATCHES_DIR,
        destination=destination,
        items=items,
        export_root=PUBLIC_EXPORT_ROOT,
    )
    export_root_error = _public_export_root_error_response(result, "moved")
    if export_root_error:
        return jsonify(export_root_error[0]), export_root_error[1]
    return jsonify(result), _public_transfer_status(result, "moved")


@app.route("/api/public/delete", methods=["POST"])
def api_delete_public():
    items, err = _public_items_payload()
    if err:
        return jsonify(err[0]), err[1]
    result = publish.delete_public_items(BATCHES_DIR, items=items)
    return jsonify(result), _public_transfer_status(result, "deleted")


@app.route("/api/prompt-history/<batch>/build", methods=["POST"])
def api_build_prompt_history(batch):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    try:
        return jsonify(build_prompt_index(BATCHES_DIR, batch_name))
    except Exception as e:
        logger.exception("Prompt history build failed for %s", batch_name)
        return jsonify({"error": str(e)}), 500


@app.route("/api/prompt-history/<batch>", methods=["GET"])
def api_get_prompt_history(batch):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    index = load_prompt_index(BATCHES_DIR, batch_name)
    if index is None:
        return jsonify({"error": "prompt history not built"}), 404
    if request.args.get("check_stale", "").lower() == "true":
        current_count = count_prompt_index_images(BATCHES_DIR, batch_name)
        index = dict(index)
        index["stale"] = current_count != index.get("image_count")
        index["current_image_count"] = current_count
    return jsonify(index)


@app.route("/api/prompt-history", methods=["GET"])
def api_get_all_prompt_history():
    return jsonify(load_all_prompt_indices(BATCHES_DIR))


@app.route("/api/search-index/<batch>/build", methods=["POST"])
def api_build_search_index(batch):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    try:
        return jsonify(summarize_search_index(build_search_index(BATCHES_DIR, batch_name)))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Search index build failed for %s", batch_name)
        return jsonify({"error": "Search index build failed"}), 500


@app.route("/api/search", methods=["GET"])
def api_search():
    query = request.args.get("q", "")
    batch = request.args.get("batch") or None
    folder = request.args.get("folder") or None
    if batch:
        batch, err = _require_batch(batch)
        if err:
            return jsonify(err[0]), err[1]
    if folder and folder not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid folder"}), 400
    try:
        limit = int(request.args.get("limit", "200"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid pagination"}), 400
    result = query_search_indices(
        BATCHES_DIR,
        query,
        batch=batch,
        folder=folder,
        limit=limit,
        offset=offset,
        snapshot=request.args.get("snapshot") or None,
    )
    return jsonify(result), (409 if result.get("snapshot_expired") else 200)


@app.route("/thumb/<batch>/<folder>/<filename>")
def serve_thumbnail(batch, folder, filename):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if not _is_viewable_folder(folder):
        return jsonify({"error": "Invalid folder"}), 400
    filepath, err = _safe_path(get_batch_content_folder(batch_name, folder), filename)
    if err:
        return jsonify({"error": err}), 400
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    kind = batch_store.media_kind(filepath)
    if kind is None:
        return jsonify({"error": "Invalid file type"}), 400

    cache_path = thumbnail_cache_path(BATCHES_DIR, batch_name, folder, filename)

    fresh = (
        thumbnail_is_fresh(cache_path, filepath, THUMB_SIZE)
        if kind in {"image", "animated_image"}
        else media_cache_is_fresh(cache_path, filepath)
    )
    if fresh:
        resp = send_file(str(cache_path), mimetype="image/webp", max_age=3600)
        resp.headers["Cache-Control"] = "public, max-age=3600, immutable"
        return resp

    try:
        generate_media_poster(filepath, cache_path, THUMB_SIZE, media_kind=kind)
        resp = send_file(str(cache_path), mimetype="image/webp", max_age=3600)
        resp.headers["Cache-Control"] = "public, max-age=3600, immutable"
        return resp
    except Exception:
        print(f"Thumbnail generation failed for {filepath}", flush=True)
        return jsonify({"error": "Failed to generate thumbnail"}), 500


def _folder_snapshot_request(batch: str, folder: str):
    batch_name, err = _require_batch(batch)
    if err:
        return None, None, None, None, None, (jsonify(err[0]), err[1])
    if folder not in batch_store.BATCH_FOLDERS:
        return None, None, None, None, None, (jsonify({"error": "Invalid folder"}), 400)
    sort_by = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    if sort_by not in ("date", "name", "shuffle"):
        sort_by = "date"
    if order not in ("asc", "desc"):
        order = "desc"
    try:
        shuffle_seed = normalize_shuffle_seed(sort_by, request.args.get("shuffle_seed", ""))
    except ValueError:
        return None, None, None, None, None, (jsonify({"error": "Invalid shuffle seed"}), 400)
    return batch_name, get_batch_folder(batch_name, folder), sort_by, order, shuffle_seed, None


@app.route("/api/v2/folders/<batch>/<folder>/snapshot")
def api_v2_folder_snapshot(batch, folder):
    batch_name, directory, sort_by, order, shuffle_seed, error = _folder_snapshot_request(
        batch, folder
    )
    if error:
        return error
    payload = _folder_index.request_snapshot(
        batch_name, folder, directory, sort_by, order, shuffle_seed
    )
    return jsonify(payload), (200 if payload["status"] == "ready" else 202)


@app.route("/api/v2/folders/<batch>/<folder>/poll")
def api_v2_folder_poll(batch, folder):
    batch_name, directory, sort_by, order, shuffle_seed, error = _folder_snapshot_request(
        batch, folder
    )
    if error:
        return error
    payload = _folder_index.poll(
        batch_name,
        folder,
        directory,
        sort_by,
        order,
        request.args.get("revision"),
        shuffle_seed,
    )
    return jsonify(payload), (200 if payload["status"] == "ready" else 202)


@app.route("/api/v2/folders/<batch>/<folder>/items")
def api_v2_folder_items(batch, folder):
    batch_name, _directory, sort_by, order, shuffle_seed, error = _folder_snapshot_request(
        batch, folder
    )
    if error:
        return error
    revision = request.args.get("revision", "")
    try:
        offset = int(request.args.get("offset", "0"))
        limit = int(request.args.get("limit", str(DEFAULT_PAGE_SIZE)))
    except ValueError:
        return jsonify({"error": "Invalid page range"}), 400
    payload = _folder_index.page(
        batch_name,
        folder,
        sort_by,
        order,
        revision,
        offset,
        limit,
        get_batch_favorite_filenames(BATCHES_DIR, batch_name),
        shuffle_seed,
    )
    if payload is None:
        return jsonify({"error": "Snapshot revision is stale"}), 409
    return jsonify(payload)


@app.route("/api/v2/folders/<batch>/<folder>/lookup")
def api_v2_folder_lookup(batch, folder):
    batch_name, _directory, sort_by, order, shuffle_seed, error = _folder_snapshot_request(
        batch, folder
    )
    if error:
        return error
    revision = request.args.get("revision", "")
    name = request.args.get("name", "")
    try:
        batch_store._validate_name(name, "file name")
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid file name"}), 400
    index = _folder_index.index_of(batch_name, folder, sort_by, order, revision, name, shuffle_seed)
    if index is not None:
        return jsonify({"revision": revision, "index": index})
    current = _folder_index.page(
        batch_name,
        folder,
        sort_by,
        order,
        revision,
        0,
        1,
        shuffle_seed=shuffle_seed,
    )
    if current is None:
        return jsonify({"error": "Snapshot revision is stale"}), 409
    return jsonify({"error": "File not found"}), 404


@app.route("/image/<batch>/<folder>/<filename>")
def serve_image(batch, folder, filename):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if not _is_viewable_folder(folder):
        return jsonify({"error": "Invalid folder"}), 400
    filepath, err = _safe_path(get_batch_content_folder(batch_name, folder), filename)
    if err:
        return jsonify({"error": err}), 400
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    mime = batch_store.media_mime(filepath)
    if mime is None:
        return jsonify({"error": "Invalid file type"}), 400
    resp = send_file(filepath, mimetype=mime, conditional=True, max_age=3600)
    resp.headers["Cache-Control"] = "public, max-age=3600, immutable"
    return resp


@app.route("/preview/<batch>/<folder>/<filename>")
def serve_hover_preview(batch, folder, filename):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if not _is_viewable_folder(folder):
        return jsonify({"error": "Invalid folder"}), 400
    filepath, err = _safe_path(get_batch_content_folder(batch_name, folder), filename)
    if err:
        return jsonify({"error": err}), 400
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    kind = batch_store.media_kind(filepath)
    if kind not in {"animated_image", "video"}:
        return jsonify({"error": "Hover preview unavailable"}), 400
    cache_path = hover_preview_cache_path(BATCHES_DIR, batch_name, folder, filename)
    try:
        if not media_cache_is_fresh(cache_path, filepath) and not generate_hover_preview(
            filepath, cache_path, media_kind=kind
        ):
            return jsonify({"error": "Hover preview unavailable"}), 503
    except (OSError, ValueError):
        return jsonify({"error": "Hover preview unavailable"}), 503
    resp = send_file(cache_path, mimetype="video/mp4", conditional=True, max_age=3600)
    resp.headers["Cache-Control"] = "public, max-age=3600, immutable"
    return resp


# ---------------------------------------------------------------------------
# AI Curation -- queue, scoring worker, and API routes
# ---------------------------------------------------------------------------

# Shared queue and storage instances
_ai_storage = RunStorage(batches_dir=BATCHES_DIR)
_worker_threads: set[threading.Thread] = set()
_worker_lock = threading.Lock()
_shutdown_started = False
_shutdown_lock = threading.Lock()

# How long to wait for in-flight scoring workers to observe a cancellation
# request and exit cleanly before giving up and letting the process die.
_SHUTDOWN_JOIN_TIMEOUT_S = 5.0


def _start_scoring_worker(run_id):
    """Start a scoring worker thread and track it for cleanup."""
    global _worker_threads
    t = threading.Thread(target=_run_scoring_worker, args=(run_id,), daemon=True)
    with _worker_lock:
        _worker_threads.add(t)
        _worker_threads = {wt for wt in _worker_threads if wt.is_alive()}
    t.start()


def _shutdown_workers() -> None:
    """Request cancellation of in-flight AI jobs and join their workers.

    Idempotent: a second call is a no-op. Runs from both ``atexit`` (normal
    interpreter shutdown) and SIGTERM/SIGINT (systemd ``ExecStop`` or Ctrl-C)
    so in-flight scoring work has a chance to finalize as cancelled instead
    of being killed mid-image.
    """
    global _shutdown_started
    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    # Mark every active AI job as cancelling. The scoring loop polls
    # is_cancel_requested() between images, so it will exit at the next
    # checkpoint and call finalize_cancelled() with no results.
    try:
        for run in _ai_queue.list_jobs():
            status = getattr(run, "status", None)
            if status in (JobState.RUNNING, JobState.QUEUED, JobState.CANCELLING):
                _ai_queue.cancel(run.run_id)
    except Exception as e:
        logger.warning("AI job cancel during shutdown raised: %s", e)

    # Give each tracked worker a short window to observe the cancel flag
    # and exit. Anything still alive after the timeout is abandoned --
    # because the threads are daemonised the process can still exit.
    deadline = time.monotonic() + _SHUTDOWN_JOIN_TIMEOUT_S
    with _worker_lock:
        workers = list(_worker_threads)
    for t in workers:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            break
        t.join(timeout=remaining)


def _on_job_promoted(run_id):
    """Callback: start scoring worker when a queued job is promoted to running."""
    _start_scoring_worker(run_id)


# Register shutdown hooks. atexit covers normal interpreter exit; the signal
# handlers cover Ctrl-C in dev and SIGTERM from systemd in production.
atexit.register(_shutdown_workers)


def _shutdown_signal_handler(_signum, _frame) -> None:
    _shutdown_workers()
    sys.exit(0)


for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, _shutdown_signal_handler)
    except (ValueError, OSError):
        # SIGTERM is not installable on Windows in some contexts, and signal
        # handlers cannot be registered from non-main threads. Skip silently.
        pass


_ai_queue = QueueManager(storage=_ai_storage, on_promote=_on_job_promoted)
_ai_client = VisionClient()


def _validate_ai_curate_request(data):
    """Validate an AI curation job submission.

    Returns (validated_params, error_response).
    If validation passes, error_response is None.
    """
    return validate_ai_curate_request(
        data,
        get_batches=get_batches,
        default_model=DEFAULT_MODEL,
        default_top_n=DEFAULT_TOP_N,
        top_n_cap=TOP_N_CAP,
        element_cap=ELEMENT_CAP,
        allowed_source_folders=ALLOWED_SOURCE_FOLDERS,
        allowed_dest_folders=ALLOWED_DEST_FOLDERS,
        allowed_models=AVAILABLE_MODELS,
    )


def _run_scoring_worker(run_id):
    """Background thread that executes scoring for a submitted job.

    Handles the full lifecycle: scoring phase, optional move phase,
    cancellation checks, and completion/failure.
    """
    run = _ai_queue.get_job(run_id)
    if run is None:
        return

    try:
        _run_scoring_worker_inner(run_id, run)
    except Exception as e:
        import traceback

        traceback.print_exc()
        _ai_queue.fail_job(run_id, error_message=f"Unhandled worker error: {e}")


def _run_scoring_worker_inner(run_id, run):
    """Core scoring logic, extracted so the outer handler can catch exceptions."""
    run_scoring_worker_inner(
        run_id=run_id,
        run=run,
        queue=_ai_queue,
        client=_ai_client,
        build_element_list_func=build_element_list,
        get_batch_folder=get_batch_folder,
        find_images_func=find_images,
        score_images_func=score_images,
        move_image_func=batch_store.move_image,
        logger=logger,
    )


app.register_blueprint(
    create_ai_curate_blueprint(
        AiCurateRouteContext(
            get_queue=lambda: _ai_queue,
            get_storage=lambda: _ai_storage,
            start_scoring_worker=_start_scoring_worker,
            validate_request=_validate_ai_curate_request,
            require_batch=_require_batch,
            build_element_list=build_element_list,
            extract_elements=extract_elements,
        )
    )
)


# ---------------------------------------------------------------------------
# Global error handlers -- return JSON for all API errors
# ---------------------------------------------------------------------------


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("index.html"), 404


@app.errorhandler(500)
def internal_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error"}), 500
    return "Internal server error", 500


@app.errorhandler(400)
def bad_request(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Bad request"}), 400
    return "Bad request", 400


@app.errorhandler(Exception)
def unhandled_exception(error):
    import traceback

    traceback.print_exc()
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error"}), 500
    return "Internal server error", 500


if __name__ == "__main__":
    # Create required directories
    try:
        BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Error: cannot create batch directory {BATCHES_DIR}: {e}")
        print("Set IMAGE_CURATOR_BATCHES to a writable location.")
        exit(1)
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Error: cannot create state directory {STATE_FILE.parent}: {e}")
        print("Set IMAGE_CURATOR_STATE to a writable location.")
        exit(1)

    # Bind to localhost by default; use IMAGE_CURATOR_HOST for other interfaces
    host = os.environ.get("IMAGE_CURATOR_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("IMAGE_CURATOR_PORT", "5000"))
    except ValueError:
        port = 5000
    print(f"Starting Image Curator on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
