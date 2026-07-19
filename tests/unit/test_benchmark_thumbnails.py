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


def test_instrumentation_js_contracts():
    """INSTALL_INSTRUMENTATION, PAGE_METRICS, BLOB_BYTES, and BLOB_METHODOLOGY
    must satisfy blob-wrapping, main-realm bridge, and snapshot contracts."""
    benchmark = load_benchmark_module()
    install = benchmark.INSTALL_INSTRUMENTATION
    combined = install + benchmark.PAGE_METRICS + benchmark.BLOB_BYTES

    # Resource timing and phase tracking
    assert "performance.setResourceTimingBufferSize" in install
    assert "expectedThumbnailCount" in install
    assert "phaseStart" in install
    assert "entry.startTime >= state.phaseStart" in install

    # Blob wrapping (once, no lexical cache access)
    assert "thumbnailBlobUrlCache" not in combined
    assert "objectUrlWrapperInstalled" in install
    assert "if (!state.objectUrlWrapperInstalled)" in install
    assert "blobUrls.set(blobUrl, object.size)" in install
    assert "blobUrls.delete(String(url))" in install
    assert "Reflect.apply(originalCreateObjectURL" in install
    assert "Reflect.apply(originalRevokeObjectURL" in install
    assert "fetch(" not in benchmark.BLOB_BYTES
    assert "benchmark DOM bridge" in benchmark.BLOB_METHODOLOGY
    assert "page-realm Blob URLs created after instrumentation" in benchmark.BLOB_METHODOLOGY

    # Main-realm script injection and DOM bridge
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

    # Live blob + phase snapshot publishing
    assert "state.publishSnapshot" in install
    assert re.search(r"blobUrls\.set\([^;]+;\s*state\.publishSnapshot\(\)", install)
    assert re.search(r"blobUrls\.delete\([^;]+;\s*state\.publishSnapshot\(\)", install)
    assert re.search(r"longTasks\.push\([^;]+;\s*state\.publishSnapshot\(\)", install)
    assert re.search(r"state\.longTasks = \[\];[\s\S]+state\.publishSnapshot\(\)", install)
    assert "blobCount" in install
    assert "blobBytes" in install


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


def test_each_checkpoint_has_required_metric_keys():
    """Every checkpoint record must include loaded_image_count,
    thumbnail_request_count, blob_live_count, blob_bytes, dom_node_count,
    browser_process_memory, frame_timing, long_tasks, and thumbnail_disk."""
    benchmark = load_benchmark_module()

    required = {
        "name",
        "elapsed_ms",
        "loaded_image_count",
        "thumbnail_request_count",
        "blob_live_count",
        "blob_bytes",
        "dom_node_count",
    }
    # These can be available/unavailable dicts but must be present
    metric_keys = {
        "browser_process_memory",
        "frame_timing",
        "long_tasks",
        "thumbnail_disk",
    }

    record = benchmark._build_checkpoint_record(
        name="first_viewport_settled",
        elapsed_ms=123.456,
        loaded_image_count=15,
        thumbnail_request_count=20,
        blob_live_count=15,
        blob_bytes=123456,
        dom_node_count=5000,
        browser_process_memory=benchmark.available(
            {"rss_bytes": 1000000, "process_count": 1}, "psutil RSS"
        ),
        frame_timing=benchmark.available({"elapsed_ms": 200, "frame_count": 10}, "rAF intervals"),
        long_tasks=benchmark.available(
            {"count": 3, "duration_ms": 150}, "PerformanceObserver longtask"
        ),
        thumbnail_disk=benchmark.available(
            {"file_count": 20, "disk_bytes": 200000}, ".thumbs directory"
        ),
    )

    assert required.issubset(set(record.keys()))
    assert metric_keys.issubset(set(record.keys()))
    assert record["elapsed_ms"] == 123.456
    assert record["loaded_image_count"] == 15
    assert record["thumbnail_request_count"] == 20
    assert record["blob_live_count"] == 15
    assert record["blob_bytes"] == 123456
    assert record["dom_node_count"] == 5000


