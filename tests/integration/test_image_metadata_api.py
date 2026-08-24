from PIL import Image
from PIL.PngImagePlugin import PngInfo

import pytest

pytestmark = pytest.mark.integration


def write_png(path, metadata=None):
    png_info = PngInfo()
    for key, value in (metadata or {}).items():
        png_info.add_text(key, value)
    Image.new("RGB", (1, 1), color="blue").save(path, pnginfo=png_info)


def test_image_metadata_api_returns_png_metadata(client, app_module):
    app_module.create_batch("metadata-batch")
    image_path = app_module.BATCHES_DIR / "metadata-batch" / "inbox" / "sample.png"
    write_png(
        image_path,
        {
            "parameters": "prompt text\nNegative prompt: bad\nSteps: 12, Sampler: Euler, CFG scale: 7, Seed: 123, Size: 512x768, Model: test-model",
            "workflow": "{}",
        },
    )

    response = client.get("/api/image-metadata/metadata-batch/inbox/sample.png")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["has_metadata"] is True
    assert payload["parameters"]["prompt"] == "prompt text"
    assert payload["parameters"]["negative_prompt"] == "bad"
    assert payload["parameters"]["steps"] == 12
    assert payload["parameters"]["model"] == "test-model"
    assert payload["workflow_available"] is True


def test_image_metadata_api_returns_false_for_non_png(client, app_module, make_file):
    app_module.create_batch("metadata-batch")
    make_file(app_module.BATCHES_DIR / "metadata-batch" / "inbox" / "sample.jpg")

    response = client.get("/api/image-metadata/metadata-batch/inbox/sample.jpg")

    assert response.status_code == 200
    assert response.get_json()["has_metadata"] is False


def test_image_metadata_api_returns_json_sidecar_for_typed_media(client, app_module, make_file):
    app_module.create_batch("metadata-batch")
    media = app_module.BATCHES_DIR / "metadata-batch" / "inbox" / "sample.mp4"
    make_file(media)
    media.with_name("sample.mp4.json").write_text(
        '{"website":"example","rating":5}', encoding="utf-8"
    )

    response = client.get("/api/image-metadata/metadata-batch/inbox/sample.mp4")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["has_metadata"] is True
    assert payload["has_png_metadata"] is False
    assert payload["has_sidecar"] is True
    assert payload["sidecar"]["name"] == "sample.mp4.json"
    assert '"website": "example"' in payload["sidecar"]["text"]


def test_image_metadata_api_validates_folder_and_missing_file(client, app_module):
    app_module.create_batch("metadata-batch")

    bad_folder = client.get("/api/image-metadata/metadata-batch/not-a-folder/sample.png")
    missing = client.get("/api/image-metadata/metadata-batch/inbox/missing.png")

    assert bad_folder.status_code == 400
    assert missing.status_code == 404
