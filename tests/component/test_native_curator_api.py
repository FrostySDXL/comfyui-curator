import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from image_curator.native_settings import NativeCuratorSettings

pytestmark = pytest.mark.component


REPO_ROOT = Path(__file__).resolve().parents[2]


class _Router:
    def __init__(self):
        self.handlers = {}

    def add_get(self, path, handler):
        self.handlers[("GET", path)] = handler

    def add_post(self, path, handler):
        self.handlers[("POST", path)] = handler


class _Request:
    def __init__(self, payload=None):
        self._payload = payload
        self.match_info = {}
        self.query = {}

    async def json(self):
        return self._payload


def _load_native_routes(monkeypatch):
    mock_web = MagicMock()
    mock_web.json_response.side_effect = lambda data, status=200: SimpleNamespace(
        status=status, text=json.dumps(data), headers={}
    )
    mock_web.FileResponse.side_effect = lambda path, **kwargs: SimpleNamespace(
        status=200, path=Path(path), headers=dict(kwargs.get("headers", {}))
    )
    mock_aiohttp = MagicMock(web=mock_web)
    monkeypatch.setitem(sys.modules, "aiohttp", mock_aiohttp)
    monkeypatch.setitem(sys.modules, "aiohttp.web", mock_web)
    path = REPO_ROOT / "image_curator" / "native_routes.py"
    spec = importlib.util.spec_from_file_location("image_curator.native_routes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _invoke(router, method, path, payload=None, match_info=None, query=None):
    request = _Request(payload)
    request.match_info = match_info or {}
    request.query = query or {}
    response = await router.handlers[(method, path)](request)
    return response.status, json.loads(response.text)


async def _invoke_response(router, method, path, match_info):
    request = _Request()
    request.match_info = match_info
    return await router.handlers[(method, path)](request)


def _symlink_directory_or_skip(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlink unavailable on this platform or permission set: {exc}")


def _editable_request(settings, **changes):
    payload = {
        "batch_root": str(settings.batch_root),
        "import_source": str(settings.import_source),
        "public_export_enabled": settings.public_export_root is not None,
        "public_export_root": str(settings.public_export_root or ""),
        "llm_base_url": settings.llm_base_url,
        "models": list(settings.available_models),
        "default_model": settings.default_model,
        "api_key": "",
        "clear_api_key": False,
        "request_timeout": settings.request_timeout,
    }
    payload.update(changes)
    return payload


def test_native_settings_and_batch_state_contracts(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            available_models=("vision",),
            default_model="vision",
        )
        router = _Router()
        app = SimpleNamespace(router=router)
        native_routes.register_native_routes(app, native_routes.NativeCuratorService(settings))

        status, payload = await _invoke(router, "GET", "/api/curator/settings")
        assert status == 200
        assert payload == {
            "batch_root": str(settings.batch_root),
            "import_source": str(settings.import_source),
            "public_export_enabled": False,
            "public_export_root": "",
            "llm_base_url": "http://localhost:8080",
            "models": ["vision"],
            "default_model": "vision",
            "ai_api_key_set": False,
            "request_timeout": 120,
            "config_error": False,
        }

        status, payload = await _invoke(router, "POST", "/api/curator/batches", {"name": "alpha"})
        assert status == 200
        assert payload == {"success": True}

        status, payload = await _invoke(
            router, "POST", "/api/curator/active-batch", {"batch": "alpha"}
        )
        assert status == 200
        assert payload == {"success": True}

        status, payload = await _invoke(router, "GET", "/api/curator/batches")
        assert status == 200
        assert payload["batches"] == ["alpha"]
        assert payload["active_batch"] == "alpha"
        assert payload["counts"]["alpha"] == {
            "inbox": 0,
            "shortlisted": 0,
            "finals": 0,
            "rejects": 0,
        }
        assert payload["batch_meta"]["alpha"]["modified_at"] > 0
        assert payload["pending_count"] == 0

    asyncio.run(scenario())


def test_native_settings_post_updates_secret_without_echo_and_supports_clear(tmp_path, monkeypatch):
    async def scenario():
        from image_curator.native_settings import NativeConfigStore

        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=(tmp_path / "batches").resolve(),
            import_source=(tmp_path / "output").resolve(),
            state_file=tmp_path / "state.json",
            api_key="old-secret",
            config_store=NativeConfigStore(tmp_path / "system"),
        )
        lifecycle = SimpleNamespace(update_settings=settings.update)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings), lifecycle
        )
        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/settings",
            {
                "batch_root": str((tmp_path / "new-batches").resolve()),
                "import_source": str((tmp_path / "new-output").resolve()),
                "public_export_enabled": False,
                "public_export_root": "",
                "llm_base_url": "http://localhost:9999",
                "models": [" a ", "a", "b"],
                "default_model": "b",
                "api_key": "replacement-secret",
                "clear_api_key": False,
                "request_timeout": 30,
            },
        )
        assert status == 200
        assert payload["ai_api_key_set"] is True
        assert "replacement-secret" not in json.dumps(payload)
        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/settings",
            _editable_request(settings, models=["a", "b"], clear_api_key=True),
        )
        assert status == 200
        assert payload["ai_api_key_set"] is False

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["ai_api_key_set", "config_error"])
def test_native_settings_post_rejects_read_only_response_fields(tmp_path, monkeypatch, field):
    async def scenario():
        from image_curator.native_settings import NativeConfigStore

        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            config_store=NativeConfigStore(tmp_path / "system"),
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/settings",
            _editable_request(settings, **{field: False}),
        )

        assert status == 400
        assert payload == {"error": "Unknown settings field"}
        assert not settings.config_store.path.exists()

    asyncio.run(scenario())


def test_native_settings_conflict_maps_to_409(tmp_path, monkeypatch):
    """A SettingsConflictError from lifecycle.update_settings maps to 409."""
    from image_curator.native_settings import (
        NativeConfigStore,
        NativeCuratorSettings,
        SettingsConflictError,
    )

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=(tmp_path / "batches").resolve(),
            import_source=(tmp_path / "output").resolve(),
            state_file=tmp_path / "state.json",
            config_store=NativeConfigStore(tmp_path / "system"),
        )

        def _conflict_update(data):
            raise SettingsConflictError("AI work is active")

        lifecycle = SimpleNamespace(update_settings=_conflict_update)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router),
            native_routes.NativeCuratorService(settings),
            lifecycle,
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/settings",
            {
                "batch_root": str((tmp_path / "new-batches").resolve()),
                "import_source": str((tmp_path / "new-output").resolve()),
                "public_export_enabled": False,
                "public_export_root": "",
                "llm_base_url": "http://localhost:9999",
                "models": ["a"],
                "default_model": "a",
                "api_key": "",
                "clear_api_key": False,
                "request_timeout": 30,
            },
        )
        assert status == 409
        assert payload == {"error": "Settings cannot change while AI work is active"}

    asyncio.run(scenario())


def test_native_settings_unexpected_runtime_error_maps_to_500(tmp_path, monkeypatch):
    """A generic RuntimeError from lifecycle.update_settings maps to 500,
    NOT to 409 (only SettingsConflictError gets 409)."""
    from image_curator.native_settings import NativeConfigStore, NativeCuratorSettings

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=(tmp_path / "batches").resolve(),
            import_source=(tmp_path / "output").resolve(),
            state_file=tmp_path / "state.json",
            config_store=NativeConfigStore(tmp_path / "system"),
        )

        def _unexpected_error(data):
            raise RuntimeError("something unexpected broke")

        lifecycle = SimpleNamespace(update_settings=_unexpected_error)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router),
            native_routes.NativeCuratorService(settings),
            lifecycle,
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/settings",
            {
                "batch_root": str((tmp_path / "new-batches").resolve()),
                "import_source": str((tmp_path / "new-output").resolve()),
                "public_export_enabled": False,
                "public_export_root": "",
                "llm_base_url": "http://localhost:9999",
                "models": ["a"],
                "default_model": "a",
                "api_key": "",
                "clear_api_key": False,
                "request_timeout": 30,
            },
        )
        assert status == 500
        assert "Could not update settings" in payload.get("error", "")

    asyncio.run(scenario())


