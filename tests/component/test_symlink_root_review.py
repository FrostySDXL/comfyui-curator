"""Independent acceptance: real directory aliases through both move adapters."""

import asyncio
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from image_curator import batch_store
from image_curator.move_history import MoveHistory
from image_curator.native_settings import NativeConfigStore, NativeCuratorSettings
from tests.component.test_native_curator_api import (
    _editable_request,
    _invoke,
    _load_native_routes,
    _Router,
)

pytestmark = pytest.mark.component


def _directory_alias(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Windows can create directory junctions without symlink privilege.
        # No shell-built paths and no production filesystem are involved.
        env = dict(os.environ, CURATOR_TEST_LINK=str(link), CURATOR_TEST_TARGET=str(target))
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "New-Item -ItemType Junction -Path $env:CURATOR_TEST_LINK "
                "-Target $env:CURATOR_TEST_TARGET -ErrorAction Stop | Out-Null",
            ],
            env=env,
            check=True,
            capture_output=True,
            timeout=15,
        )
    assert link.resolve() == target.resolve()


@pytest.fixture
def aliased_library(tmp_path):
    target = tmp_path / "external-library"
    batch_store.create_batch(target, "review")
    alias = tmp_path / "configured-library"
    _directory_alias(alias, target)
    (target / "review/inbox/image.png").write_bytes(b"original image")
    (target / "review/inbox/image.png.json").write_bytes(b'{"seed":"123"}')
    return alias, target


def _assert_restored(target):
    assert (target / "review/inbox/image.png").read_bytes() == b"original image"
    assert (target / "review/inbox/image.png.json").read_bytes() == b'{"seed":"123"}'
    assert list((target / "review/finals").iterdir()) == []


def test_flask_alias_move_then_undo_using_real_root(app_module, monkeypatch, aliased_library):
    alias, target = aliased_library
    monkeypatch.setattr(app_module, "BATCHES_DIR", alias)
    client = app_module.app.test_client()
    moved = client.post(
        "/api/move",
        json={
            "batch": "review",
            "filename": "image.png",
            "source": "inbox",
            "destination": "finals",
        },
    )
    assert moved.status_code == 200, moved.json
    token = moved.json["operation_id"]
    assert client.get("/api/move-history").json["operations"][0]["id"] == token
    # Reconstruct through the canonical path; the journal must be the same.
    monkeypatch.setattr(app_module, "BATCHES_DIR", target)
    restored = client.post("/api/move-batch/undo", json={"operation_id": token})
    assert restored.status_code == 200, restored.json
    assert restored.json["status"] == "undone"
    _assert_restored(target)


def test_native_alias_bulk_move_and_restarted_undo(monkeypatch, tmp_path, aliased_library):
    alias, target = aliased_library
    native = _load_native_routes(monkeypatch)

    async def scenario():
        settings = NativeCuratorSettings(alias, tmp_path / "output", tmp_path / "state.json")
        service = native.NativeCuratorService(settings)
        router = _Router()
        native.register_native_routes(SimpleNamespace(router=router), service)
        try:
            status, moved = await _invoke(
                router,
                "POST",
                "/api/curator/move-batch",
                {
                    "batch": "review",
                    "filenames": ["image.png"],
                    "source": "inbox",
                    "destination": "finals",
                },
            )
            assert status == 200 and moved["success"], moved
        finally:
            service.close()
        restarted = native.NativeCuratorService(settings)
        router = _Router()
        native.register_native_routes(SimpleNamespace(router=router), restarted)
        try:
            status, history = await _invoke(router, "GET", "/api/curator/move-history")
            assert status == 200 and history["operations"][0]["id"] == moved["operation_id"]
            status, restored = await _invoke(
                router,
                "POST",
                "/api/curator/move-batch/undo",
                {"operation_id": moved["operation_id"]},
            )
            assert status == 200 and restored["status"] == "undone", restored
        finally:
            restarted.close()

    asyncio.run(scenario())
    _assert_restored(target)