def test_checkpoint_unavailable_metrics_preserve_reason():
    """When a metric is unavailable at checkpoint time, the record must
    retain the explicit reason, not substitute a default."""
    benchmark = load_benchmark_module()

    record = benchmark._build_checkpoint_record(
        name="first_viewport_settled",
        elapsed_ms=50.0,
        loaded_image_count=0,
        thumbnail_request_count=0,
        blob_live_count=None,
        blob_bytes=None,
        dom_node_count=500,
        browser_process_memory=benchmark.unavailable("WebDriver service PID unavailable"),
        frame_timing=benchmark.unavailable("No frame data"),
        long_tasks=benchmark.unavailable("Long Tasks API unavailable in this browser/context"),
        thumbnail_disk=benchmark.available({"file_count": 0, "disk_bytes": 0}, ".thumbs directory"),
    )

    assert record["browser_process_memory"]["available"] is False
    assert "WebDriver service PID unavailable" in str(record["browser_process_memory"]["reason"])
    assert record["frame_timing"]["available"] is False
    assert record["frame_timing"]["reason"] == "No frame data"
    assert record["long_tasks"]["available"] is False
    assert record["long_tasks"]["reason"] is not None
    assert record["thumbnail_disk"]["available"] is True
    assert record["thumbnail_disk"]["value"]["file_count"] == 0


def test_full_traversal_visits_all_regions_without_requiring_all_elements_terminal():
    """Full traversal must visit every grid region and settle each approached
    region without requiring all DOM thumbnails to be in a loaded/error state
    before declaring completion."""
    benchmark = load_benchmark_module()
    traverse = benchmark.TRAVERSAL_GRID

    assert "totalPositions" in traverse
    assert "regionsVisited" in traverse
    assert "5000" in traverse or "regionElapsed" in traverse
    assert "currentRegion" in traverse
    # Must NOT gate on all images being loaded
    full_loaded_check = re.search(r"(?<!visible)(?:all.*loaded|loaded.*===.*expected)", traverse)
    assert full_loaded_check is None, "Full traversal must not require all thumbnails to be loaded"


def test_viewport_settle_predicate_includes_expected_count_guard():
    """VIEWPORT_SETTLE_ASYNC must require state.count === expectedCount so
    that stale companion-batch thumbnails do not satisfy the settle
    condition before the primary batch finishes rendering."""
    benchmark = load_benchmark_module()
    settle = benchmark.VIEWPORT_SETTLE_ASYNC

    assert "state.count === expectedCount" in settle, (
        "settle predicate must include expectedCount guard for stale companion rejection"
    )
    assert "state.visibleLoaded === state.visibleCount" in settle
    assert "state.visibleCount > 0" in settle


