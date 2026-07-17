import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest


def load_benchmark_module():
    script_path = Path(__file__).parents[2] / "scripts" / "benchmark_thumbnails.py"
    spec = importlib.util.spec_from_file_location("benchmark_thumbnails", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["benchmark_thumbnails"] = module
    spec.loader.exec_module(module)
    return module


def test_cli_defaults_are_firefox_first_and_native(monkeypatch):
    benchmark = load_benchmark_module()
    monkeypatch.setattr(sys, "argv", ["benchmark_thumbnails.py"])

    args = benchmark.parse_args()

    assert args.browser == "firefox"
    assert args.sizes == [100, 500, 2000]
    assert args.url == "http://127.0.0.1:8188/curator"
    assert args.mode == "native"
    assert args.headless is False
    assert args.output_root == Path("tmp/thumbnail-benchmarks")


def test_standalone_requires_explicit_batch_root_under_output_root(tmp_path):
    benchmark = load_benchmark_module()
    output_root = tmp_path / "bench"

    with pytest.raises(benchmark.BenchmarkError, match="--batch-root"):
        benchmark.validate_standalone_root(None, output_root)
    with pytest.raises(benchmark.BenchmarkError, match="under --output-root"):
        benchmark.validate_standalone_root(tmp_path / "other", output_root)

    assert (
        benchmark.validate_standalone_root(output_root / "batches", output_root)
        == (output_root / "batches").resolve()
    )


def test_runtime_paths_match_native_and_standalone_contracts():
    benchmark = load_benchmark_module()

    native = benchmark.runtime_paths("native")
    standalone = benchmark.runtime_paths("standalone")

    assert native.settings == "/api/curator/settings"
    assert native.batches == "/api/curator/batches"
    assert native.active_batch == "/api/curator/active-batch"
    assert native.thumbnail_prefix == "/curator/thumb/"
    assert standalone.settings is None
    assert standalone.batches == "/api/batches"
    assert standalone.active_batch == "/api/active-batch"
    assert standalone.thumbnail_prefix == "/thumb/"


def test_report_url_rejects_credentials_and_query_data():
    benchmark = load_benchmark_module()

    with pytest.raises(benchmark.BenchmarkError, match="credentials"):
        benchmark.report_safe_url("http://user:secret@127.0.0.1:8188/curator")
    with pytest.raises(benchmark.BenchmarkError, match="query"):
        benchmark.report_safe_url("http://127.0.0.1:8188/curator?token=secret")

    assert benchmark.report_safe_url("http://127.0.0.1:8188/curator") == (
        "http://127.0.0.1:8188/curator"
    )


def test_active_batch_session_restores_after_ambiguous_switch_failure(monkeypatch, tmp_path):
    benchmark = load_benchmark_module()
    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=tmp_path,
        active_batch="operator-batch",
    )
    calls = []

    def fake_set_active_batch(_runtime, batch):
        calls.append(batch)
        if batch == "benchmark-batch":
            raise benchmark.BenchmarkError("response lost")

    monkeypatch.setattr(benchmark, "set_active_batch", fake_set_active_batch)
    session = benchmark.ActiveBatchSession(runtime)

    with pytest.raises(benchmark.BenchmarkError, match="response lost"):
        session.switch("benchmark-batch")
    session.restore()

    assert calls == ["benchmark-batch", "operator-batch"]


def test_set_active_batch_serializes_disabled_state_as_empty_string(monkeypatch, tmp_path):
    benchmark = load_benchmark_module()
    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=tmp_path,
        active_batch=None,
    )
    captured = {}

    def fake_request(origin, path, *, method="GET", body=None):
        captured.update(origin=origin, path=path, method=method, body=body)
        return {"success": True}

    monkeypatch.setattr(benchmark, "_request_json", fake_request)

    benchmark.set_active_batch(runtime, None)

    assert captured["body"] == {"batch": ""}


