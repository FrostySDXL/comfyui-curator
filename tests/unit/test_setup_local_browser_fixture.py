import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image


def load_fixture_module():
    script_path = Path(__file__).parents[2] / "scripts" / "setup_local_browser_fixture.py"
    spec = importlib.util.spec_from_file_location("setup_local_browser_fixture", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["setup_local_browser_fixture"] = module
    spec.loader.exec_module(module)
    return module


def test_create_fixture_builds_isolated_batches(tmp_path):
    fixture = load_fixture_module()

    result = fixture.create_fixture(tmp_path)

    assert result.batches_dir == tmp_path / "batches"
    assert result.comfyui_dir == tmp_path / "comfyui-outputs"
    assert result.url == "http://127.0.0.1:8188/curator"
    assert not (tmp_path / "state.json").exists()

    for batch in ("manual-test", "second-batch"):
        for folder in ("inbox", "shortlisted", "finals", "rejects"):
            assert (tmp_path / "batches" / batch / folder).is_dir()

    assert (tmp_path / "batches" / "manual-test" / "inbox" / "portrait_a.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "inbox" / "landscape_b.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "inbox" / "product_tabletop_c.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "inbox" / "character_turnaround_d.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "inbox" / "macro_botanical_e.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "shortlisted" / "shortlisted_c.png").is_file()
    assert (
        tmp_path / "batches" / "manual-test" / "shortlisted" / "shortlisted_environment_f.png"
    ).is_file()
    assert (tmp_path / "batches" / "manual-test" / "finals" / "final_d.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "finals" / "final_square_g.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "rejects" / "reject_soft_h.png").is_file()
    assert (tmp_path / "batches" / "second-batch" / "inbox" / "alternate_a.png").is_file()
    assert (tmp_path / "batches" / "second-batch" / "inbox" / "alternate_wide_b.png").is_file()
    assert (
        tmp_path / "batches" / "second-batch" / "shortlisted" / "alternate_shortlisted_c.png"
    ).is_file()
    assert (tmp_path / "comfyui-outputs" / "pending_import.png").is_file()
    assert (tmp_path / "comfyui-outputs" / "pending_import_metadata.png").is_file()
    assert (tmp_path / "batches" / "manual-test" / "public" / "final_d-public.png").is_file()
    assert (tmp_path / "batches" / "second-batch" / "public" / "alternate_a-public.png").is_file()

    with Image.open(tmp_path / "batches" / "manual-test" / "inbox" / "portrait_a.png") as image:
        text = image.text
    assert {"parameters", "prompt", "workflow"}.issubset(text)
    assert "Negative prompt:" in text["parameters"]
    assert "Sampler: DPM++ 2M SDE Karras" in text["parameters"]

    batch_favorites = json.loads(
        (tmp_path / "batches" / "manual-test" / ".favorites.json").read_text(encoding="utf-8")
    )
    universal_favorites = json.loads(
        (tmp_path / "batches" / ".favorites.json").read_text(encoding="utf-8")
    )
    assert batch_favorites["images"] == ["final_d.png", "portrait_a.png"]
    assert universal_favorites["images"][0]["batch"] == "manual-test"
    assert universal_favorites["images"][0]["filename"] == "final_d.png"


def test_env_lines_are_shell_specific_and_use_fixture_paths(tmp_path):
    fixture = load_fixture_module()
    result = fixture.create_fixture(tmp_path, port=5123)

    powershell_lines = result.env_lines("powershell")
    cmd_lines = result.env_lines("cmd")

    assert powershell_lines == [
        f'$env:IMAGE_CURATOR_BATCHES="{result.batches_dir}"',
        f'$env:IMAGE_CURATOR_COMFYUI="{result.comfyui_dir}"',
    ]
    assert cmd_lines == [
        f"set IMAGE_CURATOR_BATCHES={result.batches_dir}",
        f"set IMAGE_CURATOR_COMFYUI={result.comfyui_dir}",
    ]
    assert result.url == "http://127.0.0.1:5123/curator"
    assert not any(
        "IMAGE_CURATOR_STATE" in line
        or "IMAGE_CURATOR_HOST" in line
        or "IMAGE_CURATOR_PORT" in line
        for line in powershell_lines + cmd_lines
    )
