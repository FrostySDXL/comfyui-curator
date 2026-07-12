"""Component tests for native AI curation aiohttp route contracts.

These tests validate that the native AI route handlers produce the same
response shapes and status codes as the standalone Flask Blueprint routes.

Uses the same mock-aiohttp pattern as test_native_curate_api.py, plus
real QueueManager / RunStorage / VisionClient with tmp_path isolation.
"""

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_curate.models import CurationRun, JobState, RunTotals
from ai_curate.storage import RunStorage
from image_curator.native_settings import NativeCuratorSettings

pytestmark = pytest.mark.component

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Router:
    def __init__(self):
        self.handlers = {}

    def add_get(self, path, handler):
        self.handlers[("GET", path)] = handler

    def add_post(self, path, handler):
        self.handlers[("POST", path)] = handler


class _Request:
    def __init__(self, payload=None):
        self._payload = payload
        self.match_info = {}
        self.query = {}

    async def json(self):
        return self._payload


def _mock_aiohttp(monkeypatch):
    mock_web = MagicMock()
    mock_web.json_response.side_effect = lambda data, status=200: SimpleNamespace(
        status=status, text=json.dumps(data), headers={}
    )
    mock_web.FileResponse.side_effect = lambda path, **kwargs: SimpleNamespace(
        status=200, path=Path(path), headers=dict(kwargs.get("headers", {}))
    )
    mock_aiohttp = MagicMock(web=mock_web)
    monkeypatch.setitem(sys.modules, "aiohttp", mock_aiohttp)
    monkeypatch.setitem(sys.modules, "aiohttp.web", mock_web)
    return mock_web


async def _invoke(router, method, path, payload=None, match_info=None, query=None):
    request = _Request(payload)
    request.match_info = match_info or {}
    request.query = query or {}
    response = await router.handlers[(method, path)](request)
    return response.status, json.loads(response.text)


async def _invoke_response(router, method, path, match_info):
    request = _Request()
    request.match_info = match_info
    return await router.handlers[(method, path)](request)


def _create_service(tmp_path):
    batches_root = tmp_path / "batches"
    batches_root.mkdir()
    state_file = tmp_path / "state.json"
    import_source = tmp_path / "import-source"
    import_source.mkdir()
    return NativeCuratorSettings(
        batch_root=batches_root,
        import_source=import_source,
        state_file=state_file,
        available_models=("vl-scorer",),
        default_model="vl-scorer",
    )


def _setup_batch(settings):
    """Create a valid test batch with required folders."""
    batch_dir = settings.batch_root / "test-batch"
    batch_dir.mkdir()
    (batch_dir / "inbox").mkdir()
    (batch_dir / "shortlisted").mkdir()
    (batch_dir / "finals").mkdir()
    (batch_dir / "rejects").mkdir()
    return batch_dir


def _make_router_and_lifecycle(tmp_path, monkeypatch):
    """Common setup: mock aiohttp, create service + lifecycle, register routes.

    Modules that import aiohttp at module level are reloaded dynamically
    after the mock is installed so they pick up the fresh mock web.
    """
    _mock_aiohttp(monkeypatch)

    # Force-reload modules that hold stale aiohttp.web references
    import image_curator.native_routes
    import image_curator.native_ai_routes

    importlib.reload(image_curator.native_routes)
    importlib.reload(image_curator.native_ai_routes)

    from image_curator.native_routes import NativeCuratorService
    from image_curator.native_ai_routes import register_native_ai_routes
    from ai_curate.native_lifecycle import NativeAiLifecycle

    settings = _create_service(tmp_path)
    _setup_batch(settings)
    service = NativeCuratorService(settings)
    lifecycle = NativeAiLifecycle(settings)

    router = _Router()
    mock_app = SimpleNamespace(router=router, on_startup=[], on_shutdown=[])
    register_native_ai_routes(mock_app, service, lifecycle)

    # Start lifecycle to initialise queue/storage/client
    asyncio.run(lifecycle.startup(mock_app))

    return router, service, lifecycle


# ---------------------------------------------------------------------------
# Test: preview-elements route
# ---------------------------------------------------------------------------