def _checkpoint_cold_driver(
    benchmark,
    spec,
    *,
    viewport="ready",
    traversal="success",
    grid_scroll=(2000, 700),
    resource_count=50,
    dom_extra=None,
    monkeypatch=None,
):
    """Build FakeDriver, deps, session for _prepare_checkpoint_cold_phase.

    viewport: "ready", "timeout", or "unavailable"
    traversal: "success", "unsettled", "frame_cap", or "unavailable"

    Returns (driver, deps, session, hooks dict with events, instrument_count,
    scroll_ops, traversal_calls, client_height, distinct_loaded).
    """

    events: list = []
    instrument_count = [0]
    scroll_ops: list = []
    traversal_calls: list = []
    client_height_val = [None]
    distinct_loaded_log: list = []
    resource_requests_so_far = [0]

    class FakeSession:
        def switch(self, batch):
            events.append(("switch", batch))

    class FakeDriver:
        def __init__(self):
            self._active_batch = None
            self._view_count = 0

        def get(self, url):
            events.append(("navigate", url))

        def execute_script(self, script):
            # DOM stats
            if "getElementsByTagName" in script:
                base = {
                    "domNodeCount": 500,
                    "blobCacheEntryCount": 3,
                    "blobObservation": {"available": True, "reason": None},
                    "longTasks": {
                        "available": True,
                        "entries": [{"startTime": 100, "duration": 50}],
                    },
                    "navigation": {"domContentLoadedMs": 300, "loadEventMs": 500},
                }
                if dom_extra:
                    base.update(dom_extra)
                return base
            # Resource Timing entries
            if "performance.getEntriesByType('resource')" in script:
                active_size = (
                    spec.size if self._active_batch == spec.primary_batch else spec.companion_size
                )
                count = min(resource_requests_so_far[0] + 10, active_size)
                resource_requests_so_far[0] = count
                return [
                    {
                        "name": f"http://localhost/curator/thumb/b/inbox/{i}.png",
                        "duration": 8.0,
                        "transferSize": 0,
                        "encodedBodySize": 2048,
                    }
                    for i in range(min(count, resource_count))
                ]
            # Grid state (viewport settle / _query_grid_loaded)
            if "visibleCount" in script and "visibleLoaded" in script:
                self._view_count += 1
                active_size = (
                    spec.size if self._active_batch == spec.primary_batch else spec.companion_size
                )
                loaded = min(self._view_count * active_size, active_size)
                distinct_loaded_log.append(loaded)
                return {
                    "count": active_size,
                    "loaded": loaded,
                    "visibleCount": min(15, active_size),
                    "visibleLoaded": min(15, loaded),
                    "currentBatch": self._active_batch,
                }
            # Grid dimension query
            if "scrollHeight" in script and "clientHeight" in script:
                client_height_val[0] = grid_scroll[1]
                return [grid_scroll[0], grid_scroll[1]]
            # ScrollTop set (captured for scroll restoration tests)
            if "scrollTop" in script and ".content" in script and "=" in script:
                m = re.search(r"scrollTop\s*=\s*(\d+)", script)
                if m:
                    scroll_ops.append(int(m.group(1)))
            return {}

        def execute_async_script(self, script, *args):
            if "selectBatch" in script:
                self._active_batch = args[0] if args else None
                return {"ok": True}
            if "blobUrls" in script or "curator-thumbnail-benchmark-bridge" in script:
                return {"available": True, "count": 3, "bytes": 30000}
            # Viewport settle async
            if "expectedCount" in script and "timeoutMs" in script:
                if viewport == "unavailable":
                    return {
                        "available": False,
                        "reason": "Grid scroll container not found",
                    }
                if viewport == "timeout":
                    return {
                        "available": True,
                        "ready": False,
                        "elapsedMs": 5000.0,
                        "intervals": [16, 17, 16],
                        "state": {
                            "count": spec.size,
                            "loaded": 5,
                            "visibleCount": 20,
                            "visibleLoaded": 5,
                        },
                    }
                # viewport == "ready"
                return {
                    "available": True,
                    "ready": True,
                    "elapsedMs": 350.0,
                    "intervals": [16, 17, 18, 20, 16],
                    "state": {
                        "count": spec.size,
                        "loaded": 15,
                        "visibleCount": min(20, spec.size),
                        "visibleLoaded": min(20, spec.size),
                        "currentBatch": self._active_batch,
                    },
                }
            # Traversal
            if "viewportSettled" in script and "visitedRegions" in script:
                positions = args[0] if args and isinstance(args[0], list) else []
                traversal_calls.append(list(positions))
                n = len(positions)
                if traversal == "unavailable":
                    return {"available": False, "reason": "Grid scroll container not found"}
                if traversal == "frame_cap":
                    return {
                        "available": True,
                        "elapsedMs": 150,
                        "mode": "traversal",
                        "intervals": [16, 17],
                        "frameCapReached": True,
                        "regionsVisited": n - 1 if n > 1 else 0,
                        "totalPositions": n,
                        "visitedRegions": [
                            {
                                "region": i,
                                "scrollPosition": positions[i],
                                "visibleCount": 10,
                                "visibleLoaded": 10,
                                "settled": True,
                                "regionElapsedMs": 50,
                            }
                            for i in range(max(0, n - 1))
                        ],
                    }
                regions = []
                for i in range(n):
                    settled = True
                    if traversal == "unsettled" and i == n - 1:
                        settled = False
                    regions.append(
                        {
                            "region": i,
                            "scrollPosition": positions[i] if i < n else 0,
                            "visibleCount": 10,
                            "visibleLoaded": 10,
                            "settled": settled,
                            "regionElapsedMs": 50,
                        }
                    )
                return {
                    "available": True,
                    "elapsedMs": 300 if n <= 2 else 800,
                    "mode": "traversal",
                    "intervals": [16, 17, 18],
                    "frameCapReached": False,
                    "regionsVisited": n,
                    "totalPositions": n,
                    "visitedRegions": regions,
                }
            return {"available": True, "elapsedMs": 100, "intervals": []}

    def fake_instrument(driver, count):
        instrument_count[0] += 1

    if monkeypatch is not None:
        monkeypatch.setattr(benchmark, "_install_instrumentation", fake_instrument)

    driver = FakeDriver()

    # Minimal OptionalDependencies stand-in for psutil-based RSS
    _MemInfo = type("_MemInfo", (), {"rss": 50_000_000})
    _FakeProc = type(
        "_FakeProc",
        (),
        {
            "children": staticmethod(lambda recursive=False: []),
            "name": staticmethod(lambda: spec.browser),
            "memory_info": staticmethod(lambda: _MemInfo()),
        },
    )
    _FakePsutil = type("_FakePsutil", (), {"Process": staticmethod(lambda pid: _FakeProc())})
    _svc = type("_Svc", (), {"process": type("_Proc", (), {"pid": 1234})()})()
    driver.service = _svc
    deps = type("_FakeDeps", (), {"psutil": _FakePsutil()})()
    session = FakeSession()

    hooks = {
        "events": events,
        "instrument_count": instrument_count,
        "scroll_ops": scroll_ops,
        "traversal_calls": traversal_calls,
        "client_height": client_height_val,
        "distinct_loaded": distinct_loaded_log,
    }
    return driver, deps, session, hooks


