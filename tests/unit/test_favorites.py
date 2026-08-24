import json

from image_curator.favorites import (
    get_batch_favorite_filenames,
    load_favorites,
    resolve_universal_favorites,
    save_favorites,
    toggle_favorite,
)


def make_batch(batches_dir, batch="alpha"):
    for folder in ("inbox", "shortlisted", "finals", "rejects"):
        (batches_dir / batch / folder).mkdir(parents=True, exist_ok=True)


def test_load_empty_favorites_for_batch_and_universal(tmp_path):
    assert load_favorites(tmp_path, "alpha") == []
    assert load_favorites(tmp_path) == []


def test_save_load_batch_roundtrip(tmp_path):
    save_favorites(tmp_path, ["one.png", "two.png"], "alpha")

    assert load_favorites(tmp_path, "alpha") == ["one.png", "two.png"]


def test_save_load_universal_roundtrip(tmp_path):
    data = [{"batch": "alpha", "filename": "one.png", "added_at": "now"}]
    save_favorites(tmp_path, data)

    assert load_favorites(tmp_path) == data


def test_toggle_adds_to_both_scopes(tmp_path):
    make_batch(tmp_path)

    result = toggle_favorite(tmp_path, "alpha", "one.png")

    assert result == {"batch": True, "universal": True}
    assert load_favorites(tmp_path, "alpha") == ["one.png"]
    universal = load_favorites(tmp_path)
    assert universal[0]["batch"] == "alpha"
    assert universal[0]["filename"] == "one.png"


def test_toggle_removes_from_both_scopes(tmp_path):
    make_batch(tmp_path)
    toggle_favorite(tmp_path, "alpha", "one.png")

    result = toggle_favorite(tmp_path, "alpha", "one.png")

    assert result == {"batch": False, "universal": False}
    assert load_favorites(tmp_path, "alpha") == []
    assert load_favorites(tmp_path) == []


def test_get_batch_favorite_filenames_returns_set(tmp_path):
    save_favorites(tmp_path, ["b.png", "a.png"], "alpha")

    assert get_batch_favorite_filenames(tmp_path, "alpha") == {"a.png", "b.png"}


def test_resolve_universal_favorites_includes_present_file_folder(tmp_path):
    make_batch(tmp_path)
    (tmp_path / "alpha" / "shortlisted" / "one.png").write_bytes(b"x")
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "one.png", "added_at": "now"}])

    assert resolve_universal_favorites(tmp_path) == [
        {
            "batch": "alpha",
            "filename": "one.png",
            "folder": "shortlisted",
            "size": 1,
            "added_at": "now",
        }
    ]


def test_resolve_universal_favorites_includes_typed_media(tmp_path):
    make_batch(tmp_path)
    for filename in ("animation.gif", "clip.mp4", "track.mp3"):
        (tmp_path / "alpha" / "inbox" / filename).write_bytes(b"media")
    save_favorites(
        tmp_path,
        [
            {"batch": "alpha", "filename": filename, "added_at": "now"}
            for filename in ("animation.gif", "clip.mp4", "track.mp3")
        ],
    )

    resolved = resolve_universal_favorites(tmp_path)

    assert {item["filename"] for item in resolved} == {
        "animation.gif",
        "clip.mp4",
        "track.mp3",
    }


def test_resolve_universal_favorites_skips_missing_files(tmp_path):
    make_batch(tmp_path)
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "missing.png", "added_at": "now"}])

    assert resolve_universal_favorites(tmp_path) == []


def test_atomic_write_leaves_no_tmp_residue(tmp_path):
    save_favorites(tmp_path, ["one.png"], "alpha")

    assert not list((tmp_path / "alpha").glob("*.tmp"))


def test_load_corrupt_favorites_returns_empty(tmp_path):
    path = tmp_path / "alpha" / ".favorites.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    assert load_favorites(tmp_path, "alpha") == []


def test_batch_storage_shape_is_images_array(tmp_path):
    save_favorites(tmp_path, ["one.png"], "alpha")

    data = json.loads((tmp_path / "alpha" / ".favorites.json").read_text(encoding="utf-8"))

    assert data == {"images": ["one.png"]}


