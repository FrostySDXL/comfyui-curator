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
        "watcher_enabled": False,
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
