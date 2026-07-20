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
    """FakeDriver/session/hooks for _prepare_checkpoint_cold_phase.
    viewport: ready/timeout/unavailable; traversal: success/unsettled/frame_cap/unavailable."""

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
    assert len(hooks["traversal_calls"]) == 3  # companion + primary partial + primary full

    # ---- Gap-free traversal, client height, scroll restore ----
    assert hooks["client_height"][0] == 700
    # First is companion, last two are primary partial + full
    partial_pos = hooks["traversal_calls"][1]
    full_pos = hooks["traversal_calls"][2]
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


def _shared_benchmark_driver(
    benchmark,
    spec,
    *,
    viewport="ready",
    traversal="success",
    grid_scroll=(2000, 700),
):
    """Configurable FakeDriver for _select_and_traverse, cold, warm, A-B-A."""
    events: list = []
    scroll_ops: list[int] = []
    client_height_val: list = [None]
    positions_passed: list[list[int]] = []
    instrument_args: list[tuple] = []
    quit_flag = [False]
    resource_log: list[list[dict]] = [[]]

    class FakeDriver:
        capabilities = {}
        service = type("Svc", (), {"process": type("Pr", (), {"pid": 1234})()})()

        def __init__(self):
            self._active_batch = None

        def get(self, url):
            events.append(("navigate", url))

        def refresh(self):
            events.append(("refresh",))

        def execute_script(self, script):
            if "scrollHeight" in script and "clientHeight" in script:
                client_height_val[0] = grid_scroll[1]
                return [grid_scroll[0], grid_scroll[1]]
            if "getElementsByTagName" in script:
                return {
                    "domNodeCount": 500,
                    "blobCacheEntryCount": 3,
                    "blobObservation": {"available": True, "reason": None},
                    "longTasks": {"available": True, "entries": []},
                    "navigation": {"domContentLoadedMs": 300, "loadEventMs": 500},
                }
            if "performance.getEntriesByType('resource')" in script:
                # Return currently accumulated resource log
                return resource_log[-1] if resource_log else []
            if "#grid .thumb:not(.loading-placeholder)" in script:
                # _wait_for_grid (has visibleCount) vs _query_grid_loaded (returns int)
                if "visibleCount" in script:
                    count_val = 50
                    if spec and self._active_batch:
                        if self._active_batch == spec.primary_batch:
                            count_val = spec.size
                        elif self._active_batch == spec.companion_batch:
                            count_val = spec.companion_size
                    return {
                        "count": count_val,
                        "loaded": count_val,
                        "visibleCount": 15,
                        "visibleLoaded": 15,
                    }
                return 42  # _query_grid_loaded: distinct loaded count
            if "scrollTop" in script and "=" in script and ".content" in script:
                m = re.search(r"scrollTop\s*=\s*(\d+)", script)
                if m:
                    val = int(m.group(1))
                    scroll_ops.append(val)
                    events.append(("scroll_restore", val))
            if "removeItem" in script:
                events.append(("clear_localstorage",))
            return {}

        def execute_async_script(self, script, *args):
            if "selectBatch" in script:
                self._active_batch = args[0] if args else None
                events.append(("select_batch", args[0] if args else None))
                return {"ok": True}
            if "Benchmark DOM bridge" in script or "blobUrls" in script:
                return {"available": True, "count": 3, "bytes": 30000}
            if "expectedCount" in script and "timeoutMs" in script:
                expected = args[0] if args else 0
                events.append(("viewport_settle", expected))
                if viewport == "unavailable":
                    return {"available": False, "reason": "Grid scroll container not found"}
                if viewport == "timeout":
                    return {
                        "available": True,
                        "ready": False,
                        "elapsedMs": 5000.0,
                        "intervals": [16, 17],
                        "state": {
                            "count": expected,
                            "loaded": 5,
                            "visibleCount": 20,
                            "visibleLoaded": 5,
                        },
                    }
                return {
                    "available": True,
                    "ready": True,
                    "elapsedMs": 350.0,
                    "intervals": [16, 17, 18, 20, 16],
                    "state": {
                        "count": expected,
                        "loaded": 15,
                        "visibleCount": min(20, expected),
                        "visibleLoaded": min(20, expected),
                    },
                }
            if "viewportSettled" in script and "visitedRegions" in script:
                positions = list(args[0]) if args and isinstance(args[0], list) else []
                positions_passed.append(list(positions))
                events.append(("traversal", len(positions)))
                n = len(positions)
                if traversal == "unavailable":
                    return {"available": False, "reason": "Grid scroll container not found"}
                capped = traversal == "frame_cap"
                unsettled = traversal == "unsettled"
                count = max(0, n - 1) if capped else n
                regions = [
                    {
                        "region": i,
                        "scrollPosition": positions[i] if i < len(positions) else 0,
                        "visibleCount": 10,
                        "visibleLoaded": 10,
                        "settled": not (unsettled and i == n - 1),
                        "regionElapsedMs": 50,
                    }
                    for i in range(count)
                ]
                return {
                    "available": True,
                    "elapsedMs": 150 if capped else 800,
                    "mode": "traversal",
                    "intervals": [16, 17] if capped else [16, 17, 18],
                    "frameCapReached": capped,
                    "regionsVisited": count,
                    "totalPositions": n,
                    "visitedRegions": regions,
                }
            if "content.scrollTop" in script and "requestAnimationFrame" in script:
                return {
                    "available": True,
                    "elapsedMs": 200,
                    "intervals": [],
                    "frameCapReached": False,
                }
            if "applySidebarWidth" in script:
                return {"available": True, "elapsedMs": 100, "intervals": [], "restored": True}
            return {"available": True, "elapsedMs": 100, "intervals": []}

        def quit(self):
            quit_flag[0] = True

    _MemInfo = type("_MemInfo", (), {"rss": 50_000_000})
    _FakeProc = type(
        "_FakeProc",
        (),
        {
            "children": staticmethod(lambda recursive=False: []),
            "name": staticmethod(lambda: "firefox"),
            "memory_info": staticmethod(lambda: _MemInfo()),
        },
    )
    _FakePsutil = type("_FakePsutil", (), {"Process": staticmethod(lambda pid: _FakeProc())})
    deps = type("_FakeDeps", (), {"psutil": _FakePsutil()})()

    hooks = {
        "events": events,
        "scroll_ops": scroll_ops,
        "client_height": client_height_val,
        "positions_passed": positions_passed,
        "instrument_args": instrument_args,
        "quit_flag": quit_flag,
        "resource_log": resource_log,
    }
    return FakeDriver(), deps, hooks


