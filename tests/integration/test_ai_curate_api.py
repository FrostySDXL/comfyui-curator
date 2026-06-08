"""Integration tests for AI curation Flask API routes."""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.integration

from ai_curate.models import JobState, CurationRun, RunTotals


@pytest.fixture
def client(app_module, monkeypatch, tmp_path):
    """Create a Flask test client with temp directories."""
    batches_dir = app_module.BATCHES_DIR
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
    def test_preview_with_explicit_elements(self, client):
        """POST /api/ai-curate/preview-elements with elements returns them plus quality defaults."""
        resp = client.post(
            "/api/ai-curate/preview-elements",
            json={"elements": ["Blue sky", "Red dress"]},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "elements" in data
        assert "Blue sky" in data["elements"]
        assert "Red dress" in data["elements"]
        # Quality elements appended by default (backward compat: no quality_flags = all)
        assert data["count"] >= 4

    def test_preview_with_quality_flags_set(self, client):
        """POST with quality_flags appends only selected quality elements."""
        resp = client.post(
            "/api/ai-curate/preview-elements",
            json={"elements": ["Blue sky"], "quality_flags": ["anatomy"]},
        )
        data = resp.get_json()
        assert "Blue sky" in data["elements"]
        assert any("Clean anatomy" in e for e in data["elements"])
        assert not any("No visual artifacts" in e for e in data["elements"])

    def test_preview_with_empty_quality_flags(self, client):
        """POST with quality_flags=[] appends no quality elements."""
        resp = client.post(
            "/api/ai-curate/preview-elements",
            json={"elements": ["Blue sky"], "quality_flags": []},
        )
        data = resp.get_json()
        assert data["count"] == 1
        assert data["elements"] == ["Blue sky"]

    def test_preview_missing_elements(self, client):
        """POST without elements returns 400."""
        resp = client.post("/api/ai-curate/preview-elements", json={})
        assert resp.status_code == 400


class TestSubmitJob:
    def test_submit_valid_job(self, client, app_module):
        """POST /api/ai-curate/jobs with valid data returns 201."""
        with patch.object(app_module, "_run_scoring_worker"):
            resp = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "elements": ["wide shot of landscape"],
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
                "elements": ["test"],
            },
        )
        assert resp.status_code == 400

    def test_submit_nonexistent_batch(self, client):
        """POST with nonexistent batch returns 400."""
        resp = client.post(
            "/api/ai-curate/jobs",
            json={
                "batch": "no-such-batch",
                "elements": ["test"],
            },
        )
        assert resp.status_code == 400

    def test_submit_missing_elements(self, client):
        """POST without elements returns 400."""
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
                "elements": ["test"],
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
                "elements": ["test"],
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
                "elements": ["test"],
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
                "elements": [f"element {i}" for i in range(20)],
            },
        )
        assert resp.status_code == 400

    def test_submit_defaults_applied(self, client, app_module):
        """POST with minimal data gets default values."""
        with patch.object(app_module, "_run_scoring_worker"):
            resp = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "elements": ["test"],
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
    def test_get_existing_job(self, client, app_module):
        """GET /api/ai-curate/jobs/<id> returns the job."""
        with patch.object(app_module, "_run_scoring_worker"):
            submit_resp = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "elements": ["test"],
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
    def test_cancel_queued_job(self, client, app_module):
        """POST /api/ai-curate/jobs/<id>/cancel cancels a queued job."""
        with patch.object(app_module, "_run_scoring_worker"):
            # Submit two jobs so second is queued
            client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "elements": ["first"],
                    "model": "vl-scorer",
                },
            )
            submit2 = client.post(
                "/api/ai-curate/jobs",
                json={
                    "batch": "test-batch",
                    "elements": ["second"],
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

    def test_list_runs_with_persisted_data(self, client, app_module):
        """GET .../runs returns persisted run IDs after a run is saved."""

        # Use the app's storage so data is visible to API routes
        storage = app_module._ai_storage

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

        resp = client.get("/api/ai-curate/batches/test-batch/runs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "runs" in data
        assert len(data["runs"]) >= 2
        assert "run-001" in data["runs"]
        assert "run-002" in data["runs"]

    def test_get_run_with_persisted_data(self, client, app_module):
        """GET .../runs/<run_id> returns full run data after persistence."""

        storage = app_module._ai_storage

        run = CurationRun(
            run_id="run-003",
            batch="test-batch",
            prompt="detailed prompt",
            status=JobState.COMPLETED,
            totals=RunTotals(images=10, scored=8, failed=2, moved=0),
        )
        storage.save_run(run)

        resp = client.get("/api/ai-curate/batches/test-batch/runs/run-003")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == "run-003"
        assert data["batch"] == "test-batch"
        assert data["prompt"] == "detailed prompt"
        assert data["status"] == "completed"
        assert data["totals"]["images"] == 10
        assert data["totals"]["scored"] == 8

    def test_get_latest_run_with_persisted_data(self, client, app_module):
        """GET .../runs/latest returns the most recent run."""

        storage = app_module._ai_storage

        run1 = CurationRun(
            run_id="run-old",
            batch="test-batch",
            prompt="old prompt",
            status=JobState.COMPLETED,
        )
        storage.save_run(run1)

        run2 = CurationRun(
            run_id="run-latest",
            batch="test-batch",
            prompt="latest prompt",
            status=JobState.COMPLETED,
        )
        storage.save_run(run2)

        resp = client.get("/api/ai-curate/batches/test-batch/runs/latest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == "run-latest"
        assert data["prompt"] == "latest prompt"

    def test_batch_runs_nonexistent_batch(self, client):
        """GET .../runs returns 404 for a batch that does not exist."""
        resp = client.get("/api/ai-curate/batches/nonexistent-batch/runs")
        assert resp.status_code == 404


class TestPathTraversal:
    """Verify that route parameters block path traversal."""

    def test_traversal_run_id_rejected_by_storage(self, client, app_module):
        """A run_id containing ../ is either blocked by Flask routing or storage."""
        # Create a valid batch first
        client.post("/api/batches", json={"name": "traversal-test"})
        # Flask string converter may reject the slashes; either 404 or 500 is acceptable
        resp = client.get("/api/ai-curate/batches/traversal-test/runs/..%2Fescape")
        assert resp.status_code in (404, 500)

    def test_traversal_batch_name_not_found(self, client):
        """A batch name containing ../ returns 404 (batch not found)."""
        resp = client.get("/api/ai-curate/batches/../escape/runs")
        assert resp.status_code == 404