def test_native_metadata_and_media_contracts_enforce_boundaries(tmp_path, monkeypatch):
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        image_path = settings.batch_root / "alpha" / "inbox" / "sample.png"
        png_info = PngInfo()
        png_info.add_text("parameters", "prompt text\nSteps: 12, Seed: 7")
        Image.new("RGB", (4, 4), color="blue").save(image_path, pnginfo=png_info)
        public_dir = settings.batch_root / "alpha" / "public"
        public_dir.mkdir()
        public_path = public_dir / "posted.jpg"
        Image.new("RGB", (4, 4), color="red").save(public_path)
        (settings.batch_root / "alpha" / "inbox" / "notes.txt").write_text(
            "private", encoding="utf-8"
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        metadata_route = "/api/curator/image-metadata/{batch}/{folder}/{name}"
        status, payload = await _invoke(
            router,
            "GET",
            metadata_route,
            match_info={"batch": "alpha", "folder": "inbox", "name": "sample.png"},
        )
        assert status == 200
        assert payload["has_metadata"] is True
        assert payload["parameters"]["prompt"] == "prompt text"

        image_response = await _invoke_response(
            router,
            "GET",
            "/curator/image/{batch}/{folder}/{name}",
            {"batch": "alpha", "folder": "public", "name": "posted.jpg"},
        )
        assert image_response.path == public_path.resolve()
        assert image_response.headers["Cache-Control"] == "public, max-age=3600, immutable"

        thumb_response = await _invoke_response(
            router,
            "GET",
            "/curator/thumb/{batch}/{folder}/{name}",
            {"batch": "alpha", "folder": "inbox", "name": "sample.png"},
        )
        assert thumb_response.path.name == "inbox__sample.webp"
        assert thumb_response.headers == {
            "Content-Type": "image/webp",
            "Cache-Control": "public, max-age=3600, immutable",
        }

        for match_info, expected in (
            (
                {"batch": "alpha", "folder": "inbox", "name": "..\\sample.png"},
                (400, {"error": "Invalid path"}),
            ),
            (
                {"batch": "alpha", "folder": "inbox", "name": "notes.txt"},
                (400, {"error": "Invalid file type"}),
            ),
            (
                {"batch": "alpha", "folder": "unknown", "name": "sample.png"},
                (400, {"error": "Invalid folder"}),
            ),
            (
                {"batch": "alpha", "folder": "inbox", "name": "missing.png"},
                (404, {"error": "File not found"}),
            ),
        ):
            assert await _invoke(router, "GET", metadata_route, match_info=match_info) == expected

    asyncio.run(scenario())


def test_native_media_rejects_symlinked_review_folder(tmp_path, monkeypatch):
    from PIL import Image

    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        outside = tmp_path / "outside"
        outside.mkdir()
        Image.new("RGB", (2, 2), color="red").save(outside / "outside.png")
        inbox = settings.batch_root / "alpha" / "inbox"
        inbox.rmdir()
        _symlink_directory_or_skip(inbox, outside)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "GET",
            "/api/curator/image-metadata/{batch}/{folder}/{name}",
            match_info={"batch": "alpha", "folder": "inbox", "name": "outside.png"},
        ) == (400, {"error": "Invalid path"})

    asyncio.run(scenario())


def test_native_service_rejects_content_directory_resolved_outside_root(tmp_path, monkeypatch):
    native_routes = _load_native_routes(monkeypatch)
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
    )
    batch = settings.batch_root / "alpha"
    inbox = batch / "inbox"
    outside = tmp_path / "outside"
    inbox.mkdir(parents=True)
    outside.mkdir()
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == inbox:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    service = native_routes.NativeCuratorService(settings)

    with pytest.raises(ValueError, match="Invalid path"):
        service.resolve_content_directory("alpha", "inbox")


def test_native_listing_and_direct_source_entry_use_real_content_boundary(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        source = inbox / "sample.png"
        source.write_bytes(b"image")
        outside = tmp_path / "outside"
        outside.mkdir()
        real_resolve = Path.resolve
        real_is_symlink = Path.is_symlink

        def resolve(path, *args, **kwargs):
            if path == inbox:
                return outside
            return real_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )
        assert await _invoke(
            router,
            "GET",
            "/api/curator/images/{batch}/{folder}",
            match_info={"batch": "alpha", "folder": "inbox"},
        ) == (400, {"error": "Invalid path"})

        monkeypatch.setattr(Path, "resolve", real_resolve)
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda path: True if path == source else real_is_symlink(path),
        )
        assert await _invoke(
            router,
            "GET",
            "/api/curator/image-metadata/{batch}/{folder}/{name}",
            match_info={"batch": "alpha", "folder": "inbox", "name": "sample.png"},
        ) == (400, {"error": "Invalid path"})

    asyncio.run(scenario())


def test_native_media_rejects_public_directory_resolved_outside_root(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        public = settings.batch_root / "alpha" / "public"
        public.mkdir()
        outside = tmp_path / "outside-public"
        outside.mkdir()
        (outside / "posted.png").write_bytes(b"outside")
        real_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == public:
                return outside
            return real_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "GET",
            "/api/curator/image-metadata/{batch}/{folder}/{name}",
            match_info={"batch": "alpha", "folder": "public", "name": "posted.png"},
        ) == (400, {"error": "Invalid path"})

    asyncio.run(scenario())


def test_native_media_rejects_symlinked_public_folder(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        outside = tmp_path / "outside-public"
        outside.mkdir()
        (outside / "posted.png").write_bytes(b"outside")
        public = settings.batch_root / "alpha" / "public"
        _symlink_directory_or_skip(public, outside)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "GET",
            "/api/curator/image-metadata/{batch}/{folder}/{name}",
            match_info={"batch": "alpha", "folder": "public", "name": "posted.png"},
        ) == (400, {"error": "Invalid path"})

    asyncio.run(scenario())


def test_native_service_rejects_thumbnail_cache_resolved_outside_batch(tmp_path, monkeypatch):
    from image_curator import batch_store

    native_routes = _load_native_routes(monkeypatch)
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
    )
    batch_store.create_batch(settings.batch_root, "alpha")
    thumbs = settings.batch_root / "alpha" / ".thumbs"
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == thumbs or path.parent == thumbs:
            return outside / path.name if path != thumbs else outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    service = native_routes.NativeCuratorService(settings)

    with pytest.raises(ValueError, match="Invalid thumbnail cache path"):
        service.resolve_thumbnail_cache("alpha", "inbox", "sample.png")


def test_native_thumbnail_rejects_symlinked_cache_without_external_write(tmp_path, monkeypatch):
    from PIL import Image

    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        source = settings.batch_root / "alpha" / "inbox" / "sample.png"
        Image.new("RGB", (2, 2), color="blue").save(source)
        outside = tmp_path / "outside-cache"
        outside.mkdir()
        thumbs = settings.batch_root / "alpha" / ".thumbs"
        _symlink_directory_or_skip(thumbs, outside)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "GET",
            "/curator/thumb/{batch}/{folder}/{name}",
            match_info={"batch": "alpha", "folder": "inbox", "name": "sample.png"},
        ) == (400, {"error": "Invalid thumbnail cache path"})
        assert list(outside.iterdir()) == []

    asyncio.run(scenario())


