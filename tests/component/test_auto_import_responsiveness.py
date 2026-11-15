import asyncio
import threading
from unittest.mock import MagicMock

from tests.component.test_native_ai_curate_api import _invoke, _make_router_and_lifecycle
from tests.component.test_native_curator_api import _load_native_routes, _Router


def test_ai_submit_does_not_block_event_loop_during_settings_lock(tmp_path, monkeypatch):
    router, service, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
    held, release = threading.Event(), threading.Event()

    def hold_settings_lock():
        with lifecycle._state_lock:
            held.set()
            release.wait(3)

    holder = threading.Thread(target=hold_settings_lock)
    holder.start()
    assert held.wait(2)

    async def scenario():
        task = asyncio.create_task(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {
                    "batch": "test-batch",
                    "elements": ["test"],
                    "model": "vl-scorer",
                },
            )
        )
        try:
            await asyncio.wait_for(asyncio.sleep(0.05), 1)
            assert not task.done()
        finally:
            release.set()
            status, _ = await task
            assert status == 201

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        holder.join(3)
        service.close()


def test_ai_validation_and_submission_pin_settings_during_root_switch(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeConfigStore, SettingsConflictError
    from tests.component.test_native_curator_api import _editable_request

    router, service, lifecycle = _make_router_and_lifecycle(tmp_path, monkeypatch)
    settings = lifecycle.settings
    settings.config_store = NativeConfigStore(tmp_path / "config")
    other_root = tmp_path / "other-batches"
    other_root.mkdir()
    payload = _editable_request(settings, batch_root=str(other_root))
    entered, release = threading.Event(), threading.Event()
    original = service.batches_payload
    monkeypatch.setattr(lifecycle, "_launch_worker", lambda run_id: None)

    def slow_validation():
        entered.set()
        assert release.wait(3)
        return original()

    monkeypatch.setattr(service, "batches_payload", slow_validation)
    outcomes = []

    def change_settings():
        try:
            lifecycle.update_settings(payload)
            outcomes.append("changed")
        except SettingsConflictError:
            outcomes.append("conflict")

    async def scenario():
        task = asyncio.create_task(
            _invoke(
                router,
                "POST",
                "/api/curator/ai-curate/jobs",
                {
                    "batch": "test-batch",
                    "elements": ["test"],
                    "model": "vl-scorer",
                },
            )
        )
        assert await asyncio.to_thread(entered.wait, 2)
        changer = threading.Thread(target=change_settings)
        changer.start()
        try:
            await asyncio.sleep(0.05)
            assert changer.is_alive()
        finally:
            release.set()
        status, _ = await task
        changer.join(3)
        assert status == 201
        assert outcomes == ["conflict"]
        assert settings.batch_root == tmp_path / "batches"

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        service.close()


def test_timed_out_shutdown_cleans_up_after_worker_exits(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeCuratorSettings

    native_routes = _load_native_routes(monkeypatch)
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
    )
    service = native_routes.NativeCuratorService(settings)
    finished, release = threading.Event(), threading.Event()
    worker = threading.Thread(target=release.wait)
    worker.start()
    service.auto_import.thread = worker
    monkeypatch.setattr(service.auto_import, "close", lambda: False)
    service.folder_index.close = MagicMock(side_effect=finished.set)
    service.search_index_jobs.close = MagicMock()
    service.close()
    assert not finished.is_set()
    release.set()
    assert finished.wait(2)
    worker.join(2)
    service.folder_index.close.assert_called_once()


def test_status_does_not_wait_for_import_lock(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeCuratorSettings

    async def scenario():
        native_routes = _load_native_routes(monkeypatch)
        source = tmp_path / "output"
        source.mkdir()
        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=source,
            state_file=tmp_path / "state.json",
        )
        service = native_routes.NativeCuratorService(settings)
        router = _Router()
        native_routes.register_native_routes(type("App", (), {"router": router})(), service)
        held, release = threading.Event(), threading.Event()

        def hold_import():
            with service.auto_import.lock:
                held.set()
                release.wait(3)

        holder = threading.Thread(target=hold_import)
        holder.start()
        assert held.wait(2)
        try:

            async def get_status():
                return await router.handlers[("GET", "/api/curator/import-status")](None)

            await asyncio.wait_for(
                asyncio.gather(*(get_status() for _ in range(8)), asyncio.to_thread(lambda: None)),
                1,
            )
        finally:
            release.set()
            holder.join(3)
            service.close()

    asyncio.run(scenario())
