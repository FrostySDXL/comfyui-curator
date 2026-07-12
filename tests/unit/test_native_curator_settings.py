import json
from pathlib import Path

import pytest


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


def test_native_config_store_persists_versioned_config_atomically(tmp_path):
    from image_curator.native_settings import NativeConfigStore

    store = NativeConfigStore(tmp_path)
    saved = store.save({"batch_root": str((tmp_path / "batches").resolve())})

    assert saved["version"] == 1
    assert store.load() == saved
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8")) == saved
    assert not (tmp_path / "config.json.tmp").exists()


def test_native_settings_persisted_values_precede_environment_fallbacks(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeConfigStore, NativeCuratorSettings

    system_dir = tmp_path / "system"
    configured_batches = (tmp_path / "configured-batches").resolve()
    configured_import = (tmp_path / "configured-import").resolve()
    configured_exports = (tmp_path / "configured-exports").resolve()
    NativeConfigStore(system_dir).save(
        {
            "batch_root": str(configured_batches),
            "import_source": str(configured_import),
            "public_export_enabled": True,
            "public_export_root": str(configured_exports),
            "llm_base_url": "http://configured:9000",
            "models": ["one", "two"],
            "default_model": "two",
            "api_key": "stored-secret",
            "request_timeout": 45,
        }
    )
    monkeypatch.setenv("IMAGE_CURATOR_BATCHES", str(tmp_path / "env-batches"))
    monkeypatch.setenv("IMAGE_CURATOR_MODEL", "env-model")
    settings = NativeCuratorSettings.from_host_paths(
        get_system_user_directory=lambda _name: str(system_dir),
        get_output_directory=lambda: str(tmp_path / "host-output"),
    )
    assert settings.batch_root == configured_batches
    assert settings.import_source == configured_import
    assert settings.public_export_root == configured_exports
    assert settings.available_models == ("one", "two")
    assert settings.default_model == "two"
    assert settings.llm_base_url == "http://configured:9000"
    assert settings.request_timeout == 45
    payload = settings.editable_payload()
    assert payload["ai_api_key_set"] is True
    assert "stored-secret" not in json.dumps(payload)


def test_native_config_store_rejects_unsafe_and_malformed_targets_without_mutation(
    tmp_path, monkeypatch
):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("external", encoding="utf-8")
    link = system / "config.json"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(NativeConfigError):
        NativeConfigStore(system).save({"batch_root": str(tmp_path.resolve())})
    assert outside.read_text(encoding="utf-8") == "external"
    link.unlink()
    (system / "config.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(NativeConfigError, match="Stored settings are invalid"):
        NativeConfigStore(system).load()


def test_native_config_store_rejects_resolved_escape_on_windows_logic(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    target = system / "config.json"
    real_resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **k: (
            tmp_path / "outside" if path == target else real_resolve(path, *a, **k)
        ),
    )
    with pytest.raises(NativeConfigError, match="Unsafe settings storage"):
        NativeConfigStore(system).save({})
    assert not target.exists()


def test_native_config_store_load_rejects_dangling_config_symlink(tmp_path):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    config = system / "config.json"
    try:
        config.symlink_to(tmp_path / "missing.json")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlink unavailable on this platform: {exc}")

    with pytest.raises(NativeConfigError, match="Unsafe settings storage"):
        NativeConfigStore(system).load()


def test_native_config_store_load_checks_dangling_symlink_on_windows_logic(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    config = system / "config.json"
    real_exists = Path.exists
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if path == config else real_exists(path),
    )
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: True if path == config else real_is_symlink(path),
    )

    with pytest.raises(NativeConfigError, match="Unsafe settings storage"):
        NativeConfigStore(system).load()


def test_native_settings_malformed_config_uses_safe_fallback_without_overwrite(tmp_path):
    from image_curator.native_settings import NativeCuratorSettings

    system = tmp_path / "system"
    system.mkdir()
    config = system / "config.json"
    config.write_text("{malformed", encoding="utf-8")
    settings = NativeCuratorSettings.from_host_paths(
        get_system_user_directory=lambda _name: str(system),
        get_output_directory=lambda: str(tmp_path / "output"),
    )
    assert settings.batch_root == system / "batches"
    assert config.read_text(encoding="utf-8") == "{malformed"


def test_native_settings_invalid_schema_uses_safe_fallback_without_overwrite(tmp_path):
    from image_curator.native_settings import NativeCuratorSettings

    system = tmp_path / "system"
    system.mkdir()
    config = system / "config.json"
    invalid = {"version": 1, "models": "not-a-list", "request_timeout": "secret-text"}
    config.write_text(json.dumps(invalid), encoding="utf-8")
    settings = NativeCuratorSettings.from_host_paths(
        get_system_user_directory=lambda _name: str(system),
        get_output_directory=lambda: str(tmp_path / "output"),
    )
    assert settings.config_error is True
    assert json.loads(config.read_text(encoding="utf-8")) == invalid


def test_native_config_atomic_failure_preserves_existing_file_and_cleans_temp(
    tmp_path, monkeypatch
):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    store = NativeConfigStore(tmp_path / "system")
    original = store.save({"models": ["one"]})
    monkeypatch.setattr(
        "image_curator.native_settings.os.replace",
        lambda *_: (_ for _ in ()).throw(OSError("fail")),
    )
    with pytest.raises(NativeConfigError, match="Could not save settings"):
        store.save({"models": ["two"]})
    assert store.load() == original
    assert not store.tmp_path.exists()


def test_native_config_save_converts_non_directory_system_path_without_leak(tmp_path):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "private-system-name"
    system.write_text("occupied", encoding="utf-8")

    with pytest.raises(NativeConfigError) as error:
        NativeConfigStore(system).save({})

    assert str(system) not in str(error.value)
    assert system.read_text(encoding="utf-8") == "occupied"


def test_native_config_save_converts_mkdir_failure_without_leak(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "private-system-name"
    real_mkdir = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == system:
            raise OSError(f"cannot create {system}")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(NativeConfigError) as error:
        NativeConfigStore(system).save({})

    assert str(system) not in str(error.value)


def test_native_config_save_rejects_symlinked_temp_without_mutation(tmp_path):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    store = NativeConfigStore(system)
    original = store.save({"models": ["old"]})
    outside = tmp_path / "outside.json"
    outside.write_text("external", encoding="utf-8")
    try:
        store.tmp_path.symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlink unavailable on this platform: {exc}")

    with pytest.raises(NativeConfigError, match="Unsafe settings storage"):
        store.save({"models": ["new"]})

    assert store.load() == original
    assert outside.read_text(encoding="utf-8") == "external"
    assert store.tmp_path.is_symlink()


@pytest.mark.parametrize("target_name", ["config.json", "config.json.tmp"])
def test_native_config_save_rejects_non_regular_targets_without_mutation(tmp_path, target_name):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    store = NativeConfigStore(system)
    target = system / target_name
    target.mkdir()

    with pytest.raises(NativeConfigError, match="Unsafe settings storage"):
        store.save({"models": ["new"]})

    assert target.is_dir()
    other = store.tmp_path if target == store.path else store.path
    assert not other.exists()


def test_native_config_save_rejects_temp_resolved_escape_without_mutation(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    store = NativeConfigStore(system)
    original = store.save({"models": ["old"]})
    real_resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **k: (
            tmp_path / "outside.json" if path == store.tmp_path else real_resolve(path, *a, **k)
        ),
    )

    with pytest.raises(NativeConfigError, match="Unsafe settings storage"):
        store.save({"models": ["new"]})

    monkeypatch.setattr(Path, "resolve", real_resolve)
    assert store.load() == original
    assert not store.tmp_path.exists()


def test_native_config_save_does_not_remove_hostile_temp_after_write_failure(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeConfigError, NativeConfigStore

    system = tmp_path / "system"
    system.mkdir()
    store = NativeConfigStore(system)
    hostile = store.tmp_path
    hostile.write_text("hostile", encoding="utf-8")
    real_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: False if path == hostile else real_is_file(path),
    )

    with pytest.raises(NativeConfigError, match="Unsafe settings storage"):
        store.save({})

    assert hostile.read_text(encoding="utf-8") == "hostile"
    assert not store.path.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"batch_root": "relative"},
        {"public_export_enabled": "yes"},
        {"llm_base_url": "file:///unsafe"},
        {"models": "model"},
        {"default_model": "missing"},
        {"request_timeout": 0},
        {"request_timeout": True},
    ],
)
def test_native_settings_reject_invalid_path_and_scalar_types(tmp_path, change):
    from image_curator.native_settings import (
        NativeConfigError,
        NativeConfigStore,
        NativeCuratorSettings,
    )

    settings = NativeCuratorSettings(
        batch_root=(tmp_path / "batches").resolve(),
        import_source=(tmp_path / "output").resolve(),
        state_file=tmp_path / "state.json",
        available_models=("model",),
        default_model="model",
        config_store=NativeConfigStore(tmp_path / "system"),
    )
    payload = _editable_request(settings, models=["model"])
    payload.update(change)
    with pytest.raises(NativeConfigError):
        settings.update(payload)
    assert not settings.config_store.path.exists()