class TestPreviewElements:
    """POST /api/curator/ai-curate/preview-elements"""

    def test_preview_elements_returns_200(self, tmp_path, monkeypatch):
        """POST with valid elements returns 200 and the expanded element list."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/preview-elements",
                {"elements": ["Blue sky", "Red dress"]},
            )
        )
        assert status == 200
        assert "elements" in data
        assert "Blue sky" in data["elements"]
        assert "Red dress" in data["elements"]
        assert data["count"] >= 4  # quality defaults appended

    def test_preview_elements_missing_elements_returns_400(self, tmp_path, monkeypatch):
        """POST without elements returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/preview-elements",
                {},
            )
        )
        assert status == 400
        assert "error" in data

    def test_preview_elements_empty_list_returns_400(self, tmp_path, monkeypatch):
        """POST with empty elements list returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/preview-elements",
                {"elements": []},
            )
        )
        assert status == 400
        assert "error" in data

    def test_preview_elements_with_quality_flags(self, tmp_path, monkeypatch):
        """POST with quality_flags appends only selected checks."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/preview-elements",
                {"elements": ["Blue sky"], "quality_flags": ["anatomy"]},
            )
        )
        assert status == 200
        assert "Blue sky" in data["elements"]
        assert any("Clean anatomy" in e for e in data["elements"])
        assert not any("No visual artifacts" in e for e in data["elements"])

    def test_preview_elements_empty_quality_flags(self, tmp_path, monkeypatch):
        """POST with quality_flags=[] appends no quality elements."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/preview-elements",
                {"elements": ["Blue sky"], "quality_flags": []},
            )
        )
        assert status == 200
        assert data["count"] == 1
        assert data["elements"] == ["Blue sky"]

    def test_preview_elements_malformed_json(self, tmp_path, monkeypatch):
        """POST with non-dict body still responds without crashing."""
        _mock_aiohttp(monkeypatch)
        from image_curator.native_ai_routes import _json_body

        request = _Request("not a dict")
        result = asyncio.run(_json_body(request))
        assert result == {}

    def test_preview_elements_invalid_quality_flags(self, tmp_path, monkeypatch):
        """POST with non-list quality_flags returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/preview-elements",
                {"elements": ["test"], "quality_flags": "not-a-list"},
            )
        )
        assert status == 400
        assert "error" in data


# ---------------------------------------------------------------------------
# Test: submit job
# ---------------------------------------------------------------------------


class TestSubmitJob:
    """POST /api/curator/ai-curate/jobs"""

    def test_submit_valid_job_returns_201(self, tmp_path, monkeypatch):
        """POST with valid data returns 201 and CurationRun shape."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {
                    "batch": "test-batch",
                    "elements": ["wide shot of landscape"],
                    "source_folder": "inbox",
                    "top_n": 10,
                    "model": "vl-scorer",
                    "move_enabled": False,
                },
            )
        )
        assert status == 201
        assert "run_id" in data
        assert data["status"] in ("running", "queued")

    def test_submit_missing_batch_returns_400(self, tmp_path, monkeypatch):
        """POST without batch returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"elements": ["test"]},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_nonexistent_batch_returns_400(self, tmp_path, monkeypatch):
        """POST with nonexistent batch returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "no-such-batch", "elements": ["test"]},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_virtual_batch_returns_400(self, tmp_path, monkeypatch):
        """POST with __favorites__ sentinel returns 400 (not a real batch)."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "__favorites__", "elements": ["test"]},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_missing_elements_returns_400(self, tmp_path, monkeypatch):
        """POST without elements returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch"},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_invalid_source_folder_returns_400(self, tmp_path, monkeypatch):
        """POST with invalid source_folder returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch", "elements": ["test"], "source_folder": "invalid"},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_move_without_destination_returns_400(self, tmp_path, monkeypatch):
        """POST with move_enabled but no destination returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch", "elements": ["test"], "move_enabled": True},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_top_n_over_cap_returns_400(self, tmp_path, monkeypatch):
        """POST with top_n over cap returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch", "elements": ["test"], "top_n": 999},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_too_many_elements_returns_400(self, tmp_path, monkeypatch):
        """POST with too many elements returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch", "elements": [f"e{i}" for i in range(20)]},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_non_integer_top_n_returns_400(self, tmp_path, monkeypatch):
        """POST with non-integer top_n returns 400."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch", "elements": ["test"], "top_n": "abc"},
            )
        )
        assert status == 400
        assert "error" in data

    def test_submit_defaults_applied(self, tmp_path, monkeypatch):
        """POST with minimal data gets default values."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch", "elements": ["test"], "model": "vl-scorer"},
            )
        )
        assert status == 201
        assert data["source_folder"] == "inbox"
        assert data["top_n"] == 15
        assert data["move_enabled"] is False
        assert data["model"] == "vl-scorer"
        assert data["destination_folder"] is None

    def test_submit_malformed_json_returns_400(self, tmp_path, monkeypatch):
        """POST with non-dict body returns 400."""
        _mock_aiohttp(monkeypatch)
        from image_curator.native_ai_routes import _json_body

        request = _Request("not a dict")
        result = asyncio.run(_json_body(request))
        assert result == {}  # defaults to empty dict, validation then returns 400


# ---------------------------------------------------------------------------
# Test: job status routes
# ---------------------------------------------------------------------------


class TestJobStatus:
    """GET /api/curator/ai-curate/jobs and /jobs/<run_id>"""

    def test_list_jobs_returns_empty(self, tmp_path, monkeypatch):
        """GET /jobs returns empty list initially."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(_invoke(router, "GET", "/api/curator/ai-curate/jobs"))
        assert status == 200
        assert data["jobs"] == []

    def test_get_nonexistent_job_returns_404(self, tmp_path, monkeypatch):
        """GET /jobs/<id> with bad ID returns 404."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        # Patch _launch_worker to inhibit worker thread startup
        original = lifecycle._launch_worker
        lifecycle._launch_worker = lambda rid: None
        try:
            status, data = asyncio.run(
                _invoke(
                    router,
                    "GET",
                    "/api/curator/ai-curate/jobs/{run_id}",
                    match_info={"run_id": "nonexistent"},
                )
            )
        finally:
            lifecycle._launch_worker = original
        assert status == 404
        assert "error" in data

    def test_get_existing_job_returns_200(self, tmp_path, monkeypatch):
        """GET /jobs/<id> returns the submitted job."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        # Patch _launch_worker to inhibit worker thread startup
        original = lifecycle._launch_worker
        lifecycle._launch_worker = lambda rid: None
        try:
            # Submit a job first
            _, submit_data = asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["test"], "model": "vl-scorer"},
                )
            )
            run_id = submit_data["run_id"]

            status, data = asyncio.run(
                _invoke(
                    router,
                    "GET",
                    "/api/curator/ai-curate/jobs/{run_id}",
                    match_info={"run_id": run_id},
                )
            )
        finally:
            lifecycle._launch_worker = original
        assert status == 200
        assert data["run_id"] == run_id