def test_native_batch_writes_reject_non_string_json_values(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        batch_store.save_state(settings.state_file, {"active_batch": "alpha"})
        settings.import_source.mkdir()
        (settings.import_source / "pending.png").write_bytes(b"pending")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        malformed_values = (None, [], {}, 1, True)
        for value in malformed_values:
            assert await _invoke(router, "POST", "/api/curator/batches", {"name": value}) == (
                400,
                {"error": "Invalid batch name"},
            )
            assert await _invoke(router, "POST", "/api/curator/active-batch", {"batch": value}) == (
                400,
                {"error": "Invalid batch name"},
            )
            assert await _invoke(router, "POST", "/api/curator/import-all", {"batch": value}) == (
                400,
                {"error": "Invalid batch name"},
            )

        assert batch_store.get_batches(settings.batch_root) == ["alpha"]
        assert batch_store.load_state(settings.state_file) == {"active_batch": "alpha"}
        assert (settings.import_source / "pending.png").read_bytes() == b"pending"

    asyncio.run(scenario())


def test_native_images_contract_sorting_and_validation(tmp_path, monkeypatch):
    from image_curator import batch_store
    from image_curator.favorites import toggle_favorite

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        (inbox / "b.png").write_bytes(b"bb")
        (inbox / "a.jpg").write_bytes(b"a")
        (inbox / "ignored.txt").write_text("no", encoding="utf-8")
        toggle_favorite(settings.batch_root, "alpha", "a.jpg")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        route = "/api/curator/images/{batch}/{folder}"
        status, payload = await _invoke(
            router,
            "GET",
            route,
            match_info={"batch": "alpha", "folder": "inbox"},
            query={"sort": "name", "order": "asc"},
        )
        assert status == 200
        assert payload == [
            {"name": "a.jpg", "size": 1, "favorite": True},
            {"name": "b.png", "size": 2, "favorite": False},
        ]

        status, payload = await _invoke(
            router,
            "GET",
            route,
            match_info={"batch": "missing", "folder": "inbox"},
        )
        assert (status, payload) == (404, {"error": "Batch does not exist"})

        status, payload = await _invoke(
            router,
            "GET",
            route,
            match_info={"batch": "alpha", "folder": "public"},
        )
        assert (status, payload) == (400, {"error": "Invalid folder"})

    asyncio.run(scenario())


def test_native_images_excludes_symlink_entry_without_stat(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        linked = settings.batch_root / "alpha" / "inbox" / "linked.png"
        linked.write_bytes(b"linked")
        monkeypatch.setattr(
            native_routes.batch_store, "get_images", lambda *_args, **_kwargs: [linked]
        )
        real_is_symlink = Path.is_symlink
        real_stat = Path.stat
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda path: True if path == linked else real_is_symlink(path),
        )

        def stat(path, *args, **kwargs):
            if path == linked:
                raise AssertionError("native listing must not stat a symlink entry")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "GET",
            "/api/curator/images/{batch}/{folder}",
            match_info={"batch": "alpha", "folder": "inbox"},
        ) == (200, [])

    asyncio.run(scenario())


def test_native_import_all_contract_uses_configured_source(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        settings.import_source.mkdir()
        (settings.import_source / "one.png").write_bytes(b"one")
        (settings.import_source / "skip.txt").write_bytes(b"skip")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        route = "/api/curator/import-all"
        assert await _invoke(router, "POST", route, {"batch": ""}) == (
            400,
            {"error": "Batch required"},
        )
        assert await _invoke(router, "POST", route, {"batch": "missing"}) == (
            404,
            {"error": "Batch does not exist"},
        )
        assert await _invoke(router, "POST", route, {"batch": "alpha"}) == (
            200,
            {"success": True, "count": 1},
        )
        assert (settings.batch_root / "alpha" / "inbox" / "one.png").read_bytes() == b"one"
        assert (settings.import_source / "skip.txt").exists()

    asyncio.run(scenario())


def test_native_import_rejects_inbox_resolved_outside_root_before_mutation(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        settings.import_source.mkdir()
        pending = settings.import_source / "pending.png"
        pending.write_bytes(b"pending")
        inbox = settings.batch_root / "alpha" / "inbox"
        outside = tmp_path / "outside-import"
        outside.mkdir()
        real_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == inbox:
                return outside
            return real_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(router, "POST", "/api/curator/import-all", {"batch": "alpha"}) == (
            400,
            {"error": "Invalid import destination"},
        )
        assert pending.read_bytes() == b"pending"
        assert list(outside.iterdir()) == []

    asyncio.run(scenario())


def test_native_routes_reject_enumerated_batch_without_safe_root_directory(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        settings.batch_root.mkdir()
        monkeypatch.setattr(native_routes.batch_store, "get_batches", lambda _root: ["linked"])
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "GET",
            "/api/curator/images/{batch}/{folder}",
            match_info={"batch": "linked", "folder": "inbox"},
        ) == (404, {"error": "Batch does not exist"})

    asyncio.run(scenario())


def test_native_batch_summary_excludes_batch_with_unsafe_stage_before_helpers(
    tmp_path, monkeypatch
):
    from image_curator import batch_store

    native_routes = _load_native_routes(monkeypatch)
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
    )
    batch_store.create_batch(settings.batch_root, "alpha")
    unsafe_stage = settings.batch_root / "alpha" / "shortlisted"
    outside = tmp_path / "outside-summary"
    outside.mkdir()
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == unsafe_stage:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(
        native_routes.batch_store,
        "get_batch_counts",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unsafe count traversal")),
    )
    monkeypatch.setattr(
        native_routes.batch_store,
        "get_batch_metadata",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unsafe metadata traversal")),
    )

    payload = native_routes.NativeCuratorService(settings).batches_payload()

    assert payload["batches"] == []
    assert payload["counts"] == {}
    assert payload["batch_meta"] == {}


def test_native_batch_summary_excludes_batch_with_non_directory_ai_curate(tmp_path, monkeypatch):
    """batch_summary_safe returns False when <batch>/ai-curate exists
    but is not a real directory (e.g. a regular file)."""
    from image_curator import batch_store

    native_routes = _load_native_routes(monkeypatch)
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
    )
    batch_store.create_batch(settings.batch_root, "alpha")
    ai_curate = settings.batch_root / "alpha" / "ai-curate"
    ai_curate.write_text("not-a-directory", encoding="utf-8")
    monkeypatch.setattr(
        native_routes.batch_store,
        "get_batch_counts",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unsafe count traversal")),
    )
    monkeypatch.setattr(
        native_routes.batch_store,
        "get_batch_metadata",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unsafe metadata traversal")),
    )

    payload = native_routes.NativeCuratorService(settings).batches_payload()

    assert payload["batches"] == []
    assert payload["counts"] == {}
    assert payload["batch_meta"] == {}


# ---------------------------------------------------------------------------
# Native move / delete-rejects mutations
# ---------------------------------------------------------------------------


def test_native_move_moves_single_file(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        source_path = settings.batch_root / "alpha" / "inbox" / "pic.png"
        source_path.write_bytes(b"image-data")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/move",
            {
                "batch": "alpha",
                "filename": "pic.png",
                "source": "inbox",
                "destination": "shortlisted",
            },
        )
        assert status == 200
        assert payload == {"success": True}
        assert not (settings.batch_root / "alpha" / "inbox" / "pic.png").exists()
        assert (
            settings.batch_root / "alpha" / "shortlisted" / "pic.png"
        ).read_bytes() == b"image-data"

    asyncio.run(scenario())


def test_native_move_nonexistent_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "POST",
            "/api/curator/move",
            {
                "batch": "nope",
                "filename": "pic.png",
                "source": "inbox",
                "destination": "shortlisted",
            },
        ) == (404, {"error": "Batch does not exist"})

    asyncio.run(scenario())