def test_cold_phase_orchestration_checkpoints_flow(monkeypatch, tmp_path):
    benchmark = load_benchmark_module()
    from pathlib import Path

    spec = benchmark.build_fixture_specs("run-flow", [50], ["firefox"])[0]
    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=Path(tmp_path),
        active_batch=None,
    )
    (Path(tmp_path) / spec.primary_batch / ".thumbs").mkdir(parents=True)

    driver, deps, session, hooks = _checkpoint_cold_driver(
        benchmark,
        spec,
        viewport="ready",
        resource_count=50,
        monkeypatch=monkeypatch,
    )

    checkpoints, companion_ready, final_readiness, cp_w = benchmark._prepare_checkpoint_cold_phase(
        driver,
        deps,
        session,
        runtime,
        spec,
        timeout=0.5,
    )

    # ---- Basic structure and cumulative requests ----
    assert len(checkpoints) == 3
    names = [cp["name"] for cp in checkpoints]
    assert names == ["first_viewport_settled", "partial_traversal", "full_traversal"]
    for cp in checkpoints:
        for key in (
            "loaded_image_count",
            "thumbnail_request_count",
            "blob_live_count",
            "blob_bytes",
            "dom_node_count",
            "browser_process_memory",
            "frame_timing",
            "long_tasks",
            "thumbnail_disk",
            "elapsed_ms",
        ):
            assert key in cp
    assert companion_ready is not None
    assert final_readiness is not None
    assert hooks["instrument_count"][0] == 1

    cp1, cp2, cp3 = checkpoints
    assert cp1["thumbnail_request_count"] >= 0
    assert cp2["thumbnail_request_count"] >= cp1["thumbnail_request_count"]
    assert cp3["thumbnail_request_count"] >= cp2["thumbnail_request_count"]
    assert cp1["loaded_image_count"] <= spec.size
    assert cp2["loaded_image_count"] <= spec.size
    assert cp3["loaded_image_count"] <= spec.size
    assert len(hooks["traversal_calls"]) == 2

    # ---- Gap-free traversal, client height, scroll restore ----
    assert hooks["client_height"][0] == 700
    partial_pos = hooks["traversal_calls"][0]
    full_pos = hooks["traversal_calls"][1]
    region_step = round(700 * 0.6)
    for positions, expected_last in [(partial_pos, 800), (full_pos, 2000)]:
        for i in range(1, len(positions)):
            assert positions[i] - positions[i - 1] <= region_step
        assert positions[-1] == expected_last
    assert hooks["scroll_ops"][-1] == 0

    # ---- first_viewport_ms from cp1 ----
    assert final_readiness["first_viewport_ms"] == pytest.approx(cp1["elapsed_ms"], rel=0.01)
    assert cp1["frame_timing"]["available"] is True