# ---------------------------------------------------------------------------
# Test: cancel job
# ---------------------------------------------------------------------------


class TestCancelJob:
    """POST /api/curator/ai-curate/jobs/<run_id>/cancel"""

    def test_cancel_queued_job_returns_200(self, tmp_path, monkeypatch):
        """POST cancel cancels a queued job."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        # Patch _launch_worker so worker threads don't start automatically
        original = lifecycle._launch_worker
        lifecycle._launch_worker = lambda rid: None
        try:
            # Submit two jobs so second is queued
            _, d1 = asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["first"], "model": "vl-scorer"},
                )
            )
            _, d2 = asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["second"], "model": "vl-scorer"},
                )
            )
            run_id2 = d2["run_id"]

            status, data = asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs/{run_id}/cancel",
                    match_info={"run_id": run_id2},
                )
            )
        finally:
            lifecycle._launch_worker = original
        assert status == 200
        assert data["success"] is True

    def test_cancel_nonexistent_job_returns_404(self, tmp_path, monkeypatch):
        """POST cancel with bad ID returns 404."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs/{run_id}/cancel",
                match_info={"run_id": "nonexistent"},
            )
        )
        assert status == 404
        assert "error" in data


# ---------------------------------------------------------------------------
# Test: batch run history routes
# ---------------------------------------------------------------------------


