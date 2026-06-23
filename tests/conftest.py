import importlib
from pathlib import Path

import pytest


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    module = importlib.import_module("app")

    batches_dir = tmp_path / "batches"
    comfyui_output = tmp_path / "comfyui-outputs"
    state_file = tmp_path / "state.json"

    batches_dir.mkdir()
    comfyui_output.mkdir()

    monkeypatch.setattr(module, "BATCHES_DIR", batches_dir)
    monkeypatch.setattr(module, "COMFYUI_OUTPUT", comfyui_output)
    monkeypatch.setattr(module, "STATE_FILE", state_file)
    monkeypatch.setattr(module, "PUBLIC_EXPORT_ROOT", None)
    module.watcher.seen_files = set()
    module.app.config.update(TESTING=True)

    return module


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture
def sample_image_names():
    return ["img_b.png", "img_a.png", "preview.webp"]


def _touch(path: Path, content: bytes = b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@pytest.fixture
def make_file():
    return _touch