class TestSelectAndTraverse:
    def test_success_returns_readiness_fields(self):
        benchmark = load_benchmark_module()
        spec = benchmark.build_fixture_specs("run-t", [50], ["firefox"])[0]
        driver, deps, hooks = _shared_benchmark_driver(benchmark, spec)
        readiness = benchmark._select_and_traverse(driver, "p", 50, timeout=30.0)
        assert readiness["ready"] is True
        assert readiness["elapsed_ms"] > 0
        assert readiness["first_viewport_ms"] == pytest.approx(350.0, rel=0.01)
        assert readiness["available"] is True
        assert readiness["reason"] is None
        assert readiness["warnings"] == []
        assert readiness["state"]["loaded"] == 42

    @pytest.mark.parametrize(
        "vp,tr,expect_ready,expect_avail,expect_warnings",
        [
            ("ready", "success", True, True, []),
            ("timeout", "success", False, True, ["Viewport did not settle"]),
            ("unavailable", "success", False, False, ["Viewport settle unavailable"]),
            ("ready", "unsettled", False, True, ["unsettled"]),
            ("ready", "frame_cap", False, True, ["frame-capped"]),
            ("ready", "unavailable", False, False, ["traversal unavailable"]),
        ],
    )
    def test_edge_cases(self, vp, tr, expect_ready, expect_avail, expect_warnings):
        benchmark = load_benchmark_module()
        spec = benchmark.build_fixture_specs("run-e", [50], ["firefox"])[0]
        driver, deps, hooks = _shared_benchmark_driver(
            benchmark,
            spec,
            viewport=vp,
            traversal=tr,
        )
        r = benchmark._select_and_traverse(driver, "t", 50, timeout=30.0)
        assert r["ready"] is expect_ready
        assert r["available"] is expect_avail
        if expect_ready and expect_avail:
            assert r["reason"] is None
        else:
            assert r["reason"] is not None
        for word in expect_warnings:
            assert any(word in w for w in r["warnings"]), f"missing '{word}' in {r['warnings']}"

    def test_full_traversal_positions_and_scroll_restore(self):
        benchmark = load_benchmark_module()
        spec = benchmark.build_fixture_specs("run-p", [50], ["firefox"])[0]
        driver, deps, hooks = _shared_benchmark_driver(
            benchmark,
            spec,
            grid_scroll=(2000, 700),
        )
        benchmark._select_and_traverse(driver, "t", 50, timeout=30.0)
        # Scroll restored to top
        assert hooks["scroll_ops"][-1] == 0
        # Positions captured: gap-free, start=0, exact bottom
        assert len(hooks["positions_passed"]) == 1
        positions = hooks["positions_passed"][0]
        region_h = max(300, round(700 * 0.6))
        assert positions[0] == 0
        assert positions[-1] == 2000
        for i in range(1, len(positions)):
            assert positions[i] - positions[i - 1] <= region_h


