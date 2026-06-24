"""
Image Curator v2 - Batch-based organization with auto-import
Web UI for reviewing and organizing AI-generated images.
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
from image_curator.png_metadata import extract_png_metadata
from image_curator.media import generate_thumbnail, thumbnail_cache_path, thumbnail_is_fresh
from image_curator.prompt_history import (
    build_prompt_index,
    count_prompt_index_images,
    load_all_prompt_indices,
    load_prompt_index,
)
from image_curator.watcher import ImageWatcher as _ImageWatcher
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
POLL_INTERVAL = 2  # seconds
ENABLE_WATCHER = os.environ.get("IMAGE_CURATOR_ENABLE_WATCHER", "").strip().lower() == "true"
_PUBLIC_EXPORT_ROOT_RAW = os.environ.get("IMAGE_CURATOR_PUBLIC_EXPORTS", "").strip()
PUBLIC_EXPORT_ROOT = Path(_PUBLIC_EXPORT_ROOT_RAW).expanduser() if _PUBLIC_EXPORT_ROOT_RAW else None

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
    """Import all pending images from comfyui-outputs to a batch's inbox.

    Resets the watcher's seen-files set so any pre-existing files are
    re-discovered on the next watcher tick. Uses the public ``reset_seen``
    method instead of touching the watcher's private lock directly so
    the coupling is explicit and stays correct if the watcher changes.
    """
    count = batch_store.import_all_pending(COMFYUI_OUTPUT, BATCHES_DIR, batch_name)
    watcher.reset_seen()
    return count


class ImageWatcher(_ImageWatcher):
    """Compatibility wrapper using app-level dependencies."""

    def __init__(self) -> None:
        super().__init__(
            comfyui_output=lambda: COMFYUI_OUTPUT,
            image_extensions=IMAGE_EXTENSIONS,
            load_state=load_state,
            get_batch_folder=get_batch_folder,
            move_image=batch_store.move_image,
            poll_interval=POLL_INTERVAL,
        )


watcher = ImageWatcher()


@app.route("/")
def index():
    return render_template(
        "index.html",
        available_models=AVAILABLE_MODELS,
        default_model=DEFAULT_MODEL,
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
            {"name": img.name, "size": img.stat().st_size, "favorite": img.name in fav_set}
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

    return jsonify(extract_png_metadata(filepath))


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
    return jsonify({"success": True})


@app.route("/api/move-batch", methods=["POST"])
def api_move_batch():
    data = request.json or {}
    batch = data.get("batch")
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    filenames = data.get("filenames", [])
    source = data.get("source")
    destination = data.get("destination")

    if not all([batch_name, filenames, source, destination]):
        return jsonify({"error": "Missing parameters"}), 400

    if source not in batch_store.BATCH_FOLDERS or destination not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid source or destination folder"}), 400

    moved = 0
    skipped = 0
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
        moved, skipped_in_loop = batch_store.move_images(
            source_dir=source_dir,
            names=valid_filenames,
            dest_dir=dest_dir,
        )
        skipped += skipped_in_loop
    if moved == 0 and filenames:
        # Zero files moved is a legitimate no-op (e.g. all requested files
        # were already in the destination or no longer exist), not a client
        # error. Surface success=False so the UI can show a hint, but keep
        # a 200 status so callers don't treat this as a 4xx failure.
        return jsonify({"success": False, "moved": 0, "skipped": skipped})
    return jsonify({"success": True, "moved": moved, "skipped": skipped})


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
        if f.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                f.unlink()
            except OSError:
                failed += 1
                continue
            # Remove cached thumbnail too
            cache_file = thumbnail_cache_path(BATCHES_DIR, batch_name, "rejects", f.name)
            if cache_file.exists():
                try:
                    cache_file.unlink()
                except OSError:
                    pass
            count += 1
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

    cache_path = thumbnail_cache_path(BATCHES_DIR, batch_name, folder, filename)

    if thumbnail_is_fresh(cache_path, filepath, THUMB_SIZE):
        resp = send_file(str(cache_path), mimetype="image/webp", max_age=3600)
        resp.headers["Cache-Control"] = "public, max-age=3600, immutable"
        return resp

    try:
        generate_thumbnail(filepath, cache_path, THUMB_SIZE)
        resp = send_file(str(cache_path), mimetype="image/webp", max_age=3600)
        resp.headers["Cache-Control"] = "public, max-age=3600, immutable"
        return resp
    except Exception:
        print(f"Thumbnail generation failed for {filepath}", flush=True)
        return jsonify({"error": "Failed to generate thumbnail"}), 500


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
    resp = send_file(filepath, max_age=3600)
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

    # Stop accepting new watcher callbacks first so an in-progress watcher
    # tick cannot race with the directory move we may issue below.
    try:
        watcher.stop()
    except Exception as e:
        logger.warning("Watcher stop raised during shutdown: %s", e)

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

for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, lambda signum, _frame: (_shutdown_workers(), sys.exit(0)))
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


@app.route("/api/ai-curate/preview-elements", methods=["POST"])
def api_ai_curate_preview_elements():
    """Preview the combined element list before scoring.

    Request body:
        {"elements": ["elem1", "elem2"], "quality_flags": ["anatomy"]}

    Returns:
        {"elements": ["elem1", "elem2", "Clean anatomy ..."], "count": N}
    """
    data = request.json or {}
    explicit = data.get("elements")
    if not explicit or not isinstance(explicit, list):
        return jsonify({"error": "elements is required (list of strings)"}), 400
    explicit = [str(e).strip() for e in explicit if str(e).strip()]
    if not explicit:
        return jsonify({"error": "elements must contain at least one non-empty entry"}), 400

    quality_flags = data.get("quality_flags")
    if quality_flags is not None and not isinstance(quality_flags, list):
        return jsonify({"error": "quality_flags must be a list of strings"}), 400
    elements = build_element_list(explicit, quality_flags)

    return jsonify({"elements": elements, "count": len(elements)})


@app.route("/api/ai-curate/jobs", methods=["POST"])
def api_ai_curate_submit_job():
    """Submit a new AI curation job.

    Request body:
        {
            "batch": "batch-name",
            "prompt": "description",
            "source_folder": "inbox",
            "elements": null,
            "top_n": 15,
            "model": "your-model-name",
            "move_enabled": false,
            "destination_folder": null
        }

    Returns:
        {"run_id": "...", "status": "running"|"queued", ...}
    """
    data = request.json or {}
    params, error = _validate_ai_curate_request(data)
    if error:
        return jsonify(error[0]), error[1]

    run = _ai_queue.submit(params)

    # If the job is running, start the scoring worker via the shared helper
    if run.status == JobState.RUNNING:
        _start_scoring_worker(run.run_id)

    return jsonify(run.to_dict()), 201


@app.route("/api/ai-curate/jobs", methods=["GET"])
def api_ai_curate_list_jobs():
    """List all current AI curation jobs.

    Returns:
        {"jobs": [...]}
    """
    jobs = _ai_queue.list_jobs()
    return jsonify({"jobs": [j.to_dict() for j in jobs]})


@app.route("/api/ai-curate/jobs/<run_id>", methods=["GET"])
def api_ai_curate_get_job(run_id):
    """Get status of a specific AI curation job.

    Returns:
        Full CurationRun dict or 404.
    """
    run = _ai_queue.get_job(run_id)
    if run is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(run.to_dict())


@app.route("/api/ai-curate/jobs/<run_id>/cancel", methods=["POST"])
def api_ai_curate_cancel_job(run_id):
    """Cancel a queued or running AI curation job.

    Cancellation during scoring discards all results.
    Cancellation during move phase is not allowed in v1.

    Returns:
        {"success": true} or error.
    """
    run = _ai_queue.get_job(run_id)
    if run is None:
        return jsonify({"error": "job not found"}), 404

    result = _ai_queue.cancel(run_id)
    if result:
        # If the job was running and is now in CANCELLING state,
        # the scoring worker will detect it and finalize.
        # If it was queued, it's immediately CANCELLED.
        return jsonify({"success": True})
    else:
        return jsonify({"error": "cannot cancel job in current state"}), 400


@app.route("/api/ai-curate/batches/<batch>/runs", methods=["GET"])
def api_ai_curate_batch_runs(batch):
    """List historical AI curation runs for a batch.

    Returns:
        {"runs": ["run001", "run002", ...]}
    """
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    run_ids = _ai_storage.list_runs(batch_name)
    return jsonify({"runs": run_ids})


@app.route("/api/ai-curate/batches/<batch>/runs/latest", methods=["GET"])
def api_ai_curate_get_latest_run(batch):
    """Retrieve the most recent historical run for a batch.

    Returns:
        Full CurationRun dict or 404.
    """
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    run = _ai_storage.load_latest(batch_name)
    if run is None:
        return jsonify({"error": "no runs found"}), 404
    return jsonify(run.to_dict())


@app.route("/api/ai-curate/batches/<batch>/runs/<run_id>", methods=["GET"])
def api_ai_curate_get_run(batch, run_id):
    """Retrieve a specific historical run for a batch.

    Returns:
        Full CurationRun dict or 404.
    """
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    run = _ai_storage.load_run(batch_name, run_id)
    if run is None:
        return jsonify({"error": "run not found"}), 404
    return jsonify(run.to_dict())


@app.route("/api/ai-curate/batches/<batch>/element-history", methods=["GET"])
def api_ai_curate_element_history(batch):
    """Return recent unique element sets for a batch (deduped by content).

    Query params:
        limit: max entries to return (default 10)

    Returns:
        {"history": [{"run_id": "...", "timestamp": "...", "elements": [...]}, ...]}
    """
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    try:
        limit = int(request.args.get("limit", "10"))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(limit, 50))

    run_ids = _ai_storage.list_runs(batch_name)
    history = []
    seen = set()
    for run_id in reversed(run_ids):
        if len(history) >= limit:
            break
        run = _ai_storage.load_run(batch_name, run_id)
        if run is None or not run.elements:
            continue
        # Only include user-provided elements (exclude quality defaults)
        user_elements = [
            e
            for e in run.elements
            if e not in extract_elements("")  # quality-only extraction yields the defaults
        ]
        if not user_elements:
            continue
        key = "\n".join(sorted(user_elements))
        if key in seen:
            continue
        seen.add(key)
        history.append(
            {
                "run_id": run.run_id,
                "timestamp": run.created_at or "",
                "elements": user_elements,
            }
        )
    return jsonify({"history": history})


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

    # Start the ComfyUI auto-import watcher (disabled by default; opt-in via env var)
    if ENABLE_WATCHER:
        if COMFYUI_OUTPUT.exists():
            watcher.start()
            print(f"Image watcher started (watching {COMFYUI_OUTPUT})")
        else:
            print(
                f"Image watcher skipped: {COMFYUI_OUTPUT} does not exist. "
                "Set IMAGE_CURATOR_COMFYUI to enable auto-import."
            )
    else:
        print("Image watcher disabled. Set IMAGE_CURATOR_ENABLE_WATCHER=true to enable.")

    # Bind to localhost by default; use IMAGE_CURATOR_HOST for other interfaces
    host = os.environ.get("IMAGE_CURATOR_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("IMAGE_CURATOR_PORT", "5000"))
    except ValueError:
        port = 5000
    print(f"Starting Image Curator on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
