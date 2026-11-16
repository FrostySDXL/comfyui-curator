"""Regression coverage for AI job cancellation wiring.

The native smoke test reported that the AI sidebar Cancel button answered
``job not found``.  The click listener passed the DOM event into
``aiCancelJob(jobId)``, so the request path carried a stringified event
instead of the active run id and the native cancel route returned 404.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.frontend_source import extract_function_body, read_frontend_js

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ai_cancel_binding_lifecycle_executes_real_frontend_sources() -> None:
    """The sidebar button, Activity Center, and leaked-event paths must cancel by run id."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for AI cancel binding regression")
    result = subprocess.run(
        [node, str(REPO_ROOT / "tests/unit/ai_cancel_binding_test.js")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AI cancel binding checks passed" in result.stdout


def test_ai_sidebar_cancel_listener_does_not_forward_the_click_event() -> None:
    events_js = Path("static/js/events.js").read_text(encoding="utf-8")

    assert "aiCancelBtn.addEventListener('click', () => aiCancelJob())" in events_js
    assert "aiCancelBtn.addEventListener('click', aiCancelJob)" not in events_js


def test_ai_cancel_job_rejects_non_string_job_ids() -> None:
    job_js = read_frontend_js()
    body = extract_function_body(job_js, "async function aiCancelJob(jobId = aiCurrentJobId)")

    guard = "if (typeof jobId !== 'string' || !jobId) jobId = aiCurrentJobId;"
    assert guard in body
    assert body.index(guard) < body.index("fetch(")


def test_ai_job_activity_adapter_keeps_its_explicit_run_id() -> None:
    job_js = read_frontend_js()

    # Activity Center cancellation must stay bound to the job that registered it
    # even after aiCurrentJobId moves on to a newer run.
    assert "cancel: () => aiCancelJob(job.run_id || aiCurrentJobId)" in job_js
    assert "cancel: () => aiCancelJob(submittedJobId)" in job_js
