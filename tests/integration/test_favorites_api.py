import pytest

pytestmark = pytest.mark.integration


def test_empty_batch_favorites_returns_empty_list(client, create_batch):
    create_batch("alpha")

    response = client.get("/api/curator/favorites/alpha")

    assert response.status_code == 200
    assert response.get_json() == {"filenames": []}


def test_toggle_favorite_adds_batch_and_universal(client, create_batch, native_settings, make_file):
    create_batch("alpha")
    make_file(native_settings.batch_root / "alpha" / "inbox" / "one.png")

    response = client.post("/api/curator/favorites/alpha", json_body={"filename": "one.png"})

    assert response.status_code == 200
    assert response.get_json() == {"batch": True, "universal": True}
    assert client.get("/api/curator/favorites/alpha").get_json() == {"filenames": ["one.png"]}
    assert client.get("/api/curator/favorites").get_json()["favorites"][0]["folder"] == "inbox"


def test_toggle_favorite_removes_from_batch_and_universal(
    client, create_batch, native_settings, make_file
):
    create_batch("alpha")
    make_file(native_settings.batch_root / "alpha" / "inbox" / "one.png")
    client.post("/api/curator/favorites/alpha", json_body={"filename": "one.png"})

    response = client.post("/api/curator/favorites/alpha", json_body={"filename": "one.png"})

    assert response.status_code == 200
    assert response.get_json() == {"batch": False, "universal": False}
    assert client.get("/api/curator/favorites/alpha").get_json() == {"filenames": []}
    assert client.get("/api/curator/favorites").get_json() == {"favorites": []}


def test_images_response_includes_favorite_field(client, create_batch, native_settings, make_file):
    create_batch("alpha")
    make_file(native_settings.batch_root / "alpha" / "inbox" / "one.png")
    client.post("/api/curator/favorites/alpha", json_body={"filename": "one.png"})

    response = client.get("/api/curator/images/alpha/inbox")

    assert response.status_code == 200
    assert response.get_json()[0]["favorite"] is True


def test_universal_post_resolves_correct_folder(client, create_batch, native_settings, make_file):
    create_batch("alpha")
    make_file(native_settings.batch_root / "alpha" / "finals" / "one.png")

    response = client.post(
        "/api/curator/favorites", json_body={"batch": "alpha", "filename": "one.png"}
    )

    assert response.status_code == 200
    favorite = client.get("/api/curator/favorites").get_json()["favorites"][0]
    assert favorite["batch"] == "alpha"
    assert favorite["folder"] == "finals"
