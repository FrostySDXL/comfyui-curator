"""Integration tests for AI curation Flask API routes."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

pytestmark = pytest.mark.integration

# Import the Flask app
import app as app_module
from ai_curate.models import JobState, CurationRun, ImageResult, RunTotals


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a Flask test client with temp directories."""
    # Patch the batch/state directories to use tmp_path
    batches_dir = tmp_path / "batches"
    batches_dir.mkdir()
    state_file = tmp_path / "state.json"

    # Create a test batch
    test_batch = batches_dir / "test-batch"
    test_batch.mkdir()
    (test_batch / "inbox").mkdir()
    (test_batch / "shortlisted").mkdir()
    (test_batch / "finals").mkdir()
    (test_batch / "rejects").mkdir()

    monkeypatch.setattr(app_module, "BATCHES_DIR", batches_dir)
    monkeypatch.setattr(app_module, "STATE_FILE", state_file)
    monkeypatch.setattr(app_module, "COMFYUI_OUTPUT", tmp_path / "comfyui-outputs")

    # Also patch the AI storage to use the temp batches dir
    from ai_curate.storage import RunStorage

    monkeypatch.setattr(app_module, "_ai_storage", RunStorage(batches_dir=batches_dir))

    # Re-init the queue with the patched storage
    from ai_curate.queue import QueueManager

    monkeypatch.setattr(
        app_module,
        "_ai_queue",
        QueueManager(
            storage=RunStorage(batches_dir=batches_dir),
        ),
    )

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


class TestPreviewElements:
    @pytest.mark.integration
    def test_preview_from_prompt(self, client):
        """POST /api/ai-curate/preview-elements returns extracted elements."""
        resp = client.post(
            "/api/ai-curate/preview-elements",
            json={"prompt": "wide shot of girl on rooftop"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "elements" in data
        assert data["count"] > 0
        assert any("wide shot" in e.lower() for e in data["elements"])

    def test_preview_with_explicit_elements(self, client):
        """POST with explicit elements returns them plus quality elements."""
        resp = client.post(
            "/api/ai-curate/preview-elements",
            json={"prompt": "test", "elements": ["Blue sky", "Red dress"]},
        )
        data = resp.get_json()
        assert "Blue sky" in data["elements"]
        assert "Red dress" in data["elements"]
        # Quality elements should be appended
        assert data["count"] >= 4

    def test_preview_missing_prompt(self, client):
        """POST without prompt returns 400."""
        resp = client.post("/api/ai-curate/preview-elements", json={})
        assert resp.status_code == 400


class TestSubmitJob:
    def test_submit_valid_job(self, client):
        """POST /api/ai-curate/jobs with valid data returns 201."""
        with patch.object(app_module, "_run_scoring_worker"):
            resp = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "prompt": "wide shot of landscape",
                    "source_folder": "inbox",
                    "top_n": 10,
                    "model": "vl-scorer",
                    "move_enabled": False,
                },
            )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["run_id"]
        assert data["status"] in ("running", "queued")

    def test_submit_missing_batch(self, client):
        """POST without batch returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "prompt": "test",
            },
        )
        assert resp.status_code == 400

    def test_submit_nonexistent_batch(self, client):
        """POST with nonexistent batch returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "batch": "no-such-batch",
                "prompt": "test",
            },
        )
        assert resp.status_code == 400

    def test_submit_missing_prompt(self, client):
        """POST without prompt returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "batch": "test-batch",
            },
        )
        assert resp.status_code == 400

    def test_submit_invalid_source_folder(self, client):
        """POST with invalid source_folder returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "batch": "test-batch",
                "prompt": "test",
                "source_folder": "invalid",
            },
        )
        assert resp.status_code == 400

    def test_submit_move_without_destination(self, client):
        """POST with move_enabled but no destination returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "batch": "test-batch",
                "prompt": "test",
                "move_enabled": True,
            },
        )
        assert resp.status_code == 400

    def test_submit_top_n_over_cap(self, client):
        """POST with top_n over cap returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "batch": "test-batch",
                "prompt": "test",
                "top_n": 999,
            },
        )
        assert resp.status_code == 400

    def test_submit_too_many_elements(self, client):
        """POST with too many elements returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "batch": "test-batch",
                "prompt": "test",
                "elements": [f"element {i}" for i in range(20)],
            },
        )
        assert resp.status_code == 400

    def test_submit_defaults_applied(self, client):
        """POST with minimal data gets default values."""
        with patch.object(app_module, "_run_scoring_worker"):
            resp = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "prompt": "test prompt",
                    "model": "vl-scorer",
                },
            )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["source_folder"] == "inbox"
        assert data["top_n"] == 15
        assert data["move_enabled"] is False
        assert data["model"] == "vl-scorer"
        assert data["destination_folder"] is None


class TestGetJob:
    def test_get_existing_job(self, client):
        """GET /api/ai-curate/jobs/<id> returns the job."""
        with patch.object(app_module, "_run_scoring_worker"):
            submit_resp = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "prompt": "test",
                    "model": "vl-scorer",
                },
            )
        run_id = submit_resp.get_json()["run_id"]

        resp = client.get(f"/api/ai-curate/jobs/{run_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == run_id

    def test_get_nonexistent_job(self, client):
        """GET /api/ai-curate/jobs/<id> with bad ID returns 404."""
        resp = client.get("/api/ai-curate/jobs/nonexistent")
        assert resp.status_code == 404


class TestListJobs:
    def test_list_jobs_empty(self, client):
        """GET /api/ai-curate/jobs returns empty list initially."""
        resp = client.get("/api/ai-curate/jobs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["jobs"] == []


class TestCancelJob:
    def test_cancel_queued_job(self, client):
        """POST /api/ai-curate/jobs/<id>/cancel cancels a queued job."""
        with patch.object(app_module, "_run_scoring_worker"):
            # Submit two jobs so second is queued
            client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "prompt": "first",
                    "model": "vl-scorer",
                },
            )
            submit2 = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "prompt": "second",
                    "model": "vl-scorer",
                },
            )
        run_id2 = submit2.get_json()["run_id"]

        resp = client.post(f"/api/ai-curate/jobs/{run_id2}/cancel")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_cancel_nonexistent_job(self, client):
        """POST cancel with bad ID returns 404."""
        resp = client.post("/api/ai-curate/jobs/nonexistent/cancel")
        assert resp.status_code == 404


class TestBatchRuns:
    def test_list_runs_empty(self, client):
        """GET /api/ai-curate/batches/<batch>/runs returns empty initially."""
        resp = client.get("/api/ai-curate/batches/test-batch/runs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["runs"] == []

    def test_get_nonexistent_run(self, client):
        """GET /api/ai-curate/batches/<batch>/runs/<id> returns 404."""
        resp = client.get("/api/ai-curate/batches/test-batch/runs/nonexistent")
        assert resp.status_code == 404

    def test_get_latest_run_empty(self, client):
        """GET /api/ai-curate/batches/<batch>/runs/latest returns 404 when no runs."""
        resp = client.get("/api/ai-curate/batches/test-batch/runs/latest")
        assert resp.status_code == 404
