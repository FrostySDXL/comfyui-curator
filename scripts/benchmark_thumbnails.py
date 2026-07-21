"""Run repeatable Firefox-first thumbnail and cache benchmarks.

This is an optional operator harness. It injects measurement code at runtime and
does not alter Curator's production thumbnail loading behavior.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import shutil
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, PngImagePlugin


HARNESS_VERSION = "1.0"
REPORT_SCHEMA = "comfyui-curator.thumbnail-benchmark-report.v1"
MANIFEST_SCHEMA = "comfyui-curator.thumbnail-benchmark-manifest.v1"
MARKER_SCHEMA = "comfyui-curator.thumbnail-benchmark-owner.v1"
OWNERSHIP_MARKER = ".curator-thumbnail-benchmark-owner.json"
BATCH_FOLDERS = ("inbox", "shortlisted", "finals", "rejects")
DEFAULT_OUTPUT_ROOT = Path("tmp") / "thumbnail-benchmarks"
DEFAULT_FIREFOX_BINARY = Path(r"C:\Program Files\Mozilla Firefox\firefox.exe")
DEFAULT_CHROME_BINARY = Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
DEFAULT_URL = "http://127.0.0.1:8188/curator"
DEFAULT_TIMEOUT = 45.0
BRIDGE_ID = "curator-thumbnail-benchmark-bridge-v1"
BLOB_METHODOLOGY = (
    "Exact Blob.size sum published through the benchmark DOM bridge for page-realm Blob URLs "
    "created after instrumentation; revoked URLs and companion pre-instrumentation blobs are excluded"
)
SENSITIVE_REPORT_KEYS = {
    "profile",
    "profile_path",
    "profile_dir",
    "settings",
    "settings_payload",
    "driver_path",
    "firefox_driver",
    "chrome_driver",
    "api_key",
    "credentials",
}


class BenchmarkError(RuntimeError):
    """Actionable harness failure."""


class CleanupRefused(BenchmarkError):
    """Raised when ownership cannot be proven before deletion."""


@dataclass(frozen=True)
class RuntimePaths:
    settings: str | None
    batches: str
    active_batch: str
    thumbnail_prefix: str


@dataclass(frozen=True)
class RuntimeContext:
    origin: str
    page_url: str
    paths: RuntimePaths
    batch_root: Path
    active_batch: str | None


@dataclass(frozen=True)
class FixtureSpec:
    run_id: str
    browser: str
    size: int
    primary_batch: str
    companion_batch: str
    companion_size: int

    @property
    def batches(self) -> tuple[str, str]:
        return self.primary_batch, self.companion_batch


@dataclass(frozen=True)
class OptionalDependencies:
    webdriver: Any
    firefox_options: Any
    firefox_service: Any
    chrome_options: Any
    chrome_service: Any
    psutil: Any


def runtime_paths(mode: str) -> RuntimePaths:
    if mode == "native":
        return RuntimePaths(
            settings="/api/curator/settings",
            batches="/api/curator/batches",
            active_batch="/api/curator/active-batch",
            thumbnail_prefix="/curator/thumb/",
        )
    if mode == "standalone":
        return RuntimePaths(
            settings=None,
            batches="/api/batches",
            active_batch="/api/active-batch",
            thumbnail_prefix="/thumb/",
        )
    raise BenchmarkError(f"Unsupported runtime mode: {mode}")


def _resolved_descendant(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise BenchmarkError(f"Path must be under --output-root: {resolved_path}") from exc
    if resolved_path == resolved_root:
        raise BenchmarkError("Batch root must be a child directory under --output-root")
    return resolved_path


def validate_standalone_root(batch_root: Path | None, output_root: Path) -> Path:
    if batch_root is None:
        raise BenchmarkError("Standalone mode requires an explicit --batch-root")
    try:
        return _resolved_descendant(Path(batch_root), Path(output_root))
    except BenchmarkError as exc:
        raise BenchmarkError(
            "Standalone --batch-root must be under --output-root so it is explicitly temporary "
            "and benchmark-owned"
        ) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=("firefox", "chrome", "all"), default="firefox")
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 500, 2000])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--mode", choices=("native", "standalone"), default="native")
    parser.add_argument("--batch-root", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--keep-fixtures", action="store_true")
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Recover benchmark batches listed by manifests and proven by ownership markers",
    )
    parser.add_argument("--firefox-binary", type=Path, default=DEFAULT_FIREFOX_BINARY)
    parser.add_argument("--chrome-binary", type=Path, default=DEFAULT_CHROME_BINARY)
    parser.add_argument("--firefox-driver", type=Path)
    parser.add_argument("--chrome-driver", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    if any(size <= 0 for size in args.sizes):
        parser.error("--sizes values must be positive integers")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def build_fixture_specs(run_id: str, sizes: list[int], browsers: list[str]) -> list[FixtureSpec]:
    safe_run = "".join(character for character in run_id.lower() if character.isalnum())[-12:]
    specs = []
    for browser in browsers:
        for size in sizes:
            prefix = f"thumb-bench-{safe_run}-{browser}-{size}"
            specs.append(
                FixtureSpec(
                    run_id=run_id,
                    browser=browser,
                    size=size,
                    primary_batch=f"{prefix}-a",
                    companion_batch=f"{prefix}-b",
                    companion_size=max(3, min(25, math.ceil(size / 20))),
                )
            )
    return specs


def _marker_payload(run_id: str, batch: str) -> dict[str, str]:
    return {"schema": MARKER_SCHEMA, "run_id": run_id, "batch": batch}


def _write_marker(batch_dir: Path, run_id: str, batch: str) -> None:
    (batch_dir / OWNERSHIP_MARKER).write_text(
        json.dumps(_marker_payload(run_id, batch), indent=2), encoding="utf-8"
    )


def _write_seed_png(path: Path, index: int) -> None:
    colors = ((44, 88, 150), (136, 66, 108), (55, 125, 89))
    color = colors[index % len(colors)]
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text(
        "parameters", f"deterministic benchmark fixture {index}, Seed: {7000 + index}"
    )
    image = Image.new("RGB", (384, 256), color=color)
    draw = ImageDraw.Draw(image)
    for stripe in range(0, 384, 32):
        shade = tuple(min(255, channel + ((stripe // 32) % 4) * 8) for channel in color)
        draw.rectangle((stripe, 0, stripe + 15, 256), fill=shade)
    draw.rectangle((20, 176, 364, 236), fill=(16, 18, 24))
    draw.text((32, 194), f"Thumbnail benchmark seed {index + 1}", fill=(238, 241, 246))
    image.save(path, pnginfo=metadata, optimize=False)


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _create_one_fixture_batch(
    batch_root: Path, seed_paths: list[Path], run_id: str, batch: str, image_count: int
) -> None:
    batch_dir = batch_root / batch
    if batch_dir.exists():
        raise BenchmarkError(f"Refusing to reuse existing benchmark batch: {batch}")
    batch_dir.mkdir(parents=False)
    _write_marker(batch_dir, run_id, batch)
    for folder in BATCH_FOLDERS:
        (batch_dir / folder).mkdir()
    for index in range(image_count):
        destination = batch_dir / "inbox" / f"benchmark-{index:06d}.png"
        _link_or_copy(seed_paths[index % len(seed_paths)], destination)


def create_fixture_batches(batch_root: Path, seed_dir: Path, specs: list[FixtureSpec]) -> None:
    batch_root.mkdir(parents=True, exist_ok=True)
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_paths = [seed_dir / f"seed-{index + 1}.png" for index in range(3)]
    for index, seed_path in enumerate(seed_paths):
        if not seed_path.exists():
            _write_seed_png(seed_path, index)
    for spec in specs:
        _create_one_fixture_batch(
            batch_root, seed_paths, spec.run_id, spec.primary_batch, spec.size
        )
        _create_one_fixture_batch(
            batch_root,
            seed_paths,
            spec.run_id,
            spec.companion_batch,
            spec.companion_size,
        )


def _validate_direct_batch_child(batch_root: Path, batch_path: Path, batch: str) -> Path:
    if batch_path.is_symlink():
        raise CleanupRefused(f"Refusing symlinked benchmark batch: {batch}")
    resolved_root = batch_root.resolve()
    resolved_batch = batch_path.resolve()
    if resolved_batch.parent != resolved_root or resolved_batch.name != batch:
        raise CleanupRefused(f"Refusing path outside resolved benchmark batch root: {batch}")
    return resolved_batch


def remove_owned_batch(batch_root: Path, batch_path: Path, run_id: str, batch: str) -> None:
    resolved_batch = _validate_direct_batch_child(batch_root, batch_path, batch)
    marker_path = resolved_batch / OWNERSHIP_MARKER
    if marker_path.is_symlink() or not marker_path.is_file():
        raise CleanupRefused(f"Refusing {batch}: ownership marker is missing or unsafe")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanupRefused(f"Refusing {batch}: ownership marker is unreadable") from exc
    if marker != _marker_payload(run_id, batch):
        raise CleanupRefused(f"Refusing {batch}: ownership marker does not match manifest")
    shutil.rmtree(resolved_batch)


def summarize_thumbnail_resources(
    entries: list[dict[str, Any]], thumbnail_prefix: str
) -> dict[str, Any]:
    thumbnail_entries = [
        entry for entry in entries if thumbnail_prefix in str(entry.get("name", ""))
    ]
    encoded_values = [entry.get("encodedBodySize") for entry in thumbnail_entries]
    transfer_values = [entry.get("transferSize") for entry in thumbnail_entries]
    byte_sizes_available = all(
        isinstance(value, (int, float)) for value in encoded_values + transfer_values
    )
    heuristic: dict[str, Any] = {
        "available": byte_sizes_available,
        "value": None,
        "reason": None,
        "methodology": "transferSize == 0 and encodedBodySize > 0",
    }
    if byte_sizes_available:
        hits = sum(
            1
            for encoded, transfer in zip(encoded_values, transfer_values, strict=True)
            if transfer == 0 and encoded > 0
        )
        heuristic["value"] = {
            "candidate_hits": hits,
            "candidate_misses": len(thumbnail_entries) - hits,
            "ratio": round(hits / len(thumbnail_entries), 4) if thumbnail_entries else None,
        }
    else:
        heuristic["reason"] = (
            "Resource Timing byte sizes were unavailable for one or more thumbnails"
        )
    return {
        "request_count": len(thumbnail_entries),
        "duration_ms": round(
            sum(float(entry.get("duration") or 0) for entry in thumbnail_entries), 3
        ),
        "encoded_body_bytes": int(sum(encoded_values)) if byte_sizes_available else None,
        "transfer_bytes": int(sum(transfer_values)) if byte_sizes_available else None,
        "cache_hit_heuristic": heuristic,
        "methodology": "Resource Timing entries whose URL contains the runtime thumbnail prefix",
    }


def unavailable(reason: str, methodology: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "value": None, "reason": reason}
    if methodology:
        result["methodology"] = methodology
    return result


def available(value: Any, methodology: str) -> dict[str, Any]:
    return {"available": True, "value": value, "reason": None, "methodology": methodology}


def sanitize_report(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_report(item)
            for key, item in value.items()
            if key.lower() not in SENSITIVE_REPORT_KEYS
        }
    if isinstance(value, list):
        return [sanitize_report(item) for item in value]
    return value


def sanitize_exception_message(exc: Exception) -> str:
    first_line = str(exc).splitlines()[0].strip() if str(exc) else "no message"
    first_line = re.sub(r"(https?://)(?:[^/@\s]+)@", r"\1<redacted>@", first_line)
    first_line = re.sub(r"(?i)\b[a-z]:[\\/].*$", "<path>", first_line)
    return first_line[:300]


def browser_stage_error(stage: str, exc: Exception) -> BenchmarkError:
    return BenchmarkError(
        f"Browser stage '{stage}' failed ({type(exc).__name__}): {sanitize_exception_message(exc)}"
    )


def _summary_metric(metric: Any) -> str:
    if isinstance(metric, dict) and "available" in metric:
        if not metric["available"]:
            return f"Unavailable: {metric.get('reason') or 'reason not supplied'}"
        return str(metric.get("value"))
    return str(metric)


def render_markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Thumbnail Benchmark Summary",
        "",
        f"- Schema: `{report['schema']}`",
        f"- Run: `{report['run_id']}`",
        f"- Mode: `{report['mode']}`",
        f"- Active batch: {report.get('active_batch_restore', {}).get('status', 'unknown')}",
        f"- Cleanup: {report.get('cleanup', {}).get('status', 'unknown')}",
        f"- Profiles: {report.get('profile_cleanup', {}).get('status', 'unknown')}",
        "",
        "| Browser | Size | Phase | Class | Requests | Grid ready | Long tasks | Status |",
        "|---|---:|---|---|---:|---|---|---|",
    ]
    for result in report.get("browser_results", []):
        if result.get("status") != "ok":
            lines.append(
                f"| {result.get('browser', 'unknown')} | {result.get('size', '-')} | - | - | - | - | - | Failed: {result.get('error', 'unknown')} |"
            )
            continue
        for phase in result.get("phases", []):
            metrics = phase.get("cross_browser_metrics", phase.get("metrics", {}))
            resources = metrics.get("thumbnail_resources", {})
            has_checkpoints = bool(phase.get("checkpoints"))
            lines.append(
                "| {browser} {version} | {size} | {phase} | {classification} | {requests} | "
                "{ready} | {long_tasks} | {status} |".format(
                    browser=result["browser"],
                    version=result.get("version", "unknown"),
                    size=result["size"],
                    phase=phase["phase"],
                    classification=phase["classification"],
                    requests=resources.get("request_count", "-"),
                    ready=_summary_metric(
                        metrics.get("grid_readiness", unavailable("not measured"))
                    ),
                    long_tasks=_summary_metric(
                        metrics.get("long_tasks", unavailable("not measured"))
                    ),
                    status="ok (with checkpoints)" if has_checkpoints else "ok",
                )
            )
    # Render checkpoint detail sections
    checkpoint_data: list[dict[str, Any]] = []
    for result in report.get("browser_results", []):
        if result.get("status") != "ok":
            continue
        for phase in result.get("phases", []):
            for cp in phase.get("checkpoints", []):
                checkpoint_data.append(
                    {
                        "browser": result["browser"],
                        "version": result.get("version", "unknown"),
                        "size": result["size"],
                        **cp,
                    }
                )
    if checkpoint_data:
        lines.extend(["", "## Checkpoints", ""])
        lines.append("| Browser | Size | Checkpoint | Loaded | Requests | Blobs | DOM |")
        lines.append("|---|---|---|---:|---:|---:|---:|")
        for cp in checkpoint_data:
            lines.append(
                "| {browser} {version} | {size} | {name} | {loaded} | {requests} | {blobs} | {dom} |".format(
                    browser=cp["browser"],
                    version=cp["version"],
                    size=cp["size"],
                    name=cp.get("name", "-"),
                    loaded=cp.get("loaded_image_count", "-"),
                    requests=cp.get("thumbnail_request_count", "-"),
                    blobs=cp.get("blob_live_count", "-"),
                    dom=cp.get("dom_node_count", "-"),
                )
            )
    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(
        [
            "",
            "## Method Notes",
            "",
            "- Cache hits are a Resource Timing heuristic, not a browser cache guarantee.",
            "- Blob bytes come from page-realm create/revoke events published through a JSON DOM bridge.",
            "- Process memory is browser-process RSS/working set measured through psutil.",
            "- Unsupported metrics remain unavailable with a reason in the JSON report.",
        ]
    )
    return "\n".join(lines) + "\n"


def report_safe_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BenchmarkError("--url must be an absolute HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise BenchmarkError("--url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise BenchmarkError("--url must not contain query data or a fragment")
    return url


def _origin(url: str) -> str:
    parsed = urlsplit(report_safe_url(url))
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_json(
    origin: str, path: str, *, method: str = "GET", body: dict[str, Any] | None = None
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = Request(origin + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise BenchmarkError(f"Runtime request {path} failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise BenchmarkError(
            f"Runtime unavailable at {origin}; start Curator and verify --url/--mode"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"Runtime request {path} returned unusable data") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError(f"Runtime request {path} did not return a JSON object")
    return payload


def resolve_runtime(args: argparse.Namespace) -> RuntimeContext:
    paths = runtime_paths(args.mode)
    origin = _origin(args.url)
    batches_payload = _request_json(origin, paths.batches)
    if not isinstance(batches_payload.get("batches"), list):
        raise BenchmarkError("Runtime batches endpoint did not return a batches list")
    active_batch = batches_payload.get("active_batch")
    if active_batch is not None and not isinstance(active_batch, str):
        raise BenchmarkError("Runtime batches endpoint returned an invalid active batch")
    if args.mode == "native":
        assert paths.settings is not None
        settings_payload = _request_json(origin, paths.settings)
        batch_root_value = settings_payload.get("batch_root")
        if not isinstance(batch_root_value, str) or not batch_root_value:
            raise BenchmarkError("Native settings endpoint did not provide a usable batch root")
        batch_root = Path(batch_root_value).resolve()
    else:
        batch_root = validate_standalone_root(args.batch_root, args.output_root)
    if not batch_root.is_dir():
        raise BenchmarkError(f"Resolved benchmark batch root does not exist: {batch_root}")
    return RuntimeContext(origin, args.url, paths, batch_root, active_batch)


def set_active_batch(runtime: RuntimeContext, batch: str | None) -> None:
    _request_json(
        runtime.origin,
        runtime.paths.active_batch,
        method="POST",
        body={"batch": batch if batch is not None else ""},
    )


class ActiveBatchSession:
    """Arm restoration before each switch because response loss can follow mutation."""

    def __init__(self, runtime: RuntimeContext) -> None:
        self.runtime = runtime
        self._switch_attempted = False
        self._restored = False

    def switch(self, batch: str) -> None:
        self._switch_attempted = True
        set_active_batch(self.runtime, batch)

    @property
    def switch_attempted(self) -> bool:
        return self._switch_attempted

    def restore(self) -> None:
        if not self._switch_attempted or self._restored:
            return
        set_active_batch(self.runtime, self.runtime.active_batch)
        self._restored = True


def load_optional_dependencies() -> OptionalDependencies:
    try:
        webdriver = importlib.import_module("selenium.webdriver")
        firefox_options = importlib.import_module("selenium.webdriver.firefox.options").Options
        firefox_service = importlib.import_module("selenium.webdriver.firefox.service").Service
        chrome_options = importlib.import_module("selenium.webdriver.chrome.options").Options
        chrome_service = importlib.import_module("selenium.webdriver.chrome.service").Service
    except ImportError as exc:
        raise BenchmarkError(
            "Selenium is unavailable. Install optional dependencies with "
            "`.venv\\Scripts\\python.exe -m pip install -e .[benchmark]`"
        ) from exc
    try:
        psutil = importlib.import_module("psutil")
    except ImportError as exc:
        raise BenchmarkError(
            "psutil is unavailable. Install optional dependencies with "
            "`.venv\\Scripts\\python.exe -m pip install -e .[benchmark]`"
        ) from exc
    return OptionalDependencies(
        webdriver,
        firefox_options,
        firefox_service,
        chrome_options,
        chrome_service,
        psutil,
    )


def requested_browsers(browser: str) -> list[str]:
    return ["firefox", "chrome"] if browser == "all" else [browser]


def browser_availability(args: argparse.Namespace, browser: str) -> str | None:
    binary = args.firefox_binary if browser == "firefox" else args.chrome_binary
    driver = args.firefox_driver if browser == "firefox" else args.chrome_driver
    if not binary.is_file():
        return f"{browser.title()} binary not found at the configured path; use --{browser}-binary"
    if driver is not None and not driver.is_file():
        return f"Explicit {browser} driver not found; correct --{browser}-driver or omit it for Selenium Manager"
    return None


def create_driver(
    dependencies: OptionalDependencies,
    browser: str,
    args: argparse.Namespace,
    profile_dir: Path,
) -> Any:
    profile_dir.mkdir(parents=True, exist_ok=False)
    try:
        if browser == "firefox":
            options = dependencies.firefox_options()
            options.binary_location = str(args.firefox_binary)
            options.add_argument("-profile")
            options.add_argument(str(profile_dir))
            if args.headless:
                options.add_argument("-headless")
            service = dependencies.firefox_service(
                executable_path=str(args.firefox_driver) if args.firefox_driver else None
            )
            driver = dependencies.webdriver.Firefox(options=options, service=service)
        else:
            options = dependencies.chrome_options()
            options.binary_location = str(args.chrome_binary)
            options.add_argument(f"--user-data-dir={profile_dir}")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            if args.headless:
                options.add_argument("--headless=new")
            service = dependencies.chrome_service(
                executable_path=str(args.chrome_driver) if args.chrome_driver else None
            )
            driver = dependencies.webdriver.Chrome(options=options, service=service)
    except Exception as exc:
        raise browser_stage_error("WebDriver startup", exc) from exc
    driver.set_page_load_timeout(args.timeout)
    driver.set_script_timeout(max(args.timeout, 60))
    driver.set_window_size(1440, 1000)
    return driver


INSTALL_INSTRUMENTATION = r"""
const expectedThumbnailCount = Number(arguments[0]) || 0;
if (typeof performance.setResourceTimingBufferSize === 'function') {
    performance.setResourceTimingBufferSize(Math.max(5000, expectedThumbnailCount * 3 + 1000));
}
performance.clearResourceTimings();