def test_cold_companion_event_order(monkeypatch, tmp_path):
    """session_switch < navigate < companion select < viewport settle
    < companion traversal < scroll restore < instrumentation
    < primary select < primary viewport settle; companion traversal first."""
    benchmark = load_benchmark_module()
    spec = benchmark.build_fixture_specs("run-cc", [50], ["firefox"])[0]
    root = Path(tmp_path)
    (root / spec.primary_batch / ".thumbs").mkdir(parents=True)
    (root / spec.companion_batch / ".thumbs").mkdir(parents=True)
    driver, deps, hooks = _shared_benchmark_driver(benchmark, spec)

    def _patch_install(_driver, count):
        hooks["events"].append(("instrument", count))

    benchmark._install_instrumentation = _patch_install

    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=root,
        active_batch=None,
    )

    class FakeSession:
        def switch(self, batch):
            hooks["events"].append(("session_switch", batch))

    benchmark._prepare_checkpoint_cold_phase(driver, deps, FakeSession(), runtime, spec, timeout=30)
    ev = hooks["events"]

    s_switch = next(
        i for i, e in enumerate(ev) if e[0] == "session_switch" and e[1] == spec.companion_batch
    )
    nav = next(i for i, e in enumerate(ev) if e[0] == "navigate")
    c_sel = next(
        i for i, e in enumerate(ev) if e[0] == "select_batch" and e[1] == spec.companion_batch
    )
    c_vp = next(
        i for i, e in enumerate(ev) if e[0] == "viewport_settle" and e[1] == spec.companion_size
    )
    c_trv = next(i for i, e in enumerate(ev) if e[0] == "traversal")
    c_sr = next(i for i, e in enumerate(ev) if e[0] == "scroll_restore")
    ins = next(i for i, e in enumerate(ev) if e[0] == "instrument")
    p_sel = next(
        i for i, e in enumerate(ev) if e[0] == "select_batch" and e[1] == spec.primary_batch
    )
    p_vp = next(i for i, e in enumerate(ev) if e[0] == "viewport_settle" and e[1] == spec.size)

    assert s_switch < nav < c_sel < c_vp < c_trv < c_sr < ins < p_sel < p_vp, (
        f"order violation: s_switch={s_switch} nav={nav} c_sel={c_sel} c_vp={c_vp} "
        f"c_trv={c_trv} c_sr={c_sr} ins={ins} p_sel={p_sel} p_vp={p_vp}"
    )

    trv_events = [(i, e) for i, e in enumerate(ev) if e[0] == "traversal"]
    assert trv_events[0][0] == c_trv, "first traversal must be companion"
    pre_instr_primary = [
        i for i, e in enumerate(ev[:ins]) if e[0] == "select_batch" and e[1] == spec.primary_batch
    ]
    assert not pre_instr_primary, (
        "no all-terminal wait: primary select_batch before instrumentation"
    )


def test_benchmark_case_cold_companion_warnings_propagated(monkeypatch, tmp_path):
    """Cold phase warnings: generic + unique detailed each appear exactly once."""
    benchmark = load_benchmark_module()
    driver, deps, hooks, spec, runtime, session, args = _setup_benchmark_case(
        monkeypatch, tmp_path, benchmark
    )
    uw = "unique-companion-detailed-warning-cold-x9z2"

    def fake_cold_phase(drv, deps, session, runtime, spec, timeout):
        cr = {
            "ready": False,
            "elapsed_ms": 500.0,
            "first_viewport_ms": None,
            "state": {"loaded": 0, "count": spec.companion_size},
            "available": True,
            "reason": "companion not ready",
            "warnings": [uw],
        }
        fr = {
            "ready": True,
            "elapsed_ms": 300.0,
            "first_viewport_ms": 200.0,
            "state": {"count": spec.size, "loaded": spec.size},
        }
        return [{"name": "cp"}] * 3, cr, fr, []

    monkeypatch.setattr(benchmark, "_prepare_checkpoint_cold_phase", fake_cold_phase)
    result = benchmark.benchmark_case(deps, args, runtime, spec, tmp_path / "profile", session)
    cw = next(p for p in result["phases"] if p["phase"] == "cold_initial_load")["warnings"]
    gm = "Initial companion batch did not become ready before cold measurement"
    assert gm in " ".join(cw) and uw in cw
    assert sum(1 for w in cw if gm in w) == 1
    assert sum(1 for w in cw if uw in w) == 1


