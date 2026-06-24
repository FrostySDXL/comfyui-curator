from PIL import Image
from PIL.PngImagePlugin import PngInfo
import pytest

pytestmark = pytest.mark.integration


def write_png(path, parameters):
    png_info = PngInfo()
    png_info.add_text("parameters", parameters)
    Image.new("RGB", (1, 1), color="blue").save(path, pnginfo=png_info)


def test_build_prompt_index_for_batch(client, app_module):
    app_module.create_batch("alpha")
    write_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")

    response = client.post("/api/prompt-history/alpha/build")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["batch"] == "alpha"
    assert payload["prompt_count"] == 1


def test_get_cached_prompt_index_matches_built(client, app_module):
    app_module.create_batch("alpha")
    write_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
    built = client.post("/api/prompt-history/alpha/build").get_json()

    response = client.get("/api/prompt-history/alpha")

    assert response.status_code == 200
    assert response.get_json() == built


def test_rebuild_prompt_index_overwrites_cache(client, app_module):
    app_module.create_batch("alpha")
    write_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
    first = client.post("/api/prompt-history/alpha/build").get_json()
    write_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "two.png", "dog\nSteps: 1")

    second = client.post("/api/prompt-history/alpha/build").get_json()
    assert second["image_count"] == first["image_count"] + 1
    assert (
        client.get("/api/prompt-history/alpha").get_json()["image_count"] == second["image_count"]
    )


def test_staleness_check_false_when_counts_match(client, app_module):
    app_module.create_batch("alpha")
    write_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
    client.post("/api/prompt-history/alpha/build")

    response = client.get("/api/prompt-history/alpha?check_stale=true")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stale"] is False
    assert payload["current_image_count"] == 1


def test_staleness_check_ignores_non_png_review_images(client, app_module):
    app_module.create_batch("alpha")
    write_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
    Image.new("RGB", (1, 1), color="red").save(
        app_module.BATCHES_DIR / "alpha" / "inbox" / "sidecar.jpg"
    )
    client.post("/api/prompt-history/alpha/build")

    response = client.get("/api/prompt-history/alpha?check_stale=true")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stale"] is False
    assert payload["current_image_count"] == 1


def test_get_missing_prompt_index_returns_404(client, app_module):
    app_module.create_batch("alpha")

    response = client.get("/api/prompt-history/alpha")
    assert response.status_code == 404


def test_aggregate_endpoint_returns_all_built_indices(client, app_module):
    app_module.create_batch("alpha")
    app_module.create_batch("beta")
    write_png(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png", "cat\nSteps: 1")
    write_png(app_module.BATCHES_DIR / "beta" / "inbox" / "two.png", "dog\nSteps: 1")
    client.post("/api/prompt-history/alpha/build")
    client.post("/api/prompt-history/beta/build")

    response = client.get("/api/prompt-history")

    assert response.status_code == 200
    payload = response.get_json()
    assert sorted(payload["batches"].keys()) == ["alpha", "beta"]
    assert payload["total_prompts"] == 2
