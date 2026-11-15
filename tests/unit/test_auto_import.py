import threading

import pytest

from image_curator import batch_store
from image_curator.auto_import import AutoImport
from image_curator.native_settings import NativeCuratorSettings


def test_auto_import_waits_for_stability_and_pairs_sidecar(tmp_path):
    source = tmp_path / "output"
    source.mkdir()
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    enabled = [False]
    refreshed = []
    service = AutoImport(lambda: (source, root, state, enabled[0]), refreshed.append)
    media = source / "image.png"
    media.write_bytes(b"first")
    service.poll()
    assert media.exists()
    enabled[0] = True
    service.poll()
    media.write_bytes(b"changed")
    (source / "image.png.json").write_text("{}")
    service.poll()
    assert media.exists()
    service.poll()
    assert (root / "one" / "inbox" / "image.png").read_bytes() == b"changed"
    assert (root / "one" / "inbox" / "image.png.json").read_text() == "{}"
    assert refreshed == ["one"]


def test_auto_import_destination_changes_reset_stability_and_invalid_pauses(tmp_path):
    source = tmp_path / "output"
    source.mkdir()
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    batch_store.create_batch(root, "two")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    service = AutoImport(lambda: (source, root, state, True), lambda batch: None)
    media = source / "a.jpg"
    media.write_bytes(b"data")
    service.poll()
    batch_store.save_state(state, {"active_batch": "two"})
    service.poll()
    assert media.exists()
    service.poll()
    assert (root / "two" / "inbox" / "a.jpg").exists()
    media.write_bytes(b"new")
    batch_store.save_state(state, {"active_batch": "missing"})
    service.poll()
    assert media.exists()
    assert service.status()["auto_import_error"]


@pytest.mark.parametrize("change", ["media", "new_sidecar", "changed_sidecar"])
def test_changed_members_after_scan_are_not_imported(tmp_path, monkeypatch, change):
    source = tmp_path / "output"
    source.mkdir()
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    media = source / "a.png"
    media.write_bytes(b"data")
    sidecar = source / "a.png.json"
    if change == "changed_sidecar":
        sidecar.write_text("{}")
    service = AutoImport(lambda: (source, root, state, True), lambda batch: None)
    service.poll()
    original = batch_store.import_all_pending_detailed

    def change_before_transfer(*args, **kwargs):
        if change == "media":
            media.write_bytes(b"new data")
        else:
            sidecar.write_text('{"new": true}')
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_store, "import_all_pending_detailed", change_before_transfer)
    service.poll()
    assert media.exists()
    assert not (root / "one" / "inbox" / "a.png").exists()


def test_overlapping_source_is_rejected_even_through_root_alias(tmp_path):
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    batch_store.create_batch(root, "two")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    source = root / "two" / "shortlisted"
    media = source / "a.png"
    media.write_bytes(b"reviewed")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    service = AutoImport(lambda: (source, alias, state, True), lambda batch: None)
    service.poll()
    assert "overlap" in service.status()["auto_import_error"]
    with pytest.raises(ValueError, match="overlap"):
        service.manual("one")
    assert media.exists()
    ancestor_service = AutoImport(lambda: (tmp_path, alias, state, True), lambda batch: None)
    ancestor_service.poll()
    assert "overlap" in ancestor_service.status()["auto_import_error"]
    with pytest.raises(ValueError, match="overlap"):
        ancestor_service.manual("one")


def test_worker_imports_without_browser_and_stops(tmp_path):
    source = tmp_path / "output"
    source.mkdir()
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    (source / "a.png").write_bytes(b"data")
    imported = threading.Event()
    service = AutoImport(lambda: (source, root, state, True), lambda batch: imported.set())
    try:
        service.start()
        service.start()
        assert imported.wait(5)
        assert (root / "one" / "inbox" / "a.png").is_file()
    finally:
        service.close()
    assert not service.thread.is_alive()


def test_shutdown_stops_before_next_automatic_file(tmp_path, monkeypatch):
    source = tmp_path / "output"
    source.mkdir()
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    for name in ("a.png", "b.png"):
        (source / name).write_bytes(b"data")
    service = AutoImport(lambda: (source, root, state, True), lambda batch: None)
    original = batch_store.move_image
    entered, release = threading.Event(), threading.Event()

    def slow_move(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_store, "move_image", slow_move)
    service.poll()
    service.start()
    try:
        assert entered.wait(3)
        service.stop_event.set()
        release.set()
        service.close()
        assert len(list(source.glob("*.png"))) == 1
    finally:
        release.set()
        service.close()


def test_manual_import_serializes_with_automatic_import(tmp_path, monkeypatch):
    source = tmp_path / "output"
    source.mkdir()
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    (source / "a.png").write_bytes(b"data")
    service = AutoImport(lambda: (source, root, state, True), lambda batch: None)
    service.poll()
    entered, release = threading.Event(), threading.Event()
    original = batch_store.import_all_pending_detailed

    def slow_import(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_store, "import_all_pending_detailed", slow_import)
    automatic = threading.Thread(target=service.poll)
    manual = threading.Thread(target=service.manual, args=("one",))
    automatic.start()
    assert entered.wait(2)
    manual.start()
    release.set()
    automatic.join(3)
    manual.join(3)
    assert not automatic.is_alive() and not manual.is_alive()
    assert list((root / "one" / "inbox").iterdir()) == [root / "one" / "inbox" / "a.png"]


def test_failure_status_is_deduplicated_and_retained(tmp_path, monkeypatch):
    source = tmp_path / "output"
    source.mkdir()
    root = tmp_path / "batches"
    batch_store.create_batch(root, "one")
    state = tmp_path / "state.json"
    batch_store.save_state(state, {"active_batch": "one"})
    media = source / "a.png"
    media.write_bytes(b"data")
    service = AutoImport(lambda: (source, root, state, True), lambda batch: None)
    monkeypatch.setattr(batch_store, "move_image", lambda *args: False)
    service.poll()
    service.poll()
    failure = service.status()["auto_import_failure"]
    assert failure and not failure["paused"]
    assert "retrying" in failure["message"]
    service.poll()
    assert service.status()["auto_import_failure"] == failure
    media.unlink()
    service.poll()
    assert service.status()["auto_import_error"] == ""
    assert service.status()["auto_import_failure"] == failure


def test_native_auto_import_setting_defaults_off_and_persists(tmp_path):
    system = tmp_path / "system"
    create = lambda: NativeCuratorSettings.from_host_paths(
        get_system_user_directory=lambda _: str(system),
        get_output_directory=lambda: str(tmp_path / "output"),
    )
    settings = create()
    assert settings.auto_import_enabled is False
    data = settings.editable_payload()
    data.pop("ai_api_key_set")
    data.pop("config_error")
    settings.update(data | {"auto_import_enabled": True})
    assert create().auto_import_enabled is True
