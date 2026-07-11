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
    }
    assert not any(
        key in settings.public_payload()
        for key in ("batch_root", "import_source", "state_file", "api_key", "token")
    )