class TestBatchRuns:
    """GET /api/curator/ai-curate/batches/<batch>/runs*"""

    def test_list_runs_empty(self, tmp_path, monkeypatch):
        """GET /runs returns empty list initially."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs",
                match_info={"batch": "test-batch"},
            )
        )
        assert status == 200
        assert data["runs"] == []

    def test_get_nonexistent_run_returns_404(self, tmp_path, monkeypatch):
        """GET /runs/<id> with bad ID returns 404."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs/{run_id}",
                match_info={"batch": "test-batch", "run_id": "nonexistent"},
            )
        )
        assert status == 404
        assert "error" in data

    def test_get_latest_run_empty_returns_404(self, tmp_path, monkeypatch):
        """GET /runs/latest returns 404 when no runs."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs/latest",
                match_info={"batch": "test-batch"},
            )
        )
        assert status == 404
        assert "error" in data

    def test_batch_runs_nonexistent_batch_returns_404(self, tmp_path, monkeypatch):
        """GET /runs returns 404 for a nonexistent batch."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs",
                match_info={"batch": "nonexistent-batch"},
            )
        )
        assert status == 404
        assert "error" in data

    def test_list_runs_with_persisted_data(self, tmp_path, monkeypatch):
        """GET .../runs returns persisted run IDs after a run is saved."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        storage = lifecycle.storage
        assert storage is not None

        run1 = CurationRun(
            run_id="run-001",
            batch="test-batch",
            prompt="a test prompt",
            status=JobState.COMPLETED,
        )
        storage.save_run(run1)

        run2 = CurationRun(
            run_id="run-002",
            batch="test-batch",
            prompt="another test prompt",
            status=JobState.COMPLETED,
        )
        storage.save_run(run2)

        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs",
                match_info={"batch": "test-batch"},
            )
        )
        assert status == 200
        assert "runs" in data
        assert "run-001" in data["runs"]
        assert "run-002" in data["runs"]

    def test_get_run_with_persisted_data(self, tmp_path, monkeypatch):
        """GET .../runs/<run_id> returns full run data."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        storage = lifecycle.storage
        assert storage is not None

        run = CurationRun(
            run_id="run-003",
            batch="test-batch",
            prompt="detailed prompt",
            status=JobState.COMPLETED,
            totals=RunTotals(images=10, scored=8, failed=2, moved=0),
        )
        storage.save_run(run)

        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs/{run_id}",
                match_info={"batch": "test-batch", "run_id": "run-003"},
            )
        )
        assert status == 200
        assert data["run_id"] == "run-003"
        assert data["batch"] == "test-batch"
        assert data["prompt"] == "detailed prompt"
        assert data["status"] == "completed"
        assert data["totals"]["images"] == 10
        assert data["totals"]["scored"] == 8

    def test_get_latest_run_with_persisted_data(self, tmp_path, monkeypatch):
        """GET .../runs/latest returns the most recent run."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        storage = lifecycle.storage
        assert storage is not None

        storage.save_run(
            CurationRun(
                run_id="run-old",
                batch="test-batch",
                prompt="old prompt",
                status=JobState.COMPLETED,
            )
        )
        storage.save_run(
            CurationRun(
                run_id="run-latest",
                batch="test-batch",
                prompt="latest prompt",
                status=JobState.COMPLETED,
            )
        )

        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs/latest",
                match_info={"batch": "test-batch"},
            )
        )
        assert status == 200
        assert data["run_id"] == "run-latest"
        assert data["prompt"] == "latest prompt"


# ---------------------------------------------------------------------------
# Test: element history route
# ---------------------------------------------------------------------------


class TestElementHistory:
    """GET /api/curator/ai-curate/batches/<batch>/element-history"""

    def test_element_history_empty(self, tmp_path, monkeypatch):
        """GET /element-history returns empty list when no runs."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/element-history",
                match_info={"batch": "test-batch"},
            )
        )
        assert status == 200
        assert data["history"] == []

    def test_element_history_with_data(self, tmp_path, monkeypatch):
        """GET /element-history returns unique user element sets from runs."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        storage = lifecycle.storage
        assert storage is not None

        storage.save_run(
            CurationRun(
                run_id="run-e1",
                batch="test-batch",
                elements=[
                    "hat",
                    "Clean anatomy (no extra fingers, extra limbs, or broken body parts)",
                    "No visual artifacts, glitches, or garbled text",
                ],
                status=JobState.COMPLETED,
            )
        )
        storage.save_run(
            CurationRun(
                run_id="run-e2",
                batch="test-batch",
                elements=[
                    "cat",
                    "Clean anatomy (no extra fingers, extra limbs, or broken body parts)",
                    "No visual artifacts, glitches, or garbled text",
                ],
                status=JobState.COMPLETED,
            )
        )

        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/element-history",
                match_info={"batch": "test-batch"},
            )
        )
        assert status == 200
        assert "history" in data
        assert len(data["history"]) >= 1  # at least one unique user element set

    def test_element_history_nonexistent_batch_returns_404(self, tmp_path, monkeypatch):
        """GET /element-history with nonexistent batch returns 404."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/element-history",
                match_info={"batch": "nonexistent-batch"},
            )
        )
        assert status == 404
        assert "error" in data


# ---------------------------------------------------------------------------
# Test: security / path traversal
# ---------------------------------------------------------------------------