def test_native_settings_allow_empty_model_configuration(tmp_path):
    from image_curator.native_settings import NativeConfigStore, NativeCuratorSettings

    settings = NativeCuratorSettings(
        batch_root=(tmp_path / "batches").resolve(),
        import_source=(tmp_path / "output").resolve(),
        state_file=tmp_path / "state.json",
        config_store=NativeConfigStore(tmp_path / "system"),
    )
    result = settings.update(_editable_request(settings, models=[], default_model=""))
    assert result["models"] == []
    assert result["default_model"] == ""


@pytest.mark.parametrize("field", ["ai_api_key_set", "config_error"])
def test_native_settings_rejects_read_only_response_fields_on_update(tmp_path, field):
    from image_curator.native_settings import (
        NativeConfigError,
        NativeConfigStore,
        NativeCuratorSettings,
    )

    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        config_store=NativeConfigStore(tmp_path / "system"),
    )

    with pytest.raises(NativeConfigError, match="Unknown settings field"):
        settings.update(_editable_request(settings, **{field: False}))

    assert not settings.config_store.path.exists()


@pytest.mark.parametrize("field", ["batch_root", "import_source", "public_export_root"])
def test_native_settings_rejects_direct_symlink_paths(tmp_path, field):
    from image_curator.native_settings import (
        NativeConfigError,
        NativeConfigStore,
        NativeCuratorSettings,
    )

    safe = tmp_path / "safe"
    safe.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(safe, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlink unavailable on this platform: {exc}")
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        config_store=NativeConfigStore(tmp_path / "system"),
    )

    with pytest.raises(NativeConfigError) as error:
        settings.update(
            _editable_request(
                settings,
                public_export_enabled=field == "public_export_root",
                **{field: str(linked)},
            )
        )

    assert str(linked) not in str(error.value)
    assert not settings.config_store.path.exists()