const bridgeId = 'curator-thumbnail-benchmark-bridge-v1';
let bridge = document.getElementById(bridgeId);
if (!bridge) {
    bridge = document.createElement('div');
    bridge.id = bridgeId;
    bridge.hidden = true;
    bridge.setAttribute('data-thumbnail-benchmark-bridge', 'v1');
    (document.body || document.documentElement).appendChild(bridge);
}
bridge.textContent = JSON.stringify({
    schema: 'comfyui-curator.thumbnail-benchmark-bridge.v1',
    available: false,
    reason: 'Main-realm instrumentation did not execute'
});

const installInPageRealm = function(expectedThumbnailCount, bridgeId) {
    const bridge = document.getElementById(bridgeId);
    if (!bridge) return;
    let state = window.__thumbnailBenchmark;
    if (!state || state.schema !== 'comfyui-curator.thumbnail-benchmark-state.v1') {
        state = {
            schema: 'comfyui-curator.thumbnail-benchmark-state.v1',
            longTasks: [],
            longTaskSupported: false,
            longTaskObserverInstalled: false,
            blobUrls: new Map(),
            objectUrlWrapperInstalled: false,
            phaseStart: performance.now()
        };
        window.__thumbnailBenchmark = state;
    }
    state.publishSnapshot = function() {
        const blobSizes = Array.from(state.blobUrls.values());
        bridge.textContent = JSON.stringify({
            schema: 'comfyui-curator.thumbnail-benchmark-bridge.v1',
            available: true,
            reason: null,
            longTaskSupported: state.longTaskSupported,
            longTasks: state.longTasks.slice(),
            phaseStart: state.phaseStart,
            blobCount: blobSizes.length,
            blobBytes: blobSizes.reduce((sum, size) => sum + size, 0)
        });
    };
    if (!state.longTaskObserverInstalled) {
        const supported = window.PerformanceObserver &&
            PerformanceObserver.supportedEntryTypes &&
            PerformanceObserver.supportedEntryTypes.includes('longtask');
        state.longTaskSupported = Boolean(supported);
        if (supported) {
            const observer = new PerformanceObserver(list => {
                for (const entry of list.getEntries()) {
                    if (entry.startTime >= state.phaseStart) {
                        state.longTasks.push({startTime: entry.startTime, duration: entry.duration});
                        state.publishSnapshot();
                    }
                }
            });
            observer.observe({type: 'longtask', buffered: true});
            state.longTaskObserver = observer;
        }
        state.longTaskObserverInstalled = true;
    }
    if (!state.objectUrlWrapperInstalled) {
        const originalCreateObjectURL = URL.createObjectURL;
        const originalRevokeObjectURL = URL.revokeObjectURL;
        URL.createObjectURL = function(object) {
            const blobUrl = Reflect.apply(originalCreateObjectURL, URL, [object]);
            if (object instanceof Blob) {
                state.blobUrls.set(blobUrl, object.size);
                state.publishSnapshot();
            }
            return blobUrl;
        };
        URL.revokeObjectURL = function(url) {
            const result = Reflect.apply(originalRevokeObjectURL, URL, [url]);
            state.blobUrls.delete(String(url));
            state.publishSnapshot();
            return result;
        };
        state.objectUrlWrapperInstalled = true;
    }
    state.longTasks = [];
    state.phaseStart = performance.now();
    if (typeof performance.setResourceTimingBufferSize === 'function') {
        performance.setResourceTimingBufferSize(Math.max(5000, expectedThumbnailCount * 3 + 1000));
    }
    performance.clearResourceTimings();
    state.publishSnapshot();
};

