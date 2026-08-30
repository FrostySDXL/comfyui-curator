import json
import time


def test_search_api_builds_sidecar_index_and_filters_folder_scope(client, app_module, make_file):
    app_module.create_batch("external")
    inbox = app_module.BATCHES_DIR / "external" / "inbox"
    finals = app_module.BATCHES_DIR / "external" / "finals"
    make_file(inbox / "blue.jpg")
    make_file(finals / "red.jpg")
    (inbox / "blue.jpg.json").write_text(
        json.dumps({"tags": "blue_hair portrait"}), encoding="utf-8"
    )
    (finals / "red.jpg.json").write_text(
        json.dumps({"tags": "red_hair portrait"}), encoding="utf-8"
    )

    built = client.post("/api/search-index/external/build")
    response = client.get(
        "/api/search",
        query_string={"q": "portrait", "batch": "external", "folder": "inbox"},
    )

    assert built.status_code == 200
    assert built.get_json()["item_count"] == 2
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 1
    assert payload["items"][0]["name"] == "blue.jpg"
    assert payload["indexed_batches"] == ["external"]
    assert payload["missing_batches"] == []
    assert payload["index_statuses"][0]["batch"] == "external"
    assert payload["index_statuses"][0]["status"] == "ready"
    assert payload["index_statuses"][0]["item_count"] == 2
    assert payload["index_statuses"][0]["built_at"]


def test_search_api_validates_scope_and_limit(client, app_module):
    app_module.create_batch("safe")

    missing_batch = client.get("/api/search", query_string={"q": "x", "batch": "missing"})
    invalid_folder = client.get(
        "/api/search", query_string={"q": "x", "batch": "safe", "folder": "../inbox"}
    )
    invalid_limit = client.get("/api/search", query_string={"q": "x", "limit": "many"})

    assert missing_batch.status_code == 404
    assert invalid_folder.status_code == 400
    assert invalid_limit.status_code == 400


def test_search_api_pages_results_with_a_stable_snapshot(client, app_module, make_file):
    app_module.create_batch("large")
    inbox = app_module.BATCHES_DIR / "large" / "inbox"
    for number in range(5):
        make_file(inbox / f"match-{number}.jpg")
    assert client.post("/api/search-index/large/build").status_code == 200

    first = client.get(
        "/api/search",
        query_string={"q": "match", "batch": "large", "limit": 2},
    ).get_json()
    second_response = client.get(
        "/api/search",
        query_string={
            "q": "match",
            "batch": "large",
            "limit": 2,
            "offset": first["next_offset"],
            "snapshot": first["snapshot"],
        },
    )

    assert second_response.status_code == 200
    second = second_response.get_json()
    assert [item["name"] for item in second["items"]] == [
        "match-2.jpg",
        "match-3.jpg",
    ]
    assert second["offset"] == 2
    assert second["next_offset"] == 4
    assert second["has_more"] is True
    assert second["snapshot"] == first["snapshot"]


def test_search_index_job_routes_report_terminal_status_and_cancel_completed_job(
    client, app_module
):
    app_module.create_batch("async")

    submitted = client.post("/api/search-index/async/jobs")
    assert submitted.status_code == 202
    job_id = submitted.get_json()["job_id"]
    assert submitted.get_json()["status"] in {"queued", "running"}

    deadline = time.monotonic() + 2
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/api/search-index/jobs/{job_id}")
        if status.get_json()["status"] == "completed":
            break
        time.sleep(0.01)
    assert status is not None
    assert status.status_code == 200
    assert status.get_json()["status"] == "completed"
    assert (app_module.BATCHES_DIR / "async" / "search-index.json").is_file()

    cancelled = client.post(f"/api/search-index/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.get_json()["status"] == "completed"
    assert cancelled.get_json()["cancel_accepted"] is False
    assert client.get("/api/search-index/jobs/missing").status_code == 404