def test_universal_storage_shape_is_images_array(tmp_path):
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "one.png", "added_at": "now"}])

    data = json.loads((tmp_path / ".favorites.json").read_text(encoding="utf-8"))

    assert data == {"images": [{"batch": "alpha", "filename": "one.png", "added_at": "now"}]}


def test_resolve_universal_favorites_skips_symlinked_file(tmp_path, monkeypatch):
    from pathlib import Path

    make_batch(tmp_path)
    file_path = tmp_path / "alpha" / "inbox" / "one.png"
    file_path.write_bytes(b"data")
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "one.png", "added_at": "now"}])

    real_is_symlink = Path.is_symlink

    def is_symlink(path, *args, **kwargs):
        if path == file_path:
            return True
        return real_is_symlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    assert resolve_universal_favorites(tmp_path) == []


def test_resolve_universal_favorites_skips_symlinked_stage(tmp_path, monkeypatch):
    from pathlib import Path

    make_batch(tmp_path)
    file_path = tmp_path / "alpha" / "inbox" / "one.png"
    file_path.write_bytes(b"data")
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "one.png", "added_at": "now"}])

    real_is_symlink = Path.is_symlink

    def is_symlink(path, *args, **kwargs):
        if path == tmp_path / "alpha" / "inbox":
            return True
        return real_is_symlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    assert resolve_universal_favorites(tmp_path) == []


def test_resolve_universal_favorites_skips_unsupported_extension(tmp_path):
    make_batch(tmp_path)
    (tmp_path / "alpha" / "inbox" / "notes.txt").write_text("text", encoding="utf-8")
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "notes.txt", "added_at": "now"}])

    assert resolve_universal_favorites(tmp_path) == []


def test_resolve_universal_favorites_skips_non_regular_file(tmp_path):
    make_batch(tmp_path)
    (tmp_path / "alpha" / "inbox" / "subdir").mkdir()
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "subdir", "added_at": "now"}])

    assert resolve_universal_favorites(tmp_path) == []


def test_resolve_universal_favorites_skips_resolved_escape(tmp_path, monkeypatch):
    from pathlib import Path

    make_batch(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escaped.png").write_bytes(b"escaped")
    file_path = tmp_path / "alpha" / "inbox" / "escaped.png"
    file_path.write_bytes(b"data")
    save_favorites(tmp_path, [{"batch": "alpha", "filename": "escaped.png", "added_at": "now"}])

    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == file_path:
            return outside / "escaped.png"
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert resolve_universal_favorites(tmp_path) == []


def test_load_favorites_rejects_symlinked_universal_store(tmp_path, monkeypatch):
    from pathlib import Path

    store = tmp_path / ".favorites.json"
    store.write_text(
        '{"images": [{"batch": "a", "filename": "x.png", "added_at": "t"}]}', encoding="utf-8"
    )

    real_is_symlink = Path.is_symlink

    def is_symlink(path, *args, **kwargs):
        if path == store:
            return True
        return real_is_symlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    assert load_favorites(tmp_path) == []


def test_load_favorites_rejects_symlinked_batch_store(tmp_path, monkeypatch):
    from pathlib import Path

    make_batch(tmp_path)
    store = tmp_path / "alpha" / ".favorites.json"
    store.write_text('{"images": ["one.png"]}', encoding="utf-8")

    real_is_symlink = Path.is_symlink

    def is_symlink(path, *args, **kwargs):
        if path == store:
            return True
        return real_is_symlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    assert load_favorites(tmp_path, "alpha") == []


def test_find_file_folder_oserror_on_symlink_returns_none(tmp_path, monkeypatch):
    from pathlib import Path

    make_batch(tmp_path)
    (tmp_path / "alpha" / "inbox" / "one.png").write_bytes(b"data")

    real_is_symlink = Path.is_symlink

    def is_symlink(path, *args, **kwargs):
        if path == tmp_path / "alpha" / "inbox":
            raise OSError("unreachable")
        return real_is_symlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    from image_curator.favorites import _find_file_folder

    assert _find_file_folder(tmp_path, "alpha", "one.png") is None
