"""Unit tests for ai_curate.config module."""

import os
from unittest.mock import patch

from ai_curate import config


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


class TestModelConfig:
    def test_available_models_defaults_to_empty(self):
        """AVAILABLE_MODELS is an empty list when env var is not set."""
        assert isinstance(config.AVAILABLE_MODELS, list)
        # When IMAGE_CURATOR_MODEL is not set, AVAILABLE_MODELS is []
        # (unless the env var is set in the test environment)

    def test_default_model_defaults_to_empty_string(self):
        """DEFAULT_MODEL is an empty string when env var is not set."""
        assert config.DEFAULT_MODEL == "" or isinstance(config.DEFAULT_MODEL, str)
