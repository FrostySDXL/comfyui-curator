"""Shared test fixtures.

The HTTP fixtures start the real native aiohttp adapter on an ephemeral
loopback port. Tests talk to it with a small synchronous urllib client so the
filesystem/API workflow layer still exercises real HTTP without Flask.
"""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import sys as _sys
import types as _types


def _import_real_native_modules():
    """Import native adapters against real aiohttp, not a leaked test mock.

    Earlier tests replace ``sys.modules["aiohttp"]`` with MagicMock hosts. If
    those mocks leak, the adapter module keeps a mock ``web`` and real HTTP
    handlers return SimpleNamespace objects. Drop any non-module or mocked
    entries and import the real modules for the HTTP fixtures.
    """
    for key in ("aiohttp", "aiohttp.web"):
        module = _sys.modules.get(key)
        if module is not None and not isinstance(module, _types.ModuleType):
            _sys.modules.pop(key, None)
    import image_curator as _package

    for name in ("native_routes", "native_ai_routes"):
        key = f"image_curator.{name}"
        module = _sys.modules.get(key)
        if module is not None and not isinstance(getattr(module, "web", None), _types.ModuleType):
            _sys.modules.pop(key, None)
        # Popping sys.modules does not clear the parent-package attribute; a
        # stale mocked submodule would otherwise be returned by ``from ...``.
        if hasattr(_package, name):
            delattr(_package, name)
    from aiohttp import web as _real_web  # noqa: F401 - ensure aiohttp.web is loaded
    from image_curator import native_ai_routes, native_routes

    return native_routes, native_ai_routes


import pytest

# Tests must be hermetic: never read the operator's .env or inherit live
# IMAGE_CURATOR_* configuration from the shell that launched pytest.
import os as _os

for _key in tuple(_os.environ):
    if _key.startswith("IMAGE_CURATOR_"):
        _os.environ.pop(_key, None)
try:
    import dotenv as _dotenv
except ImportError:  # pragma: no cover - dotenv is a CLI/test dependency
    pass
else:
    _dotenv.load_dotenv = lambda *args, **kwargs: False

from image_curator import batch_store
from image_curator.native_settings import NativeCuratorSettings


class _Response:
    """Minimal Flask-test-client-compatible response over real HTTP."""

    def __init__(self, status_code: int, data: bytes, headers) -> None:
        self.status_code = status_code
        self.data = data
        self.headers = headers

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")

    @property
    def mimetype(self) -> str:
        return (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()

    @property
    def json(self):
        return json.loads(self.text)

    def get_json(self):
        return self.json

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<_Response {self.status_code} {self.mimetype}>"


class _SyncClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body=None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        query_string=None,
        timeout: float = 15.0,
    ) -> _Response:
        url = self.base_url + path
        if query_string:
            pairs = query_string.items() if isinstance(query_string, dict) else query_string
            encoded = urllib.parse.urlencode(list(pairs), doseq=True)
            url += ("&" if "?" in url else "?") + encoded
        request_headers = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method.upper()
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return _Response(response.status, response.read(), response.headers)
        except urllib.error.HTTPError as exc:
            return _Response(exc.code, exc.read(), exc.headers)

    def get(self, path: str, **kwargs) -> _Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> _Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> _Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> _Response:
        return self.request("DELETE", path, **kwargs)


class _ThreadedAiohttpServer:
    """Run a real aiohttp application on an ephemeral loopback port."""

    def __init__(self, app) -> None:
        self.app = app
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.port: int | None = None
        self.error: BaseException | None = None
        self._stop: asyncio.Event | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> str:
        self.thread.start()
        if not self.ready.wait(15):
            raise RuntimeError("native aiohttp test server did not start")
        if self.error is not None:
            raise self.error
        assert self.port is not None
        return f"http://127.0.0.1:{self.port}"

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        except BaseException as exc:  # pragma: no cover - startup diagnostics
            self.error = exc
            self.ready.set()
        finally:
            self.loop.close()

    async def _serve(self) -> None:
        from aiohttp import web

        runner = web.AppRunner(self.app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sockets = getattr(site._server, "sockets", None) or ()
        if not sockets:  # pragma: no cover - platform guard
            raise RuntimeError("native aiohttp test server has no listening socket")
        self.port = sockets[0].getsockname()[1]
        self._stop = asyncio.Event()
        self.ready.set()
        await self._stop.wait()
        await runner.cleanup()

    def close(self) -> None:
        if self.thread.is_alive() and self._stop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)
        self.thread.join(15)


@pytest.fixture
def native_settings(tmp_path):
    batches = tmp_path / "batches"
    import_source = tmp_path / "comfyui-outputs"
    batches.mkdir()
    import_source.mkdir()
    return NativeCuratorSettings(
        batch_root=batches,
        import_source=import_source,
        state_file=tmp_path / "state.json",
    )


@pytest.fixture
def native_service(native_settings):
    pytest.importorskip("aiohttp")
    native_routes, _ = _import_real_native_modules()

    service = native_routes.NativeCuratorService(native_settings)
    yield service
    service.close()


@pytest.fixture
def client(native_settings, native_service):
    pytest.importorskip("aiohttp")
    from aiohttp import web

    native_routes, _ = _import_real_native_modules()

    app = web.Application()
    native_routes.register_native_routes(app, native_service)
    server = _ThreadedAiohttpServer(app)
    base_url = server.start()
    try:
        yield _SyncClient(base_url)
    finally:
        server.close()


@pytest.fixture
def ai_lifecycle(native_settings):
    from ai_curate.native_lifecycle import NativeAiLifecycle

    native_settings.available_models = ("vl-scorer",)
    native_settings.default_model = "vl-scorer"
    lifecycle = NativeAiLifecycle(native_settings)
    asyncio.run(lifecycle.startup(None))
    # Keep jobs deterministic: never start the real scoring thread.
    lifecycle._launch_worker = lambda run_id: None
    yield lifecycle
    asyncio.run(lifecycle.shutdown(None))


@pytest.fixture
def ai_client(native_settings, native_service, ai_lifecycle):
    pytest.importorskip("aiohttp")
    from aiohttp import web

    native_routes, native_ai_routes = _import_real_native_modules()

    batch_store.create_batch(native_settings.batch_root, "test-batch")
    app = web.Application()
    native_routes.register_native_routes(app, native_service, ai_lifecycle)
    native_ai_routes.register_native_ai_routes(app, native_service, ai_lifecycle)
    server = _ThreadedAiohttpServer(app)
    base_url = server.start()
    try:
        yield _SyncClient(base_url)
    finally:
        server.close()


@pytest.fixture
def sample_image_names():
    return ["img_b.png", "img_a.png", "preview.webp"]


def _touch(path: Path, content: bytes = b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@pytest.fixture
def make_file():
    return _touch


@pytest.fixture
def create_batch(native_settings):
    def _create(name: str) -> Path:
        created = batch_store.create_batch(native_settings.batch_root, name)
        assert created is True
        return native_settings.batch_root / name

    return _create