def test_alias_store_is_canonical_and_internal_escape_still_refused(tmp_path, aliased_library):
    alias, target = aliased_library
    history = MoveHistory(alias)
    assert history.root == target.resolve()
    assert history._lock is MoveHistory(target)._lock
    receipt = history.move("review", "inbox", "finals", ["image.png"])
    inbox = target / "review/inbox"
    inbox.rmdir()  # Empty directory in this test only; originals are in finals.
    outside = tmp_path / "outside"
    outside.mkdir()
    _directory_alias(inbox, outside)
    result = history.undo(receipt.operation_id)
    assert result.moved == 0 and result.remaining == 1
    assert list(outside.iterdir()) == []
    assert (target / "review/finals/image.png").read_bytes() == b"original image"
    assert json.loads((target / ".curator-undo/history.json").read_text())[0]["items"]


def test_native_settings_preserves_real_root_alias_on_save_and_reload(tmp_path, aliased_library):
    alias, _target = aliased_library
    system = tmp_path / "system"
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "old-library",
        import_source=tmp_path / "output",
        state_file=system / "state.json",
        config_store=NativeConfigStore(system),
    )
    settings.update(_editable_request(settings, batch_root=str(alias)))
    restarted = NativeCuratorSettings.from_host_paths(
        get_system_user_directory=lambda _name: str(system),
        get_output_directory=lambda: str(tmp_path / "output"),
    )
    assert restarted.batch_root == alias
    assert MoveHistory(restarted.batch_root).root == alias.resolve()


def test_internal_journal_alias_is_not_trusted(tmp_path, aliased_library):
    alias, target = aliased_library
    outside = tmp_path / "external-journal"
    outside.mkdir()
    _directory_alias(target / ".curator-undo", outside)
    with pytest.raises(OSError):
        MoveHistory(alias).list_operations()
    assert list(outside.iterdir()) == []


def test_dangling_configured_alias_does_not_create_target(tmp_path):
    target = tmp_path / "disconnected-library"
    target.mkdir()
    alias = tmp_path / "configured-library"
    _directory_alias(alias, target)
    target.rmdir()  # Empty test directory simulates a disconnected target.
    with pytest.raises(OSError):
        MoveHistory(alias).list_operations()
    assert not target.exists()


def test_store_stays_on_original_target_if_alias_changes(tmp_path, aliased_library):
    alias, target = aliased_library
    history = MoveHistory(alias)
    other = tmp_path / "different-library"
    batch_store.create_batch(other, "review")
    if alias.is_symlink():
        alias.unlink()
    else:
        alias.rmdir()  # Remove only the test junction, never its target tree.
    _directory_alias(alias, other)
    receipt = history.move("review", "inbox", "finals", ["image.png"])
    assert receipt.moved == 1
    assert history.undo(receipt.operation_id).status == "undone"
    _assert_restored(target)
    assert not (other / ".curator-undo").exists()
    assert list((other / "review/inbox").iterdir()) == []


def test_dangling_alias_history_routes_fail_as_json(app_module, monkeypatch, tmp_path):
    target = tmp_path / "disconnected"
    target.mkdir()
    alias = tmp_path / "configured"
    _directory_alias(alias, target)
    target.rmdir()
    monkeypatch.setattr(app_module, "BATCHES_DIR", alias)
    client = app_module.app.test_client()
    for response in (
        client.get("/api/move-history"),
        client.post("/api/move-batch/undo", json={"operation_id": "test-token"}),
    ):
        assert response.status_code == 500
        assert response.json == {"error": "Move history is unavailable"}

    native = _load_native_routes(monkeypatch)

    async def scenario():
        settings = NativeCuratorSettings(alias, tmp_path / "output", tmp_path / "state.json")
        service = native.NativeCuratorService(settings)
        router = _Router()
        native.register_native_routes(SimpleNamespace(router=router), service)
        try:
            for method, route, payload in (
                ("GET", "/api/curator/move-history", None),
                ("POST", "/api/curator/move-batch/undo", {"operation_id": "test-token"}),
            ):
                status, data = await _invoke(router, method, route, payload)
                assert status == 500
                assert data == {"error": "Move history is unavailable"}
        finally:
            service.close()

    asyncio.run(scenario())
    assert not target.exists()
