"""Unit tests for ai_curate.models -- run data model serialization."""

import pytest
from ai_curate.models import JobState, ImageResult, RunTotals, CurationRun


class TestJobState:
    def test_all_states_defined(self):
        expected = {
            "queued",
            "running",
            "cancelling",
            "completed",
            "failed",
            "cancelled",
        }
        assert set(s.value for s in JobState) == expected

    def test_string_comparison(self):
        assert JobState.QUEUED == "queued"
        assert JobState.RUNNING == "running"


class TestImageResult:
    def test_to_dict_round_trip(self):
        r = ImageResult(
            filename="test.png",
            score=5,
            total=8,
            details={1: "YES", 2: "NO"},
            failed=False,
            error_message="",
            moved_to="/tmp/batches/test/shortlisted/test.png",
        )
        d = r.to_dict()
        r2 = ImageResult.from_dict(d)
        assert r2.filename == r.filename
        assert r2.score == r.score
        assert r2.total == r.total
        assert r2.details == r.details
        assert r2.failed == r.failed
        assert r2.moved_to == r.moved_to

    def test_failed_result(self):
        r = ImageResult(filename="bad.png", failed=True, error_message="timeout")
        d = r.to_dict()
        r2 = ImageResult.from_dict(d)
        assert r2.failed is True
        assert r2.error_message == "timeout"

    def test_no_moved_to_when_none(self):
        r = ImageResult(filename="test.png")
        d = r.to_dict()
        assert "moved_to" not in d


class TestRunTotals:
    def test_to_dict_round_trip(self):
        t = RunTotals(images=42, scored=40, failed=2, moved=15)
        d = t.to_dict()
        t2 = RunTotals.from_dict(d)
        assert t2.images == 42
        assert t2.scored == 40
        assert t2.failed == 2
        assert t2.moved == 15


class TestCurationRun:
    def test_auto_generates_run_id(self):
        run = CurationRun(batch="test-batch")
        assert run.run_id
        assert len(run.run_id) == 12

    def test_to_dict_round_trip(self):
        run = CurationRun(
            batch="test-batch",
            source_folder="inbox",
            destination_folder="shortlisted",
            move_enabled=True,
            prompt="wide shot of landscape",
            elements=["Wide shot framing", "landscape"],
            model="vl-scorer",
            top_n=10,
            status=JobState.COMPLETED,
            results=[
                ImageResult(filename="a.png", score=5, total=6),
                ImageResult(
                    filename="b.png",
                    score=3,
                    total=6,
                    failed=True,
                    error_message="timeout",
                ),
            ],
            totals=RunTotals(images=2, scored=1, failed=1, moved=1),
        )
        d = run.to_dict()
        run2 = CurationRun.from_dict(d)
        assert run2.run_id == run.run_id
        assert run2.batch == run.batch
        assert run2.move_enabled is True
        assert run2.prompt == run.prompt
        assert len(run2.elements) == 2
        assert len(run2.results) == 2
        assert run2.results[0].filename == "a.png"
        assert run2.results[1].failed is True
        assert run2.totals.images == 2
        assert run2.source_folder == run.source_folder
        assert run2.destination_folder == run.destination_folder
        assert run2.model == run.model
        assert run2.top_n == run.top_n
        assert run2.status == run.status
        assert run2.created_at == run.created_at
        assert run2.completed_at == run.completed_at
        assert run2.error_message == run.error_message

    def test_default_status_is_queued(self):
        run = CurationRun(batch="test")
        assert run.status == JobState.QUEUED

    def test_default_move_disabled(self):
        run = CurationRun(batch="test")
        assert run.move_enabled is False
        assert run.destination_folder is None