def test_native_move_missing_params(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        missing_combos = [
            {"batch": "alpha"},
            {"batch": "alpha", "filename": "pic.png"},
        ]
        for payload in missing_combos:
            assert await _invoke(router, "POST", "/api/curator/move", payload) == (
                400,
                {"error": "Missing parameters"},
            )

    asyncio.run(scenario())


def test_native_move_invalid_source_or_dest_folder(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        source_path = settings.batch_root / "alpha" / "inbox" / "pic.png"
        source_path.write_bytes(b"image-data")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        invalid_combos = [
            ("inbox", "public"),
            ("unknown", "inbox"),
            ("inbox", "unknown"),
        ]
        for src, dst in invalid_combos:
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/move",
                {"batch": "alpha", "filename": "pic.png", "source": src, "destination": dst},
            )
            assert status == 400
            assert "Invalid" in payload["error"]

    asyncio.run(scenario())


def test_native_move_missing_file(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "POST",
            "/api/curator/move",
            {
                "batch": "alpha",
                "filename": "ghost.png",
                "source": "inbox",
                "destination": "shortlisted",
            },
        ) == (404, {"error": "File not found"})

    asyncio.run(scenario())


def test_native_move_rejects_malformed_types(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        base = {
            "batch": "alpha",
            "filename": "pic.png",
            "source": "inbox",
            "destination": "shortlisted",
        }
        for key in ("batch", "filename", "source", "destination"):
            for bad_value in (None, [], {}, 1, True):
                payload = dict(base)
                payload[key] = bad_value
                status, payload_result = await _invoke(router, "POST", "/api/curator/move", payload)
                assert status == 400, f"expected 400 for key={key} value={bad_value!r}"
                assert "Missing parameters" in payload_result["error"]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Native move-batch
# ---------------------------------------------------------------------------


def test_native_move_batch_bulk_moves_files(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        (inbox / "one.png").write_bytes(b"one")
        (inbox / "two.jpg").write_bytes(b"two")
        (inbox / "ignore.txt").write_text("no", encoding="utf-8")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/move-batch",
            {
                "batch": "alpha",
                "filenames": ["one.png", "two.jpg", "ignore.txt"],
                "source": "inbox",
                "destination": "finals",
            },
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["moved"] == 3
        assert payload["skipped"] == 0
        assert not (inbox / "one.png").exists()
        assert not (inbox / "two.jpg").exists()
        assert not (inbox / "ignore.txt").exists()
        assert (settings.batch_root / "alpha" / "finals" / "one.png").read_bytes() == b"one"
        assert (settings.batch_root / "alpha" / "finals" / "two.jpg").read_bytes() == b"two"

    asyncio.run(scenario())


def test_native_move_batch_nonexistent_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "POST",
            "/api/curator/move-batch",
            {
                "batch": "nope",
                "filenames": ["pic.png"],
                "source": "inbox",
                "destination": "shortlisted",
            },
        ) == (404, {"error": "Batch does not exist"})

    asyncio.run(scenario())


def test_native_move_batch_missing_params(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "POST",
            "/api/curator/move-batch",
            {"batch": "alpha"},
        ) == (400, {"error": "Missing parameters"})

    asyncio.run(scenario())


def test_native_move_batch_all_skipped_returns_success_false(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/move-batch",
            {
                "batch": "alpha",
                "filenames": ["ghost.png"],
                "source": "inbox",
                "destination": "finals",
            },
        )
        assert status == 200
        assert payload["success"] is False
        assert payload["moved"] == 0
        assert payload["skipped"] >= 1

    asyncio.run(scenario())


def test_native_move_batch_rejects_non_list_filenames(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for bad_filenames in ("not-a-list", None, 42, True, {}):
            assert await _invoke(
                router,
                "POST",
                "/api/curator/move-batch",
                {
                    "batch": "alpha",
                    "filenames": bad_filenames,
                    "source": "inbox",
                    "destination": "shortlisted",
                },
            ) == (400, {"error": "Missing parameters"})

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Native delete-rejects
# ---------------------------------------------------------------------------


def test_native_delete_rejects_removes_files_and_thumbnail_cache(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        rejects_dir = settings.batch_root / "alpha" / "rejects"
        bad = rejects_dir / "bad.png"
        bad.write_bytes(b"bad-image")

        # Create a matching thumbnail cache entry
        from image_curator.media import thumbnail_cache_path

        cache = thumbnail_cache_path(settings.batch_root, "alpha", "rejects", "bad.png")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(b"cached-thumb")

        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/delete-rejects/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["count"] == 1
        assert not bad.exists()
        assert not cache.exists()

    asyncio.run(scenario())


def test_native_get_batch_favorites_returns_sorted_filenames(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "b.png").write_bytes(b"bb")
        (inbox / "a.jpg").write_bytes(b"a")
        # Pre-populate batch favorites via shared helper
        from image_curator.favorites import save_favorites

        save_favorites(settings.batch_root, ["b.png", "a.jpg"], "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/favorites/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload == {"filenames": ["a.jpg", "b.png"]}

    asyncio.run(scenario())


def test_native_post_batch_favorite_toggles_both_scopes(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "one.png").write_bytes(b"xx")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        # Toggle ON
        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/favorites/{batch}",
            {"filename": "one.png"},
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload == {"batch": True, "universal": True}

        # Verify batch favorites list reflects the toggle
        status, get_payload = await _invoke(
            router,
            "GET",
            "/api/curator/favorites/{batch}",
            match_info={"batch": "alpha"},
        )
        assert get_payload == {"filenames": ["one.png"]}

        # Toggle OFF
        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/favorites/{batch}",
            {"filename": "one.png"},
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload == {"batch": False, "universal": False}

        # Verify batch favorites list is empty
        status, get_payload = await _invoke(
            router,
            "GET",
            "/api/curator/favorites/{batch}",
            match_info={"batch": "alpha"},
        )
        assert get_payload == {"filenames": []}

    asyncio.run(scenario())


def test_native_get_universal_favorites_resolves_existing_files(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        (settings.batch_root / "alpha" / "shortlisted" / "one.png").write_bytes(b"data")
        (settings.batch_root / "alpha" / "finals" / "two.jpg").write_bytes(b"12345")
        # Write universal favorites via toggles, which populates addedAt fields
        from image_curator.favorites import toggle_favorite as tf

        tf(settings.batch_root, "alpha", "one.png")
        tf(settings.batch_root, "alpha", "two.jpg")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(router, "GET", "/api/curator/favorites")
        assert status == 200
        favs = payload["favorites"]
        assert len(favs) == 2
        by_filename = {f["filename"]: f for f in favs}
        assert by_filename["one.png"]["batch"] == "alpha"
        assert by_filename["one.png"]["folder"] == "shortlisted"
        assert by_filename["one.png"]["size"] == 4
        assert by_filename["two.jpg"]["batch"] == "alpha"
        assert by_filename["two.jpg"]["folder"] == "finals"
        assert by_filename["two.jpg"]["size"] == 5

    asyncio.run(scenario())


def test_native_post_universal_favorite_toggles_by_batch_and_filename(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "img.png").write_bytes(b"yy")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        # Toggle ON via universal endpoint
        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/favorites",
            {"batch": "alpha", "filename": "img.png"},
        )
        assert status == 200
        assert payload == {"batch": True, "universal": True}

        # Verify in universal list
        status, uni_payload = await _invoke(router, "GET", "/api/curator/favorites")
        assert len(uni_payload["favorites"]) == 1
        assert uni_payload["favorites"][0]["filename"] == "img.png"

        # Toggle OFF via universal endpoint
        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/favorites",
            {"batch": "alpha", "filename": "img.png"},
        )
        assert status == 200
        assert payload == {"batch": False, "universal": False}

        # Universal list empty
        status, uni_payload = await _invoke(router, "GET", "/api/curator/favorites")
        assert uni_payload["favorites"] == []

    asyncio.run(scenario())


def test_native_batch_favorites_rejects_nonexistent_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router, "GET", "/api/curator/favorites/{batch}", match_info={"batch": "nope"}
        ) == (404, {"error": "Batch does not exist"})

        assert await _invoke(
            router,
            "POST",
            "/api/curator/favorites/{batch}",
            {"filename": "x.png"},
            match_info={"batch": "nope"},
        ) == (404, {"error": "Batch does not exist"})

    asyncio.run(scenario())


def test_native_favorites_rejects_favorites_sentinel_as_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router, "GET", "/api/curator/favorites/{batch}", match_info={"batch": "__favorites__"}
        ) == (404, {"error": "Batch does not exist"})

        assert await _invoke(
            router,
            "POST",
            "/api/curator/favorites/{batch}",
            {"filename": "x.png"},
            match_info={"batch": "__favorites__"},
        ) == (404, {"error": "Batch does not exist"})

        assert await _invoke(
            router,
            "POST",
            "/api/curator/favorites",
            {"batch": "__favorites__", "filename": "x.png"},
        ) == (400, {"error": "Batch does not exist"})

    asyncio.run(scenario())


def test_native_favorites_rejects_malformed_field_types(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        # Malformed filename in batch-scoped POST
        for bad_filename in (None, [], {}, 1, True):
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/favorites/{batch}",
                {"filename": bad_filename},
                match_info={"batch": "alpha"},
            )
            assert status == 400, f"expected 400 for filename={bad_filename!r}"
            assert "filename required" in payload["error"]

        # Malformed batch in universal POST
        for bad_batch in (None, [], {}, 1, True):
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/favorites",
                {"batch": bad_batch, "filename": "x.png"},
            )
            assert status == 400, f"expected 400 for batch={bad_batch!r}"

        # Malformed filename in universal POST
        for bad_filename in (None, [], {}, 1, True):
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/favorites",
                {"batch": "alpha", "filename": bad_filename},
            )
            assert status == 400, f"expected 400 for filename={bad_filename!r}"
            assert "filename required" in payload["error"]

    asyncio.run(scenario())