def test_native_settings_rejects_intermediate_symlink_path(tmp_path):
    from image_curator.native_settings import (
        NativeConfigError,
        NativeConfigStore,
        NativeCuratorSettings,
    )

    safe = tmp_path / "safe"
    safe.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(safe, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlink unavailable on this platform: {exc}")
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        config_store=NativeConfigStore(tmp_path / "system"),
    )

    with pytest.raises(NativeConfigError, match="batch_root"):
        settings.update(_editable_request(settings, batch_root=str(linked / "missing")))

    assert not (safe / "missing").exists()


@pytest.mark.parametrize("field", ["batch_root", "import_source", "public_export_root"])
def test_native_settings_rejects_existing_non_directory_paths(tmp_path, field):
    from image_curator.native_settings import (
        NativeConfigError,
        NativeConfigStore,
        NativeCuratorSettings,
    )

    file_path = tmp_path / "file-target"
    file_path.write_text("keep", encoding="utf-8")
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        config_store=NativeConfigStore(tmp_path / "system"),
    )

    with pytest.raises(NativeConfigError) as error:
        settings.update(
            _editable_request(
                settings,
                public_export_enabled=field == "public_export_root",
                **{field: str(file_path)},
            )
        )

    assert field in str(error.value)
    assert str(file_path) not in str(error.value)
    assert file_path.read_text(encoding="utf-8") == "keep"