const script = document.createElement('script');
script.textContent = `(${installInPageRealm.toString()})(${JSON.stringify(expectedThumbnailCount)}, ${JSON.stringify(bridgeId)});`;
try {
    (document.head || document.documentElement).appendChild(script);
} catch (error) {
    bridge.textContent = JSON.stringify({
        schema: 'comfyui-curator.thumbnail-benchmark-bridge.v1',
        available: false,
        reason: 'Main-realm inline script injection failed'
    });
} finally {
    script.remove();
}
try {
    return JSON.parse(bridge.textContent);
} catch (error) {
    return {available: false, reason: 'Benchmark DOM bridge did not contain valid JSON'};
}
"""


SELECT_BATCH = r"""
const done = arguments[arguments.length - 1];
const batch = arguments[0];
try {
    if (typeof selectBatch !== 'function') throw new Error('selectBatch is unavailable');
    selectBatch(batch);
    done({ok: true});
} catch (error) {
    done({ok: false, error: String(error && error.message || error)});
}
"""


SCROLL_GRID = r"""
const done = arguments[arguments.length - 1];
const content = document.querySelector('.content');
if (!content) { done({available: false, reason: 'Grid scroll container not found'}); return; }
const original = content.scrollTop;
const intervals = [];
const started = performance.now();
let previous = started;
let frames = 0;
function step(now) {
    if (frames > 0) intervals.push(now - previous);
    previous = now;
    frames += 1;
    const bottom = Math.max(0, content.scrollHeight - content.clientHeight);
    if (content.scrollTop >= bottom || frames >= 2000) {
        content.scrollTop = original;
        done({available: true, elapsedMs: performance.now() - started, intervals, frameCapReached: frames >= 2000});
        return;
    }
    content.scrollTop = Math.min(bottom, content.scrollTop + Math.max(80, content.clientHeight * 0.65));
    requestAnimationFrame(step);
}
requestAnimationFrame(step);
"""


VIEWPORT_SETTLE_ASYNC = r"""
const done = arguments[arguments.length - 1];
const expectedCount = Number(arguments[0]) || 0;
const timeoutMs = Number(arguments[1]) || 30000;

const intervals = [];
const started = performance.now();
let previous = started;
const deadline = started + timeoutMs;

function readState() {
    var thumbs = Array.from(document.querySelectorAll('#grid .thumb:not(.loading-placeholder)'));
    var images = thumbs.map(function(t) { return t.querySelector('img'); }).filter(Boolean);
    var visible = images.filter(function(img) {
        var rect = img.getBoundingClientRect();
        return rect.bottom > 0 && rect.top < window.innerHeight;
    });
    return {
        count: thumbs.length,
        renderedCount: thumbs.length,
        expectedCount: expectedCount,
        loaded: images.filter(function(img) { return img.classList.contains('loaded'); }).length,
        visibleCount: visible.length,
        visibleLoaded: visible.filter(function(img) { return img.classList.contains('loaded'); }).length,
        currentBatch: typeof currentBatch === 'undefined' ? null : currentBatch
    };
}

function step(now) {
    var dt = now - previous;
    intervals.push(dt);
    previous = now;

    var state = readState();

    if (state.renderedCount > 0 && state.renderedCount <= state.expectedCount
        && state.visibleCount > 0 && state.visibleLoaded === state.visibleCount) {
        done({
            available: true,
            ready: true,
            elapsedMs: now - started,
            intervals: intervals,
            state: state
        });
        return;
    }
    if (now >= deadline) {
        done({
            available: true,
            ready: false,
            elapsedMs: now - started,
            intervals: intervals,
            state: state
        });
        return;
    }
    requestAnimationFrame(step);
}
requestAnimationFrame(step);
"""


SIDEBAR_WIDTH_PHASE = r"""
const done = arguments[arguments.length - 1];
if (typeof applySidebarWidth !== 'function' || typeof applyAiSidebarWidth !== 'function') {
    done({available: false, reason: 'Sidebar width functions unavailable'});
    return;
}
function readObservableWidths() {
    const styles = getComputedStyle(document.documentElement);
    const left = Number.parseFloat(styles.getPropertyValue('--sidebar-width'));
    const right = Number.parseFloat(styles.getPropertyValue('--ai-sidebar-width'));
    if (!Number.isFinite(left) || !Number.isFinite(right)) return null;
    return {left, right};
}
const originalWidths = readObservableWidths();
if (!originalWidths) {
    done({available: false, reason: 'Computed sidebar CSS widths are unavailable'});
    return;
}
const intervals = [];
const widths = [[240, 320], [360, 420], [500, 300], [280, 480]];
let index = 0;
let previous = performance.now();
const started = previous;
function step(now) {
    intervals.push(now - previous);
    previous = now;
    if (index < widths.length) {
        const pair = widths[index++];
        applySidebarWidth(pair[0], false);
        applyAiSidebarWidth(pair[1], false);
        requestAnimationFrame(step);
        return;
    }
    applySidebarWidth(originalWidths.left, false);
    applyAiSidebarWidth(originalWidths.right, false);
    requestAnimationFrame(() => {
        const restoredWidths = readObservableWidths();
        const restored = Boolean(restoredWidths) &&
            Math.abs(restoredWidths.left - originalWidths.left) < 0.01 &&
            Math.abs(restoredWidths.right - originalWidths.right) < 0.01;
        done({
            available: true,
            elapsedMs: performance.now() - started,
            intervals,
            restored,
            originalWidths,
            restoredWidths
        });
    });
}
requestAnimationFrame(step);
"""


RESOURCE_ENTRIES = r"""
return performance.getEntriesByType('resource').map(entry => ({
    name: entry.name,
    duration: entry.duration,
    transferSize: Number.isFinite(entry.transferSize) ? entry.transferSize : null,
    encodedBodySize: Number.isFinite(entry.encodedBodySize) ? entry.encodedBodySize : null,
    responseEnd: entry.responseEnd
}));
"""


PAGE_METRICS = r"""
function readBridgeSnapshot() {
    const bridge = document.getElementById('curator-thumbnail-benchmark-bridge-v1');
    if (!bridge) return {available: false, reason: 'Benchmark DOM bridge element is unavailable'};
    try {
        const snapshot = JSON.parse(bridge.textContent);
        if (!snapshot || snapshot.schema !== 'comfyui-curator.thumbnail-benchmark-bridge.v1') {
            return {available: false, reason: 'Benchmark DOM bridge schema is invalid'};
        }
        if (!snapshot.available) {
            return {available: false, reason: snapshot.reason || 'Main-realm instrumentation is unavailable'};
        }
        return {available: true, snapshot};
    } catch (error) {
        return {available: false, reason: 'Benchmark DOM bridge JSON is invalid'};
    }
}
const bridgeResult = readBridgeSnapshot();
const longTasks = bridgeResult.available && bridgeResult.snapshot.longTaskSupported
    ? {available: true, entries: bridgeResult.snapshot.longTasks || []}
    : {
        available: false,
        reason: bridgeResult.available
            ? 'Long Tasks API unavailable in this browser/context'
            : bridgeResult.reason
    };
