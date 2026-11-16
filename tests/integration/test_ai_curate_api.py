"""Integration tests for the native AI curation HTTP API."""

import pytest

pytestmark = pytest.mark.integration

from ai_curate.models import CurationRun, JobState, RunTotals


class TestPreviewElements:
    @pytest.mark.integration
    def test_preview_with_explicit_elements(self, ai_client):
        """POST preview-elements with elements returns them plus quality defaults."""
        resp = ai_client.post(
            "/api/curator/ai-curate/preview-elements",
            json_body={"elements": ["Blue sky", "Red dress"]},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "elements" in data
        assert "Blue sky" in data["elements"]
        assert "Red dress" in data["elements"]
        # Quality elements appended by default (backward compat: no quality_flags = all)
        assert data["count"] >= 4

    def test_preview_with_quality_flags_set(self, ai_client):
        """POST with quality_flags appends only selected quality elements."""
        resp = ai_client.post(
            "/api/curator/ai-curate/preview-elements",
            json_body={"elements": ["Blue sky"], "quality_flags": ["anatomy"]},
        )
        data = resp.get_json()
        assert "Blue sky" in data["elements"]
        assert any("Clean anatomy" in e for e in data["elements"])
        assert not any("No visual artifacts" in e for e in data["elements"])

    def test_preview_with_empty_quality_flags(self, ai_client):
        """POST with quality_flags=[] appends no quality elements."""
        resp = ai_client.post(
            "/api/curator/ai-curate/preview-elements",
            json_body={"elements": ["Blue sky"], "quality_flags": []},
        )
        data = resp.get_json()
        assert data["count"] == 1
        assert data["elements"] == ["Blue sky"]

    def test_preview_missing_elements(self, ai_client):
        """POST without elements returns 400."""
        resp = ai_client.post("/api/curator/ai-curate/preview-elements", json_body={})
        assert resp.status_code == 400


class TestSubmitJob:
    def test_submit_valid_job(self, ai_client):
        """POST jobs with valid data returns 201."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
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

    def test_submit_missing_batch(self, ai_client):
        """POST without batch returns 400."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "elements": ["test"],
            },
        )
        assert resp.status_code == 400

    def test_submit_nonexistent_batch(self, ai_client):
        """POST with nonexistent batch returns 400."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "no-such-batch",
                "elements": ["test"],
            },
        )
        assert resp.status_code == 400

    def test_submit_missing_elements(self, ai_client):
        """POST without elements returns 400."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
            },
        )
        assert resp.status_code == 400

    def test_submit_invalid_source_folder(self, ai_client):
        """POST with invalid source_folder returns 400."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["test"],
                "source_folder": "invalid",
            },
        )
        assert resp.status_code == 400

    def test_submit_move_without_destination(self, ai_client):
        """POST with move_enabled but no destination returns 400."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["test"],
                "move_enabled": True,
            },
        )
        assert resp.status_code == 400

    def test_submit_top_n_over_cap(self, ai_client):
        """POST with top_n over cap returns 400."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["test"],
                "top_n": 999,
            },
        )
        assert resp.status_code == 400

    def test_submit_too_many_elements(self, ai_client):
        """POST with too many elements returns 400."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": [f"element {i}" for i in range(20)],
            },
        )
        assert resp.status_code == 400

    def test_submit_defaults_applied(self, ai_client):
        """POST with minimal data gets default values."""
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
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

    def test_submit_empty_configured_list_rejects_model(
        self, ai_client, ai_lifecycle, native_settings, monkeypatch
    ):
        """POST with empty configured models returns 400 and does not queue a job."""
        monkeypatch.setattr(native_settings, "available_models", ())
        monkeypatch.setattr(native_settings, "default_model", "")
        jobs_before = len(ai_lifecycle.queue.list_jobs())
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["test"],
                "model": "any-model",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "model is not configured" in data.get("error", "")
        jobs_after = len(ai_lifecycle.queue.list_jobs())
        assert jobs_after == jobs_before, "Queue must not be mutated"

    def test_submit_unknown_configured_model_rejected(self, ai_client, ai_lifecycle):
        """POST with model not in configured list returns 400, no queue job."""
        jobs_before = len(ai_lifecycle.queue.list_jobs())
        resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["test"],
                "model": "other-model",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "model is not configured" in data.get("error", "")
        jobs_after = len(ai_lifecycle.queue.list_jobs())
        assert jobs_after == jobs_before, "Queue must not be mutated"