def _setup_benchmark_case(monkeypatch, tmp_path, benchmark, **driver_kw):
    spec = benchmark.build_fixture_specs("run-bc", [50], ["firefox"])[0]
    root = Path(tmp_path)
    (root / spec.primary_batch / ".thumbs").mkdir(parents=True)
    (root / spec.companion_batch / ".thumbs").mkdir(parents=True)

    driver, deps, hooks = _shared_benchmark_driver(
        benchmark,
        spec,
        **driver_kw,
    )

    def _patch_install(_driver, count):
        hooks["instrument_args"].append(count)
        hooks["events"].append(("instrument", count))
        hooks["resource_log"].append([])

    benchmark._install_instrumentation = _patch_install
    monkeypatch.setattr(
        benchmark,
        "_browser_process_memory",
        lambda *a: benchmark.available({"rss_bytes": 1000000, "process_count": 1}, "psutil"),
    )
    monkeypatch.setattr(benchmark, "create_driver", lambda *a, **kw: driver)
    monkeypatch.setattr(benchmark, "set_active_batch", lambda rt, b: None)

    def fake_select_and_traverse(drv, batch, count, timeout):
        hooks["events"].append(("select", batch, count))
        if hooks["resource_log"]:
            hooks["resource_log"][-1].extend(
                {
                    "name": f"http://localhost/curator/thumb/b/inbox/{i}.png",
                    "duration": 8.0,
                    "transferSize": 0,
                    "encodedBodySize": 2048,
                }
                for i in range(count)
            )
        return {
            "ready": True,
            "elapsed_ms": 500.0,
            "first_viewport_ms": 200.0,
            "state": {"loaded": count, "count": count},
            "available": True,
            "reason": None,
            "warnings": [],
        }

    monkeypatch.setattr(benchmark, "_select_and_traverse", fake_select_and_traverse)

    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=root,
        active_batch=None,
    )
    session = benchmark.ActiveBatchSession(runtime)
    args = type(
        "_FakeArgs", (), {"timeout": 30, "headless": True, "firefox_binary": Path("fake")}
    )()
    return driver, deps, hooks, spec, runtime, session, args


def test_warm_reload_and_aba_use_select_and_traverse(monkeypatch, tmp_path):
    """Warm/ABA select+instrument order: cold companion, warm primary,
    combined A-B-A instrument, ABA companion, ABA primary; no instrument
    between B/A pair; primary readiness first_viewport_ms==200, elapsed<500."""
    benchmark = load_benchmark_module()
    driver, deps, hooks, spec, runtime, session, args = _setup_benchmark_case(
        monkeypatch, tmp_path, benchmark
    )
    result = benchmark.benchmark_case(deps, args, runtime, spec, tmp_path / "profile", session)
    cs, s, pb, cb = spec.companion_size, spec.size, spec.primary_batch, spec.companion_batch
    assert [e for e in hooks["events"] if e[0] == "select"] == [
        ("select", cb, cs),
        ("select", pb, s),
        ("select", cb, cs),
        ("select", pb, s),
    ]
    all_ev = [e for e in hooks["events"] if e[0] in ("select", "instrument")]
    cii = next(i for i, e in enumerate(all_ev) if e == ("instrument", s + cs))
    assert all_ev[cii - 1] == ("select", pb, s)
    assert all_ev[cii + 1] == ("select", cb, cs)
    assert all_ev[cii + 2] == ("select", pb, s)
    assert sum(1 for e in hooks["instrument_args"] if e == s + cs) == 1
    gr = [p for p in result["phases"] if p["phase"] == "batch_a_b_a_switch"][0][
        "cross_browser_metrics"
    ]["grid_readiness"]
    assert gr["available"] and gr["value"]["ready"]
    assert gr["value"]["elapsed_ms"] < 500
    assert gr["value"]["first_viewport_ms"] == pytest.approx(200.0, rel=0.05)