@pytest.mark.parametrize(
    "viewport_mode,expected_cp1_ready,expected_cp1_avail,"
    "expect_first_viewport_ms_null,expect_warning_keyword,expect_readiness_reason",
    [
        # success
        ("ready", True, True, False, None, None),
        # timeout
        ("timeout", False, True, True, "timed out", "Viewport did not settle within timeout"),
        # unavailable
        ("unavailable", False, False, True, "unavailable", "Grid scroll container not found"),
    ],
)
def test_viewport_checkpoint_edge_cases(
    monkeypatch,
    tmp_path,
    viewport_mode,
    expected_cp1_ready,
    expected_cp1_avail,
    expect_first_viewport_ms_null,
    expect_warning_keyword,
    expect_readiness_reason,
):
    """Parametrized viewport ready, timeout, and unavailable scenarios."""
    benchmark = load_benchmark_module()
    from pathlib import Path

    spec = benchmark.build_fixture_specs("run-vp", [50], ["firefox"])[0]
    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=Path(tmp_path),
        active_batch=None,
    )
    (Path(tmp_path) / spec.primary_batch / ".thumbs").mkdir(parents=True)

    driver, deps, session, _hooks = _checkpoint_cold_driver(
        benchmark,
        spec,
        viewport=viewport_mode,
        resource_count=50,
        monkeypatch=monkeypatch,
    )

    cp, _, final_readiness, cp_w = benchmark._prepare_checkpoint_cold_phase(
        driver,
        deps,
        session,
        runtime,
        spec,
        timeout=0.5,
    )

    cp1 = cp[0]
    r = cp1["readiness"]
    assert r["ready"] is expected_cp1_ready
    assert r["available"] is expected_cp1_avail
    assert r.get("reason") == expect_readiness_reason

    if expect_first_viewport_ms_null:
        assert final_readiness["first_viewport_ms"] is None
    else:
        assert final_readiness["first_viewport_ms"] == pytest.approx(cp1["elapsed_ms"], rel=0.01)

    if expect_warning_keyword:
        assert any(expect_warning_keyword in w.lower() for w in cp_w), (
            f"expected '{expect_warning_keyword}' in warnings: {cp_w}"
        )


