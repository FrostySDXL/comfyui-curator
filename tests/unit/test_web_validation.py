from pathlib import Path

from image_curator.web_validation import require_existing_batch, safe_path


def test_safe_path_allows_file_inside_base(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "file.png").write_text("")

    resolved, err = safe_path(base, "file.png")

    assert err is None
    assert resolved == (base / "file.png").resolve()


def test_safe_path_allows_nested_file_inside_base(tmp_path):
    base = tmp_path / "base"
    (base / "sub").mkdir(parents=True)

    resolved, err = safe_path(base, "sub", "file.png")

    assert err is None
    assert resolved == (base / "sub" / "file.png").resolve()


def test_safe_path_blocks_parent_traversal(tmp_path):
    base = tmp_path / "base"
    base.mkdir()

    resolved, err = safe_path(base, "..", "outside.png")

    assert resolved is None
    assert err == "Invalid path"


def test_safe_path_blocks_absolute_path(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    absolute = str((tmp_path / "other" / "file.png").resolve())

    resolved, err = safe_path(base, absolute)

    assert resolved is None
    assert err == "Invalid path"


def test_require_existing_batch_accepts_known_batch():
    batch, err = require_existing_batch("alpha", lambda: ["alpha", "beta"])

    assert batch == "alpha"
    assert err is None


def test_require_existing_batch_rejects_missing_batch():
    batch, err = require_existing_batch("missing", lambda: ["alpha"])

    assert batch is None
    assert err == ({"error": "Batch does not exist"}, 404)


def test_require_existing_batch_rejects_blank_batch():
    batch, err = require_existing_batch("", lambda: ["alpha"])

    assert batch is None
    assert err == ({"error": "Batch does not exist"}, 404)


def test_safe_path_blocks_absolute_path_object(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    absolute = Path(tmp_path / "other" / "file.png")

    resolved, err = safe_path(base, str(absolute))

    assert resolved is None
    assert err == "Invalid path"