return {
    domNodeCount: document.getElementsByTagName('*').length,
    blobCacheEntryCount: bridgeResult.available ? bridgeResult.snapshot.blobCount : null,
    blobObservation: bridgeResult.available
        ? {available: true, reason: null}
        : {available: false, reason: bridgeResult.reason},
    longTasks,
    navigation: performance.getEntriesByType('navigation')[0] ? {
        domContentLoadedMs: performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd,
        loadEventMs: performance.getEntriesByType('navigation')[0].loadEventEnd
    } : null
};
"""


BLOB_BYTES = r"""
const done = arguments[arguments.length - 1];
const bridge = document.getElementById('curator-thumbnail-benchmark-bridge-v1');
if (!bridge) {
    done({available: false, reason: 'Benchmark DOM bridge element is unavailable'});
    return;
}
try {
    const snapshot = JSON.parse(bridge.textContent);
    if (!snapshot || snapshot.schema !== 'comfyui-curator.thumbnail-benchmark-bridge.v1') {
        done({available: false, reason: 'Benchmark DOM bridge schema is invalid'});
    } else if (!snapshot.available) {
        done({available: false, reason: snapshot.reason || 'Main-realm instrumentation is unavailable'});
    } else if (!Number.isFinite(snapshot.blobCount) || !Number.isFinite(snapshot.blobBytes)) {
        done({available: false, reason: 'Benchmark DOM bridge blob measurements are invalid'});
    } else {
        done({available: true, count: snapshot.blobCount, bytes: snapshot.blobBytes});
    }
} catch (error) {
    done({available: false, reason: 'Benchmark DOM bridge JSON is invalid'});
}
"""


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def _install_instrumentation(driver: Any, expected_thumbnail_count: int) -> None:
    driver.execute_script(INSTALL_INSTRUMENTATION, expected_thumbnail_count)


def summarize_frames(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw.get("available"):
        return unavailable(str(raw.get("reason") or "Frame timing unavailable"))
    intervals = [float(value) for value in raw.get("intervals", []) if float(value) >= 0]
    value = {
        "elapsed_ms": round(float(raw.get("elapsedMs") or 0), 3),
        "frame_count": len(intervals),
        "mean_interval_ms": round(statistics.fmean(intervals), 3) if intervals else None,
        "p50_interval_ms": _percentile(intervals, 0.5),
        "p95_interval_ms": _percentile(intervals, 0.95),
        "max_interval_ms": round(max(intervals), 3) if intervals else None,
        "intervals_over_50ms": sum(value > 50 for value in intervals),
        "jank_ratio_over_50ms": round(sum(value > 50 for value in intervals) / len(intervals), 4)
        if intervals
        else None,
        "frame_cap_reached": bool(raw.get("frameCapReached", False)),
    }
    return available(value, "requestAnimationFrame intervals during the scripted operation")


def _wait_for_grid(driver: Any, expected_count: int, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    first_viewport_ms = None
    last_state: dict[str, Any] = {}
    while time.perf_counter() - started < timeout:
        state = driver.execute_script(
            """
const thumbs = Array.from(document.querySelectorAll('#grid .thumb:not(.loading-placeholder)'));
const images = thumbs.map(thumb => thumb.querySelector('img')).filter(Boolean);
const visible = images.filter(image => {
    const rect = image.getBoundingClientRect();
    return rect.bottom > 0 && rect.top < window.innerHeight;
});
return {
    count: thumbs.length,
    loaded: images.filter(image => image.classList.contains('loaded')).length,
    visibleCount: visible.length,
    visibleLoaded: visible.filter(image => image.classList.contains('loaded')).length,
    currentBatch: typeof currentBatch === 'undefined' ? null : currentBatch
};
"""
        )
        last_state = state
        if (
            first_viewport_ms is None
            and state["visibleCount"] > 0
            and state["visibleLoaded"] == state["visibleCount"]
        ):
            first_viewport_ms = (time.perf_counter() - started) * 1000
        if state["count"] == expected_count and state["loaded"] == expected_count:
            return {
                "ready": True,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "first_viewport_ms": round(first_viewport_ms, 3)
                if first_viewport_ms is not None
                else None,
                "state": state,
            }
        time.sleep(0.05)
    return {
        "ready": False,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "first_viewport_ms": round(first_viewport_ms, 3) if first_viewport_ms is not None else None,
        "state": last_state,
    }


def _build_checkpoint_record(
    name: str,
    elapsed_ms: float,
    loaded_image_count: int,
    thumbnail_request_count: int,
    blob_live_count: int | None,
    blob_bytes: int | None,
    dom_node_count: int,
    browser_process_memory: dict[str, Any],
    frame_timing: dict[str, Any],
    long_tasks: dict[str, Any],
    thumbnail_disk: dict[str, Any],
    readiness: dict[str, Any] | None = None,
    blob_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a measurement checkpoint record with all required metric slots.

    Every slot must be a dict conforming to the available/unavailable pattern.
    Scalar convenience fields (loaded_image_count, thumbnail_request_count, etc.)
    are carried at the top level for quick inspection without drilling into
    available/value wrappers.

    readiness carries the checkpoint gate state (ready, elapsed, visited/total
    counts, timed-out region flag, frame-cap status).
    blob_observation carries the available/unavailable wrapper for live blob
    URL observation with methodology and reason.
    """
    record: dict[str, Any] = {
        "name": name,
        "elapsed_ms": elapsed_ms,
        "loaded_image_count": loaded_image_count,
        "thumbnail_request_count": thumbnail_request_count,
        "blob_live_count": blob_live_count,
        "blob_bytes": blob_bytes,
        "dom_node_count": dom_node_count,
        "browser_process_memory": browser_process_memory,
        "frame_timing": frame_timing,
        "long_tasks": long_tasks,
        "thumbnail_disk": thumbnail_disk,
    }
    if readiness is not None:
        record["readiness"] = readiness
    if blob_observation is not None:
        record["blob_observation"] = blob_observation
    return record


DYNAMIC_TRAVERSAL_GRID = r"""
// dynamic-traversal-growth-v1
const done = arguments[arguments.length - 1];
const expectedCount = Number(arguments[0]) || 0;
const targetCount = Number(arguments[1]) || 0;
const maxTotalFrames = Number(arguments[2]) || 5000;
const mode = arguments[3] === 'partial' ? 'partial' : 'full';
const content = document.querySelector('.content');
if (!content) { done({available: false, reason: 'Grid scroll container not found'}); return; }

const intervals = [];
const visitedRegions = [];
const growthEvents = [];
const started = performance.now();
let previous = started;
let stagnationFrames = 0;
const stagnationMax = 120;
const regionTimeoutMs = 5000;

function renderedCount() {
    const thumbs = document.querySelectorAll('#grid .thumb:not(.loading-placeholder)');
    return thumbs.length;
}

function loadedImgCount() {
    const images = document.querySelectorAll('#grid .thumb:not(.loading-placeholder) img.loaded');
    return images.length;
}

function viewportSettled() {
    const images = Array.from(
        document.querySelectorAll('#grid .thumb:not(.loading-placeholder) img')
    ).filter(Boolean);
    const visible = images.filter(function(img) {
        const rect = img.getBoundingClientRect();
        return rect.bottom > 0 && rect.top < window.innerHeight;
    });
    if (visible.length === 0) return {settled: true, visible: 0, loaded: 0};
    const loaded = visible.filter(function(img) { return img.classList.contains('loaded'); }).length;
    return {settled: loaded === visible.length, visible: visible.length, loaded: loaded};
}

const initialScrollExtent = Math.max(0, content.scrollHeight - content.clientHeight);
const initiallyFullyRendered = renderedCount() >= expectedCount;
let previousScrollHeight = content.scrollHeight;
let previousRenderedCount = renderedCount();
let regionStartTime = started;
let regionIndex = 0;
let lastRecordedPosition = null;
let targetBoundaryVisited = false;
let finalBottomVisited = false;

function currentBoundary(maxScroll) {
    if (mode === 'partial' && initiallyFullyRendered) {
        const ratio = expectedCount > 0 ? Math.min(1, targetCount / expectedCount) : 0;
        return Math.min(maxScroll, Math.round(maxScroll * ratio));
    }
    return maxScroll;
}

function recordRegion(now, state) {
    visitedRegions.push({
        region: regionIndex,
        scrollPosition: content.scrollTop,
        visibleCount: state.visible,
        visibleLoaded: state.loaded,
        settled: state.settled,
        regionElapsedMs: Math.round(now - regionStartTime)
    });
    regionIndex += 1;
    lastRecordedPosition = content.scrollTop;
}

function step(now) {
    const dt = now - previous;
    intervals.push(dt);
    previous = now;

    if (intervals.length >= maxTotalFrames) {
        finish(false, true, null);
        return;
    }

    const currentScrollHeight = content.scrollHeight;
    const currentRendered = renderedCount();
    if (currentScrollHeight > previousScrollHeight || currentRendered > previousRenderedCount) {
        growthEvents.push({
            frame: intervals.length,
            prevHeight: previousScrollHeight,
            newHeight: currentScrollHeight,
            prevRenderedCount: previousRenderedCount,
            renderedCount: currentRendered
        });
        previousScrollHeight = currentScrollHeight;
        previousRenderedCount = currentRendered;
        stagnationFrames = 0;
        targetBoundaryVisited = false;
        finalBottomVisited = false;
        lastRecordedPosition = null;
        regionStartTime = now;
    }

    const clientHeight = content.clientHeight;
    const maxScroll = Math.max(0, currentScrollHeight - clientHeight);
    const stepSize = Math.max(300, Math.round(clientHeight * 0.6));
    const boundary = currentBoundary(maxScroll);
    const state = viewportSettled();
    const regionElapsed = now - regionStartTime;

    if (!state.settled && regionElapsed > regionTimeoutMs) {
        recordRegion(now, state);
        finish(false, false, null, 'Visible images did not settle at traversal boundary ' + content.scrollTop);
        return;
    }

    if (!state.settled) {
        requestAnimationFrame(step);
        return;
    }

    if (lastRecordedPosition !== content.scrollTop) recordRegion(now, state);

    const atBoundary = Math.abs(content.scrollTop - boundary) <= 2;
    if (atBoundary && currentRendered >= targetCount) {
        targetBoundaryVisited = true;
        finalBottomVisited = Math.abs(content.scrollTop - maxScroll) <= 2;
        const fullCountReached = mode !== 'full' || currentRendered >= expectedCount;
        finish(fullCountReached, false, null);
        return;
    }

    if (content.scrollTop < boundary - 2) {
        content.scrollTop = Math.min(boundary, content.scrollTop + stepSize);
        lastRecordedPosition = null;
        regionStartTime = now;
        stagnationFrames = 0;
    } else if (currentRendered < targetCount) {
        content.dispatchEvent(new Event('scroll', {bubbles: true}));
        stagnationFrames += 1;
        if (stagnationFrames > stagnationMax) {
            finish(false, false, 'Grid growth stagnated at ' + currentRendered + ' of ' + targetCount + ' rendered images');
            return;
        }
    }

    requestAnimationFrame(step);
}

function finish(ready, frameCapReached, stagnationReason, unsettledReason) {
    const unsettled = visitedRegions.filter(function(r) { return !r.settled; }).length;
    done({
        available: true,
        ready: ready,
        elapsedMs: performance.now() - started,
        intervals: intervals,
        frameCapReached: frameCapReached,
        expectedCount: expectedCount,
        targetCount: targetCount,
        renderedCount: renderedCount(),
        loadedCount: loadedImgCount(),
        growthEvents: growthEvents,
        regionsVisited: visitedRegions.length,
        visitedRegions: visitedRegions,
        initialScrollExtent: initialScrollExtent,
        finalScrollExtent: Math.max(0, content.scrollHeight - content.clientHeight),
        scrollExtent: Math.max(0, content.scrollHeight - content.clientHeight),
        finalScrollTop: content.scrollTop,
        targetBoundary: currentBoundary(Math.max(0, content.scrollHeight - content.clientHeight)),
        targetBoundaryVisited: targetBoundaryVisited,
        finalBottomVisited: finalBottomVisited,
        bottomVisited: finalBottomVisited,
        unsettledCount: unsettled,
        stagnationReason: stagnationReason,
        unsettledReason: unsettledReason || null,
        scrollRestored: false
    });
}
requestAnimationFrame(step);
"""