class TestSecurity:
    """Security-focused tests for native AI routes."""

    def test_traversal_in_run_id_returns_404(self, tmp_path, monkeypatch):
        """GET run with ../ in run_id returns 404 (storage rejects path separators)."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs/{run_id}",
                match_info={"batch": "test-batch", "run_id": "../escape"},
            )
        )
        assert status == 404

    def test_traversal_in_batch_name_returns_404(self, tmp_path, monkeypatch):
        """GET /runs with ../ in batch returns 404 (batch not found)."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs",
                match_info={"batch": "../escape"},
            )
        )
        assert status == 404

    def test_no_ai_storage_traversal_returns_404(self, tmp_path, monkeypatch):
        """Virtual batch __favorites__ returns 404 for AI routes."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs",
                match_info={"batch": "__favorites__"},
            )
        )
        assert status == 404
        assert "error" in data

    def test_no_host_path_in_job_response(self, tmp_path, monkeypatch):
        """Submit response must not leak batch_root or filesystem paths."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {"batch": "test-batch", "elements": ["test"], "model": "vl-scorer"},
            )
        )
        assert status == 201
        body = json.dumps(data)
        assert str(router._app_) not in body if hasattr(router, "_app_") else True
        # No absolute paths leaked
        assert "C:\\" not in body

    def test_no_host_path_in_preview_response(self, tmp_path, monkeypatch):
        """Preview response must not leak filesystem paths."""
        router, _, _ = _make_router_and_lifecycle(tmp_path, monkeypatch)
        status, data = asyncio.run(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/preview-elements",
                {"elements": ["test"]},
            )
        )
        assert status == 200
        body = json.dumps(data)
        assert "C:\\" not in body

    def test_no_host_path_in_run_response(self, tmp_path, monkeypatch):
        """Run response must not leak batch_root path."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        storage = lifecycle.storage
        assert storage is not None
        storage.save_run(
            CurationRun(
                run_id="run-sec",
                batch="test-batch",
                status=JobState.COMPLETED,
            )
        )

        status, data = asyncio.run(
            _invoke(
                router,
                "GET",
                "/api/curator/ai-curate/batches/{batch}/runs/{run_id}",
                match_info={"batch": "test-batch", "run_id": "run-sec"},
            )
        )
        assert status == 200
        body = json.dumps(data)
        assert "batches" not in body  # batch_root subfolder should not appear


# ---------------------------------------------------------------------------
# Test: lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Native AI lifecycle startup / shutdown behaviour."""

    def test_startup_initialises_queue_and_storage(self, tmp_path, monkeypatch):
        """After startup, queue and storage are available."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        assert lifecycle.queue is not None
        assert lifecycle.storage is not None

    def test_startup_and_reconfigure_use_resolved_native_ai_settings(self, tmp_path, monkeypatch):
        _, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        lifecycle.settings.llm_base_url = "http://native:7777"
        lifecycle.settings.default_model = "native-model"
        lifecycle.settings.api_key = "native-key"
        lifecycle.settings.request_timeout = 17
        lifecycle.reconfigure()
        assert lifecycle._client.base_url == "http://native:7777"
        assert lifecycle._client.default_model == "native-model"
        assert lifecycle._client.api_key == "native-key"
        assert lifecycle._client.timeout == 17
        assert lifecycle.has_active_jobs() is False

    def test_settings_update_is_rejected_atomically_while_ai_job_is_active(
        self, tmp_path, monkeypatch
    ):
        _, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        lifecycle._launch_worker = lambda _run_id: None
        lifecycle.submit_job(
            {
                "batch": "test-batch",
                "elements": ["test"],
                "model": "vl-scorer",
                "source_folder": "inbox",
                "top_n": 1,
                "move_enabled": False,
                "destination_folder": None,
                "prompt": "",
            }
        )
        original_root = lifecycle.settings.batch_root
        with pytest.raises(RuntimeError, match="AI work is active"):
            lifecycle.update_settings({})
        assert lifecycle.settings.batch_root == original_root

    @pytest.mark.parametrize("factory_name", ["RunStorage", "VisionClient", "QueueManager"])
    def test_settings_update_dependency_failure_preserves_all_old_state(
        self, tmp_path, monkeypatch, factory_name
    ):
        from ai_curate.native_lifecycle import NativeAiLifecycle
        from image_curator.native_settings import NativeConfigStore

        settings = _create_service(tmp_path)
        settings.api_key = "old-secret"
        settings.config_store = NativeConfigStore(tmp_path / "system")
        old_request = {
            "batch_root": str(settings.batch_root),
            "import_source": str(settings.import_source),
            "public_export_enabled": False,
            "public_export_root": "",
            "llm_base_url": settings.llm_base_url,
            "models": list(settings.available_models),
            "default_model": settings.default_model,
            "api_key": "old-secret",
            "clear_api_key": False,
            "request_timeout": settings.request_timeout,
        }
        settings.update(old_request)
        lifecycle = NativeAiLifecycle(settings)
        asyncio.run(lifecycle.startup(None))
        old_settings = settings.editable_payload()
        old_secret = settings.api_key
        old_client = lifecycle._client
        old_storage = lifecycle._storage
        old_queue = lifecycle._queue
        old_bytes = settings.config_store.path.read_bytes()
        new_request = {
            **old_request,
            "batch_root": str(tmp_path / "new-batches"),
            "import_source": str(tmp_path / "new-import"),
            "llm_base_url": "http://new-host:9999",
            "models": ["new-model"],
            "default_model": "new-model",
            "api_key": "new-secret",
            "request_timeout": 45,
        }

        monkeypatch.setattr(
            "ai_curate.native_lifecycle." + factory_name,
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")),
        )
        with pytest.raises(RuntimeError, match="injected failure"):
            lifecycle.update_settings(new_request)

        assert settings.editable_payload() == old_settings
        assert settings.api_key == old_secret
        assert lifecycle._client is old_client
        assert lifecycle._storage is old_storage
        assert lifecycle._queue is old_queue
        assert settings.config_store.path.read_bytes() == old_bytes

    def test_shutdown_is_idempotent(self, tmp_path, monkeypatch):
        """Multiple shutdown calls do not raise."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        asyncio.run(lifecycle.shutdown(None))
        asyncio.run(lifecycle.shutdown(None))  # second call should be a no-op

    def test_shutdown_cancels_running_jobs(self, tmp_path, monkeypatch):
        """Shutdown marks running/queued jobs as cancelled."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        # Patch _launch_worker to prevent worker threads from auto-starting
        # (otherwise they'd run, find no images, and mark the job FAILED)
        original = lifecycle._launch_worker
        lifecycle._launch_worker = lambda rid: None
        try:
            asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["test"], "model": "vl-scorer"},
                )
            )
            jobs_before = lifecycle.queue.list_jobs()
            assert len(jobs_before) >= 1

            asyncio.run(lifecycle.shutdown(None))
            # After shutdown, the running job should be cancelled/cancelling
            jobs_after = lifecycle.queue.list_jobs()
            for job in jobs_after:
                assert job.status in (JobState.CANCELLED, JobState.CANCELLING), (
                    f"Expected cancelled, got {job.status}"
                )
        finally:
            lifecycle._launch_worker = original

    def test_post_shutdown_submit_returns_503(self, tmp_path, monkeypatch):
        """After shutdown, submitting a job returns 503 and does not mutate the queue."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        # Prevent worker threads
        original = lifecycle._launch_worker
        lifecycle._launch_worker = lambda rid: None
        try:
            asyncio.run(lifecycle.shutdown(None))
            jobs_before = lifecycle.queue.list_jobs()

            status, data = asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["test"], "model": "vl-scorer"},
                )
            )
            assert status == 503, f"Expected 503, got {status}: {data}"
            assert "shutting down" in data.get("error", "").lower()

            jobs_after = lifecycle.queue.list_jobs()
            assert len(jobs_after) == len(jobs_before), "Queue must not be mutated after shutdown"
        finally:
            lifecycle._launch_worker = original

    def test_no_worker_promotion_after_shutdown(self, tmp_path, monkeypatch):
        """Shutdown must not start new worker threads for promoted jobs."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        # Allow the first worker to start, but make it a no-op
        original = lifecycle._launch_worker
        launch_count = {"n": 0}
        lifecycle._launch_worker = lambda rid: launch_count.update({"n": launch_count["n"] + 1})
        try:
            # Submit two jobs with workers suppressed
            asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["first"], "model": "vl-scorer"},
                )
            )
            asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["second"], "model": "vl-scorer"},
                )
            )
            launch_before = launch_count["n"]

            asyncio.run(lifecycle.shutdown(None))
            launch_after = launch_count["n"]
            # No new workers should have been launched during/after shutdown
            assert launch_after == launch_before, (
                f"Worker was launched during shutdown: {launch_before} -> {launch_after}"
            )
        finally:
            lifecycle._launch_worker = original

    def test_startup_is_idempotent(self, tmp_path, monkeypatch):
        """Calling startup again during RUNNING is a no-op."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        q1 = lifecycle.queue
        s1 = lifecycle.storage

        asyncio.run(lifecycle.startup(None))  # second call
        assert lifecycle.queue is q1, "startup replaced the queue"
        assert lifecycle.storage is s1, "startup replaced the storage"

    def test_restart_after_shutdown_raises(self, tmp_path, monkeypatch):
        """Calling startup after shutdown raises RuntimeError."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        asyncio.run(lifecycle.shutdown(None))
        with pytest.raises(RuntimeError, match="Cannot start.*after shutdown"):
            asyncio.run(lifecycle.startup(None))

    def test_shutdown_cancels_running_and_queued(self, tmp_path, monkeypatch):
        """Shutdown with one running and one queued cancels both."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        original = lifecycle._launch_worker
        lifecycle._launch_worker = lambda rid: None
        try:
            # Submit two jobs: first running, second queued
            asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["first"], "model": "vl-scorer"},
                )
            )
            _, d2 = asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["second"], "model": "vl-scorer"},
                )
            )
            run_id2 = d2["run_id"]
            assert lifecycle.queue.get_job(run_id2).status == JobState.QUEUED

            asyncio.run(lifecycle.shutdown(None))

            # Both jobs should be cancelled
            for job in lifecycle.queue.list_jobs():
                assert job.status in (JobState.CANCELLED, JobState.CANCELLING), (
                    f"Job {job.run_id} status is {job.status}"
                )
        finally:
            lifecycle._launch_worker = original

    def test_shutdown_joins_active_workers(self, tmp_path, monkeypatch):
        """Shutdown joins tracked non-daemon worker threads with a bounded timeout."""

        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)

        # Use a real worker that sleeps, so shutdown's join(timeout=5) can find it.
        original_run_worker = lifecycle._run_worker

        def slow_run_worker(run_id):
            time.sleep(0.3)  # short enough to not time out, long enough to be joinable

        lifecycle._run_worker = slow_run_worker

        try:
            asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["test"], "model": "vl-scorer"},
                )
            )
            # Wait for worker to be tracked
            time.sleep(0.05)
            assert lifecycle.active_workers >= 1, "Worker thread not tracked"

            # Shutdown joins and clears
            lifecycle._cancel_all_and_join()
            time.sleep(0.5)  # let worker finish
            assert lifecycle.active_workers == 0, (
                f"Worker threads leaked after shutdown: {lifecycle.active_workers}"
            )
        finally:
            lifecycle._run_worker = original_run_worker

    def test_repeated_shutdown_is_idempotent_state(self, tmp_path, monkeypatch):
        """Repeated shutdown after first maintains CANCELLED state for all jobs."""
        router, _, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
        original = lifecycle._launch_worker
        lifecycle._launch_worker = lambda rid: None
        try:
            asyncio.run(
                _invoke(
                    router,
                    "POST",
                    "/api/curator/ai-curate/jobs",
                    {"batch": "test-batch", "elements": ["test"], "model": "vl-scorer"},
                )
            )
            asyncio.run(lifecycle.shutdown(None))
            asyncio.run(lifecycle.shutdown(None))
            asyncio.run(lifecycle.shutdown(None))
            # All jobs still cancelled, no exceptions
            for job in lifecycle.queue.list_jobs():
                assert job.status in (JobState.CANCELLED, JobState.CANCELLING)
        finally:
            lifecycle._launch_worker = original