def test_native_universal_favorites_skips_stale_missing_entries(tmp_path, monkeypatch):
    from image_curator import batch_store
    from image_curator.favorites import toggle_favorite as tf

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "present.png").write_bytes(b"here")
        tf(settings.batch_root, "alpha", "present.png")

        # Add a universal entry for a file that never existed
        from image_curator.favorites import load_favorites, save_favorites

        universal = load_favorites(settings.batch_root)
        universal.append({"batch": "alpha", "filename": "ghost.png", "added_at": "old"})
        save_favorites(settings.batch_root, universal)

        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(router, "GET", "/api/curator/favorites")
        assert status == 200
        favs = payload["favorites"]
        filenames = {f["filename"] for f in favs}
        assert "present.png" in filenames
        assert "ghost.png" not in filenames

    asyncio.run(scenario())


def test_native_delete_rejects_skips_cache_resolved_into_sibling_batch(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        batch_store.create_batch(settings.batch_root, "other")
        bad = settings.batch_root / "alpha" / "rejects" / "bad.png"
        bad.write_bytes(b"bad-image")
        thumbs_dir = settings.batch_root / "alpha" / ".thumbs"
        thumbs_dir.mkdir()
        cache_file = thumbs_dir / "rejects__bad.webp"
        cache_file.write_bytes(b"cache-data")
        other_thumbs = settings.batch_root / "other" / ".thumbs"
        other_thumbs.mkdir(parents=True)
        real_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == cache_file:
                return other_thumbs / "rejects__bad.webp"
            if path == cache_file.parent:
                return other_thumbs
            return real_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/delete-rejects/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["count"] == 1
        assert not bad.exists()
        assert cache_file.read_bytes() == b"cache-data"

    asyncio.run(scenario())


def test_native_delete_rejects_nonexistent_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        assert await _invoke(
            router,
            "POST",
            "/api/curator/delete-rejects/{batch}",
            match_info={"batch": "nope"},
        ) == (404, {"error": "Batch does not exist"})

    asyncio.run(scenario())


def test_native_delete_rejects_skips_symlinks(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        rejects_dir = settings.batch_root / "alpha" / "rejects"
        (rejects_dir / "normal.png").write_bytes(b"normal")
        outside = tmp_path / "outside-target"
        outside.mkdir()
        (outside / "outside.png").write_bytes(b"outside")
        linked = rejects_dir / "linked.png"
        _symlink_directory_or_skip(linked, outside / "outside.png")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/delete-rejects/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["count"] == 1
        assert not (rejects_dir / "normal.png").exists()
        assert (outside / "outside.png").exists()

    asyncio.run(scenario())


def test_native_move_rejects_symlink_source_and_leaves_target_untouched(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        src = settings.batch_root / "alpha" / "inbox" / "pic.png"
        src.write_bytes(b"image-data")
        real_is_symlink = Path.is_symlink

        def is_symlink(path, *args, **kwargs):
            if path == src:
                return True
            return real_is_symlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "is_symlink", is_symlink)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/move",
            {
                "batch": "alpha",
                "filename": "pic.png",
                "source": "inbox",
                "destination": "shortlisted",
            },
        )
        assert status == 400
        assert payload["error"] == "Invalid path"
        assert src.read_bytes() == b"image-data"
        assert not (settings.batch_root / "alpha" / "shortlisted" / "pic.png").exists()

    asyncio.run(scenario())


def test_native_move_rejects_non_regular_source(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        src = settings.batch_root / "alpha" / "inbox" / "subdir"
        src.mkdir()
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/move",
            {
                "batch": "alpha",
                "filename": "subdir",
                "source": "inbox",
                "destination": "shortlisted",
            },
        )
        assert status == 404
        assert payload["error"] == "File not found"
        assert src.is_dir()

    asyncio.run(scenario())


def test_native_move_rejects_symlink_destination_without_mutating_source(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        src = settings.batch_root / "alpha" / "inbox" / "pic.png"
        src.write_bytes(b"image-data")
        dst = settings.batch_root / "alpha" / "shortlisted" / "pic.png"
        dst.write_bytes(b"stale")
        real_is_symlink = Path.is_symlink

        def is_symlink(path, *args, **kwargs):
            if path == dst:
                return True
            return real_is_symlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "is_symlink", is_symlink)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/move",
            {
                "batch": "alpha",
                "filename": "pic.png",
                "source": "inbox",
                "destination": "shortlisted",
            },
        )
        assert status == 400
        assert payload["error"] == "Invalid path"
        assert src.exists()
        assert src.read_bytes() == b"image-data"

    asyncio.run(scenario())


def test_native_move_batch_skips_symlink_and_non_regular_sources(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        good = inbox / "ok.png"
        good.write_bytes(b"ok")
        bad_sym = inbox / "linked.png"
        bad_sym.write_bytes(b"sym-target")
        subdir = inbox / "adir"
        subdir.mkdir()
        real_is_symlink = Path.is_symlink

        def is_symlink(path, *args, **kwargs):
            if path == bad_sym:
                return True
            return real_is_symlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "is_symlink", is_symlink)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/move-batch",
            {
                "batch": "alpha",
                "filenames": ["ok.png", "linked.png", "adir"],
                "source": "inbox",
                "destination": "finals",
            },
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["moved"] == 1
        assert payload["skipped"] == 2
        assert not (inbox / "ok.png").exists()
        assert (settings.batch_root / "alpha" / "finals" / "ok.png").read_bytes() == b"ok"
        assert (inbox / "linked.png").read_bytes() == b"sym-target"
        assert subdir.is_dir()

    asyncio.run(scenario())


def test_native_delete_rejects_skips_cache_when_thumbs_is_symlink(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        rejects_dir = settings.batch_root / "alpha" / "rejects"
        bad = rejects_dir / "bad.png"
        bad.write_bytes(b"bad-image")
        thumbs_dir = settings.batch_root / "alpha" / ".thumbs"
        thumbs_dir.mkdir()
        cache_file = thumbs_dir / "rejects__bad.webp"
        cache_file.write_bytes(b"cache-data")
        real_is_symlink = Path.is_symlink

        def is_symlink(path, *args, **kwargs):
            if path == thumbs_dir:
                return True
            return real_is_symlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "is_symlink", is_symlink)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/delete-rejects/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["count"] == 1
        assert not bad.exists()
        assert cache_file.read_bytes() == b"cache-data"

    asyncio.run(scenario())