def _is_dynamic_traversal_ready(result: dict[str, Any]) -> bool:
    """Return True when the dynamic traversal reached its target and settled.

    The script must report ready, reach the target count and boundary, avoid
    frame caps and failure reasons, and reach the final bottom for a full target.
    """
    if not result.get("available", False):
        return False
    if not result.get("ready", False):
        return False
    if result.get("frameCapReached", False):
        return False
    if result.get("stagnationReason") is not None or result.get("unsettledReason") is not None:
        return False
    rendered = int(result.get("renderedCount", 0))
    target = int(result.get("targetCount", 0))
    if rendered < target:
        return False
    if not result.get("targetBoundaryVisited", False):
        return False
    expected = int(result.get("expectedCount", 0))
    if target >= expected and not result.get("finalBottomVisited", False):
        return False
    unsettled = int(result.get("unsettledCount", 0))
    if unsettled > 0:
        return False
    return True


def _dynamic_traversal_warnings(result: dict[str, Any], context: str = "") -> list[str]:
    """Generate warnings from a dynamic traversal result."""
    warnings: list[str] = []
    if not result.get("available", False):
        reason = result.get("reason") or "no reason supplied"
        warnings.append(f"Dynamic traversal unavailable for {context}: {reason}")
        return warnings
    if result.get("frameCapReached", False):
        warnings.append(f"Dynamic traversal frame-capped for {context}")
    stagnation = result.get("stagnationReason")
    if stagnation:
        warnings.append(f"Dynamic traversal stagnated for {context}: {stagnation}")
    unsettled_reason = result.get("unsettledReason")
    if unsettled_reason:
        warnings.append(
            f"Dynamic traversal viewport was unsettled for {context}: {unsettled_reason}"
        )
    rendered = int(result.get("renderedCount", 0))
    target = int(result.get("targetCount", 0))
    if rendered < target:
        warnings.append(
            f"Dynamic traversal incomplete for {context}: {rendered}/{target} images rendered"
        )
    if not result.get("targetBoundaryVisited", False):
        warnings.append(f"Dynamic traversal did not settle its target boundary for {context}")
    expected = int(result.get("expectedCount", 0))
    if target >= expected and not result.get("finalBottomVisited", False):
        warnings.append(f"Dynamic traversal did not reach the current final bottom for {context}")
    unsettled = int(result.get("unsettledCount", 0))
    if unsettled > 0:
        warnings.append(f"Dynamic traversal had {unsettled} unsettled region(s) for {context}")
    return warnings


def _build_checkpoint_warnings(checkpoint_name: str, readiness: dict[str, Any]) -> list[str]:
    """Generate warning strings for checkpoint states that indicate
    degraded or incomplete measurement.

    Handles first-viewport checkpoints (timeout/unavailable) and traversal
    checkpoints (unsettled regions, frame caps, unavailable).
    """
    warnings: list[str] = []
    if not readiness.get("available", True):
        reason = readiness.get("reason") or "no reason supplied"
        warnings.append(f"Checkpoint '{checkpoint_name}' was unavailable: {reason}")
        return warnings
    state = readiness.get("state", {})
    unsettled = int(state.get("unsettled_region_count", 0))
    if unsettled > 0:
        warnings.append(
            f"Checkpoint '{checkpoint_name}' had {unsettled} unsettled/timed-out region(s)"
        )
    if state.get("frame_cap_reached"):
        warnings.append(f"Checkpoint '{checkpoint_name}' reached its rAF frame cap")
    if not readiness.get("ready", True):
        regions_visited = int(state.get("regions_visited") or 0)
        total_regions = int(state.get("total_regions") or 0)
        if total_regions > 0 and regions_visited != total_regions:
            warnings.append(
                f"Checkpoint '{checkpoint_name}' visited {regions_visited} "
                f"of {total_regions} target regions"
            )
        elif not warnings:  # cp1 timeout (no region counts)
            elapsed = readiness.get("elapsed_ms", 0)
            warnings.append(
                f"Checkpoint '{checkpoint_name}' timed out or was not ready "
                f"(elapsed {elapsed:.0f} ms)"
            )
    return warnings


def _select_and_traverse(driver: Any, batch: str, count: int, timeout: float) -> dict[str, Any]:
    """Select a batch, settle first viewport, perform full controlled traversal.

    Returns a readiness dict compatible with existing _phase_metrics/summary
    and A-B-A total-elapsed tracking.  Every batch selection gets its own
    VIEWPORT_SETTLE_ASYNC so first_viewport_ms is per-batch.  After the full
    deterministic traversal the grid is scrolled back to top.
    """
    response = driver.execute_async_script(SELECT_BATCH, batch)
    if not response.get("ok"):
        raise BenchmarkError(f"Could not select batch {batch}: {response.get('error')}")

    wall_started = time.perf_counter()

    # ---- First viewport settle (per-batch) ----
    viewport_result: dict[str, Any] = driver.execute_async_script(
        VIEWPORT_SETTLE_ASYNC, count, int(timeout * 1000)
    )
    viewport_available = bool(viewport_result.get("available", False))
    viewport_ready = bool(viewport_result.get("ready", False))
    _vp_ok = viewport_ready and viewport_available
    first_viewport_ms: float | None = (
        round(float(viewport_result.get("elapsedMs", 0)), 3) if _vp_ok else None
    )

    # ---- Full dynamic traversal ----
    dynamic_result: dict[str, Any] = driver.execute_async_script(
        DYNAMIC_TRAVERSAL_GRID, count, count, 5000, "full"
    )
    traversal_available = bool(dynamic_result.get("available", False))
    traversal_ready = _is_dynamic_traversal_ready(dynamic_result) if traversal_available else False

    # Capture loaded count from dynamic result for state reporting
    loaded_after = int(dynamic_result.get("loadedCount", 0)) if traversal_available else 0

    # Restore scrollTop=0 so subsequent phases start at top
    driver.execute_script("var c=document.querySelector('.content');if(c)c.scrollTop=0;")

    # ---- Warnings ----
    warnings: list[str] = []
    if not viewport_available:
        warnings.append(f"Viewport settle unavailable for batch {batch}")
    elif not viewport_ready:
        warnings.append(f"Viewport did not settle within timeout for batch {batch}")
    warnings.extend(_dynamic_traversal_warnings(dynamic_result, f"batch {batch}"))

    overall_ready = _vp_ok and traversal_ready and traversal_available

    # Build an actionable reason string on failure
    reason: str | None = None
    if not overall_ready:
        parts: list[str] = []
        if not viewport_available:
            parts.append("viewport settle script unavailable")
        elif not viewport_ready:
            parts.append("viewport did not settle within timeout")
        if not traversal_available:
            parts.append(
                f"dynamic traversal script unavailable: {dynamic_result.get('reason', 'unknown')}"
            )
        elif not traversal_ready:
            if dynamic_result.get("frameCapReached"):
                parts.append("dynamic traversal reached frame cap")
            stagnation = dynamic_result.get("stagnationReason")
            if stagnation:
                parts.append(f"dynamic traversal stagnated: {stagnation}")
            rendered = int(dynamic_result.get("renderedCount", 0))
            target = int(dynamic_result.get("targetCount", 0))
            if rendered < target:
                parts.append(f"dynamic traversal incomplete ({rendered}/{target} rendered)")
            if not dynamic_result.get("targetBoundaryVisited", False):
                parts.append("dynamic traversal did not settle its target boundary")
            if not dynamic_result.get("finalBottomVisited", False):
                parts.append("dynamic traversal did not reach the current final bottom")
            unsettled = int(dynamic_result.get("unsettledCount", 0))
            if unsettled > 0:
                parts.append(f"dynamic traversal had {unsettled} unsettled region(s)")
        if parts:
            reason = "; ".join(parts)

    return {
        "ready": overall_ready,
        "available": viewport_available and traversal_available,
        "elapsed_ms": round((time.perf_counter() - wall_started) * 1000, 3),
        "first_viewport_ms": first_viewport_ms,
        "state": {
            "loaded": loaded_after,
            "count": count,
            "rendered_count": int(dynamic_result.get("renderedCount", 0)),
            "expected_count": count,
            "target_count": count,
            "visibleCount": int(viewport_result.get("state", {}).get("visibleCount", 0))
            if viewport_available
            else 0,
            "visibleLoaded": int(viewport_result.get("state", {}).get("visibleLoaded", 0))
            if viewport_available
            else 0,
            "traversal_ready": traversal_ready,
            "regions_visited": (
                int(dynamic_result.get("regionsVisited", 0)) if traversal_available else 0
            ),
            "total_positions": 0,  # dynamic: no static positions
            "frame_cap_reached": (
                bool(dynamic_result.get("frameCapReached", False)) if traversal_available else False
            ),
            "unsettled_region_count": (
                int(dynamic_result.get("unsettledCount", 0)) if traversal_available else 0
            ),
        },
        "reason": reason,
        "warnings": warnings,
    }


