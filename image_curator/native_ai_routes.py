"""Aiohttp route adapter for the native AI curation lifecycle.

Registers AI curation routes under /api/curator/ai-curate/* using the
shared ai_curate modules, with queue/storage/validation provided by the
NativeAiLifecycle and batch lookups from NativeCuratorService.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

if __package__ and "." in __package__:
    from ..ai_curate.elements import build_element_list, extract_elements
    from ..ai_curate.job_validation import validate_ai_curate_request
    from ..ai_curate.config import (
        DEFAULT_TOP_N,
        TOP_N_CAP,
        ELEMENT_CAP,
        ALLOWED_SOURCE_FOLDERS,
        ALLOWED_DEST_FOLDERS,
    )
    from ..ai_curate.native_lifecycle import LifecycleShutdownError, ModelNotAllowedError
else:
    from ai_curate.elements import build_element_list, extract_elements
    from ai_curate.job_validation import validate_ai_curate_request
    from ai_curate.config import (
        DEFAULT_TOP_N,
        TOP_N_CAP,
        ELEMENT_CAP,
        ALLOWED_SOURCE_FOLDERS,
        ALLOWED_DEST_FOLDERS,
    )
    from ai_curate.native_lifecycle import LifecycleShutdownError, ModelNotAllowedError

logger = logging.getLogger(__name__)


async def _json_body(request) -> dict[str, Any]:
    """Parse request body as JSON dict, returning {} for malformed payloads."""
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _string_field(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key, "")
    return value if isinstance(value, str) else None


def register_native_ai_routes(app, service, lifecycle) -> None:
    """Register AI curation route handlers on an aiohttp application."""

    # ---- preview-elements ----

    async def preview_elements(request):
        data = await _json_body(request)
        explicit = data.get("elements")
        if not explicit or not isinstance(explicit, list):
            return web.json_response(
                {"error": "elements is required (list of strings)"}, status=400
            )
        explicit = [str(e).strip() for e in explicit if str(e).strip()]
        if not explicit:
            return web.json_response(
                {"error": "elements must contain at least one non-empty entry"},
                status=400,
            )

        quality_flags = data.get("quality_flags")
        if quality_flags is not None and not isinstance(quality_flags, list):
            return web.json_response(
                {"error": "quality_flags must be a list of strings"}, status=400
            )
        elements = build_element_list(explicit, quality_flags)
        return web.json_response({"elements": elements, "count": len(elements)})

    # ---- jobs ----

    async def submit_job(request):
        data = await _json_body(request)
        default_model = lifecycle.settings.default_model
        allowed = list(lifecycle.settings.available_models)
        params, error = validate_ai_curate_request(
            data,
            get_batches=lambda: [b for b in service.batches_payload()["batches"]],
            default_model=default_model,
            default_top_n=DEFAULT_TOP_N,
            top_n_cap=TOP_N_CAP,
            element_cap=ELEMENT_CAP,
            allowed_source_folders=ALLOWED_SOURCE_FOLDERS,
            allowed_dest_folders=ALLOWED_DEST_FOLDERS,
            allowed_models=allowed,
        )
        if error:
            return web.json_response(error[0], status=error[1])

        if lifecycle.queue is None:
            return web.json_response({"error": "AI queue not available"}, status=503)

        try:
            run = lifecycle.submit_job(params)
        except LifecycleShutdownError:
            return web.json_response(
                {"error": "AI curation is shutting down; no new jobs accepted"}, status=503
            )
        except ModelNotAllowedError:
            return web.json_response({"error": "model is not configured"}, status=400)

        return web.json_response(run.to_dict(), status=201)

    async def list_jobs(request):
        if lifecycle.queue is None:
            return web.json_response({"jobs": []})
        try:
            jobs = lifecycle.queue.list_jobs()
        except Exception:
            logger.exception("Error listing AI jobs")
            return web.json_response({"error": "Internal error"}, status=500)
        return web.json_response({"jobs": [j.to_dict() for j in jobs]})

    async def get_job(request):
        run_id = request.match_info["run_id"]
        if lifecycle.queue is None:
            return web.json_response({"error": "AI queue not available"}, status=503)
        try:
            run = lifecycle.queue.get_job(run_id)
        except Exception:
            logger.exception("Error getting AI job %s", run_id)
            return web.json_response({"error": "Internal error"}, status=500)
        if run is None:
            return web.json_response({"error": "job not found"}, status=404)
        return web.json_response(run.to_dict())

    async def cancel_job(request):
        run_id = request.match_info["run_id"]
        if lifecycle.queue is None:
            return web.json_response({"error": "AI queue not available"}, status=503)
        run = lifecycle.queue.get_job(run_id)
        if run is None:
            return web.json_response({"error": "job not found"}, status=404)
        try:
            result = lifecycle.queue.cancel(run_id)
        except Exception:
            logger.exception("Error cancelling AI job %s", run_id)
            return web.json_response({"error": "Internal error"}, status=500)
        if result:
            return web.json_response({"success": True})
        return web.json_response({"error": "cannot cancel job in current state"}, status=400)

    # ---- batch run history ----

    def _validate_batch(batch: str) -> web.Response | None:
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        return None

    async def batch_runs(request):
        batch = request.match_info["batch"]
        err = _validate_batch(batch)
        if err is not None:
            return err
        if lifecycle.storage is None:
            return web.json_response({"error": "AI storage not available"}, status=503)
        try:
            run_ids = lifecycle.storage.list_runs(batch)
        except ValueError:
            return web.json_response({"error": "Batch does not exist"}, status=404)
        except Exception:
            logger.exception("Error listing runs for batch %s", batch)
            return web.json_response({"error": "Internal error"}, status=500)
        return web.json_response({"runs": run_ids})

    async def get_latest_run(request):
        batch = request.match_info["batch"]
        err = _validate_batch(batch)
        if err is not None:
            return err
        if lifecycle.storage is None:
            return web.json_response({"error": "AI storage not available"}, status=503)
        try:
            run = lifecycle.storage.load_latest(batch)
        except ValueError:
            return web.json_response({"error": "Batch does not exist"}, status=404)
        except Exception:
            logger.exception("Error loading latest run for batch %s", batch)
            return web.json_response({"error": "Internal error"}, status=500)
        if run is None:
            return web.json_response({"error": "no runs found"}, status=404)
        return web.json_response(run.to_dict())

    async def get_run(request):
        batch = request.match_info["batch"]
        run_id = request.match_info["run_id"]
        err = _validate_batch(batch)
        if err is not None:
            return err
        if lifecycle.storage is None:
            return web.json_response({"error": "AI storage not available"}, status=503)
        try:
            run = lifecycle.storage.load_run(batch, run_id)
        except ValueError:
            return web.json_response({"error": "run not found"}, status=404)
        except Exception:
            logger.exception("Error loading run %s for batch %s", run_id, batch)
            return web.json_response({"error": "Internal error"}, status=500)
        if run is None:
            return web.json_response({"error": "run not found"}, status=404)
        return web.json_response(run.to_dict())

    async def element_history(request):
        batch = request.match_info["batch"]
        err = _validate_batch(batch)
        if err is not None:
            return err
        if lifecycle.storage is None:
            return web.json_response({"error": "AI storage not available"}, status=503)
        try:
            limit = int(request.query.get("limit", "10"))
        except (ValueError, TypeError):
            limit = 10
        limit = max(1, min(limit, 50))

        try:
            storage = lifecycle.storage
            run_ids = storage.list_runs(batch)
        except ValueError:
            return web.json_response({"error": "Batch does not exist"}, status=404)
        except Exception:
            logger.exception("Error in element history for batch %s", batch)
            return web.json_response({"error": "Internal error"}, status=500)

        history: list[dict[str, Any]] = []
        seen: set[str] = set()
        for run_id in reversed(run_ids):
            if len(history) >= limit:
                break
            try:
                run = storage.load_run(batch, run_id)
            except Exception:
                continue
            if run is None or not run.elements:
                continue
            user_elements = [e for e in run.elements if e not in extract_elements("")]
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
        return web.json_response({"history": history})

    # ---- register all routes ----

    app.router.add_post("/api/curator/ai-curate/preview-elements", preview_elements)
    app.router.add_post("/api/curator/ai-curate/jobs", submit_job)
    app.router.add_get("/api/curator/ai-curate/jobs", list_jobs)
    app.router.add_get("/api/curator/ai-curate/jobs/{run_id}", get_job)
    app.router.add_post("/api/curator/ai-curate/jobs/{run_id}/cancel", cancel_job)
    app.router.add_get("/api/curator/ai-curate/batches/{batch}/runs", batch_runs)
    app.router.add_get("/api/curator/ai-curate/batches/{batch}/runs/latest", get_latest_run)
    app.router.add_get("/api/curator/ai-curate/batches/{batch}/runs/{run_id}", get_run)
    app.router.add_get("/api/curator/ai-curate/batches/{batch}/element-history", element_history)