def test_cold_preparation_loads_companion_before_instrumented_primary(monkeypatch, tmp_path):
    benchmark = load_benchmark_module()
    events = []
    spec = benchmark.build_fixture_specs("run-abc", [100], ["firefox"])[0]
    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=tmp_path,
        active_batch="operator-batch",
    )

    class FakeSession:
        def switch(self, batch):
            events.append(("activate", batch))

    class FakeDriver:
        def get(self, url):
            events.append(("navigate", url))

    def fake_select(_driver, batch, count, _timeout):
        events.append(("select", batch, count))
        return {"ready": True, "batch": batch}

    def fake_instrument(_driver, count):
        events.append(("instrument", count))

    monkeypatch.setattr(benchmark, "_select_and_wait", fake_select)
    monkeypatch.setattr(benchmark, "_install_instrumentation", fake_instrument)

    companion_ready, primary_ready = benchmark.prepare_cold_phase(
        FakeDriver(), FakeSession(), runtime, spec, timeout=30
    )

    assert events == [
        ("activate", spec.companion_batch),
        ("navigate", runtime.page_url),
        ("select", spec.companion_batch, spec.companion_size),
        ("instrument", spec.size),
        ("select", spec.primary_batch, spec.size),
    ]
    assert ("activate", spec.primary_batch) not in events
    assert companion_ready["batch"] == spec.companion_batch
    assert primary_ready["batch"] == spec.primary_batch