def test_aba_companion_warnings_propagated(monkeypatch, tmp_path):
    """Companion traversal warnings reach A-B-A phase warnings, deduplicated."""
    benchmark = load_benchmark_module()
    driver, deps, hooks, spec, runtime, session, args = _setup_benchmark_case(
        monkeypatch,
        tmp_path,
        benchmark,
    )
    companion_warning_text = "companion traversal frame-capped"
    call_seq = [0]

    def warning_traverse(drv, batch, count, timeout):
        call_seq[0] += 1
        # A-B-A companion call (3rd overall: cold companion, warm reload, then this)
        if call_seq[0] == 3 and batch == spec.companion_batch:
            return {
                "ready": False,
                "elapsed_ms": 500,
                "first_viewport_ms": 200,
                "state": {"loaded": 2, "count": count},
                "available": True,
                "reason": "companion traversal incomplete",
                "warnings": [companion_warning_text],
            }
        return {
            "ready": True,
            "elapsed_ms": 500,
            "first_viewport_ms": 200,
            "state": {"loaded": count, "count": count},
            "available": True,
            "reason": None,
            "warnings": [],
        }

    monkeypatch.setattr(benchmark, "_select_and_traverse", warning_traverse)
    result = benchmark.benchmark_case(deps, args, runtime, spec, tmp_path / "profile", session)
    aba = [p for p in result["phases"] if p["phase"] == "batch_a_b_a_switch"]
    assert len(aba) == 1
    aba_warnings = aba[0]["warnings"]
    assert companion_warning_text in " ".join(aba_warnings)
    assert any("did not become ready" in w for w in aba_warnings)


def test_aba_resource_entries_cumulative(monkeypatch, tmp_path):
    """A-B-A phase request_count == companion_size + primary_size after one
    instrumentation boundary before both traversals."""
    benchmark = load_benchmark_module()
    driver, deps, hooks, spec, runtime, session, args = _setup_benchmark_case(
        monkeypatch,
        tmp_path,
        benchmark,
    )

    result = benchmark.benchmark_case(deps, args, runtime, spec, tmp_path / "profile", session)
    aba = [p for p in result["phases"] if p["phase"] == "batch_a_b_a_switch"]
    assert len(aba) == 1
    req_count = aba[0]["cross_browser_metrics"]["thumbnail_resources"]["request_count"]
    assert req_count == spec.companion_size + spec.size, (
        f"expected {spec.companion_size + spec.size}, got {req_count}"
    )
    # One combined instrumentation boundary before A-B-A traversals
    aba_sizes = [c for c in hooks["instrument_args"] if c == spec.size + spec.companion_size]
    assert len(aba_sizes) == 1, f"expected 1 A-B-A instrumentation, got {aba_sizes}"


def test_phase_metrics_propagates_readiness_warnings():
    """_phase_metrics extends phase warnings with readiness.warnings."""
    benchmark = load_benchmark_module()
    spec = benchmark.build_fixture_specs("run-pm", [50], ["firefox"])[0]
    driver, deps, hooks = _shared_benchmark_driver(benchmark, spec)

    readiness = {
        "ready": True,
        "elapsed_ms": 500,
        "first_viewport_ms": 200,
        "state": {"loaded": 50, "count": 50},
        "warnings": ["traversal had 1 unsettled region"],
    }
    runtime = benchmark.RuntimeContext(
        origin="http://127.0.0.1:8188",
        page_url="http://127.0.0.1:8188/curator",
        paths=benchmark.runtime_paths("native"),
        batch_root=Path("."),
        active_batch=None,
    )
    metrics, warnings = benchmark._phase_metrics(
        driver,
        deps,
        runtime,
        "firefox",
        "test-batch",
        readiness=readiness,
    )
    assert any("unsettled region" in w for w in warnings)
    gr = metrics["grid_readiness"]
    assert "viewport" in gr.get("methodology", "").lower() or (
        "traversal" in gr.get("methodology", "").lower()
    )


def test_driver_quit_called_on_phase_failure(monkeypatch, tmp_path):
    """When a phase raises BenchmarkError, driver.quit must still be called."""
    benchmark = load_benchmark_module()
    driver, deps, hooks, spec, runtime, session, args = _setup_benchmark_case(
        monkeypatch,
        tmp_path,
        benchmark,
    )
    call_seq = [0]

    def failing_traverse(drv, batch, count, timeout):
        call_seq[0] += 1
        if call_seq[0] >= 2 and batch == spec.primary_batch:
            raise benchmark.BenchmarkError("simulated warm reload failure")
        return {
            "ready": True,
            "elapsed_ms": 500,
            "first_viewport_ms": 200,
            "state": {"loaded": count, "count": count},
            "available": True,
            "reason": None,
            "warnings": [],
        }

    monkeypatch.setattr(benchmark, "_select_and_traverse", failing_traverse)

    with pytest.raises(benchmark.BenchmarkError, match="simulated warm reload failure"):
        benchmark.benchmark_case(deps, args, runtime, spec, tmp_path / "profile", session)

    assert hooks["quit_flag"][0] is True
