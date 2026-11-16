"""Regression: native routes and lifecycle must import without Flask/Werkzeug."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_native_routes_and_lifecycle_import_with_flask_and_werkzeug_blocked(tmp_path):
    probe = subprocess.run(
        [sys.executable, "-c", "import aiohttp"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if probe.returncode != 0:
        pytest.skip("aiohttp is required for native route registration")

    script = r"""
import asyncio
import importlib.abc
import sys
from pathlib import Path


class _BlockRemovedWebStack(importlib.abc.MetaPathFinder):
    blocked = ("flask", "werkzeug")

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in self.blocked):
            raise ModuleNotFoundError(fullname)
        return None


sys.meta_path.insert(0, _BlockRemovedWebStack())

from aiohttp import web

from ai_curate.native_lifecycle import NativeAiLifecycle
from image_curator.native_ai_routes import register_native_ai_routes
from image_curator.native_routes import NativeCuratorService, register_native_routes
from image_curator.native_settings import NativeCuratorSettings

root = Path(sys.argv[1])
settings = NativeCuratorSettings(
    batch_root=root / "batches",
    import_source=root / "output",
    state_file=root / "state.json",
)
(root / "batches").mkdir()
(root / "output").mkdir()
settings.available_models = ("vl-scorer",)
settings.default_model = "vl-scorer"

service = NativeCuratorService(settings)
lifecycle = NativeAiLifecycle(settings)
asyncio.run(lifecycle.startup(None))
try:
    app = web.Application()
    register_native_routes(app, service, lifecycle)
    register_native_ai_routes(app, service, lifecycle)
    registered = {
        route.get_info().get("path")
        for route in app.router.routes()
        if route.get_info().get("path")
    }
    assert "/api/curator/batches" in registered
    assert "/api/curator/ai-curate/jobs" in registered
finally:
    asyncio.run(lifecycle.shutdown(None))
    service.close()

loaded = sorted(
    name
    for name in sys.modules
    if name == "flask"
    or name.startswith("flask.")
    or name == "werkzeug"
    or name.startswith("werkzeug.")
)
assert loaded == [], f"native imports loaded removed web-stack modules: {loaded}"

for blocked in ("flask", "werkzeug"):
    try:
        __import__(blocked)
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError(f"import blocker did not block {blocked}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
