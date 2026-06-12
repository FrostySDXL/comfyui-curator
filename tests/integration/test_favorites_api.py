import pytest

pytestmark = pytest.mark.integration


def test_empty_batch_favorites_returns_empty_list(client, app_module):
    app_module.create_batch("alpha")

    response = client.get("/api/favorites/alpha")

    assert response.status_code == 200
    assert response.get_json() == {"filenames": []}


def test_toggle_favorite_adds_batch_and_universal(client, app_module, make_file):
    app_module.create_batch("alpha")
    make_file(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png")

    response = client.post("/api/favorites/alpha", json={"filename": "one.png"})

    assert response.status_code == 200
    assert response.get_json() == {"batch": True, "universal": True}
    assert client.get("/api/favorites/alpha").get_json() == {"filenames": ["one.png"]}
    assert client.get("/api/favorites").get_json()["favorites"][0]["folder"] == "inbox"


def test_toggle_favorite_removes_from_batch_and_universal(client, app_module, make_file):
    app_module.create_batch("alpha")
    make_file(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png")
    client.post("/api/favorites/alpha", json={"filename": "one.png"})

    response = client.post("/api/favorites/alpha", json={"filename": "one.png"})

    assert response.status_code == 200
    assert response.get_json() == {"batch": False, "universal": False}
    assert client.get("/api/favorites/alpha").get_json() == {"filenames": []}
    assert client.get("/api/favorites").get_json() == {"favorites": []}


def test_images_response_includes_favorite_field(client, app_module, make_file):
    app_module.create_batch("alpha")
    make_file(app_module.BATCHES_DIR / "alpha" / "inbox" / "one.png")
    client.post("/api/favorites/alpha", json={"filename": "one.png"})

    response = client.get("/api/images/alpha/inbox")

    assert response.status_code == 200
    assert response.get_json()[0]["favorite"] is True


def test_universal_post_resolves_correct_folder(client, app_module, make_file):
    app_module.create_batch("alpha")
    make_file(app_module.BATCHES_DIR / "alpha" / "finals" / "one.png")

    response = client.post("/api/favorites", json={"batch": "alpha", "filename": "one.png"})

    assert response.status_code == 200
    favorite = client.get("/api/favorites").get_json()["favorites"][0]
    assert favorite["batch"] == "alpha"
    assert favorite["folder"] == "finals"