def _thumbnail_disk_metrics(batch_root: Path, batch: str) -> dict[str, int]:
    thumbnail_dir = batch_root / batch / ".thumbs"
    if not thumbnail_dir.is_dir():
        return {"file_count": 0, "disk_bytes": 0}
    files = [path for path in thumbnail_dir.iterdir() if path.is_file() and not path.is_symlink()]
    return {"file_count": len(files), "disk_bytes": sum(path.stat().st_size for path in files)}


def _browser_process_memory(
    dependencies: OptionalDependencies, driver: Any, browser: str
) -> dict[str, Any]:
    process = getattr(getattr(driver, "service", None), "process", None)
    pid = getattr(process, "pid", None)
    if not pid:
        return unavailable("WebDriver service PID unavailable")
    expected = "firefox" if browser == "firefox" else "chrome"
    try:
        root = dependencies.psutil.Process(pid)
        candidates = [root, *root.children(recursive=True)]
        browser_processes = [item for item in candidates if expected in item.name().lower()]
        if not browser_processes:
            return unavailable("No browser processes found below the WebDriver service process")
        rss = sum(item.memory_info().rss for item in browser_processes)
    except Exception as exc:
        return unavailable(f"psutil could not read the browser process tree: {type(exc).__name__}")
    return available(
        {"rss_bytes": rss, "process_count": len(browser_processes)},
        "Sum of psutil RSS/working-set values for browser-named descendants of WebDriver",
    )