def test_cleanup_refuses_unmarked_and_mismatched_batches(tmp_path):
    benchmark = load_benchmark_module()
    root = tmp_path / "batches"
    unmarked = root / "unmarked"
    mismatched = root / "mismatched"
    unmarked.mkdir(parents=True)
    mismatched.mkdir()
    (mismatched / benchmark.OWNERSHIP_MARKER).write_text(
        json.dumps(
            {
                "schema": benchmark.MARKER_SCHEMA,
                "run_id": "different-run",
                "batch": "mismatched",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(benchmark.CleanupRefused, match="ownership marker"):
        benchmark.remove_owned_batch(root, unmarked, "run-1", "unmarked")
    with pytest.raises(benchmark.CleanupRefused, match="does not match"):
        benchmark.remove_owned_batch(root, mismatched, "run-1", "mismatched")

    assert unmarked.is_dir()
    assert mismatched.is_dir()


def test_cleanup_removes_only_matching_direct_child(tmp_path):
    benchmark = load_benchmark_module()
    root = tmp_path / "batches"
    owned = root / "owned"
    owned.mkdir(parents=True)
    marker = {
        "schema": benchmark.MARKER_SCHEMA,
        "run_id": "run-1",
        "batch": "owned",
    }
    (owned / benchmark.OWNERSHIP_MARKER).write_text(json.dumps(marker), encoding="utf-8")
    (owned / "inbox").mkdir()
    (owned / "inbox" / "image.png").write_bytes(b"fixture")

    benchmark.remove_owned_batch(root, owned, "run-1", "owned")

    assert not owned.exists()
    assert root.is_dir()


def _write_recovery_manifest(benchmark, run_dir, run_id):
    manifest = {
        "schema": benchmark.MANIFEST_SCHEMA,
        "run_id": run_id,
        "batch_root": str(run_dir.parent / "batches"),
        "batches": [],
        "status": "created",
    }
    path = run_dir / "recovery-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_profile_cleanup_removes_only_manifest_owned_direct_directory(tmp_path):
    benchmark = load_benchmark_module()
    output_root = tmp_path / "thumbnail-benchmarks"
    run_id = "run-owned"
    run_dir = output_root / run_id
    profiles = run_dir / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "firefox-100").mkdir()
    (profiles / "firefox-100" / "prefs.js").write_text("fixture", encoding="utf-8")
    manifest_path = _write_recovery_manifest(benchmark, run_dir, run_id)

    outcome = benchmark.cleanup_owned_profiles(output_root, manifest_path)

    assert outcome == {"status": "removed", "removed": True, "reason": None}
    assert not profiles.exists()
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["profile_cleanup"] == outcome


def test_profile_cleanup_refuses_mismatched_manifest_run_directory(tmp_path):
    benchmark = load_benchmark_module()
    output_root = tmp_path / "thumbnail-benchmarks"
    run_dir = output_root / "actual-run"
    profiles = run_dir / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "must-remain.txt").write_text("fixture", encoding="utf-8")
    manifest_path = _write_recovery_manifest(benchmark, run_dir, "different-run")

    with pytest.raises(benchmark.CleanupRefused, match="run directory"):
        benchmark.cleanup_owned_profiles(output_root, manifest_path)

    assert profiles.is_dir()
    assert (profiles / "must-remain.txt").is_file()


def test_profile_cleanup_refuses_symlinked_profiles_directory(tmp_path):
    benchmark = load_benchmark_module()
    output_root = tmp_path / "thumbnail-benchmarks"
    run_id = "run-symlink"
    run_dir = output_root / run_id
    outside = tmp_path / "outside-profile"
    outside.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    try:
        (run_dir / "profiles").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    manifest_path = _write_recovery_manifest(benchmark, run_dir, run_id)

    with pytest.raises(benchmark.CleanupRefused, match="symlink"):
        benchmark.cleanup_owned_profiles(output_root, manifest_path)

    assert outside.is_dir()


def test_fixture_creation_uses_distinct_names_and_matching_markers(tmp_path):
    benchmark = load_benchmark_module()
    root = tmp_path / "batches"
    seed_dir = tmp_path / "seeds"
    specs = benchmark.build_fixture_specs("run-abc", [5], ["firefox"])

    benchmark.create_fixture_batches(root, seed_dir, specs)

    primary = root / specs[0].primary_batch
    companion = root / specs[0].companion_batch
    images = sorted((primary / "inbox").glob("*.png"))
    marker = json.loads((primary / benchmark.OWNERSHIP_MARKER).read_text(encoding="utf-8"))
    assert len(images) == 5
    assert len({image.name for image in images}) == 5
    assert marker == {
        "schema": benchmark.MARKER_SCHEMA,
        "run_id": "run-abc",
        "batch": specs[0].primary_batch,
    }
    assert (companion / "inbox").is_dir()
    assert all((primary / folder).is_dir() for folder in benchmark.BATCH_FOLDERS)


def test_resource_metrics_keep_unavailable_values_truthful():
    benchmark = load_benchmark_module()
    entries = [
        {
            "name": "http://localhost/curator/thumb/batch/inbox/a.png",
            "duration": 12.5,
            "transferSize": 0,
            "encodedBodySize": 2048,
        },
        {
            "name": "http://localhost/curator_static/css/base.css",
            "duration": 2,
            "transferSize": 100,
            "encodedBodySize": 80,
        },
        {
            "name": "http://localhost/curator/thumb/batch/inbox/b.png",
            "duration": 8.25,
            "transferSize": None,
            "encodedBodySize": None,
        },
    ]

    metrics = benchmark.summarize_thumbnail_resources(entries, "/curator/thumb/")

    assert metrics["request_count"] == 2
    assert metrics["duration_ms"] == 20.75
    assert metrics["encoded_body_bytes"] is None
    assert metrics["transfer_bytes"] is None
    assert metrics["cache_hit_heuristic"] == {
        "available": False,
        "value": None,
        "reason": "Resource Timing byte sizes were unavailable for one or more thumbnails",
        "methodology": "transferSize == 0 and encodedBodySize > 0",
    }


def test_injected_instrumentation_expands_resource_timing_buffer():
    benchmark = load_benchmark_module()

    assert "performance.setResourceTimingBufferSize" in benchmark.INSTALL_INSTRUMENTATION
    assert "expectedThumbnailCount" in benchmark.INSTALL_INSTRUMENTATION
    assert "phaseStart" in benchmark.INSTALL_INSTRUMENTATION
    assert "entry.startTime >= state.phaseStart" in benchmark.INSTALL_INSTRUMENTATION


def test_sidebar_instrumentation_uses_observable_css_widths_only():
    benchmark = load_benchmark_module()
    block = benchmark.SIDEBAR_WIDTH_PHASE

    assert re.search(r"(?<![\w$])sidebarWidth(?![\w$])", block) is None
    assert re.search(r"(?<![\w$])aiSidebarWidth(?![\w$])", block) is None
    assert "getComputedStyle(document.documentElement)" in block
    assert "getPropertyValue('--sidebar-width')" in block
    assert "getPropertyValue('--ai-sidebar-width')" in block
    assert "restoredWidths" in block
    assert "applySidebarWidth(originalWidths.left, false)" in block
    assert "applyAiSidebarWidth(originalWidths.right, false)" in block


def test_blob_instrumentation_wraps_once_and_avoids_lexical_cache_access():
    benchmark = load_benchmark_module()
    combined = benchmark.INSTALL_INSTRUMENTATION + benchmark.PAGE_METRICS + benchmark.BLOB_BYTES

    assert "thumbnailBlobUrlCache" not in combined
    assert "objectUrlWrapperInstalled" in benchmark.INSTALL_INSTRUMENTATION
    assert "if (!state.objectUrlWrapperInstalled)" in benchmark.INSTALL_INSTRUMENTATION
    assert "blobUrls.set(blobUrl, object.size)" in benchmark.INSTALL_INSTRUMENTATION
    assert "blobUrls.delete(String(url))" in benchmark.INSTALL_INSTRUMENTATION
    assert "Reflect.apply(originalCreateObjectURL" in benchmark.INSTALL_INSTRUMENTATION
    assert "Reflect.apply(originalRevokeObjectURL" in benchmark.INSTALL_INSTRUMENTATION
    assert "fetch(" not in benchmark.BLOB_BYTES
    assert "benchmark DOM bridge" in benchmark.BLOB_METHODOLOGY
    assert "page-realm Blob URLs created after instrumentation" in benchmark.BLOB_METHODOLOGY


def test_instrumentation_uses_main_realm_script_and_json_dom_bridge():
    benchmark = load_benchmark_module()
    install = benchmark.INSTALL_INSTRUMENTATION

    assert "document.createElement('script')" in install
    assert "script.textContent" in install
    assert "appendChild(script)" in install
    assert "script.remove()" in install
    assert benchmark.BRIDGE_ID in install
    assert "data-thumbnail-benchmark-bridge" in install
    assert "Main-realm instrumentation did not execute" in install
    assert "window.__thumbnailBenchmark" not in benchmark.PAGE_METRICS
    assert "window.__thumbnailBenchmark" not in benchmark.BLOB_BYTES
    assert "document.getElementById" in benchmark.PAGE_METRICS
    assert "document.getElementById" in benchmark.BLOB_BYTES
    assert "JSON.parse" in benchmark.PAGE_METRICS
    assert "JSON.parse" in benchmark.BLOB_BYTES
    assert "Page blob cache variable unavailable" not in (
        benchmark.PAGE_METRICS + benchmark.BLOB_BYTES + benchmark.BLOB_METHODOLOGY
    )


def test_main_realm_instrumentation_publishes_live_blob_and_phase_state():
    benchmark = load_benchmark_module()
    install = benchmark.INSTALL_INSTRUMENTATION

    assert "state.publishSnapshot" in install
    assert re.search(r"blobUrls\.set\([^;]+;\s*state\.publishSnapshot\(\)", install)
    assert re.search(r"blobUrls\.delete\([^;]+;\s*state\.publishSnapshot\(\)", install)
    assert re.search(r"longTasks\.push\([^;]+;\s*state\.publishSnapshot\(\)", install)
    assert re.search(r"state\.longTasks = \[\];[\s\S]+state\.publishSnapshot\(\)", install)
    assert "blobCount" in install
    assert "blobBytes" in install


def test_browser_stage_error_is_actionable_and_sanitized():
    benchmark = load_benchmark_module()

    class JavascriptException(Exception):
        pass

    error = benchmark.browser_stage_error(
        "sidebar width changes",
        JavascriptException(
            "failed in C:\\private\\profile\\prefs.js at "
            "https://user:secret@example.test/curator\nStacktrace: hidden"
        ),
    )
    message = str(error)

    assert "sidebar width changes" in message
    assert "JavascriptException" in message
    assert "failed in <path>" in message
    assert "user:secret" not in message
    assert "Stacktrace" not in message
    assert "C:\\private" not in message


def test_report_sanitizer_removes_profile_paths_and_settings_payloads():
    benchmark = load_benchmark_module()
    payload = {
        "browser": "firefox",
        "profile_path": "C:/private/browser-profile",
        "settings_payload": {"batch_root": "C:/private/batches", "ai_api_key_set": True},
        "nested": {"driver_path": "C:/tools/geckodriver.exe", "metric": 4},
    }

    sanitized = benchmark.sanitize_report(payload)

    assert sanitized == {"browser": "firefox", "nested": {"metric": 4}}


def test_markdown_summary_renders_unavailable_metrics_without_substitution():
    benchmark = load_benchmark_module()
    report = {
        "schema": benchmark.REPORT_SCHEMA,
        "run_id": "run-1",
        "mode": "native",
        "browser_results": [
            {
                "browser": "firefox",
                "version": "test",
                "size": 100,
                "status": "ok",
                "phases": [
                    {
                        "phase": "cold_initial_load",
                        "classification": "cold",
                        "metrics": {
                            "thumbnail_resources": {"request_count": 100},
                            "long_tasks": {
                                "available": False,
                                "value": None,
                                "reason": "Long Tasks API unavailable",
                            },
                        },
                    }
                ],
            }
        ],
        "cleanup": {"status": "completed"},
        "warnings": [],
    }

    summary = benchmark.render_markdown_summary(report)

    assert "100" in summary
    assert "Unavailable: Long Tasks API unavailable" in summary
    assert "0 long tasks" not in summary