@pytest.mark.parametrize(
    "traversal_mode,expect_cp2_ready,expect_cp2_avail,"
    "expect_cp3_ready,expect_cp3_avail,expect_unsettled,expect_warning",
    [
        ("success", True, True, True, True, 0, None),
        ("unsettled", False, True, False, True, 1, "unsettled"),
        ("frame_cap", False, True, False, True, None, "frame"),
        ("unavailable", False, False, False, False, None, "unavailable"),
    ],
)
def test_traversal_checkpoint_readiness(
    monkeypatch,
    tmp_path,
    traversal_mode,
    expect_cp2_ready,
    expect_cp2_avail,
    expect_cp3_ready,
    expect_cp3_avail,
    expect_unsettled,
    expect_warning,
):
    """Checkpoint 2/3 readiness must carry exact unsettled_region_count,
    available/reason, ready flag, and warnings reflecting traversal outcome."""
    benchmark = load_benchmark_module()
    from pathlib import Path

    spec = benchmark.build_fixture_specs("run-trv", [50], ["firefox"])[0]
    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=Path(tmp_path),
        active_batch=None,
    )
    (Path(tmp_path) / spec.primary_batch / ".thumbs").mkdir(parents=True)

    driver, deps, session, _hooks = _checkpoint_cold_driver(
        benchmark,
        spec,
        traversal=traversal_mode,
        monkeypatch=monkeypatch,
    )

    cp, _, _, cp_w = benchmark._prepare_checkpoint_cold_phase(
        driver,
        deps,
        session,
        runtime,
        spec,
        timeout=0.5,
    )

    # Verify cp2 (partial_traversal)
    r2 = cp[1]["readiness"]
    assert r2["ready"] is expect_cp2_ready, (
        f"cp2 ready: expected {expect_cp2_ready}, got {r2['ready']}"
    )
    assert r2["available"] is expect_cp2_avail
    if expect_unsettled is not None:
        state2 = r2.get("state", {})
        actual_u2 = state2.get("unsettled_region_count", 0)
        assert actual_u2 == expect_unsettled, (
            f"cp2 unsettled_region_count: expected {expect_unsettled}, got {actual_u2}"
        )

    # Verify cp3 (full_traversal)
    r3 = cp[2]["readiness"]
    assert r3["ready"] is expect_cp3_ready
    assert r3["available"] is expect_cp3_avail
    if expect_unsettled is not None:
        state3 = r3.get("state", {})
        actual_u3 = state3.get("unsettled_region_count", 0)
        assert actual_u3 == expect_unsettled

    # Verify warnings
    if expect_warning:
        assert any(expect_warning in w.lower() for w in cp_w), (
            f"expected '{expect_warning}' in warnings: {cp_w}"
        )

    # Unavailable traversals must carry reason
    if traversal_mode == "unavailable":
        assert r2.get("reason") is not None, "cp2 unavailable must have reason"
        assert r3.get("reason") is not None, "cp3 unavailable must have reason"


def test_checkpoint_data_appears_in_full_report_serialization():
    benchmark = load_benchmark_module()
    phase = benchmark._phase("cold_initial_load", "cold", {"dummy": True}, [])
    phase["checkpoints"] = [
        benchmark._build_checkpoint_record(
            name="first_viewport_settled",
            elapsed_ms=50.0,
            loaded_image_count=12,
            thumbnail_request_count=15,
            blob_live_count=12,
            blob_bytes=20000,
            dom_node_count=3500,
            browser_process_memory=benchmark.available(
                {"rss_bytes": 1000000, "process_count": 1}, "psutil RSS"
            ),
            frame_timing=benchmark.unavailable("No frame data"),
            long_tasks=benchmark.available({"count": 0, "duration_ms": 0}, "PerformanceObserver"),
            thumbnail_disk=benchmark.available({"file_count": 3, "disk_bytes": 5000}, ".thumbs"),
        ),
    ]
    serialized = json.loads(json.dumps(phase))
    assert serialized["checkpoints"] is not None
    assert len(serialized["checkpoints"]) == 1
    cp = serialized["checkpoints"][0]
    assert cp["name"] == "first_viewport_settled"
    assert cp["loaded_image_count"] == 12
    assert cp["thumbnail_request_count"] == 15
    assert cp["blob_live_count"] == 12
    assert cp["thumbnail_disk"]["available"] is True
    assert cp["long_tasks"]["available"] is True