def _phase_metrics(
    driver: Any,
    dependencies: OptionalDependencies,
    runtime: RuntimeContext,
    browser: str,
    batch: str,
    readiness: dict[str, Any] | None = None,
    frame_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    entries = driver.execute_script(RESOURCE_ENTRIES)
    page = driver.execute_script(PAGE_METRICS)
    resources = summarize_thumbnail_resources(entries, runtime.paths.thumbnail_prefix)
    blob_raw = driver.execute_async_script(BLOB_BYTES)
    if blob_raw.get("available"):
        blob_bytes = available(
            {"entry_count": blob_raw["count"], "compressed_bytes": blob_raw["bytes"]},
            BLOB_METHODOLOGY,
        )
    else:
        blob_bytes = unavailable(str(blob_raw.get("reason") or "Blob byte measurement failed"))
    if page["longTasks"].get("available"):
        tasks = page["longTasks"]["entries"]
        long_tasks = available(
            {
                "count": len(tasks),
                "duration_ms": round(sum(float(task["duration"]) for task in tasks), 3),
            },
            "PerformanceObserver longtask entries captured after harness instrumentation",
        )
    else:
        long_tasks = unavailable(str(page["longTasks"].get("reason")))
    warnings = []
    if readiness is not None:
        if not readiness["ready"]:
            warnings.append(
                f"Grid readiness timed out with {readiness.get('state', {}).get('loaded', 0)} loaded "
                f"of {readiness.get('state', {}).get('count', 0)} rendered thumbnails"
            )
        # Propagate per-readiness warnings (viewport/timeout/traversal)
        warnings.extend(readiness.get("warnings", []))
    metrics = {
        "thumbnail_resources": resources,
        "grid_readiness": available(
            {
                "ready": readiness["ready"],
                "elapsed_ms": readiness["elapsed_ms"],
                "first_viewport_ms": readiness["first_viewport_ms"],
            },
            "Harness wall clock from batch selection through viewport settle and controlled "
            "full traversal (not all expected elements terminal)",
        )
        if readiness is not None
        else unavailable("This phase does not perform grid loading"),
        "blob_cache_entries": available(
            page["blobCacheEntryCount"],
            "Live page-realm Blob URLs observed after instrumentation and published through the benchmark DOM bridge",
        )
        if page["blobCacheEntryCount"] is not None
        else unavailable(
            str(
                page.get("blobObservation", {}).get("reason")
                or "Benchmark DOM bridge blob observation is unavailable"
            )
        ),
        "blob_compressed_bytes": blob_bytes,
        "dom_node_count": available(
            page["domNodeCount"], "document.getElementsByTagName('*').length"
        ),
        "long_tasks": long_tasks,
        "frame_timing": summarize_frames(frame_data)
        if frame_data is not None
        else unavailable("This phase does not perform a frame-timed scripted operation"),
        "browser_process_memory": _browser_process_memory(dependencies, driver, browser),
        "thumbnail_disk": available(
            _thumbnail_disk_metrics(runtime.batch_root, batch),
            "Regular-file count and logical file bytes in the benchmark batch .thumbs directory",
        ),
        "navigation_timing": available(page["navigation"], "Navigation Timing Level 2")
        if page["navigation"] is not None
        else unavailable("Navigation Timing entry unavailable"),
    }
    return metrics, warnings


def _capture_checkpoint(
    driver: Any,
    dependencies: OptionalDependencies,
    runtime: RuntimeContext,
    browser: str,
    batch: str,
    *,
    name: str,
    readiness: dict[str, Any],
    frame_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture a measurement snapshot at a specific point during the cold phase.

    Collects all metric dimensions required for checkpoint attribution: loaded
    image count from the readiness state, thumbnail request count from Resource
    Timing, live blob count and bytes from the benchmark DOM bridge, DOM node
    count, browser RSS, long-task observations, frame timing (when traversal
    data is supplied), and server-side .thumbs file count and bytes.
    """
    entries = driver.execute_script(RESOURCE_ENTRIES)
    page = driver.execute_script(PAGE_METRICS)
    resources = summarize_thumbnail_resources(entries, runtime.paths.thumbnail_prefix)

    blob_raw = driver.execute_async_script(BLOB_BYTES)
    blob_live_count: int | None = blob_raw.get("count") if blob_raw.get("available") else None
    blob_bytes_val: int | None = blob_raw.get("bytes") if blob_raw.get("available") else None
    if blob_raw.get("available"):
        blob_obs = available(
            {"entry_count": blob_raw["count"], "compressed_bytes": blob_raw["bytes"]},
            BLOB_METHODOLOGY,
        )
    else:
        blob_obs = unavailable(
            str(blob_raw.get("reason") or "Benchmark DOM bridge blob observation is unavailable")
        )

    if page["longTasks"].get("available"):
        tasks = page["longTasks"]["entries"]
        long_tasks = available(
            {
                "count": len(tasks),
                "duration_ms": round(sum(float(task["duration"]) for task in tasks), 3),
            },
            "PerformanceObserver longtask entries captured after harness instrumentation",
        )
    else:
        long_tasks = unavailable(str(page["longTasks"].get("reason")))

    loaded_count = readiness.get("state", {}).get("loaded", 0) if readiness else 0

    return _build_checkpoint_record(
        name=name,
        elapsed_ms=round(float(readiness.get("elapsed_ms", 0)), 3) if readiness else 0,
        loaded_image_count=loaded_count,
        thumbnail_request_count=resources["request_count"],
        blob_live_count=blob_live_count,
        blob_bytes=blob_bytes_val,
        dom_node_count=page["domNodeCount"],
        browser_process_memory=_browser_process_memory(dependencies, driver, browser),
        frame_timing=summarize_frames(frame_data)
        if frame_data is not None
        else unavailable("No frame data for this checkpoint"),
        long_tasks=long_tasks,
        thumbnail_disk=available(
            _thumbnail_disk_metrics(runtime.batch_root, batch),
            "Regular-file count and logical file bytes in the benchmark batch .thumbs directory",
        ),
        readiness=readiness,
        blob_observation=blob_obs,
    )


def _prepare_checkpoint_cold_phase(
    driver: Any,
    dependencies: OptionalDependencies,
    active_batch_session: ActiveBatchSession,
    runtime: RuntimeContext,
    spec: FixtureSpec,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[str]]:
    """Run the cold-phase checkpoint flow: companion warm-up, viewport settle,
    partial traversal, full traversal, then final all-thumbnails readiness.

    Returns four items:
      1. checkpoints: list of three checkpoint records captured at each stage
      2. companion_ready: readiness dict for the companion batch
      3. final_readiness: readiness dict after all primary-batch thumbnails
         reach loaded/error state (preserving existing cold-phase contract)
      4. cp_warnings: human-readable warnings for checkpoint failures
    """
    active_batch_session.switch(spec.companion_batch)
    driver.get(runtime.page_url)
    companion_ready = _select_and_traverse(
        driver, spec.companion_batch, spec.companion_size, timeout
    )

    _install_instrumentation(driver, spec.size)

    # Select primary batch, but only wait for viewport — not all thumbnails
    response = driver.execute_async_script(SELECT_BATCH, spec.primary_batch)
    if not response.get("ok"):
        raise BenchmarkError(
            f"Could not select benchmark batch {spec.primary_batch}: {response.get('error')}"
        )

    # ---- Checkpoint 1: first viewport settled ----
    # Use async rAF-based viewport settle to capture frame intervals
    viewport_result = driver.execute_async_script(
        VIEWPORT_SETTLE_ASYNC, spec.size, int(timeout * 1000)
    )
    viewport_available = bool(viewport_result.get("available", False))
    viewport_ready = bool(viewport_result.get("ready", False))
    _viewport_ready = viewport_ready and viewport_available
    if not viewport_available:
        _reason = str(viewport_result.get("reason") or "viewport settle script unavailable")
    elif not viewport_ready:
        _reason = "Viewport did not settle within timeout"
    else:
        _reason = None
    viewport_readiness = {
        "ready": _viewport_ready,
        "elapsed_ms": round(float(viewport_result.get("elapsedMs", 0)), 3),
        "state": viewport_result.get("state", {}),
        "available": viewport_available,
        "reason": _reason,
    }
    cp1 = _capture_checkpoint(
        driver,
        dependencies,
        runtime,
        spec.browser,
        spec.primary_batch,
        name="first_viewport_settled",
        readiness=viewport_readiness,
        frame_data=viewport_result if viewport_available else None,
    )
    # Preserve first-viewport timing, but only when actually ready
    _first_viewport_ms = round(viewport_readiness["elapsed_ms"], 3) if _viewport_ready else None

    # ---- Checkpoint 2: partial dynamic traversal ----
    partial_target = max(1, int(math.ceil(spec.size * 0.4)))
    partial_target = min(partial_target, spec.size)
    partial_traversal: dict[str, Any] = driver.execute_async_script(
        DYNAMIC_TRAVERSAL_GRID, spec.size, partial_target, 5000, "partial"
    )
    partial_ready = _is_dynamic_traversal_ready(partial_traversal)
    partial_state = {
        "loaded": partial_traversal.get("loadedCount") if partial_traversal.get("available") else 0,
        "regions_visited": partial_traversal.get("regionsVisited"),
        "total_regions": partial_traversal.get("regionsVisited"),
        "frame_cap_reached": partial_traversal.get("frameCapReached", False),
        "unsettled_region_count": (
            int(partial_traversal.get("unsettledCount", 0))
            if partial_traversal.get("available")
            else 0
        ),
        "available": partial_traversal.get("available", False),
        "reason": partial_traversal.get("reason"),
        "rendered_count": partial_traversal.get("renderedCount"),
        "expected_count": spec.size,
        "target_count": partial_target,
        "target_boundary": partial_traversal.get("targetBoundary"),
        "target_boundary_visited": partial_traversal.get("targetBoundaryVisited", False),
        "final_bottom_visited": partial_traversal.get("finalBottomVisited", False),
    }
    cp2_readiness = {
        "ready": partial_ready,
        "elapsed_ms": partial_traversal.get("elapsedMs", 0),
        "state": partial_state,
        "available": partial_traversal.get("available", False),
        "reason": (
            partial_traversal.get("stagnationReason")
            or partial_traversal.get("reason")
            or (None if partial_ready else "partial dynamic traversal did not reach target")
        ),
    }
    cp2 = _capture_checkpoint(
        driver,
        dependencies,
        runtime,
        spec.browser,
        spec.primary_batch,
        name="partial_traversal",
        readiness=cp2_readiness,
        frame_data=partial_traversal,
    )

    # ---- Checkpoint 3: full dynamic traversal ----
    full_traversal: dict[str, Any] = driver.execute_async_script(
        DYNAMIC_TRAVERSAL_GRID, spec.size, spec.size, 5000, "full"
    )
    full_ready = _is_dynamic_traversal_ready(full_traversal)
    full_state = {
        "loaded": full_traversal.get("loadedCount") if full_traversal.get("available") else 0,
        "regions_visited": full_traversal.get("regionsVisited"),
        "total_regions": full_traversal.get("regionsVisited"),
        "frame_cap_reached": full_traversal.get("frameCapReached", False),
        "unsettled_region_count": (
            int(full_traversal.get("unsettledCount", 0)) if full_traversal.get("available") else 0
        ),
        "available": full_traversal.get("available", False),
        "reason": full_traversal.get("reason"),
        "rendered_count": full_traversal.get("renderedCount"),
        "expected_count": spec.size,
        "target_count": spec.size,
        "target_boundary": full_traversal.get("targetBoundary"),
        "target_boundary_visited": full_traversal.get("targetBoundaryVisited", False),
        "final_bottom_visited": full_traversal.get("finalBottomVisited", False),
    }
    cp3_readiness = {
        "ready": full_ready,
        "elapsed_ms": full_traversal.get("elapsedMs", 0),
        "state": full_state,
        "available": full_traversal.get("available", False),
        "reason": (
            full_traversal.get("stagnationReason")
            or full_traversal.get("reason")
            or (None if full_ready else "full dynamic traversal did not reach target")
        ),
    }
    cp3 = _capture_checkpoint(
        driver,
        dependencies,
        runtime,
        spec.browser,
        spec.primary_batch,
        name="full_traversal",
        readiness=cp3_readiness,
        frame_data=full_traversal,
    )

    # Restore scroll position to top so the next controlled_scroll phase
    # can produce meaningful frame data (full traversal left it at bottom)
    driver.execute_script("var c=document.querySelector('.content');if(c)c.scrollTop=0;")

    # Build checkpoint warnings
    cp_warnings: list[str] = []
    cp_warnings.extend(_build_checkpoint_warnings("first_viewport_settled", viewport_readiness))
    cp_warnings.extend(_build_checkpoint_warnings("partial_traversal", cp2_readiness))
    cp_warnings.extend(_build_checkpoint_warnings("full_traversal", cp3_readiness))
    # Also include dynamic traversal warnings for stagnation/frame-cap/unsettled
    cp_warnings.extend(
        _dynamic_traversal_warnings(partial_traversal, "partial_traversal checkpoint")
    )
    cp_warnings.extend(_dynamic_traversal_warnings(full_traversal, "full_traversal checkpoint"))

    # ---- Final: wait for all thumbnails (preserves existing cold-phase contract) ----
    final_readiness = _wait_for_grid(driver, spec.size, timeout)
    # Propagate first-viewport timing from checkpoint 1 when ready
    final_readiness["first_viewport_ms"] = (
        round(_first_viewport_ms, 3) if _first_viewport_ms is not None else None
    )

    return [cp1, cp2, cp3], companion_ready, final_readiness, cp_warnings


def _grid_loaded_count_js() -> str:
    """Return a JS expression that evaluates to the number of distinct loaded
    thumbnail img elements in the grid, suitable for use inside execute_script."""
    return """
var thumbs = Array.from(document.querySelectorAll('#grid .thumb:not(.loading-placeholder)'));
var images = thumbs.map(function(t) { return t.querySelector('img'); }).filter(Boolean);
return images.filter(function(img) { return img.classList.contains('loaded'); }).length;
"""


def _query_grid_loaded(driver: Any) -> int:
    """Return the current count of distinct loaded thumbnail img elements."""
    try:
        return int(driver.execute_script(_grid_loaded_count_js()))
    except (TypeError, ValueError):
        return 0


def _browser_specific_metrics(browser: str) -> dict[str, Any]:
    if browser == "firefox":
        return {
            "firefox_only": unavailable(
                "No stable Firefox-only metric is used; shared Resource Timing and psutil metrics are reported"
            ),
            "chromium_only": unavailable("Not a Chromium session"),
        }
    return {
        "firefox_only": unavailable("Not a Firefox session"),
        "chromium_only": unavailable(
            "Chrome DevTools-only values are not substituted for cross-browser metrics"
        ),
    }


def _phase(
    name: str,
    classification: str,
    metrics: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "phase": name,
        "classification": classification,
        "cross_browser_metrics": metrics,
        "warnings": warnings,
        "noisy_run": bool(warnings),
    }


def benchmark_case(
    dependencies: OptionalDependencies,
    args: argparse.Namespace,
    runtime: RuntimeContext,
    spec: FixtureSpec,
    profile_dir: Path,
    active_batch_session: ActiveBatchSession,
) -> dict[str, Any]:
    driver = create_driver(dependencies, spec.browser, args, profile_dir)
    phases: list[dict[str, Any]] = []
    stage = "cold companion and primary preparation"
    phase_failed = False
    try:
        checkpoints, companion_ready, readiness, cp_warnings = _prepare_checkpoint_cold_phase(
            driver, dependencies, active_batch_session, runtime, spec, args.timeout
        )
        stage = "cold metric collection"
        metrics, warnings = _phase_metrics(
            driver,
            dependencies,
            runtime,
            spec.browser,
            spec.primary_batch,
            readiness,
        )
        if metrics["thumbnail_resources"]["request_count"] != spec.size:
            warnings.append(
                f"Cold thumbnail request count was {metrics['thumbnail_resources']['request_count']}, expected {spec.size}"
            )
        if not companion_ready["ready"]:
            warnings.append("Initial companion batch did not become ready before cold measurement")
        # Propagate detailed companion warnings (unavailable, frame-cap, unsettled, etc.)
        for cw in companion_ready.get("warnings", []):
            if cw not in warnings:
                warnings.append(cw)
        warnings.extend(cp_warnings)
        cold_phase = _phase("cold_initial_load", "cold", metrics, warnings)
        cold_phase["checkpoints"] = checkpoints
        phases.append(cold_phase)

        stage = "controlled scroll"
        _install_instrumentation(driver, spec.size)
        scroll_data = driver.execute_async_script(SCROLL_GRID)
        stage = "controlled scroll metric collection"
        metrics, warnings = _phase_metrics(
            driver,
            dependencies,
            runtime,
            spec.browser,
            spec.primary_batch,
            frame_data=scroll_data,
        )
        if scroll_data.get("frameCapReached"):
            warnings.append("Controlled scroll reached its frame cap")
        phases.append(_phase("controlled_scroll", "warm", metrics, warnings))

        stage = "warm reload"
        driver.execute_script(
            "localStorage.removeItem('imageCurator.lastBatch'); localStorage.removeItem('imageCurator.lastFolder');"
        )
        driver.refresh()
        _install_instrumentation(driver, spec.size)
        readiness = _select_and_traverse(driver, spec.primary_batch, spec.size, args.timeout)
        stage = "warm reload metric collection"
        metrics, warnings = _phase_metrics(
            driver,
            dependencies,
            runtime,
            spec.browser,
            spec.primary_batch,
            readiness,
        )
        phases.append(_phase("warm_reload", "warm", metrics, warnings))

        stage = "batch A-B-A switch"
        _install_instrumentation(driver, spec.size + spec.companion_size)
        switch_started = time.perf_counter()
        companion_ready = _select_and_traverse(
            driver, spec.companion_batch, spec.companion_size, args.timeout
        )
        primary_ready = _select_and_traverse(driver, spec.primary_batch, spec.size, args.timeout)
        primary_ready["elapsed_ms"] = round((time.perf_counter() - switch_started) * 1000, 3)
        stage = "batch A-B-A metric collection"
        metrics, warnings = _phase_metrics(
            driver,
            dependencies,
            runtime,
            spec.browser,
            spec.primary_batch,
            primary_ready,
        )
        if not companion_ready["ready"]:
            warnings.append("Companion batch did not become ready during A -> B -> A switch")
        # Propagate detailed companion warnings (unavailable, frame-cap, unsettled, etc.)
        companion_warnings = companion_ready.get("warnings", [])
        for cw in companion_warnings:
            if cw not in warnings:
                warnings.append(cw)
        phases.append(_phase("batch_a_b_a_switch", "warm-refetch", metrics, warnings))

        stage = "sidebar width changes"
        _install_instrumentation(driver, spec.size)
        width_data = driver.execute_async_script(SIDEBAR_WIDTH_PHASE)
        stage = "sidebar width metric collection"
        metrics, warnings = _phase_metrics(
            driver,
            dependencies,
            runtime,
            spec.browser,
            spec.primary_batch,
            frame_data=width_data,
        )
        if width_data.get("available") and not width_data.get("restored"):
            warnings.append("Sidebar widths did not restore to their pre-phase values")
        phases.append(_phase("sidebar_width_changes", "warm-layout", metrics, warnings))

        stage = "browser result assembly"
        capabilities = driver.capabilities or {}
        return {
            "browser": spec.browser,
            "version": str(capabilities.get("browserVersion") or "unknown"),
            "fixture_size": spec.size,
            "size": spec.size,
            "status": "ok",
            "phases": phases,
            "browser_specific_metrics": _browser_specific_metrics(spec.browser),
        }
    except BenchmarkError:
        phase_failed = True
        raise
    except Exception as exc:
        phase_failed = True
        raise browser_stage_error(stage, exc) from exc
    finally:
        try:
            driver.quit()
        except Exception as exc:
            if not phase_failed:
                raise browser_stage_error("WebDriver shutdown", exc) from exc


def _manifest_payload(
    run_id: str, runtime: RuntimeContext, specs: list[FixtureSpec]
) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "run_id": run_id,
        "batch_root": str(runtime.batch_root),
        "batches": [
            {"name": batch, "run_id": spec.run_id} for spec in specs for batch in spec.batches
        ],
        "status": "planned",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_recovery_manifest(manifest_path: Path) -> dict[str, Any]:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CleanupRefused(f"Unsafe recovery manifest: {manifest_path.name}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanupRefused(f"Unreadable recovery manifest: {manifest_path.name}") from exc
    if manifest.get("schema") != MANIFEST_SCHEMA or not isinstance(manifest.get("run_id"), str):
        raise CleanupRefused(f"Unsupported recovery manifest: {manifest_path.name}")
    return manifest


def cleanup_owned_profiles(output_root: Path, manifest_path: Path) -> dict[str, Any]:
    resolved_output_root = output_root.resolve()
    run_dir = manifest_path.parent
    if run_dir.is_symlink():
        raise CleanupRefused("Refusing profile cleanup from a symlinked run directory")
    resolved_run_dir = run_dir.resolve()
    if resolved_run_dir.parent != resolved_output_root:
        raise CleanupRefused("Refusing profile cleanup outside the output root")
    manifest = _load_recovery_manifest(manifest_path)
    if resolved_run_dir.name != manifest["run_id"]:
        raise CleanupRefused("Manifest run identity does not match its run directory")

    profiles = run_dir / "profiles"
    if not profiles.exists() and not profiles.is_symlink():
        outcome = {"status": "not-found", "removed": False, "reason": None}
    elif profiles.is_symlink():
        raise CleanupRefused("Refusing profile cleanup from a symlinked profiles directory")
    else:
        resolved_profiles = profiles.resolve()
        if resolved_profiles.parent != resolved_run_dir or resolved_profiles.name != "profiles":
            raise CleanupRefused("Refusing escaping profiles directory")
        try:
            shutil.rmtree(resolved_profiles)
        except OSError as exc:
            outcome = {
                "status": "failed",
                "removed": False,
                "reason": f"Could not remove profiles directory: {type(exc).__name__}",
            }
        else:
            outcome = {"status": "removed", "removed": True, "reason": None}
    manifest["profile_cleanup"] = outcome
    _write_json(manifest_path, manifest)
    return outcome


def cleanup_manifest(manifest_path: Path, resolved_batch_root: Path) -> dict[str, Any]:
    manifest = _load_recovery_manifest(manifest_path)
    manifest_root = Path(str(manifest.get("batch_root", ""))).resolve()
    if manifest_root != resolved_batch_root.resolve():
        raise CleanupRefused(f"Manifest {manifest_path.name} does not match the runtime batch root")
    removed = []
    refused = []
    for item in manifest.get("batches", []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            refused.append("invalid manifest batch entry")
            continue
        batch = item["name"]
        batch_path = resolved_batch_root / batch
        if not batch_path.exists():
            continue
        try:
            remove_owned_batch(resolved_batch_root, batch_path, manifest["run_id"], batch)
            removed.append(batch)
        except CleanupRefused as exc:
            refused.append(str(exc))
    manifest["status"] = "cleaned" if not refused else "cleanup-refused"
    manifest["cleanup"] = {"removed": removed, "refused": refused}
    _write_json(manifest_path, manifest)
    return manifest["cleanup"]


def recovery_cleanup(output_root: Path, runtime: RuntimeContext) -> int:
    manifests = sorted(output_root.glob("*/recovery-manifest.json"))
    if not manifests:
        print("No thumbnail benchmark recovery manifests found")
        return 0
    refused = []
    removed = 0
    profiles_removed = 0
    for manifest in manifests:
        try:
            result = cleanup_manifest(manifest, runtime.batch_root)
            removed += len(result["removed"])
            refused.extend(result["refused"])
        except CleanupRefused as exc:
            refused.append(str(exc))
        try:
            profile_result = cleanup_owned_profiles(output_root, manifest)
            profiles_removed += int(profile_result["removed"])
            if profile_result["status"] == "failed":
                refused.append(str(profile_result["reason"]))
        except CleanupRefused as exc:
            refused.append(str(exc))
    print(
        f"Recovery cleanup removed {removed} owned benchmark batches and "
        f"{profiles_removed} profile directories"
    )
    for message in refused:
        print(f"Cleanup refused: {message}", file=sys.stderr)
    return 1 if refused else 0


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def run(args: argparse.Namespace) -> int:
    output_root = args.output_root.resolve()
    runtime = resolve_runtime(args)
    if args.cleanup:
        return recovery_cleanup(output_root, runtime)

    dependencies = load_optional_dependencies()
    browsers = requested_browsers(args.browser)
    availability_failures = {
        browser: reason
        for browser in browsers
        if (reason := browser_availability(args, browser)) is not None
    }
    available_browsers = [browser for browser in browsers if browser not in availability_failures]
    if not available_browsers:
        raise BenchmarkError("; ".join(availability_failures.values()))

    run_id = _new_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    specs = build_fixture_specs(run_id, args.sizes, available_browsers)
    manifest_path = run_dir / "recovery-manifest.json"
    manifest = _manifest_payload(run_id, runtime, specs)
    _write_json(manifest_path, manifest)

    results = [
        {
            "browser": browser,
            "version": "unavailable",
            "size": None,
            "status": "failed",
            "error": reason,
            "phases": [],
        }
        for browser, reason in availability_failures.items()
    ]
    warnings = list(availability_failures.values())
    cleanup = {"status": "not-started", "removed": [], "refused": []}
    active_batch_session = ActiveBatchSession(runtime)
    active_batch_restore = {"status": "not-needed", "error": None}
    profile_cleanup = {"status": "not-started", "removed": False, "reason": None}
    try:
        create_fixture_batches(runtime.batch_root, run_dir / "fixtures" / "seeds", specs)
        manifest["status"] = "created"
        _write_json(manifest_path, manifest)
        for spec in specs:
            try:
                profile_dir = run_dir / "profiles" / f"{spec.browser}-{spec.size}"
                results.append(
                    benchmark_case(
                        dependencies,
                        args,
                        runtime,
                        spec,
                        profile_dir,
                        active_batch_session,
                    )
                )
            except Exception as exc:
                message = str(exc) if isinstance(exc, BenchmarkError) else type(exc).__name__
                results.append(
                    {
                        "browser": spec.browser,
                        "version": "unknown",
                        "size": spec.size,
                        "status": "failed",
                        "error": message,
                        "phases": [],
                    }
                )
                warnings.append(f"{spec.browser} size {spec.size} failed: {message}")
    finally:
        try:
            active_batch_session.restore()
            if active_batch_session.switch_attempted:
                active_batch_restore["status"] = "restored"
        except BenchmarkError as exc:
            active_batch_restore = {"status": "failed", "error": str(exc)}
            warnings.append(f"Active batch restoration failed: {exc}")
        if args.keep_fixtures:
            cleanup = {"status": "kept", "removed": [], "refused": []}
            manifest["status"] = "kept"
            _write_json(manifest_path, manifest)
        else:
            try:
                cleanup_result = cleanup_manifest(manifest_path, runtime.batch_root)
                cleanup = {
                    "status": "completed" if not cleanup_result["refused"] else "refused",
                    **cleanup_result,
                }
            except CleanupRefused as exc:
                cleanup = {"status": "refused", "removed": [], "refused": [str(exc)]}
                warnings.append(str(exc))
        try:
            profile_cleanup = cleanup_owned_profiles(output_root, manifest_path)
            if profile_cleanup["status"] == "failed":
                warnings.append(str(profile_cleanup["reason"]))
        except CleanupRefused as exc:
            profile_cleanup = {"status": "refused", "removed": False, "reason": str(exc)}
            warnings.append(str(exc))

    report = sanitize_report(
        {
            "schema": REPORT_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": args.mode,
            "page_url": runtime.page_url,
            "requested_browsers": browsers,
            "requested_sizes": args.sizes,
            "headless": args.headless,
            "browser_results": results,
            "active_batch_restore": active_batch_restore,
            "cleanup": cleanup,
            "profile_cleanup": profile_cleanup,
            "warnings": warnings,
            "all_browser_failure_policy": (
                "Any requested browser failure makes the command exit nonzero; other available "
                "requested browsers still run."
            ),
        }
    )
    _write_json(run_dir / "report.json", report)
    (run_dir / "summary.md").write_text(render_markdown_summary(report), encoding="utf-8")
    print(f"Thumbnail benchmark report: {run_dir / 'summary.md'}")
    failures = any(result.get("status") != "ok" for result in results)
    return (
        1
        if failures
        or cleanup["status"] == "refused"
        or active_batch_restore["status"] == "failed"
        or profile_cleanup["status"] in ("failed", "refused")
        else 0
    )


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except BenchmarkError as exc:
        print(f"Thumbnail benchmark error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