def test_native_delete_rejects_skips_cache_when_cache_file_is_symlink(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        rejects_dir = settings.batch_root / "alpha" / "rejects"
        bad = rejects_dir / "bad.png"
        bad.write_bytes(b"bad-image")
        thumbs_dir = settings.batch_root / "alpha" / ".thumbs"
        thumbs_dir.mkdir()
        cache_file = thumbs_dir / "rejects__bad.webp"
        cache_file.write_bytes(b"cache-data")
        real_is_symlink = Path.is_symlink

        def is_symlink(path, *args, **kwargs):
            if path == cache_file:
                return True
            return real_is_symlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "is_symlink", is_symlink)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/delete-rejects/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["count"] == 1
        assert not bad.exists()
        assert cache_file.read_bytes() == b"cache-data"

    asyncio.run(scenario())


def test_native_delete_rejects_skips_cache_when_resolved_outside_root(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        rejects_dir = settings.batch_root / "alpha" / "rejects"
        bad = rejects_dir / "bad.png"
        bad.write_bytes(b"bad-image")
        outside = tmp_path / "outside-cache"
        outside.mkdir()
        thumbs_dir = settings.batch_root / "alpha" / ".thumbs"
        thumbs_dir.mkdir()
        cache_file = thumbs_dir / "rejects__bad.webp"
        cache_file.write_bytes(b"cache-data")
        real_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == cache_file:
                return outside / "rejects__bad.webp"
            return real_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/delete-rejects/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload["success"] is True
        assert payload["count"] == 1
        assert not bad.exists()
        assert cache_file.read_bytes() == b"cache-data"

    asyncio.run(scenario())


def test_native_post_favorite_rejects_ghost_filename_no_mutation(tmp_path, monkeypatch):
    from image_curator import batch_store
    from image_curator.favorites import load_favorites

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        batch_store.save_state(settings.state_file, {"active_batch": "alpha"})
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/favorites/{batch}",
            {"filename": "ghost.png"},
            match_info={"batch": "alpha"},
        )
        assert status == 404
        assert "not found" in payload["error"].lower() or "file" in payload["error"].lower()
        assert load_favorites(settings.batch_root, "alpha") == []
        assert load_favorites(settings.batch_root) == []

    asyncio.run(scenario())


def test_native_post_favorite_rejects_unsupported_extension_no_mutation(tmp_path, monkeypatch):
    from image_curator import batch_store
    from image_curator.favorites import load_favorites

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        (settings.batch_root / "alpha" / "inbox" / "notes.txt").write_text("text", encoding="utf-8")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/favorites/{batch}",
            {"filename": "notes.txt"},
            match_info={"batch": "alpha"},
        )
        assert status == 400
        assert "file type" in payload["error"].lower()
        assert load_favorites(settings.batch_root, "alpha") == []

    asyncio.run(scenario())


def test_native_post_favorite_rejects_symlinked_file_no_mutation(tmp_path, monkeypatch):
    from pathlib import Path

    from image_curator import batch_store
    from image_curator.favorites import load_favorites

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        file_path = settings.batch_root / "alpha" / "inbox" / "pic.png"
        file_path.write_bytes(b"data")
        real_is_symlink = Path.is_symlink

        def is_symlink(path, *args, **kwargs):
            if path == file_path:
                return True
            return real_is_symlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "is_symlink", is_symlink)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/favorites/{batch}",
            {"filename": "pic.png"},
            match_info={"batch": "alpha"},
        )
        assert status == 404
        assert "not found" in payload["error"].lower()
        assert load_favorites(settings.batch_root, "alpha") == []
        assert load_favorites(settings.batch_root) == []

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Native public routes
# ---------------------------------------------------------------------------


def test_native_publish_export_creates_public_copy_and_preserves_original(tmp_path, monkeypatch):
    from PIL import Image
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        source = settings.batch_root / "alpha" / "finals" / "portrait.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (12, 8), color="blue").save(source)
        original_bytes = source.read_bytes()
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/publish/export",
            {
                "batch": "alpha",
                "folder": "finals",
                "filenames": ["portrait.png"],
                "strip_metadata": True,
                "watermark": {"enabled": False},
            },
        )
        assert status == 200
        assert payload["exported"] == 1
        assert payload["files"] == [{"source": "portrait.png", "output": "portrait-public.png"}]
        assert source.read_bytes() == original_bytes
        assert (settings.batch_root / "alpha" / "public" / "portrait-public.png").exists()

    asyncio.run(scenario())


def test_native_get_all_public_returns_wrapped_list(tmp_path, monkeypatch):
    from PIL import Image
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        batch_store.create_batch(settings.batch_root, "beta")
        (settings.batch_root / "alpha" / "public").mkdir(parents=True)
        (settings.batch_root / "beta" / "public").mkdir(parents=True)
        Image.new("RGB", (4, 4), color="red").save(
            settings.batch_root / "alpha" / "public" / "a-public.png"
        )
        Image.new("RGB", (4, 4), color="green").save(
            settings.batch_root / "beta" / "public" / "b-public.png"
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(router, "GET", "/api/curator/public")
        assert status == 200
        assert "public" in payload
        assert len(payload["public"]) == 2
        assert payload["public"][0]["batch"] == "alpha"
        assert payload["public"][0]["name"] == "a-public.png"
        assert payload["public"][1]["batch"] == "beta"
        assert payload["public"][1]["name"] == "b-public.png"

    asyncio.run(scenario())


def test_native_get_batch_public_returns_flat_array(tmp_path, monkeypatch):
    from PIL import Image
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        (settings.batch_root / "alpha" / "public").mkdir(parents=True)
        Image.new("RGB", (4, 4), color="red").save(
            settings.batch_root / "alpha" / "public" / "a-public.png"
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/public/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert isinstance(payload, list)
        assert payload[0]["name"] == "a-public.png"

    asyncio.run(scenario())


def test_native_public_batch_route_rejects_virtual_sentinels(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for sentinel in ("__public__", "__favorites__"):
            status, payload = await _invoke(
                router,
                "GET",
                "/api/curator/public/{batch}",
                match_info={"batch": sentinel},
            )
            assert status == 404, f"sentinel {sentinel} should be 404"
            assert (
                "not exist" in payload["error"].lower()
                or "does not exist" in payload["error"].lower()
            )

    asyncio.run(scenario())


def test_native_public_batch_route_rejects_nonexistent_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/public/{batch}",
            match_info={"batch": "nope"},
        )
        assert status == 404
        assert "does not exist" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_publish_export_rejects_non_list_filenames(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for bad_value in ("string", None, 42, True, {}):
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/publish/export",
                {"batch": "alpha", "folder": "finals", "filenames": bad_value},
            )
            assert status == 400
            assert "filenames" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_publish_export_rejects_non_string_filename_elements(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for bad_element in (None, 42, True, [], {}):
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/publish/export",
                {
                    "batch": "alpha",
                    "folder": "finals",
                    "filenames": ["valid.png", bad_element],
                },
            )
            assert status == 400, f"element={bad_element!r} got status {status}"
            assert (
                "filename" in str(payload).lower()
                or "filenames" in str(payload).lower()
                or "invalid" in str(payload).lower()
            )

    asyncio.run(scenario())


def test_native_public_destinations_route_returns_browser_payload(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        export_root.mkdir()
        (export_root / "posts" / "batch-b").mkdir(parents=True)
        (export_root / "posts" / "batch-a").mkdir(parents=True)
        (export_root / "posts" / "notes.txt").write_text("skip")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/public/destinations",
            query={"path": "posts"},
        )
        assert status == 200
        assert payload == {
            "path": "posts",
            "parent": "",
            "directories": [
                {"name": "batch-a", "path": "posts/batch-a"},
                {"name": "batch-b", "path": "posts/batch-b"},
            ],
        }

    asyncio.run(scenario())


def test_native_public_destinations_rejects_without_export_root(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(router, "GET", "/api/curator/public/destinations")
        assert status == 400
        assert "not configured" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_public_copy_route_copies_derivative(tmp_path, monkeypatch):
    from PIL import Image
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        (settings.batch_root / "alpha" / "public").mkdir(parents=True)
        (settings.batch_root / "alpha" / "finals" / "portrait.png").parent.mkdir(
            parents=True, exist_ok=True
        )
        Image.new("RGB", (4, 4), color="blue").save(
            settings.batch_root / "alpha" / "public" / "portrait-public.png"
        )
        Image.new("RGB", (4, 4), color="red").save(
            settings.batch_root / "alpha" / "finals" / "portrait.png"
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/public/copy",
            {
                "destination": str(export_root / "posting"),
                "items": [{"batch": "alpha", "filename": "portrait-public.png"}],
            },
        )
        assert status == 200
        assert payload["copied"] == 1
        assert (export_root / "posting" / "portrait-public.png").exists()
        assert (settings.batch_root / "alpha" / "finals" / "portrait.png").exists()

    asyncio.run(scenario())


def test_native_public_move_route_moves_derivative_only(tmp_path, monkeypatch):
    from PIL import Image
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        public_copy = settings.batch_root / "alpha" / "public" / "portrait-public.png"
        public_copy.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), color="blue").save(public_copy)
        original = settings.batch_root / "alpha" / "finals" / "portrait.png"
        original.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), color="red").save(original)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/public/move",
            {
                "destination": str(export_root / "posting"),
                "items": [{"batch": "alpha", "filename": "portrait-public.png"}],
            },
        )
        assert status == 200
        assert payload["moved"] == 1
        assert not public_copy.exists()
        assert (export_root / "posting" / "portrait-public.png").exists()
        assert original.exists()

    asyncio.run(scenario())


