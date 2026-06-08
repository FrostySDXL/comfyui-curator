"""
Image Curator v2 - Batch-based organization with auto-import
Web UI for reviewing and organizing AI-generated images.
"""

import os
import logging
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template, send_file, jsonify, request
from PIL import Image
from image_curator import batch_store
from image_curator.png_metadata import extract_png_metadata

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
from ai_curate.models import CurationRun, ImageResult, JobState, RunTotals
from ai_curate.client import VisionClient
from ai_curate.scoring import score_images, find_images
from ai_curate.storage import RunStorage
from ai_curate.queue import QueueManager

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
THUMB_SIZE = (200, 200)
IMAGE_EXTENSIONS = batch_store.IMAGE_EXTENSIONS
POLL_INTERVAL = 2  # seconds
ENABLE_WATCHER = os.environ.get("IMAGE_CURATOR_ENABLE_WATCHER", "").strip().lower() == "true"

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

    Acquires the watcher's seen-files lock to prevent races between
    the background watcher and this manual import call.
    """
    with watcher._seen_lock:
        count = batch_store.import_all_pending(COMFYUI_OUTPUT, BATCHES_DIR, batch_name)
        # Reset watcher's seen files since we moved everything
        watcher.seen_files = set()
    return count


# Background watcher for auto-importing images
class ImageWatcher:
    def __init__(self):
        self.running = False
        self.thread = None
        self._seen_lock = threading.Lock()
        self.seen_files: set[str] = set()
        # Initialize with existing files so we don't import old images on startup
        if COMFYUI_OUTPUT.exists():
            self.seen_files = {
                f.name for f in COMFYUI_OUTPUT.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS
            }

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Signal the watcher to stop and wait for the current iteration."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

    def reset_seen(self):
        """Clear the seen-files set after a manual import.

        External callers (e.g. import_all_pending) must be able to
        reset tracking without touching internal state directly.
        """
        with self._seen_lock:
            self.seen_files = set()

    def _watch_loop(self):
        while self.running:
            try:
                self._check_for_new_images()
            except Exception as e:
                print(f"Watcher error: {e}")
            time.sleep(POLL_INTERVAL)

    def _check_for_new_images(self):
        state = load_state()
        active_batch = state.get("active_batch")

        if not active_batch or not COMFYUI_OUTPUT.exists():
            return

        dest_inbox = get_batch_folder(active_batch, "inbox")
        if not dest_inbox.exists():
            return

        current_files = {
            f.name for f in COMFYUI_OUTPUT.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS
        }
        with self._seen_lock:
            new_files = current_files - self.seen_files

        for filename in new_files:
            src = COMFYUI_OUTPUT / filename
            if not src.exists():
                continue
            # Wait for file-size stability (file still being written)
            for _ in range(10):
                if not src.exists():
                    break
                size1 = src.stat().st_size
                time.sleep(0.1)
                if not src.exists():
                    break
                if src.stat().st_size == size1 and size1 > 0:
                    break
            if src.exists():
                try:
                    dst = dest_inbox / filename
                    shutil.move(str(src), str(dst))
                    print(f"Auto-imported: {filename} -> {active_batch}/inbox")
                except Exception as e:
                    print(f"Failed to move {filename}: {e}")

        # Update seen files under lock
        with self._seen_lock:
            self.seen_files = (
                {f.name for f in COMFYUI_OUTPUT.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS}
                if COMFYUI_OUTPUT.exists()
                else set()
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
    try:
        resolved = (base / Path(*parts)).resolve()
    except (ValueError, OSError, TypeError):
        return None, "Invalid path"
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        return None, "Invalid path"
    return resolved, None


def _require_batch(batch_name: str) -> tuple[str | None, tuple | None]:
    """Validate that a batch name refers to an existing batch.

    Returns (batch_name, None) if valid, (None, (error_response, status_code)) if invalid.
    """
    if not batch_name or batch_name not in get_batches():
        return None, ({"error": "Batch does not exist"}, 404)
    return batch_name, None


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
    return jsonify(
        [{"name": img.name, "size": img.stat().st_size} for img in images if img.exists()]
    )


@app.route("/api/image-metadata/<batch>/<folder>/<filename>")
def api_image_metadata(batch, folder, filename):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if folder not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid folder"}), 400

    filepath, err = _safe_path(get_batch_folder(batch_name, folder), filename)
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

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src_path), str(dst_path))
    except OSError as e:
        return jsonify({"error": str(e)}), 500
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
    for filename in filenames:
        src_path, err = _safe_path(get_batch_folder(batch_name, source), filename)
        if err:
            continue
        dst_path, err = _safe_path(get_batch_folder(batch_name, destination), filename)
        if err:
            continue
        if src_path.exists():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src_path), str(dst_path))
                moved += 1
            except OSError:
                skipped += 1
        else:
            skipped += 1
    if moved == 0 and filenames:
        return (
            jsonify({"success": False, "moved": 0, "error": "No files could be moved"}),
            400,
        )
    return jsonify({"success": True, "moved": moved})


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
    cache_dir = BATCHES_DIR / batch_name / ".thumbs"
    for f in rejects_dir.iterdir():
        if f.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                f.unlink()
            except OSError:
                failed += 1
                continue
            # Remove cached thumbnail too
            cache_file = cache_dir / (f.stem + ".webp")
            if cache_file.exists():
                try:
                    cache_file.unlink()
                except OSError:
                    pass
            count += 1
    return jsonify({"success": True, "count": count, "failed": failed})


@app.route("/thumb/<batch>/<folder>/<filename>")
def serve_thumbnail(batch, folder, filename):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if folder not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid folder"}), 400
    filepath, err = _safe_path(get_batch_folder(batch_name, folder), filename)
    if err:
        return jsonify({"error": err}), 400
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    # Thumbnail caching: WebP at 200px for minimal storage (~5KB each)
    # Per-batch cache so thumbs survive folder moves within a batch
    cache_dir = BATCHES_DIR / batch_name / ".thumbs"
    cache_path = cache_dir / (Path(filename).stem + ".webp")

    if cache_path.exists() and cache_path.stat().st_mtime >= filepath.stat().st_mtime:
        resp = send_file(str(cache_path), mimetype="image/webp", max_age=3600)
        resp.headers['Cache-Control'] = 'public, max-age=3600, immutable'
        return resp

    try:
        with Image.open(filepath) as img:
            img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
            cache_dir.mkdir(parents=True, exist_ok=True)
            img.save(str(cache_path), format="WEBP", quality=60)
        resp = send_file(str(cache_path), mimetype="image/webp", max_age=3600)
        resp.headers['Cache-Control'] = 'public, max-age=3600, immutable'
        return resp
    except Exception:
        print(f"Thumbnail generation failed for {filepath}", flush=True)
        return jsonify({"error": "Failed to generate thumbnail"}), 500


@app.route("/image/<batch>/<folder>/<filename>")
def serve_image(batch, folder, filename):
    batch_name, err = _require_batch(batch)
    if err:
        return jsonify(err[0]), err[1]
    if folder not in batch_store.BATCH_FOLDERS:
        return jsonify({"error": "Invalid folder"}), 400
    filepath, err = _safe_path(get_batch_folder(batch_name, folder), filename)
    if err:
        return jsonify({"error": err}), 400
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    resp = send_file(filepath, max_age=3600)
    resp.headers['Cache-Control'] = 'public, max-age=3600, immutable'
    return resp


# ---------------------------------------------------------------------------
# AI Curation -- queue, scoring worker, and API routes
# ---------------------------------------------------------------------------

# Shared queue and storage instances
_ai_storage = RunStorage(batches_dir=BATCHES_DIR)
_worker_threads: set[threading.Thread] = set()
_worker_lock = threading.Lock()


def _start_scoring_worker(run_id):
    """Start a scoring worker thread and track it for cleanup."""
    global _worker_threads
    t = threading.Thread(target=_run_scoring_worker, args=(run_id,), daemon=True)
    with _worker_lock:
        _worker_threads.add(t)
        _worker_threads = {wt for wt in _worker_threads if wt.is_alive()}
    t.start()


def _on_job_promoted(run_id):
    """Callback: start scoring worker when a queued job is promoted to running."""
    _start_scoring_worker(run_id)


_ai_queue = QueueManager(storage=_ai_storage, on_promote=_on_job_promoted)
_ai_client = VisionClient()


def _validate_ai_curate_request(data):
    """Validate an AI curation job submission.

    Returns (validated_params, error_response).
    If validation passes, error_response is None.
    """
    batch = data.get("batch", "").strip()
    if not batch:
        return None, ({"error": "batch is required"}, 400)
    if batch not in get_batches():
        return None, ({"error": f"batch '{batch}' does not exist"}, 400)

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return None, ({"error": "prompt is required"}, 400)

    source_folder = data.get("source_folder", "inbox")
    if source_folder not in ALLOWED_SOURCE_FOLDERS:
        return None, (
            {"error": f"source_folder must be one of {sorted(ALLOWED_SOURCE_FOLDERS)}"},
            400,
        )

    # Elements: optional explicit list, otherwise auto-extracted
    elements = data.get("elements")
    if elements is not None:
        if not isinstance(elements, list):
            return None, ({"error": "elements must be a list of strings"}, 400)
        if len(elements) > ELEMENT_CAP:
            return None, ({"error": f"too many elements (max {ELEMENT_CAP})"}, 400)
        elements = [str(e).strip() for e in elements if str(e).strip()]

    # top_n validation
    top_n = data.get("top_n", DEFAULT_TOP_N)
    try:
        top_n = int(top_n)
    except (ValueError, TypeError):
        return None, ({"error": "top_n must be an integer"}, 400)
    if top_n < 1 or top_n > TOP_N_CAP:
        return None, ({"error": f"top_n must be between 1 and {TOP_N_CAP}"}, 400)

    # Move mode validation
    move_enabled = bool(data.get("move_enabled", False))
    destination_folder = data.get("destination_folder")
    if move_enabled:
        if not destination_folder or destination_folder not in ALLOWED_DEST_FOLDERS:
            return None, (
                {
                    "error": f"destination_folder is required when move_enabled and must be one of {sorted(ALLOWED_DEST_FOLDERS)}"
                },
                400,
            )

    model = (data.get("model") or DEFAULT_MODEL or "").strip()
    if not model:
        return None, (
            {"error": "model is required — set IMAGE_CURATOR_MODEL or pass model in request"},
            400,
        )

    params = {
        "batch": batch,
        "prompt": prompt,
        "source_folder": source_folder,
        "elements": elements,
        "top_n": top_n,
        "move_enabled": move_enabled,
        "destination_folder": destination_folder if move_enabled else None,
        "model": model,
    }
    return params, None


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

    # Determine elements
    if run.elements:
        elements = build_element_list(run.elements)
    else:
        elements = extract_elements(run.prompt)

    # Update run with resolved elements
    run.elements = elements

    # Find images
    image_dir = get_batch_folder(run.batch, run.source_folder)
    image_paths = find_images(image_dir)

    if not image_paths:
        _ai_queue.fail_job(run_id, error_message="No images found in source folder")
        return

    # Scoring phase with cancellation check
    def cancel_check():
        return _ai_queue.is_cancel_requested(run_id)

    progress_counter = {"scored": 0, "failed": 0}

    def on_progress(index, total, result):
        if result.failed:
            progress_counter["failed"] += 1
        else:
            progress_counter["scored"] += 1

    results, total_images = score_images(
        image_dir=image_dir,
        elements=elements,
        client=_ai_client,
        model=run.model,
        progress_callback=on_progress,
        cancel_check=cancel_check,
    )

    # Check if cancelled during scoring
    if _ai_queue.is_cancel_requested(run_id):
        _ai_queue.finalize_cancelled(run_id)
        return

    # If no results (all failed or empty), still complete
    scored = [r for r in results if not r.failed]
    failed = [r for r in results if r.failed]

    # Move phase (only if move_enabled and scoring completed)
    moved = 0
    if run.move_enabled and run.destination_folder:
        # Check if cancelled between scoring and move
        if _ai_queue.is_cancel_requested(run_id):
            _ai_queue.finalize_cancelled(run_id)
            return

        # Only move top-N non-failed images
        scored.sort(key=lambda r: r.score, reverse=True)
        top_results = scored[: run.top_n]

        dest_dir = get_batch_folder(run.batch, run.destination_folder)
        dest_dir.mkdir(parents=True, exist_ok=True)

        for r in top_results:
            if _ai_queue.is_cancel_requested(run_id):
                break
            src_path = image_dir / r.filename
            dst_path = dest_dir / r.filename
            if src_path.exists():
                try:
                    shutil.move(str(src_path), str(dst_path))
                    r.moved_to = str(dst_path)
                    moved += 1
                except Exception as e:
                    print(f"AI curate move error for {r.filename}: {e}")

    # Compute totals
    totals = RunTotals(
        images=total_images,
        scored=len(scored),
        failed=len(failed),
        moved=moved,
    )

    # Check: was cancellation requested during the move loop?
    # If files were already moved, persist partial results as cancelled
    # so the operator has an audit trail of what was moved.
    if _ai_queue.is_cancel_requested(run_id):
        if moved > 0:
            # Persist a cancelled run with partial move information
            _ai_queue.finalize_cancelled(run_id, results=results, totals=totals)
            return
        _ai_queue.finalize_cancelled(run_id)
        return

    # Complete the job; if cancel raced with completion, finalize the cancel instead
    if not _ai_queue.complete_job(run_id, results=results, totals=totals):
        _ai_queue.finalize_cancelled(run_id)


@app.route("/api/ai-curate/preview-elements", methods=["POST"])
def api_ai_curate_preview_elements():
    """Preview extracted elements from a prompt without scoring.

    Request body:
        {"prompt": "wide shot of girl on rooftop at night", "elements": null}
        or
        {"prompt": "...", "elements": ["elem1", "elem2"]}

    Returns:
        {"elements": ["Wide shot framing ...", ...], "count": N}
    """
    data = request.json or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    explicit = data.get("elements")
    if explicit and isinstance(explicit, list):
        elements = build_element_list([str(e).strip() for e in explicit if str(e).strip()])
    else:
        elements = extract_elements(prompt)

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
