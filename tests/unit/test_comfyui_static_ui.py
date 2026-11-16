"""Unit tests for the native ComfyUI template and URL compatibility."""

import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.unit.frontend_source import read_frontend_js

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# curator.html structure
# ---------------------------------------------------------------------------


class TestCuratorHtmlStructure:
    """curator.html is the sole authoritative template."""

    def _read(self):
        return (REPO_ROOT / "templates" / "curator.html").read_text(encoding="utf-8")

    def test_uses_curator_static_css(self):
        html = self._read()
        assert "/curator_static/css/" in html
        assert "/static/css/" not in html

    def test_uses_curator_static_js(self):
        html = self._read()
        assert "/curator_static/js/" in html
        assert "/static/js/" not in html

    def test_is_the_only_template(self):
        assert not (REPO_ROOT / "templates" / "index.html").exists()
        assert sorted(path.name for path in (REPO_ROOT / "templates").glob("*.html")) == [
            "curator.html"
        ]

    def test_has_no_standalone_mode_flag(self):
        html = self._read()
        assert "CURATOR_NATIVE" not in html
        assert "CURATOR_NATIVE" not in read_frontend_js()

    def test_preserves_jinja_model_block(self):
        html = self._read()
        assert "{% if available_models %}" in html
        assert "{% for model in available_models %}" in html


class TestPageBootAssets:
    """The native page references the locally shipped ordered assets."""

    def test_all_css_and_js_references_exist_locally(self):
        html = (REPO_ROOT / "templates" / "curator.html").read_text(encoding="utf-8")
        references = re.findall(r'(?:href|src)="/(curator_static)/([^"?]+)"', html)

        assert references, "curator.html should reference local page assets"
        missing = [
            f"{prefix}/{asset}"
            for prefix, asset in references
            if not (REPO_ROOT / "static" / asset).is_file()
        ]
        assert not missing, f"curator.html references missing local assets: {missing}"


# ---------------------------------------------------------------------------
# Page handler context
# ---------------------------------------------------------------------------


class TestCuratorManagerPageHandlerContext:
    def _setup_mocks(self, tmp_path, monkeypatch):
        for mod in ("server", "aiohttp", "aiohttp.web", "jinja2", "folder_paths"):
            sys.modules.pop(mod, None)

        mock_web = MagicMock()
        mock_web.json_response = MagicMock()
        mock_web.Response = MagicMock(return_value=MagicMock(status=200))
        mock_aiohttp = MagicMock()
        mock_aiohttp.web = mock_web
        sys.modules["aiohttp"] = mock_aiohttp
        sys.modules["aiohttp.web"] = mock_web

        mock_server = MagicMock()
        mock_ps = MagicMock()
        mock_ps.instance.app = MagicMock()
        mock_ps.instance.app.router = MagicMock()
        mock_server.PromptServer = mock_ps
        sys.modules["server"] = mock_server

        mock_jinja2 = MagicMock()
        sys.modules["jinja2"] = mock_jinja2

        mock_folder_paths = MagicMock()
        mock_folder_paths.get_system_user_directory.return_value = str(tmp_path / "system")
        mock_folder_paths.get_output_directory.return_value = str(tmp_path / "output")
        sys.modules["folder_paths"] = mock_folder_paths

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "py.curator_manager", REPO_ROOT / "py" / "curator_manager.py"
        )
        cm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cm)

        from image_curator.native_settings import NativeCuratorSettings

        settings = NativeCuratorSettings(
            batch_root=tmp_path / "batches",
            import_source=tmp_path / "output",
            state_file=tmp_path / "system" / "state.json",
            available_models=("native-model",),
            default_model="native-model",
        )
        monkeypatch.setattr(
            cm.NativeCuratorSettings,
            "from_host_paths",
            classmethod(lambda cls, **kwargs: settings),
        )
        return cm, mock_jinja2

    def test_page_handler_passes_configured_native_models(self, tmp_path, monkeypatch):
        cm, mock_jinja2 = self._setup_mocks(tmp_path, monkeypatch)
        cm.CuratorManager._registered = False

        import asyncio

        mock_template = MagicMock()
        mock_template.render.return_value = MagicMock()
        mock_env = MagicMock()
        mock_env.get_template.return_value = mock_template
        mock_jinja2.Environment.return_value = mock_env

        cm.CuratorManager.add_routes()

        calls = sys.modules["server"].PromptServer.instance.app.router.add_get.call_args_list
        page_call = next((c for c in calls if len(c[0]) >= 2 and c[0][0] == "/curator"), None)
        assert page_call is not None

        handler = page_call[0][1] if len(page_call[0]) >= 2 else page_call[1]["handler"]
        result = asyncio.run(handler(MagicMock()))
        assert result.status == 200

        kwargs = mock_template.render.call_args[1]
        assert kwargs == {
            "available_models": ["native-model"],
            "default_model": "native-model",
        }

    def test_does_not_import_env_config(self):
        source = (REPO_ROOT / "py" / "curator_manager.py").read_text(encoding="utf-8")
        assert "ai_curate.config" not in source
        assert "load_dotenv" not in source


# ---------------------------------------------------------------------------
# URL helpers -- unconditional native paths
# ---------------------------------------------------------------------------


def _extract_cc_helpers():
    """Extract the URL helpers from state.js for node evaluation."""
    source = read_frontend_js()
    start = source.index("function ccApiPath(path)")
    end = source.index("const SIDEBAR_WIDTH_KEY")
    return source[start:end]