def test_native_public_delete_route_removes_derivative(tmp_path, monkeypatch):
    from PIL import Image
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        public_copy = settings.batch_root / "alpha" / "public" / "portrait-public.png"
        public_copy.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), color="blue").save(public_copy)
        original = settings.batch_root / "alpha" / "finals" / "portrait.png"
        original.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), color="red").save(original)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/public/delete",
            {"items": [{"batch": "alpha", "filename": "portrait-public.png"}]},
        )
        assert status == 200
        assert payload["deleted"] == 1
        assert not public_copy.exists()
        assert original.exists()

    asyncio.run(scenario())


def test_native_public_copy_rejects_without_export_root(tmp_path, monkeypatch):
    from PIL import Image
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        (settings.batch_root / "alpha" / "public").mkdir(parents=True)
        Image.new("RGB", (4, 4), color="blue").save(
            settings.batch_root / "alpha" / "public" / "portrait-public.png"
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/public/copy",
            {
                "destination": str(tmp_path / "posting"),
                "items": [{"batch": "alpha", "filename": "portrait-public.png"}],
            },
        )
        assert status == 400
        assert "not configured" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_public_copy_rejects_non_object_items(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/public/copy",
            {
                "destination": str(tmp_path / "posting"),
                "items": [{"batch": "alpha", "filename": "pic.png"}, "bad-item"],
            },
        )
        assert status == 400
        assert "objects" in payload["error"]

    asyncio.run(scenario())


def test_native_public_copy_rejects_destination_traversal(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/public/copy",
            {
                "destination": str(tmp_path / "outside"),
                "items": [{"batch": "alpha", "filename": "pic.png"}],
            },
        )
        assert status == 400
        assert any(
            "stay inside" in f.get("error", "").lower() for f in (payload.get("files") or [])
        )

    asyncio.run(scenario())


def test_native_public_copy_move_rejects_missing_destination(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for route in ("/api/curator/public/copy", "/api/curator/public/move"):
            status, payload = await _invoke(
                router,
                "POST",
                route,
                {"items": [{"batch": "alpha", "filename": "pic.png"}]},
            )
            assert status == 400
            assert "destination" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_public_routes_reject_missing_batch(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        export_root.mkdir()
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/publish/export",
            {"batch": "nope", "folder": "finals", "filenames": ["pic.png"]},
        )
        assert status == 404
        assert "does not exist" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_publish_export_rejects_non_string_folder(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for bad_folder in (None, 42, True, {}, []):
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/publish/export",
                {"batch": "alpha", "folder": bad_folder, "filenames": ["pic.png"]},
            )
            assert status == 400, f"folder={bad_folder!r} should be 400, got {status}"
            assert "folder" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_public_routes_reject_non_string_destination(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for bad_dest in (None, 42, True, {}, []):
            for route in ("/api/curator/public/copy", "/api/curator/public/move"):
                status, payload = await _invoke(
                    router,
                    "POST",
                    route,
                    {
                        "destination": bad_dest,
                        "items": [{"batch": "alpha", "filename": "pic.png"}],
                    },
                )
                assert status == 400, f"route={route} dest={bad_dest!r} should be 400, got {status}"
                assert "destination" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_public_routes_reject_non_string_item_fields(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        export_root = tmp_path / "exports"
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for route in (
            "/api/curator/public/copy",
            "/api/curator/public/move",
            "/api/curator/public/delete",
        ):
            for bad_value in (None, 42, True, []):
                status, payload = await _invoke(
                    router,
                    "POST",
                    route,
                    {
                        "destination": str(export_root / "posting"),
                        "items": [{"batch": bad_value, "filename": "pic.png"}],
                    },
                )
                assert status == 400, f"route={route} batch={bad_value!r} should be 400"
                assert "batch" in payload["error"].lower() or "items" in payload["error"].lower()

            for bad_value in (None, 42, True, []):
                status, payload = await _invoke(
                    router,
                    "POST",
                    route,
                    {
                        "destination": str(export_root / "posting"),
                        "items": [{"batch": "alpha", "filename": bad_value}],
                    },
                )
                assert status == 400, f"route={route} filename={bad_value!r} should be 400"

    asyncio.run(scenario())


def test_native_public_export_root_symlink_rejected_real_symlink(tmp_path, monkeypatch):
    """Real symlink export root must be rejected before resolution."""
    real_root = tmp_path / "real-exports"
    real_root.mkdir()
    fake_link = tmp_path / "fake-link-exports"

    _symlink_directory_or_skip(fake_link, real_root)

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=fake_link,  # symlink
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/public/copy",
            {
                "destination": str(real_root / "posting"),
                "items": [{"batch": "alpha", "filename": "pic.png"}],
            },
        )
        assert status == 400
        assert "symlink" in str(payload).lower()

    asyncio.run(scenario())


def test_native_public_browser_path_symlink_component_rejected_real_symlink(tmp_path, monkeypatch):
    """Real symlink intermediate component must be rejected in browser path."""
    export_root = tmp_path / "exports-root"
    export_root.mkdir()
    target_dir = tmp_path / "target-dir"
    target_dir.mkdir()
    link_in_root = export_root / "linked-dir"
    _symlink_directory_or_skip(link_in_root, target_dir)

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
            public_export_root=export_root,
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/public/destinations",
            query={"path": "linked-dir"},
        )
        assert status == 400
        assert "symlink" in str(payload).lower()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Native prompt-history routes
# ---------------------------------------------------------------------------


def _write_png_test(path, parameters):
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    path.parent.mkdir(parents=True, exist_ok=True)
    png_info = PngInfo()
    png_info.add_text("parameters", parameters)
    Image.new("RGB", (1, 1), color="blue").save(path, pnginfo=png_info)


def test_native_build_prompt_index_succeeds(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        _write_png_test(
            settings.batch_root / "alpha" / "inbox" / "one.png",
            "cat\nSteps: 1",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload["batch"] == "alpha"
        assert payload["prompt_count"] == 1
        assert payload["image_count"] == 1
        assert "built_at" in payload
        assert len(payload["prompts"]) == 1

    asyncio.run(scenario())


def test_native_build_prompt_index_nonexistent_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "nope"},
        )
        assert status == 404
        assert "does not exist" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_get_prompt_index_returns_cached(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        _write_png_test(
            settings.batch_root / "alpha" / "inbox" / "one.png",
            "cat\nSteps: 1",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        # Build first
        built = (
            await _invoke(
                router,
                "POST",
                "/api/curator/prompt-history/{batch}/build",
                match_info={"batch": "alpha"},
            )
        )[1]

        # Get and compare
        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 200
        assert payload == built

    asyncio.run(scenario())


def test_native_get_prompt_index_not_built_returns_404(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 404
        assert "not built" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_get_prompt_index_nonexistent_batch(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "nope"},
        )
        assert status == 404
        assert "does not exist" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_get_prompt_index_stale_check(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        _write_png_test(
            settings.batch_root / "alpha" / "inbox" / "one.png",
            "cat\nSteps: 1",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        # Build index
        await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "alpha"},
        )

        # Check stale = false when counts match
        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "alpha"},
            query={"check_stale": "true"},
        )
        assert status == 200
        assert payload["stale"] is False
        assert payload["current_image_count"] == 1

        # Add a new image to make stale
        _write_png_test(
            settings.batch_root / "alpha" / "finals" / "two.png",
            "dog\nSteps: 1",
        )
        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "alpha"},
            query={"check_stale": "true"},
        )
        assert status == 200
        assert payload["stale"] is True
        assert payload["current_image_count"] == 2

    asyncio.run(scenario())


