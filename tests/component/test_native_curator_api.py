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
            "available_models": ["vision"],
            "default_model": "vision",
            "watcher_enabled": False,
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
