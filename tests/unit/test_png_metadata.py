from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from image_curator.png_metadata import extract_png_metadata


PARAMETERS = """1girl, red hair, long hair, <lora:DetailTweaker:0.4>, <lora:CharacterPack:0.85>

Negative prompt: bad quality, worst quality
Steps: 28, Sampler: DPM++ 2M SDE Karras, CFG scale: 3.5, Seed: 209437280461280, Size: 896x1152, Clip skip: 2, Model hash: 29d5281e0a, Model: rinFlanimeIllustrious_v40, Version: ComfyUI"""


def write_png(path: Path, metadata: dict[str, str] | None = None) -> None:
    png_info = PngInfo()
    for key, value in (metadata or {}).items():
        png_info.add_text(key, value)
    Image.new("RGB", (1, 1), color="red").save(path, pnginfo=png_info)


def test_extract_png_metadata_parses_comfyui_parameters(tmp_path):
    image_path = tmp_path / "sample.png"
    write_png(
        image_path,
        {
            "parameters": PARAMETERS,
            "prompt": '{"workflow": true}',
            "workflow": '{"workflow": true}',
        },
    )

    metadata = extract_png_metadata(image_path)

    assert metadata["has_metadata"] is True
    assert metadata["source"] == "comfyui_png"
    assert metadata["parameters"]["prompt"].startswith("1girl, red hair")
    assert metadata["parameters"]["negative_prompt"] == "bad quality, worst quality"
    assert metadata["parameters"]["steps"] == 28
    assert metadata["parameters"]["sampler"] == "DPM++ 2M SDE Karras"
    assert metadata["parameters"]["cfg_scale"] == 3.5
    assert metadata["parameters"]["seed"] == 209437280461280
    assert metadata["parameters"]["width"] == 896
    assert metadata["parameters"]["height"] == 1152
    assert metadata["parameters"]["clip_skip"] == 2
    assert metadata["parameters"]["model"] == "rinFlanimeIllustrious_v40"
    assert metadata["parameters"]["model_hash"] == "29d5281e0a"
    assert metadata["workflow_available"] is True
    assert metadata["workflow_size"] > 0
    assert metadata["raw_parameters"] == PARAMETERS
    assert metadata["loras"] == [
        {"name": "DetailTweaker", "weight": 0.4, "hash": None},
        {"name": "CharacterPack", "weight": 0.85, "hash": None},
    ]


def test_extract_png_metadata_handles_no_metadata_and_non_png(tmp_path):
    png_path = tmp_path / "plain.png"
    jpg_path = tmp_path / "plain.jpg"
    write_png(png_path)
    jpg_path.write_bytes(b"not metadata")

    assert extract_png_metadata(png_path)["has_metadata"] is False
    assert extract_png_metadata(jpg_path)["has_metadata"] is False


def test_extract_png_metadata_handles_malformed_parameters(tmp_path):
    image_path = tmp_path / "sample.png"
    write_png(image_path, {"parameters": "not an a1111 settings block"})

    metadata = extract_png_metadata(image_path)

    assert metadata["has_metadata"] is True
    assert metadata["parameters"]["prompt"] == "not an a1111 settings block"
    assert metadata["parameters"]["negative_prompt"] is None
    assert metadata["loras"] == []
