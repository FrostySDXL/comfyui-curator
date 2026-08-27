import importlib.util
from pathlib import Path

import pytest


def load_generator():
    path = Path(__file__).parents[2] / "scripts" / "generate_curator_template.py"
    spec = importlib.util.spec_from_file_location("generate_curator_template", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_transform_replaces_static_paths_and_inserts_native_marker():
    generator = load_generator()

    source = '<link href="/static/css/base.css">\n<script src="/static/js/state.js"></script>\n'

    assert generator.transform(source) == (
        '<link href="/curator_static/css/base.css">\n'
        "<script>window.CURATOR_NATIVE = true;</script>\n    "
        '<script src="/curator_static/js/state.js"></script>\n'
    )


def test_transform_inserts_before_first_script_src_even_with_preceding_vendor_script():
    generator = load_generator()

    source = '<script src="/vendor.js"></script>\n<script src="/static/js/state.js"></script>\n'
    result = generator.transform(source)

    assert result.startswith(
        '<script>window.CURATOR_NATIVE = true;</script>\n    <script src="/vendor.js"></script>\n'
    )
    assert "/curator_static/js/state.js" in result


def test_transform_rejects_existing_native_marker():
    generator = load_generator()

    with pytest.raises(ValueError, match="already contains"):
        generator.transform(
            '<script>window.CURATOR_NATIVE = true;</script>\n<script src="/static/js/a.js">'
        )


def test_transform_reports_missing_ordered_script():
    generator = load_generator()

    with pytest.raises(ValueError, match="no ordered script tag"):
        generator.transform("<p>no scripts</p>\n")


def test_transform_matches_shipped_template():
    generator = load_generator()
    source = Path("templates/index.html").read_text(encoding="utf-8")
    expected = Path("templates/curator.html").read_text(encoding="utf-8")

    assert generator.transform(source) == expected


def test_write_is_noop_when_output_is_current(tmp_path):
    generator = load_generator()
    source = tmp_path / "index.html"
    output = tmp_path / "curator.html"
    source.write_text('<script src="/static/js/state.js"></script>\n', encoding="utf-8")
    generator.write(source, output)
    before = output.stat().st_mtime_ns

    assert generator.write(source, output) is False
    assert output.stat().st_mtime_ns == before


def test_check_reports_missing_or_stale_output(tmp_path, capsys):
    generator = load_generator()
    source = tmp_path / "index.html"
    output = tmp_path / "curator.html"
    source.write_text('<script src="/static/js/state.js"></script>\n', encoding="utf-8")

    assert generator.check(source, output) is False
    message = capsys.readouterr().out.lower()
    assert "missing" in message
    assert "python scripts/generate_curator_template.py --write" in message
    assert not output.exists()

    output.write_text("stale", encoding="utf-8")
    before = output.read_bytes()
    before_mtime = output.stat().st_mtime_ns
    assert generator.check(source, output) is False
    assert "stale" in capsys.readouterr().out.lower()
    assert output.read_bytes() == before
    assert output.stat().st_mtime_ns == before_mtime


def test_check_accepts_current_output(tmp_path):
    generator = load_generator()
    source = tmp_path / "index.html"
    output = tmp_path / "curator.html"
    source.write_text('<script src="/static/js/state.js"></script>\n', encoding="utf-8")
    output.write_text(generator.transform(source.read_text(encoding="utf-8")), encoding="utf-8")

    assert generator.check(source, output) is True


def test_invalid_source_check_preserves_existing_output(tmp_path, capsys):
    generator = load_generator()
    source = tmp_path / "index.html"
    output = tmp_path / "curator.html"
    source.write_text("<p>invalid</p>\n", encoding="utf-8")
    output.write_bytes(b"existing")

    assert generator.check(source, output) is False
    assert "no ordered script tag" in capsys.readouterr().out
    assert output.read_bytes() == b"existing"


def test_check_reports_invalid_output_encoding(tmp_path, capsys):
    generator = load_generator()
    source = tmp_path / "index.html"
    output = tmp_path / "curator.html"
    source.write_text('<script src="/static/js/state.js"></script>\n', encoding="utf-8")
    output.write_bytes(b"\xff")

    assert generator.check(source, output) is False
    assert "utf-8" in capsys.readouterr().out.lower()


def test_write_repairs_invalid_utf8_output_without_changing_source(tmp_path):
    generator = load_generator()
    source = tmp_path / "index.html"
    output = tmp_path / "curator.html"
    source_bytes = b'<script src="/static/js/state.js"></script>\n'
    source.write_bytes(source_bytes)
    output.write_bytes(b"\xff")

    assert generator.write(source, output) is True
    assert source.read_bytes() == source_bytes
    assert generator.check(source, output) is True


def test_write_invalid_source_preserves_existing_output(tmp_path):
    generator = load_generator()
    source = tmp_path / "index.html"
    output = tmp_path / "curator.html"
    source.write_text("<p>invalid</p>\n", encoding="utf-8")
    output.write_bytes(b"existing")

    with pytest.raises(ValueError):
        generator.write(source, output)
    assert output.read_bytes() == b"existing"


def test_check_requires_explicit_write_or_check_mode(monkeypatch):
    generator = load_generator()

    with pytest.raises(SystemExit):
        generator.parse_args([])

    assert generator.parse_args(["--check"]).check is True
    assert generator.parse_args(["--write"]).write is True


def test_main_returns_check_and_write_statuses(monkeypatch):
    generator = load_generator()
    monkeypatch.setattr(generator, "check", lambda: True)
    assert generator.main(["--check"]) == 0
    monkeypatch.setattr(generator, "check", lambda: False)
    assert generator.main(["--check"]) == 1
    monkeypatch.setattr(generator, "write", lambda: False)
    assert generator.main(["--write"]) == 0
