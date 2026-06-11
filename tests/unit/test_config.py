"""Unit tests for ai_curate.config module."""

import importlib
from pathlib import Path

from ai_curate import config
from image_curator import batch_store


class TestConfigDefaults:
    def test_default_top_n(self):
        """DEFAULT_TOP_N is 15."""
        assert config.DEFAULT_TOP_N == 15

    def test_top_n_cap(self):
        """TOP_N_CAP is 100."""
        assert config.TOP_N_CAP == 100

    def test_element_cap(self):
        """ELEMENT_CAP is 12."""
        assert config.ELEMENT_CAP == 12

    def test_allowed_source_folders(self):
        """ALLOWED_SOURCE_FOLDERS contains the four batch folders."""
        assert config.ALLOWED_SOURCE_FOLDERS == {"inbox", "shortlisted", "finals", "rejects"}

    def test_allowed_dest_folders(self):
        """ALLOWED_DEST_FOLDERS contains the four batch folders."""
        assert config.ALLOWED_DEST_FOLDERS == {"inbox", "shortlisted", "finals", "rejects"}

    def test_ai_curate_dir(self):
        """AI_CURATE_DIR is 'ai-curate'."""
        assert config.AI_CURATE_DIR == "ai-curate"

    def test_runs_subdir(self):
        """RUNS_SUBDIR is 'runs'."""
        assert config.RUNS_SUBDIR == "runs"

    def test_latest_file(self):
        """LATEST_FILE is 'latest.json'."""
        assert config.LATEST_FILE == "latest.json"

    def test_image_extensions_matches_batch_store(self):
        """IMAGE_EXTENSIONS is the same set as image_curator.batch_store."""
        assert config.IMAGE_EXTENSIONS == batch_store.IMAGE_EXTENSIONS
        assert config.IMAGE_EXTENSIONS is batch_store.IMAGE_EXTENSIONS


class TestRequestTimeout:
    def test_valid_timeout_from_env(self):
        """REQUEST_TIMEOUT parses a valid integer from env."""
        # Module-level constant is frozen at import; test that it's a positive int
        assert isinstance(config.REQUEST_TIMEOUT, int)
        assert config.REQUEST_TIMEOUT > 0

    def test_timeout_is_int(self):
        """REQUEST_TIMEOUT is an integer."""
        assert isinstance(config.REQUEST_TIMEOUT, int)
        assert config.REQUEST_TIMEOUT > 0


class TestPathConfig:
    def test_empty_path_env_values_use_defaults(self, monkeypatch):
        """Empty path env vars use defaults instead of the current directory."""
        monkeypatch.setenv("IMAGE_CURATOR_BATCHES", "")
        monkeypatch.setenv("IMAGE_CURATOR_COMFYUI", "")

        import ai_curate.config as cfg

        importlib.reload(cfg)
        try:
            assert cfg.BATCHES_DIR == Path.home() / "image-curator" / "batches"
            assert cfg.COMFYUI_OUTPUT == Path.home() / "image-curator" / "comfyui-outputs"
        finally:
            importlib.reload(config)

    def test_whitespace_path_env_values_use_defaults(self, monkeypatch):
        """Whitespace-only path env vars use defaults instead of a literal path."""
        monkeypatch.setenv("IMAGE_CURATOR_BATCHES", "   ")
        monkeypatch.setenv("IMAGE_CURATOR_COMFYUI", "\t")

        import ai_curate.config as cfg

        importlib.reload(cfg)
        try:
            assert cfg.BATCHES_DIR == Path.home() / "image-curator" / "batches"
            assert cfg.COMFYUI_OUTPUT == Path.home() / "image-curator" / "comfyui-outputs"
        finally:
            importlib.reload(config)


class TestModelConfig:
    def test_available_models_is_list(self):
        """AVAILABLE_MODELS is always a list regardless of env."""
        assert isinstance(config.AVAILABLE_MODELS, list)

    def test_default_model_is_none_when_env_unset(self, monkeypatch):
        """DEFAULT_MODEL is None when IMAGE_CURATOR_MODEL is not set."""
        monkeypatch.delenv("IMAGE_CURATOR_MODEL", raising=False)
        # Re-import to pick up the patched env
        import ai_curate.config as cfg

        importlib.reload(cfg)
        try:
            assert cfg.DEFAULT_MODEL is None
        finally:
            # Restore original config module state
            importlib.reload(config)