def test_native_settings_accepts_safe_missing_directory_paths(tmp_path):
    from image_curator.native_settings import NativeConfigStore, NativeCuratorSettings

    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        config_store=NativeConfigStore(tmp_path / "system"),
    )
    batch_root = tmp_path / "safe" / "missing-batches"
    import_source = tmp_path / "safe" / "missing-import"
    export_root = tmp_path / "safe" / "missing-exports"

    settings.update(
        _editable_request(
            settings,
            batch_root=str(batch_root),
            import_source=str(import_source),
            public_export_enabled=True,
            public_export_root=str(export_root),
        )
    )

    assert settings.batch_root == batch_root
    assert settings.import_source == import_source
    assert settings.public_export_root == export_root
    assert not batch_root.exists()


def test_native_settings_rejects_path_resolve_escape_on_windows_logic(tmp_path, monkeypatch):
    from image_curator.native_settings import (
        NativeConfigError,
        NativeConfigStore,
        NativeCuratorSettings,
    )

    batch_root = tmp_path / "batches"
    real_resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **k: (
            tmp_path / "outside" if path == batch_root else real_resolve(path, *a, **k)
        ),
    )
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "old-batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        config_store=NativeConfigStore(tmp_path / "system"),
    )

    with pytest.raises(NativeConfigError, match="batch_root"):
        settings.update(_editable_request(settings, batch_root=str(batch_root)))

    assert not settings.config_store.path.exists()


def test_native_settings_resolve_host_paths_without_exposing_private_values(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeCuratorSettings

    monkeypatch.setenv("IMAGE_CURATOR_MODEL", "vision-a, vision-b")
    system_dir = tmp_path / "user" / "__curator"
    output_dir = tmp_path / "output"

    settings = NativeCuratorSettings.from_host_paths(
        get_system_user_directory=lambda _name: str(system_dir),
        get_output_directory=lambda: str(output_dir),
    )

    assert settings.batch_root == system_dir / "batches"
    assert settings.import_source == output_dir
    assert settings.state_file == system_dir / "state.json"
    assert settings.available_models == ("vision-a", "vision-b")
    assert settings.default_model == "vision-a"
    assert settings.public_payload() == {
        "available_models": ["vision-a", "vision-b"],
        "default_model": "vision-a",
        "public_enabled": True,
    }
    assert not any(
        key in settings.public_payload()
        for key in ("batch_root", "import_source", "state_file", "api_key", "token")
    )


def test_native_settings_public_export_root_defaults_to_none(tmp_path):
    from image_curator.native_settings import NativeCuratorSettings

    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
    )
    assert settings.public_export_root is None


def test_native_settings_public_export_root_can_be_set(tmp_path):
    from image_curator.native_settings import NativeCuratorSettings

    export_root = tmp_path / "exports"
    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        public_export_root=export_root,
    )
    assert settings.public_export_root == export_root


def test_native_settings_public_payload_excludes_public_export_root(tmp_path):
    from image_curator.native_settings import NativeCuratorSettings

    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        public_export_root=tmp_path / "exports",
    )
    assert "public_export_root" not in settings.public_payload()


def test_native_settings_public_payload_includes_public_enabled_false_when_export_root_is_none(
    tmp_path,
):
    from image_curator.native_settings import NativeCuratorSettings

    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
    )
    assert settings.public_payload().get("public_enabled") is False


def test_native_settings_public_payload_includes_public_enabled_true_when_export_root_is_set(
    tmp_path,
):
    from image_curator.native_settings import NativeCuratorSettings

    settings = NativeCuratorSettings(
        batch_root=tmp_path / "batches",
        import_source=tmp_path / "output",
        state_file=tmp_path / "state.json",
        public_export_root=tmp_path / "exports",
    )
    assert settings.public_payload().get("public_enabled") is True


def test_native_settings_from_host_paths_sets_default_public_export_root(tmp_path, monkeypatch):
    from image_curator.native_settings import NativeCuratorSettings

    monkeypatch.setenv("IMAGE_CURATOR_MODEL", "vision-a")
    system_dir = tmp_path / "user" / "__curator"
    output_dir = tmp_path / "output"

    settings = NativeCuratorSettings.from_host_paths(
        get_system_user_directory=lambda _name: str(system_dir),
        get_output_directory=lambda: str(output_dir),
    )

    assert settings.public_export_root is not None
    assert settings.public_export_root == system_dir / "public-exports"
    assert settings.public_payload().get("public_enabled") is True