class TestCcPathBehavior:
    """Verify the unconditional native URL helpers using node subprocess."""

    def _eval(self, expr):
        code = _extract_cc_helpers() + "\nconsole.log(JSON.stringify(" + expr + "));"
        result = subprocess.run(
            ["node", "-e", code],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise AssertionError(f"node failed: {result.stderr}")
        return json.loads(result.stdout.strip())

    def test_maps_api_routes(self):
        assert self._eval('ccApiPath("/api/batches")') == "/api/curator/batches"

    def test_maps_ai_routes(self):
        assert self._eval('ccApiPath("/api/ai-curate/jobs")') == "/api/curator/ai-curate/jobs"

    def test_no_double_prefix(self):
        assert self._eval('ccApiPath("/api/curator/batches")') == "/api/curator/batches"

    def test_preserves_query_string(self):
        assert (
            self._eval('ccApiPath("/api/images/b/x?sort=date")')
            == "/api/curator/images/b/x?sort=date"
        )

    def test_non_api_paths_are_unchanged(self):
        assert self._eval('ccApiPath("/curator/thumb/a")') == "/curator/thumb/a"

    def test_thumb_url_is_always_native(self):
        assert self._eval('ccThumbUrl("b","f","n.png")') == "/curator/thumb/b/f/n.png"

    def test_image_url_is_always_native(self):
        assert self._eval('ccImageUrl("b","f","n.png")') == "/curator/image/b/f/n.png"

    def test_preview_url_is_always_native(self):
        assert self._eval('ccPreviewUrl("b","f","n.png")') == "/curator/preview/b/f/n.png"

    def test_thumb_encodes_params(self):
        result = self._eval('ccThumbUrl("my batch","inbox","image (1).png")')
        assert "%20" in result
        assert "(" in result


class TestNoRawFetchBypass:
    """No fetch() call receives a raw /api/..., /thumb/, or /image/ URL."""

    def test_no_raw_api_in_fetch(self):
        source = read_frontend_js()
        raw = set()
        for m in re.finditer(r"fetch\s*\(\s*(['\"`])(/api/[^'\"`]+?)\1", source):
            raw.add(m.group(2))
        assert not raw, f"raw /api/ in fetch(): {raw}"

    def test_no_raw_thumb_in_source(self):
        source = read_frontend_js()
        matches = list(re.finditer(r"['\"`](\/thumb\/[^'\"`]+)['\"`]", source))
        assert not matches, f"raw /thumb/ URLs: {[m.group(1) for m in matches]}"

    def test_no_raw_image_in_source(self):
        source = read_frontend_js()
        matches = list(re.finditer(r"['\"`](\/image\/[^'\"`]+)['\"`]", source))
        assert not matches, f"raw /image/ URLs: {[m.group(1) for m in matches]}"


# ---------------------------------------------------------------------------
# Error propagation (safe, tmp_path-based)
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    """ModuleNotFoundError for non-server modules propagates through __init__.py."""

    def _build_temp_package(self, tmp_path, curator_manager_content):
        pkg = tmp_path / "test_pkg"
        pkg.mkdir()
        py_dir = pkg / "py"
        py_dir.mkdir()
        (py_dir / "curator_manager.py").write_text(curator_manager_content, encoding="utf-8")
        image_curator_dir = pkg / "image_curator"
        image_curator_dir.mkdir()
        (image_curator_dir / "__init__.py").write_text("", encoding="utf-8")
        ai_curate_dir = pkg / "ai_curate"
        ai_curate_dir.mkdir()
        (ai_curate_dir / "__init__.py").write_text("", encoding="utf-8")

        init_src = (REPO_ROOT / "__init__.py").read_text(encoding="utf-8")
        (pkg / "__init__.py").write_text(init_src, encoding="utf-8")
        return pkg

    @pytest.fixture(autouse=True)
    def _clean_caches(self):
        saved = {}
        for key in ("server", "aiohttp", "aiohttp.web", "jinja2", "py.curator_manager"):
            if key in sys.modules:
                saved[key] = sys.modules.pop(key)
        yield
        for key, mod in saved.items():
            if key not in sys.modules:
                sys.modules[key] = mod

    def _assert_propagates(self, tmp_path, import_name):
        import importlib.util

        cm_content = f"import {import_name}\n"
        pkg = self._build_temp_package(tmp_path, cm_content)

        init_path = pkg / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "test_pkg_e",
            str(init_path),
            submodule_search_locations=[str(pkg)],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["test_pkg_e"] = mod
        try:
            with pytest.raises(ModuleNotFoundError) as exc_info:
                spec.loader.exec_module(mod)
            assert exc_info.value.name == import_name
        finally:
            for name in tuple(sys.modules):
                if name == "test_pkg_e" or name.startswith("test_pkg_e."):
                    sys.modules.pop(name, None)

    def test_arbitrary_non_server_error_propagates(self, tmp_path):
        self._assert_propagates(tmp_path, "nonexistent_module_xyz")

    def test_aiohttp_missing_propagates(self, tmp_path):
        self._assert_propagates(tmp_path, "nonexistent_aiohttp_lib")

    def test_jinja2_missing_propagates(self, tmp_path):
        self._assert_propagates(tmp_path, "nonexistent_jinja2_lib")


class TestModeSelection:
    def test_state_js_has_no_mode_detection(self):
        source = read_frontend_js()
        assert "CURATOR_NATIVE" not in source

    def test_helpers_defined(self):
        source = read_frontend_js()
        for name in ("ccApiPath", "ccThumbUrl", "ccImageUrl", "ccPreviewUrl"):
            assert f"function {name}(" in source, f"missing: {name}"