def test_summary_renders_each_phase_once_without_duplicate_or_swap():
    benchmark = load_benchmark_module()
    av = benchmark.available
    un = benchmark.unavailable

    report = {
        "schema": benchmark.REPORT_SCHEMA,
        "run_id": "run-integrated",
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
                        "cross_browser_metrics": {
                            "thumbnail_resources": {"request_count": 100},
                            "grid_readiness": av(
                                {"ready": True, "elapsed_ms": 1500, "first_viewport_ms": 350},
                                "harness",
                            ),
                            "long_tasks": av({"count": 2, "duration_ms": 120}, "observer"),
                        },
                        "checkpoints": [
                            {
                                "name": "first_viewport_settled",
                                "loaded_image_count": 20,
                                "thumbnail_request_count": 25,
                                "blob_live_count": 20,
                                "dom_node_count": 600,
                            },
                        ],
                    },
                    {
                        "phase": "controlled_scroll",
                        "classification": "warm",
                        "cross_browser_metrics": {
                            "thumbnail_resources": {"request_count": 0},
                            "grid_readiness": un("not measured"),
                            "long_tasks": av({"count": 0, "duration_ms": 0}, "observer"),
                        },
                    },
                    {
                        "phase": "warm_reload",
                        "classification": "warm",
                        "cross_browser_metrics": {
                            "thumbnail_resources": {"request_count": 100},
                            "grid_readiness": av(
                                {"ready": True, "elapsed_ms": 800, "first_viewport_ms": 200},
                                "harness",
                            ),
                            "long_tasks": av({"count": 0, "duration_ms": 0}, "observer"),
                        },
                    },
                ],
            }
        ],
        "active_batch_restore": {"status": "restored"},
        "cleanup": {"status": "completed"},
        "profile_cleanup": {"status": "removed"},
        "warnings": [],
    }

    summary = benchmark.render_markdown_summary(report)

    # Each phase appears exactly once
    assert summary.count("cold_initial_load |") == 1
    assert summary.count("controlled_scroll |") == 1
    assert summary.count("warm_reload |") == 1
    # Only cold phase marked with checkpoints
    assert "ok (with checkpoints)" in summary
    assert summary.count("ok (with checkpoints)") == 1
    # Request counts not swapped across phases
    assert "cold_initial_load | cold | 100 |" in summary
    assert "controlled_scroll | warm | 0 |" in summary
    assert "warm_reload | warm | 100 |" in summary
    # Checkpoint section rendered
    assert "## Checkpoints" in summary
    assert "first_viewport_settled" in summary


@pytest.mark.parametrize(
    "total_h,client_h,expected_last",
    [
        (0, 1000, 0),
        (200, 1000, 200),
        (2000, 1000, 2000),
    ],
)
def test_traversal_positions_full_includes_exact_bottom(total_h, client_h, expected_last):
    benchmark = load_benchmark_module()
    positions = benchmark._build_traversal_positions(total_h, client_h, "full")
    assert positions[0] == 0
    assert positions[-1] == expected_last, f"bottom: expected {expected_last}, got {positions}"
    if expected_last > 0:
        assert expected_last in positions
    # No gap larger than region_height
    region_h = max(300, round(client_h * 0.6))
    for i in range(1, len(positions)):
        assert positions[i] - positions[i - 1] <= region_h, (
            f"gap {positions[i] - positions[i - 1]} at idx {i} exceeds {region_h}"
        )


@pytest.mark.parametrize(
    "total_h,client_h,expected_last",
    [
        (2000, 1000, 800),
    ],
)
def test_traversal_positions_partial_bounded_sequential(total_h, client_h, expected_last):
    benchmark = load_benchmark_module()
    positions = benchmark._build_traversal_positions(total_h, client_h, "partial")
    assert positions[0] == 0
    assert positions[-1] == expected_last
    region_h = max(300, round(client_h * 0.6))
    # Steps must be sequential / gap-free
    for i in range(1, len(positions)):
        assert positions[i] - positions[i - 1] <= region_h


@pytest.mark.parametrize(
    "readiness,expect_keyword",
    [
        ({"ready": False, "available": True, "elapsed_ms": 5000.0, "state": {}}, "timed out"),
        (
            {
                "ready": False,
                "available": False,
                "elapsed_ms": 0,
                "state": {},
                "reason": "Grid scroll container not found",
            },
            "unavailable",
        ),
        (
            {
                "ready": False,
                "available": True,
                "elapsed_ms": 300,
                "state": {
                    "unsettled_region_count": 2,
                    "frame_cap_reached": False,
                    "regions_visited": 2,
                    "total_regions": 3,
                },
            },
            "unsettled",
        ),
        (
            {
                "ready": False,
                "available": True,
                "elapsed_ms": 100,
                "state": {
                    "unsettled_region_count": 0,
                    "frame_cap_reached": True,
                    "regions_visited": 5,
                    "total_regions": 5,
                },
            },
            "frame",
        ),
    ],
)
def test_build_checkpoint_warnings_cases(readiness, expect_keyword):
    benchmark = load_benchmark_module()
    warnings = benchmark._build_checkpoint_warnings("test_cp", readiness)
    assert any(expect_keyword in w.lower() for w in warnings), (
        f"expected '{expect_keyword}' in warnings: {warnings}"
    )


