"""Smoke the native adapter with real aiohttp when the host dependency is installed."""

import importlib.util
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("aiohttp") is None, reason="aiohttp not installed")
def test_real_aiohttp_native_status_and_shutdown(tmp_path):
    script = r"""
import asyncio
import json
import sys
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from image_curator.native_routes import NativeCuratorService, register_native_routes
from image_curator.native_settings import NativeCuratorSettings

async def main():
    root = Path(sys.argv[1])
    output = root / "output"
    output.mkdir()
    service = NativeCuratorService(NativeCuratorSettings(
        batch_root=root / "batches", import_source=output, state_file=root / "state.json"))
    app = web.Application()
    register_native_routes(app, service)
    request = make_mocked_request("GET", "/api/curator/import-status", app=app)
    match = await app.router.resolve(request)
    response = await match.handler(request)
    payload = json.loads(response.text)
    assert payload["auto_import_enabled"] is False
    assert payload["pending_count"] == 0
    service.close()

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
