import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image

SMALL_COUNT = 120
IMAGE_RE = re.compile(r"eval_cull_\d{4}\.(png|jpg|webp|gif)$")


def load_fixture_module():
    script_path = Path(__file__).parents[2] / "scripts" / "setup_evaluation_fixture.py"
    spec = importlib.util.spec_from_file_location("setup_evaluation_fixture", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["setup_evaluation_fixture"] = module
    spec.loader.exec_module(module)
    return module


def build(tmp_path):
    fixture = load_fixture_module()
    result = fixture.create_fixture(
        tmp_path, small_count=SMALL_COUNT, large_count=0, skip_large=True
    )
    return fixture, result


def test_fixture_builds_documented_layout(tmp_path):
    fixture, result = build(tmp_path)

    assert result.batches_dir == tmp_path / "batches"
    assert result.state_file == tmp_path / "state.json"
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {
        "active_batch": "eval-culling"
    }

    culling = tmp_path / "batches" / "eval-culling"
    for folder in ("inbox", "shortlisted", "finals", "rejects", "public"):
        assert (culling / folder).is_dir()

    manifest = json.loads((tmp_path / "fixture-manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == fixture.DEFAULT_SEED
    assert manifest["small_count"] == SMALL_COUNT
    assert manifest["skip_large"] is True
    for relative, expected in manifest["directory_counts"].items():
        directory = tmp_path / relative
        assert directory.is_dir()
        actual = sum(1 for path in directory.iterdir() if path.is_file())
        assert actual == expected

    inbox = culling / "inbox"
    assert len([p for p in inbox.iterdir() if IMAGE_RE.match(p.name)]) == SMALL_COUNT
    assert manifest["directory_counts"]["batches/eval-culling/inbox"] == (
        SMALL_COUNT + 4 + 2 + fixture.SIDECAR_COUNT + fixture.STALE_COUNT
    )

    assert (culling / ".favorites.json").is_file()
    assert (culling / "prompt-history.json").is_file()
    assert (culling / "search-index.json").is_file()
    assert (culling / "ai-curate" / "latest.json").is_file()
    assert len(list((culling / "ai-curate" / "runs").glob("*.json"))) == 2
    assert (inbox / "eval_cull_corrupt.png").is_file()
    assert (inbox / "eval_cull_zero.png").is_file()
    assert len(list((culling / "public").glob("*.png"))) == fixture.PUBLIC_COUNT
    assert not (tmp_path / "batches" / "eval-paging").exists()


def test_json_payload_shapes(tmp_path):
    fixture, result = build(tmp_path)
    culling = tmp_path / "batches" / "eval-culling"

    batch_favorites = json.loads((culling / ".favorites.json").read_text(encoding="utf-8"))
    universal = json.loads((tmp_path / "batches" / ".favorites.json").read_text(encoding="utf-8"))
    assert isinstance(batch_favorites["images"], list) and len(batch_favorites["images"]) == 12
    assert all(isinstance(name, str) for name in batch_favorites["images"])
    assert isinstance(universal["images"], list) and len(universal["images"]) == 8
    assert {"batch", "filename", "added_at"} <= set(universal["images"][0])

    run_files = sorted((culling / "ai-curate" / "runs").glob("*.json"))
    statuses = []
    for run_file in run_files:
        data = json.loads(run_file.read_text(encoding="utf-8"))
        for key in ("run_id", "batch", "status", "totals", "results", "elements", "quality_flags"):
            assert key in data
        assert isinstance(data["results"], list) and data["results"]
        assert {"images", "scored", "failed", "moved"} <= set(data["totals"])
        assert isinstance(data["results"][0]["details"], dict)
        statuses.append(data["status"])
    assert "completed" in statuses and "cancelled" in statuses

    latest = json.loads((culling / "ai-curate" / "latest.json").read_text(encoding="utf-8"))
    assert set(latest) == {"run_id"}

    prompt_index = json.loads((culling / "prompt-history.json").read_text(encoding="utf-8"))
    assert {"image_count", "prompt_count", "folder_counts", "prompts"} <= set(prompt_index)
    search = json.loads((culling / "search-index.json").read_text(encoding="utf-8"))
    assert search["version"] == 1
    assert {"item_count", "source_state", "items"} <= set(search)


def test_external_favorites_sidecar_schema(tmp_path):
    fixture, result = build(tmp_path)
    inbox = tmp_path / "batches" / "eval-culling" / "inbox"

    sidecars = [p for p in inbox.iterdir() if p.suffix == ".json"]
    assert len(sidecars) == fixture.SIDECAR_COUNT
    external = [
        p
        for p in sidecars
        if json.loads(p.read_text(encoding="utf-8")).get("category") == "external_favorites"
    ]
    assert len(external) == 15
    for path in external:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["subcategory"] in ("post", "favorite")
        assert isinstance(data["tags"], str)
        assert isinstance(data["id"], str)
        assert isinstance(data["post_id"], str)
        assert isinstance(data["favorite_id"], int)
        assert isinstance(data["total"], int)


def test_determinism_same_seed(tmp_path):
    fixture = load_fixture_module()
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    fixture.create_fixture(root_a, small_count=SMALL_COUNT, large_count=0, skip_large=True)
    fixture.create_fixture(root_b, small_count=SMALL_COUNT, large_count=0, skip_large=True)

    rel_a = sorted(str(path.relative_to(root_a)) for path in root_a.rglob("*") if path.is_file())
    rel_b = sorted(str(path.relative_to(root_b)) for path in root_b.rglob("*") if path.is_file())
    assert rel_a == rel_b

    sample = Path("batches") / "eval-culling" / "inbox" / "eval_cull_0101.png"
    assert (root_a / sample).read_bytes() == (root_b / sample).read_bytes()


def test_verify_passes_then_fails(tmp_path):
    fixture, result = build(tmp_path)

    ok, problems = fixture.verify_fixture(tmp_path)
    assert ok, problems

    (tmp_path / "state.json").unlink()
    ok, problems = fixture.verify_fixture(tmp_path)
    assert not ok
    assert any("state.json" in problem for problem in problems)


def test_verify_cli_returns_nonzero_on_failure(tmp_path, monkeypatch):
    fixture, result = build(tmp_path)
    (tmp_path / "state.json").unlink()

    monkeypatch.setattr(
        sys, "argv", ["setup_evaluation_fixture.py", "--root", str(tmp_path), "--verify"]
    )
    assert fixture.main() == 1


def test_corrupt_file_not_decodable(tmp_path):
    fixture, result = build(tmp_path)
    corrupt = tmp_path / "batches" / "eval-culling" / "inbox" / "eval_cull_corrupt.png"

    with pytest.raises(Exception):
        with Image.open(corrupt) as image:
            image.verify()


def _png_parameters(path):
    with Image.open(path) as image:
        return image.text["parameters"]


def test_near_duplicate_pairs_share_token_group(tmp_path):
    fixture, result = build(tmp_path)
    inbox = tmp_path / "batches" / "eval-culling" / "inbox"

    for pair_index in range(3):
        first_name = f"eval_cull_{100 + pair_index * 2 + 1:04d}.png"
        second_name = f"eval_cull_{100 + pair_index * 2 + 2:04d}.png"
        first_prompt = _png_parameters(inbox / first_name).splitlines()[0]
        second_prompt = _png_parameters(inbox / second_name).splitlines()[0]

        shared_group = fixture.TOKEN_GROUPS[pair_index % 6]
        assert first_prompt.startswith(shared_group)
        assert second_prompt.startswith(shared_group)

        pair_marker = f"near-duplicate study pair {pair_index}"
        assert pair_marker in first_prompt
        assert pair_marker in second_prompt