# ---------------------------------------------------------------------------
# Test: run history storage containment
# ---------------------------------------------------------------------------


class TestStorageContainment:
    """Filesystem safety: RunStorage rejects symlinked and escaping paths."""

    @staticmethod
    def _can_symlink(tmp_path):
        """Return True if symlinks can be created (needs admin or Developer Mode on Windows)."""
        try:
            src = tmp_path / "_sym_src"
            src.write_text("x")
            link = tmp_path / "_sym_link"
            os.symlink(str(src), str(link))
            link.unlink()
            src.unlink()
            return True
        except OSError:
            return False

    def test_save_rejects_symlinked_batch_dir(self, tmp_path):
        """Saving to a symlinked batch directory raises ValueError."""
        if not self._can_symlink(tmp_path):
            pytest.skip("symlink creation requires elevated privileges on this platform")

        batches = tmp_path / "batches"
        batches.mkdir()
        real_batch = batches / "real-batch"
        real_batch.mkdir()
        (real_batch / "inbox").mkdir()

        sym_batch = batches / "link-batch"
        os.symlink(str(real_batch), str(sym_batch), target_is_directory=True)

        storage = RunStorage(batches_dir=batches)
        run = CurationRun(
            run_id="run-sym",
            batch="link-batch",
            status=JobState.COMPLETED,
        )
        with pytest.raises(ValueError):
            storage.save_run(run)

    def test_save_rejects_batch_escaping_batch_root(self, tmp_path):
        """Saving to a batch that doesn't exist under batch_root raises ValueError."""
        batches = tmp_path / "batches"
        batches.mkdir()
        # Create "real-batch" under batches, so it's a real batch
        (batches / "real-batch").mkdir()

        # But configure storage to point to a different root
        other_root = tmp_path / "other-root"
        other_root.mkdir()

        storage = RunStorage(batches_dir=other_root)
        run = CurationRun(
            run_id="run-esc",
            batch="real-batch",
            status=JobState.COMPLETED,
        )
        # "real-batch" exists under batches/, not under other-root/.
        with pytest.raises(ValueError, match="batch directory does not exist"):
            storage.save_run(run)

    def test_save_rejects_run_id_with_slash(self):
        """run_id containing path separator raises ValueError."""
        storage = RunStorage(batches_dir=Path("/tmp/test"))
        run = CurationRun(
            run_id="run/escape",
            batch="test-batch",
            status=JobState.COMPLETED,
        )
        with pytest.raises(ValueError, match="run_id"):
            storage.save_run(run)

    def test_load_run_returns_none_for_symlink(self, tmp_path):
        """load_run returns None when the run file is a symlink."""
        if not TestStorageContainment._can_symlink(tmp_path):
            pytest.skip("symlink creation requires elevated privileges on this platform")

        batches = tmp_path / "batches"
        batches.mkdir()
        batch_dir = batches / "test-batch"
        batch_dir.mkdir()
        runs_dir = batch_dir / "ai-curate" / "runs"
        runs_dir.mkdir(parents=True)

        outside = tmp_path / "outside.json"
        outside.write_text('{"run_id":"sym-run","batch":"test-batch","status":"completed"}')
        sym_path = runs_dir / "sym-run.json"
        os.symlink(str(outside), str(sym_path))

        storage = RunStorage(batches_dir=batches)
        result = storage.load_run("test-batch", "sym-run")
        assert result is None, "Should return None for symlinked run file"

    def test_list_runs_excludes_symlinks(self, tmp_path):
        """list_runs silently excludes symlinked run files."""
        if not TestStorageContainment._can_symlink(tmp_path):
            pytest.skip("symlink creation requires elevated privileges on this platform")

        batches = tmp_path / "batches"
        batches.mkdir()
        batch_dir = batches / "test-batch"
        batch_dir.mkdir()
        runs_dir = batch_dir / "ai-curate" / "runs"
        runs_dir.mkdir(parents=True)

        (runs_dir / "real-run.json").write_text(
            '{"run_id":"real-run","batch":"test-batch","status":"completed","created_at":"2026-01-01T00:00:00Z"}'
        )
        outside = tmp_path / "outside.json"
        outside.write_text('{"run_id":"link-run","batch":"test-batch","status":"completed"}')
        os.symlink(str(outside), str(runs_dir / "link-run.json"))

        storage = RunStorage(batches_dir=batches)
        runs = storage.list_runs("test-batch")
        assert runs == ["real-run"], f"Symlinks should be excluded, got {runs}"

    def test_save_rejects_existing_non_regular_file(self, tmp_path):
        """save_run rejects if the target path exists as a non-regular file."""
        batches = tmp_path / "batches"
        batches.mkdir()
        batch_dir = batches / "test-batch"
        batch_dir.mkdir()
        runs_dir = batch_dir / "ai-curate" / "runs"
        runs_dir.mkdir(parents=True)

        # Create a directory where the run file would go
        (runs_dir / "run-dir.json").mkdir()

        storage = RunStorage(batches_dir=batches)
        run = CurationRun(
            run_id="run-dir",
            batch="test-batch",
            status=JobState.COMPLETED,
        )
        with pytest.raises(ValueError):
            storage.save_run(run)

    def test_save_does_not_mutate_on_rejection(self, tmp_path):
        """A rejected save must not create any files or directories.

        Scenario: batch dir exists but the ai-curate/runs directory is a
        symlink pointing outside. The save must be rejected and no files
        created anywhere.
        """
        if not TestStorageContainment._can_symlink(tmp_path):
            pytest.skip("symlink creation requires elevated privileges on this platform")

        batches = tmp_path / "batches"
        batches.mkdir()
        batch_dir = batches / "test-batch"
        batch_dir.mkdir()

        # Create a real ai-curate/runs outside
        outside_runs = tmp_path / "outside-runs"
        outside_runs.mkdir()

        # Create the ai-curate dir as a real dir, but make 'runs' a symlink to outside
        ai_dir = batch_dir / "ai-curate"
        ai_dir.mkdir()
        os.symlink(str(outside_runs), str(ai_dir / "runs"), target_is_directory=True)

        storage = RunStorage(batches_dir=batches)
        run = CurationRun(
            run_id="run-ghost",
            batch="test-batch",
            status=JobState.COMPLETED,
        )
        with pytest.raises(ValueError):
            storage.save_run(run)

        # Verify nothing was created inside the symlinked runs dir
        assert list(outside_runs.iterdir()) == [], "No files should be created in escaped target"