def test_readiness_calculation_detects_timed_out_regions():
    """_is_traversal_ready rejects unsettled, capped, mismatched, and unavailable traversals."""
    benchmark = load_benchmark_module()
    assert (
        benchmark._is_traversal_ready(
            {
                "available": True,
                "frameCapReached": False,
                "regionsVisited": 3,
                "totalPositions": 3,
                "visitedRegions": [{"settled": True}, {"settled": True}, {"settled": True}],
            }
        )
        is True
    )
    assert (
        benchmark._is_traversal_ready(
            {
                "available": True,
                "frameCapReached": False,
                "regionsVisited": 3,
                "totalPositions": 3,
                "visitedRegions": [{"settled": True}, {"settled": False}, {"settled": True}],
            }
        )
        is False
    )
    assert (
        benchmark._is_traversal_ready(
            {
                "available": True,
                "frameCapReached": True,
                "regionsVisited": 5,
                "totalPositions": 5,
                "visitedRegions": [],
            }
        )
        is False
    )
    assert benchmark._is_traversal_ready({"available": False}) is False
    assert (
        benchmark._is_traversal_ready(
            {
                "available": True,
                "frameCapReached": False,
                "regionsVisited": 2,
                "totalPositions": 5,
                "visitedRegions": [{"settled": True}, {"settled": True}],
            }
        )
        is False
    )


def test_blob_observation_unavailable_preserves_reason():
    """Blob unavailability carries methodology and reason in checkpoint records."""
    benchmark = load_benchmark_module()
    record = benchmark._build_checkpoint_record(
        name="test",
        elapsed_ms=50.0,
        loaded_image_count=0,
        thumbnail_request_count=0,
        blob_live_count=None,
        blob_bytes=None,
        dom_node_count=500,
        browser_process_memory=benchmark.unavailable("PID unavail"),
        frame_timing=benchmark.unavailable("No frame"),
        long_tasks=benchmark.unavailable("N/A"),
        thumbnail_disk=benchmark.available({"file_count": 0, "disk_bytes": 0}, ".thumbs"),
        blob_observation=benchmark.unavailable("Bridge blob unavailable"),
    )
    assert "blob_observation" in record
    assert record["blob_observation"]["available"] is False
    assert record["blob_observation"]["reason"] is not None


class _GridScriptFakeDriver:
    """Fake that returns an integer for execute_script with a top-level
    return script and raises for an IIFE (no top-level return propagation)."""

    def __init__(self, count):
        self._count = count

    def execute_script(self, script):
        stripped = script.strip()
        if stripped.startswith("(function()"):
            raise RuntimeError("IIFE without WebDriver top-level return propagates undefined")
        if "return " in script and "#grid" in script:
            return self._count
        raise RuntimeError(f"unexpected script shape: {stripped[:80]}")


def test_grid_loaded_js_has_top_level_return():
    """_grid_loaded_count_js must produce a script with a top-level return
    statement, not an IIFE, so that Selenium execute_script receives the
    integer distinct loaded count instead of None/undefined."""
    benchmark = load_benchmark_module()
    script = benchmark._grid_loaded_count_js()

    assert not script.strip().startswith("(function()"), (
        "expected top-level return, got IIFE: _grid_loaded_count_js()"
    )
    assert "return " in script
    assert "#grid .thumb:not(.loading-placeholder)" in script
    assert "classList.contains('loaded')" in script


def test_query_grid_loaded_returns_distinct_count():
    """_query_grid_loaded must return the driver's integer response when
    the script is a proper top-level return expression."""
    benchmark = load_benchmark_module()
    count = benchmark._query_grid_loaded(_GridScriptFakeDriver(42))
    assert count == 42