def test_native_get_all_prompt_indices_aggregates(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        batch_store.create_batch(settings.batch_root, "beta")
        _write_png_test(
            settings.batch_root / "alpha" / "inbox" / "one.png",
            "cat\nSteps: 1",
        )
        _write_png_test(
            settings.batch_root / "beta" / "inbox" / "two.png",
            "dog\nSteps: 1",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "alpha"},
        )
        await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "beta"},
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history",
        )
        assert status == 200
        assert sorted(payload["batches"].keys()) == ["alpha", "beta"]
        assert payload["total_prompts"] == 2

    asyncio.run(scenario())


def test_native_prompt_history_virtual_sentinels_rejected(tmp_path, monkeypatch):
    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        for sentinel in ("__favorites__", "__public__"):
            status, payload = await _invoke(
                router,
                "POST",
                "/api/curator/prompt-history/{batch}/build",
                match_info={"batch": sentinel},
            )
            assert status == 404, f"sentinel {sentinel} should be 404, got {status}"
            assert "does not exist" in payload["error"].lower()

            status, payload = await _invoke(
                router,
                "GET",
                "/api/curator/prompt-history/{batch}",
                match_info={"batch": sentinel},
            )
            assert status == 404, f"sentinel {sentinel} GET should be 404, got {status}"

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Native prompt-history safety: symlink / containment escape rejection
# ---------------------------------------------------------------------------


def test_native_build_prompt_index_rejects_symlinked_stage_no_cache(tmp_path, monkeypatch):
    """POST build must not create prompt-history.json when a review stage is a symlink."""
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        inbox.rmdir()
        outside = tmp_path / "outside-native-build"
        outside.mkdir()
        _write_png_test(outside / "escaped.png", "secret\nSteps: 1")
        _symlink_directory_or_skip(inbox, outside)

        # Also put a valid image in a safe stage
        _write_png_test(
            settings.batch_root / "alpha" / "shortlisted" / "valid.png",
            "safe prompt\nSteps: 1",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "alpha"},
        )
        assert status == 400
        assert payload == {"error": "Unsafe prompt history path"}
        assert not (settings.batch_root / "alpha" / "prompt-history.json").exists()

    asyncio.run(scenario())


def test_native_build_prompt_index_rejects_resolved_escape_stage_no_cache(tmp_path, monkeypatch):
    """POST build must not surface external content when a stage resolves outside the batch root."""
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        inbox = settings.batch_root / "alpha" / "inbox"
        outside = tmp_path / "outside-native-resolve"
        outside.mkdir()
        _write_png_test(outside / "escaped.png", "secret\nSteps: 1")
        real_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == inbox:
                return outside
            return real_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "alpha"},
        )
        assert status == 400
        assert payload == {"error": "Unsafe prompt history path"}
        cache_file = settings.batch_root / "alpha" / "prompt-history.json"
        assert not cache_file.exists()

    asyncio.run(scenario())


def test_native_stale_check_rejects_unsafe_stage(tmp_path, monkeypatch):
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        _write_png_test(settings.batch_root / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )
        assert (
            await _invoke(
                router,
                "POST",
                "/api/curator/prompt-history/{batch}/build",
                match_info={"batch": "alpha"},
            )
        )[0] == 200
        inbox = settings.batch_root / "alpha" / "inbox"
        outside = tmp_path / "outside-stale"
        outside.mkdir()
        real_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == inbox:
                return outside
            return real_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "alpha"},
            query={"check_stale": "true"},
        )
        assert status == 400
        assert payload == {"error": "Unsafe prompt history path"}

    asyncio.run(scenario())


def test_native_get_prompt_index_rejects_symlinked_cache(tmp_path, monkeypatch):
    """GET must return 404 when the cache file is a symlink."""
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        cache_path = settings.batch_root / "alpha" / "prompt-history.json"
        outside = tmp_path / "outside-load"
        outside.mkdir()
        outside_cache = outside / "fake.json"

        outside_cache.write_text(
            '{"batch": "alpha", "image_count": 999, "prompt_count": 1, "prompts": []}',
            encoding="utf-8",
        )
        try:
            cache_path.symlink_to(outside_cache)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"file symlink unavailable on this platform: {exc}")
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 404, f"expected 404 for symlinked cache, got {status}"
        assert "not built" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_get_prompt_index_rejects_non_regular_cache(tmp_path, monkeypatch):
    """GET must return 404 when the cache path is a directory instead of a regular file."""
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        # Create a directory where the cache file should be
        cache_path = settings.batch_root / "alpha" / "prompt-history.json"
        cache_path.mkdir()
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history/{batch}",
            match_info={"batch": "alpha"},
        )
        assert status == 404, f"expected 404 for non-regular cache, got {status}"
        assert "not built" in payload["error"].lower()

    asyncio.run(scenario())


def test_native_get_all_prompt_indices_skips_unsafe_caches(tmp_path, monkeypatch):
    """Aggregate must omit batches whose caches are unsafe while returning safe ones."""
    from image_curator import batch_store

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "state.json",
        )
        batch_store.create_batch(settings.batch_root, "alpha")
        batch_store.create_batch(settings.batch_root, "beta")
        _write_png_test(
            settings.batch_root / "alpha" / "inbox" / "one.png",
            "cat\nSteps: 1",
        )
        _write_png_test(
            settings.batch_root / "beta" / "inbox" / "two.png",
            "dog\nSteps: 1",
        )
        router = _Router()
        native_routes.register_native_routes(
            SimpleNamespace(router=router), native_routes.NativeCuratorService(settings)
        )

        # Build both indices
        await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "alpha"},
        )
        await _invoke(
            router,
            "POST",
            "/api/curator/prompt-history/{batch}/build",
            match_info={"batch": "beta"},
        )

        # Make beta's cache a symlink (unsafe)
        beta_cache = settings.batch_root / "beta" / "prompt-history.json"
        outside = tmp_path / "outside-aggregate"
        outside.mkdir()
        fake_cache = outside / "fake.json"
        fake_cache.write_text(
            '{"batch": "beta", "image_count": 9999, "prompt_count": 99, "prompts": []}',
            encoding="utf-8",
        )
        try:
            beta_cache.symlink_to(fake_cache)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"file symlink unavailable on this platform: {exc}")

        status, payload = await _invoke(
            router,
            "GET",
            "/api/curator/prompt-history",
        )
        assert status == 200
        assert "alpha" in payload["batches"], "safe batch alpha must be present"
        assert "beta" not in payload["batches"], "batch with symlinked cache must be omitted"
        assert payload["total_prompts"] == 1

    asyncio.run(scenario())