class TestGetJob:
    def test_get_existing_job(self, ai_client):
        """GET jobs/<id> returns the job."""
        submit_resp = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["test"],
                "model": "vl-scorer",
            },
        )
        run_id = submit_resp.get_json()["run_id"]

        resp = ai_client.get(f"/api/curator/ai-curate/jobs/{run_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == run_id

    def test_get_nonexistent_job(self, ai_client):
        """GET jobs/<id> with bad ID returns 404."""
        resp = ai_client.get("/api/curator/ai-curate/jobs/nonexistent")
        assert resp.status_code == 404


class TestListJobs:
    def test_list_jobs_empty(self, ai_client):
        """GET jobs returns empty list initially."""
        resp = ai_client.get("/api/curator/ai-curate/jobs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["jobs"] == []


class TestCancelJob:
    def test_cancel_queued_job(self, ai_client):
        """POST jobs/<id>/cancel cancels a queued job."""
        # Submit two jobs so the second remains queued (worker launcher is disabled).
        ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["first"],
                "model": "vl-scorer",
            },
        )
        submit2 = ai_client.post(
            "/api/curator/ai-curate/jobs",
            json_body={
                "batch": "test-batch",
                "elements": ["second"],
                "model": "vl-scorer",
            },
        )
        run_id2 = submit2.get_json()["run_id"]

        resp = ai_client.post(f"/api/curator/ai-curate/jobs/{run_id2}/cancel")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_cancel_nonexistent_job(self, ai_client):
        """POST cancel with bad ID returns 404."""
        resp = ai_client.post("/api/curator/ai-curate/jobs/nonexistent/cancel")
        assert resp.status_code == 404


class TestBatchRuns:
    def test_list_runs_empty(self, ai_client):
        """GET batch runs returns empty initially."""
        resp = ai_client.get("/api/curator/ai-curate/batches/test-batch/runs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["runs"] == []

    def test_get_nonexistent_run(self, ai_client):
        """GET batch runs/<id> returns 404."""
        resp = ai_client.get("/api/curator/ai-curate/batches/test-batch/runs/nonexistent")
        assert resp.status_code == 404

    def test_get_latest_run_empty(self, ai_client):
        """GET batch runs/latest returns 404 when no runs."""
        resp = ai_client.get("/api/curator/ai-curate/batches/test-batch/runs/latest")
        assert resp.status_code == 404

    def test_list_runs_with_persisted_data(self, ai_client, ai_lifecycle):
        """GET batch runs returns persisted run IDs after a run is saved."""
        storage = ai_lifecycle.storage

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

        resp = ai_client.get("/api/curator/ai-curate/batches/test-batch/runs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "runs" in data
        assert len(data["runs"]) >= 2
        assert "run-001" in data["runs"]
        assert "run-002" in data["runs"]

    def test_get_run_with_persisted_data(self, ai_client, ai_lifecycle):
        """GET batch runs/<run_id> returns full run data after persistence."""
        storage = ai_lifecycle.storage

        run = CurationRun(
            run_id="run-003",
            batch="test-batch",
            prompt="detailed prompt",
            status=JobState.COMPLETED,
            totals=RunTotals(images=10, scored=8, failed=2, moved=0),
        )
        storage.save_run(run)

        resp = ai_client.get("/api/curator/ai-curate/batches/test-batch/runs/run-003")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == "run-003"
        assert data["batch"] == "test-batch"
        assert data["prompt"] == "detailed prompt"
        assert data["status"] == "completed"
        assert data["totals"]["images"] == 10
        assert data["totals"]["scored"] == 8

    def test_get_latest_run_with_persisted_data(self, ai_client, ai_lifecycle):
        """GET batch runs/latest returns the most recent run."""
        storage = ai_lifecycle.storage

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

        resp = ai_client.get("/api/curator/ai-curate/batches/test-batch/runs/latest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == "run-latest"
        assert data["prompt"] == "latest prompt"

    def test_batch_runs_nonexistent_batch(self, ai_client):
        """GET batch runs returns 404 for a batch that does not exist."""
        resp = ai_client.get("/api/curator/ai-curate/batches/nonexistent-batch/runs")
        assert resp.status_code == 404


class TestPathTraversal:
    """Verify that route parameters block path traversal."""

    def test_traversal_run_id_rejected_by_storage(self, ai_client):
        """A run_id containing ../ is rejected by routing or storage."""
        resp = ai_client.get("/api/curator/ai-curate/batches/test-batch/runs/..%2Fescape")
        assert resp.status_code in (400, 404, 500)

    def test_traversal_batch_name_not_found(self, ai_client):
        """A batch path containing ../ never resolves to another directory."""
        resp = ai_client.get("/api/curator/ai-curate/batches/..%2Fescape/runs")
        assert resp.status_code in (400, 404)