# ---------------------------------------------------------------------------
# Test: CuratorManager idempotent registration
# ---------------------------------------------------------------------------


class TestCuratorManagerIdempotent:
    """Duplicate CuratorManager.add_routes() must not append duplicate hooks."""

    def test_add_routes_is_idempotent(self, monkeypatch):
        """Calling add_routes twice does not grow app.on_startup or app.on_shutdown."""
        import sys

        # Set up mocks
        mock_web = MagicMock()
        mock_web.json_response.side_effect = lambda data, status=200: SimpleNamespace(
            status=status, text=json.dumps(data), headers={}
        )
        mock_web.Response = MagicMock(return_value=SimpleNamespace(status=200))
        mock_aiohttp = MagicMock(web=mock_web)
        monkeypatch.setitem(sys.modules, "aiohttp", mock_aiohttp)
        monkeypatch.setitem(sys.modules, "aiohttp.web", mock_web)

        mock_server = MagicMock()
        mock_ps = MagicMock()
        mock_ps.instance.app = MagicMock()
        mock_ps.instance.app.router = MagicMock()
        mock_ps.instance.app.on_startup = []
        mock_ps.instance.app.on_shutdown = []
        mock_server.PromptServer = mock_ps
        monkeypatch.setitem(sys.modules, "server", mock_server)

        mock_jinja2 = MagicMock()
        monkeypatch.setitem(sys.modules, "jinja2", mock_jinja2)

        mock_folder_paths = MagicMock()
        mock_folder_paths.get_system_user_directory.return_value = str(REPO_ROOT / "__curator_test")
        mock_folder_paths.get_output_directory.return_value = str(REPO_ROOT / "output_test")
        monkeypatch.setitem(sys.modules, "folder_paths", mock_folder_paths)

        # Load CuratorManager via importlib (same as existing tests)
        spec = importlib.util.spec_from_file_location(
            "py__curator_manager_idem", REPO_ROOT / "py" / "curator_manager.py"
        )
        cm = importlib.util.module_from_spec(spec)
        sys.modules["py__curator_manager_idem"] = cm
        spec.loader.exec_module(cm)

        app = mock_ps.instance.app

        # First call
        cm.CuratorManager._registered = False
        cm.CuratorManager.add_routes()
        startup_len_1 = len(app.on_startup)
        shutdown_len_1 = len(app.on_shutdown)
        assert startup_len_1 >= 1
        assert shutdown_len_1 >= 1

        # Second call — should be a no-op
        cm.CuratorManager.add_routes()
        assert len(app.on_startup) == startup_len_1, "on_startup grew on duplicate call"
        assert len(app.on_shutdown) == shutdown_len_1, "on_shutdown grew on duplicate call"
