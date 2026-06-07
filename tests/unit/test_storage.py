"""Unit tests for ai_curate.storage -- run history persistence."""

import json
import pytest
from pathlib import Path
from ai_curate.models import CurationRun, ImageResult, RunTotals, JobState
from ai_curate.storage import RunStorage


@pytest.fixture
def tmp_batches(tmp_path):
    """Create a temporary batches directory structure."""
    batches = tmp_path / "batches"
    batches.mkdir()
    batch_dir = batches / "test-batch"
    batch_dir.mkdir()
    (batch_dir / "inbox").mkdir()
    return batches


@pytest.fixture
def storage(tmp_batches):
    """Create a RunStorage instance pointing at the temp batches dir."""
    return RunStorage(batches_dir=tmp_batches)


def _make_completed_run(run_id="run001", batch="test-batch"):
    """Helper to create a completed run with results."""
    return CurationRun(
        run_id=run_id,
        batch=batch,
        source_folder="inbox",
        prompt="wide shot of landscape",
        elements=["Wide shot framing", "landscape"],
        model="vl-scorer",
        top_n=10,
        status=JobState.COMPLETED,
        results=[
            ImageResult(filename="a.png", score=5, total=6),
            ImageResult(filename="b.png", score=3, total=6),
        ],
        totals=RunTotals(images=2, scored=2, failed=0, moved=0),
    )


class TestRunStorage:
    def test_save_run_creates_files(self, storage, tmp_batches):
        """Saving a completed run creates a timestamped file and latest pointer."""
        run = _make_completed_run()
        storage.save_run(run)

        ai_curate_dir = tmp_batches / "test-batch" / "ai-curate"
        runs_dir = ai_curate_dir / "runs"
        assert runs_dir.is_dir()

        # Should have at least one run file
        run_files = list(runs_dir.glob("*.json"))
        assert len(run_files) == 1

        # latest.json should exist
        latest = ai_curate_dir / "latest.json"
        assert latest.exists()

    def test_latest_points_to_most_recent(self, storage, tmp_batches):
        """latest.json points to the most recent successful run."""
        run1 = _make_completed_run(run_id="run001")
        storage.save_run(run1)

        run2 = _make_completed_run(run_id="run002")
        storage.save_run(run2)

        latest_path = tmp_batches / "test-batch" / "ai-curate" / "latest.json"
        latest_data = json.loads(latest_path.read_text())
        assert latest_data["run_id"] == "run002"

    def test_cancelled_run_not_persisted(self, storage, tmp_batches):
        """Cancelled runs are never written to history."""
        run = CurationRun(
            run_id="cancelled-run",
            batch="test-batch",
            status=JobState.CANCELLED,
        )
        # save_run should refuse to persist cancelled runs
        result = storage.save_run(run)
        assert result is False

        runs_dir = tmp_batches / "test-batch" / "ai-curate" / "runs"
        if runs_dir.exists():
            run_files = list(runs_dir.glob("*.json"))
            assert len(run_files) == 0

    def test_load_run(self, storage, tmp_batches):
        """A saved run can be loaded back by run_id."""
        run = _make_completed_run(run_id="loadable")
        storage.save_run(run)

        loaded = storage.load_run("test-batch", "loadable")
        assert loaded is not None
        assert loaded.run_id == "loadable"
        assert loaded.batch == "test-batch"
        assert loaded.status == JobState.COMPLETED

    def test_load_nonexistent_run(self, storage, tmp_batches):
        """Loading a nonexistent run returns None."""
        result = storage.load_run("test-batch", "nonexistent")
        assert result is None

    def test_list_runs(self, storage, tmp_batches):
        """list_runs returns run IDs in chronological order."""
        run1 = _make_completed_run(run_id="run001")
        storage.save_run(run1)
        run2 = _make_completed_run(run_id="run002")
        storage.save_run(run2)

        runs = storage.list_runs("test-batch")
        assert len(runs) == 2
        # Most recent last (chronological)
        assert runs[0] == "run001"
        assert runs[1] == "run002"

    def test_load_latest(self, storage, tmp_batches):
        """load_latest returns the run pointed to by latest.json."""
        run1 = _make_completed_run(run_id="run001")
        storage.save_run(run1)
        run2 = _make_completed_run(run_id="run002")
        storage.save_run(run2)

        latest = storage.load_latest("test-batch")
        assert latest is not None
        assert latest.run_id == "run002"

    def test_load_latest_no_runs(self, storage, tmp_batches):
        """load_latest returns None when no runs exist."""
        result = storage.load_latest("test-batch")
        assert result is None

    def test_save_run_preserves_results(self, storage, tmp_batches):
        """Saved run preserves all image results."""
        run = _make_completed_run()
        storage.save_run(run)

        loaded = storage.load_run("test-batch", run.run_id)
        assert len(loaded.results) == 2
        assert loaded.results[0].filename == "a.png"
        assert loaded.results[0].score == 5
        assert loaded.results[1].filename == "b.png"

    def test_load_corrupt_run_returns_none(self, storage, tmp_batches):
        """load_run returns None when the run JSON is corrupt."""
        runs_dir = tmp_batches / "test-batch" / "ai-curate" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        corrupt_file = runs_dir / "corrupt.json"
        corrupt_file.write_text("not valid json {{{", encoding="utf-8")
        result = storage.load_run("test-batch", "corrupt")
        assert result is None

    def test_load_corrupt_latest_returns_none(self, storage, tmp_batches):
        """load_latest returns None when latest.json is corrupt."""
        ai_dir = tmp_batches / "test-batch" / "ai-curate"
        ai_dir.mkdir(parents=True, exist_ok=True)
        latest_file = ai_dir / "latest.json"
        latest_file.write_text("garbage not json", encoding="utf-8")
        result = storage.load_latest("test-batch")
        assert result is None
