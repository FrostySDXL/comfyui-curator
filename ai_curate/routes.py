"""Flask Blueprint routes for AI curation APIs."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, request

from .models import JobState


@dataclass(frozen=True)
class AiCurateRouteContext:
    """App-owned dependencies needed by the AI curation HTTP layer."""

    get_queue: Callable[[], Any]
    get_storage: Callable[[], Any]
    start_scoring_worker: Callable[[str], None]
    validate_request: Callable[[dict], tuple[dict | None, tuple[dict, int] | None]]
    require_batch: Callable[[str], tuple[str | None, tuple | None]]
    build_element_list: Callable[[list[str], list[str] | None], list[str]]
    extract_elements: Callable[[str], list[str]]


def create_ai_curate_blueprint(context: AiCurateRouteContext) -> Blueprint:
    """Create the AI curation API Blueprint with app-injected dependencies."""
    bp = Blueprint("ai_curate", __name__, url_prefix="/api/ai-curate")

    @bp.route("/preview-elements", methods=["POST"])
    def api_ai_curate_preview_elements():
        """Preview scoring elements without starting a job.

        Request JSON: ``{"elements": [str, ...], "quality_flags": [str, ...]}``.
        ``quality_flags`` is optional; ``None`` preserves legacy all-quality
        behavior, while an explicit empty list means no optional quality checks.

        Response JSON: ``{"elements": [str, ...], "count": int}``.
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
        elements = context.build_element_list(explicit, quality_flags)

        return jsonify({"elements": elements, "count": len(elements)})

    @bp.route("/jobs", methods=["POST"])
    def api_ai_curate_submit_job():
        """Submit a new AI curation job.

        Request JSON is validated by ``context.validate_request`` and includes
        batch, elements, source folder, top-N, model, move mode, destination,
        and optional ``quality_flags``. Response JSON is ``CurationRun.to_dict()``
        with status ``201``; validation failures preserve existing error shapes.
        """
        data = request.json or {}
        params, error = context.validate_request(data)
        if error:
            return jsonify(error[0]), error[1]

        queue = context.get_queue()
        run = queue.submit(params)

        if run.status == JobState.RUNNING:
            context.start_scoring_worker(run.run_id)

        return jsonify(run.to_dict()), 201

    @bp.route("/jobs", methods=["GET"])
    def api_ai_curate_list_jobs():
        """List current queued/running/completed in-memory jobs.

        Response JSON: ``{"jobs": [CurationRun.to_dict(), ...]}``.
        """
        jobs = context.get_queue().list_jobs()
        return jsonify({"jobs": [j.to_dict() for j in jobs]})

    @bp.route("/jobs/<run_id>", methods=["GET"])
    def api_ai_curate_get_job(run_id):
        """Get status for one in-memory job.

        Response JSON is ``CurationRun.to_dict()`` or ``{"error": "job not found"}``
        with status ``404``.
        """
        run = context.get_queue().get_job(run_id)
        if run is None:
            return jsonify({"error": "job not found"}), 404
        return jsonify(run.to_dict())

    @bp.route("/jobs/<run_id>/cancel", methods=["POST"])
    def api_ai_curate_cancel_job(run_id):
        """Request cancellation for a queued or running AI curation job.

        Response JSON: ``{"success": true}``, ``{"error": "job not found"}``,
        or ``{"error": "cannot cancel job in current state"}``.
        """
        queue = context.get_queue()
        run = queue.get_job(run_id)
        if run is None:
            return jsonify({"error": "job not found"}), 404

        result = queue.cancel(run_id)
        if result:
            return jsonify({"success": True})
        return jsonify({"error": "cannot cancel job in current state"}), 400

    @bp.route("/batches/<batch>/runs", methods=["GET"])
    def api_ai_curate_batch_runs(batch):
        """List persisted run IDs for an existing batch.

        Response JSON: ``{"runs": [run_id, ...]}`` after batch validation.
        """
        batch_name, err = context.require_batch(batch)
        if err:
            return jsonify(err[0]), err[1]
        run_ids = context.get_storage().list_runs(batch_name)
        return jsonify({"runs": run_ids})

    @bp.route("/batches/<batch>/runs/latest", methods=["GET"])
    def api_ai_curate_get_latest_run(batch):
        """Retrieve the latest persisted run for an existing batch.

        Response JSON is ``CurationRun.to_dict()`` or ``{"error": "no runs found"}``
        with status ``404``.
        """
        batch_name, err = context.require_batch(batch)
        if err:
            return jsonify(err[0]), err[1]
        run = context.get_storage().load_latest(batch_name)
        if run is None:
            return jsonify({"error": "no runs found"}), 404
        return jsonify(run.to_dict())

    @bp.route("/batches/<batch>/runs/<run_id>", methods=["GET"])
    def api_ai_curate_get_run(batch, run_id):
        """Retrieve a specific persisted run for an existing batch.

        Response JSON is ``CurationRun.to_dict()`` or ``{"error": "run not found"}``
        with status ``404``.
        """
        batch_name, err = context.require_batch(batch)
        if err:
            return jsonify(err[0]), err[1]
        run = context.get_storage().load_run(batch_name, run_id)
        if run is None:
            return jsonify({"error": "run not found"}), 404
        return jsonify(run.to_dict())

    @bp.route("/batches/<batch>/element-history", methods=["GET"])
    def api_ai_curate_element_history(batch):
        """Return recent unique user element sets for a batch.

        Query parameter: ``limit`` clamped to 1..50, default 10. Response JSON:
        ``{"history": [{"run_id": str, "timestamp": str, "elements": [str, ...]}]}``.
        """
        batch_name, err = context.require_batch(batch)
        if err:
            return jsonify(err[0]), err[1]
        try:
            limit = int(request.args.get("limit", "10"))
        except (ValueError, TypeError):
            limit = 10
        limit = max(1, min(limit, 50))

        storage = context.get_storage()
        run_ids = storage.list_runs(batch_name)
        history = []
        seen = set()
        for run_id in reversed(run_ids):
            if len(history) >= limit:
                break
            run = storage.load_run(batch_name, run_id)
            if run is None or not run.elements:
                continue
            # Only include user-provided elements (exclude quality defaults).
            user_elements = [e for e in run.elements if e not in context.extract_elements("")]
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

    return bp
