"""Unit tests for ComfyUI native template and URL compatibility."""

import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.unit.frontend_source import read_frontend_js

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Template parity
# ---------------------------------------------------------------------------


class TestTemplateParity:
    """curator.html equals index.html after two intentional transforms."""

    def _read_html(self, name):
        return (REPO_ROOT / "templates" / name).read_text(encoding="utf-8")

    def test_curator_html_equals_index_after_static_rewrite_and_native_script(self):
        index = self._read_html("index.html")
        curator = self._read_html("curator.html")

        # Transform 1: /static/ -> /curator_static/
        expected = index.replace("/static/", "/curator_static/")
        # Transform 2: insert native-mode script before the first <script src=...>
        native_script_block = "<script>window.CURATOR_NATIVE = true;</script>\n    "
        first_script = expected.index('<script src="')
        expected = expected[:first_script] + native_script_block + expected[first_script:]

        assert curator == expected, (
            "curator.html must be index.html after /static/ -> /curator_static/ "
            "and inserting native-mode script before ordered JS assets"
        )

    def test_curator_html_content_length_matches_expected(self):
        index = self._read_html("index.html")
        curator = self._read_html("curator.html")
        # curator.html = index.html + native mode script line + /static/ ->
        # /curator_static/ (same lengths since both are 7 chars removed, 17 chars
        # added per occurrence). The overall delta should be exactly the native-mode
        # script tag length plus any small path-length diffs.
        assert len(curator) > len(index)
        assert len(curator) - len(index) < 450, (
            "curator.html should be only slightly larger than index.html"
        )


# ---------------------------------------------------------------------------
# curator.html structure
# ---------------------------------------------------------------------------


class TestCuratorHtmlStructure:
    """Native curator.html completeness and /curator_static path coverage."""

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

    def test_all_dom_ids_match_index(self):
        index = (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        curator = self._read()
        index_ids = set(re.findall(r'id="([^"]+)"', index))
        curator_ids = set(re.findall(r'id="([^"]+)"', curator))
        missing = index_ids - curator_ids
        assert not missing, f"missing DOM ids: {missing}"

    def test_css_order_matches_index(self):
        index_files = re.findall(
            r'href="[^"]*css/([^"]+\.css)"',
            (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8"),
        )
        curator_files = re.findall(r'href="[^"]*css/([^"]+\.css)"', self._read())
        assert index_files == curator_files

    def test_js_order_matches_index(self):
        index_files = re.findall(
            r'src="[^"]*js/([^"]+\.js)"',
            (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8"),
        )
        curator_files = re.findall(r'src="[^"]*js/([^"]+\.js)"', self._read())
        assert index_files == curator_files

    def test_declares_native_mode(self):
        html = self._read()
        assert "window.CURATOR_NATIVE = true" in html

    def test_preserves_jinja_model_block(self):
        html = self._read()
        assert "{% if available_models %}" in html
        assert "{% for model in available_models %}" in html


# ---------------------------------------------------------------------------
# Standalone index.html integrity
# ---------------------------------------------------------------------------


class TestStandaloneIndexHtmlUnchanged:
    def test_uses_static_paths(self):
        index = (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        assert "/static/css/" in index
        assert "/static/js/" in index
        assert "/curator_static/" not in index

    def test_no_native_mode_flag(self):
        index = (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        assert "CURATOR_NATIVE" not in index


# ---------------------------------------------------------------------------
# Page handler context
# ---------------------------------------------------------------------------


class TestCuratorManagerPageHandlerContext:
    def _setup_mocks(self):
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
        mock_folder_paths.get_system_user_directory.return_value = "C:/comfy/user/__curator"
        mock_folder_paths.get_output_directory.return_value = "C:/comfy/output"
        sys.modules["folder_paths"] = mock_folder_paths

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "py.curator_manager", REPO_ROOT / "py" / "curator_manager.py"
        )
        cm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cm)
        return cm, mock_jinja2

    def test_page_handler_passes_empty_models_and_default(self):
        cm, mock_jinja2 = self._setup_mocks()
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
        assert kwargs.get("available_models") == []
        assert kwargs.get("default_model") == ""

    def test_does_not_import_env_config(self):
        source = (REPO_ROOT / "py" / "curator_manager.py").read_text(encoding="utf-8")
        assert "ai_curate" not in source
        assert "load_dotenv" not in source


# ---------------------------------------------------------------------------
# URL helpers -- behavioral tests in both modes
# ---------------------------------------------------------------------------


def _extract_cc_helpers():
    """Extract ccApiPath, ccThumbUrl, ccImageUrl from state.js for node eval.

    Returns a JS code block where CURATOR_NATIVE is a mutable var so test
    IIFEs can toggle it before calling helpers.
    """
    source = read_frontend_js()
    start = source.index("const CURATOR_NATIVE")
    end = source.index("const SIDEBAR_WIDTH_KEY")
    block = source[start:end]
    # Replace const with var so node tests can reassign it.
    block = block.replace(
        "const CURATOR_NATIVE = (window.CURATOR_NATIVE === true);",
        "var CURATOR_NATIVE = false;",
    )
    return "var window = {};\n" + block


class TestCcApiPathBehavior:
    """Verify ccApiPath mapping in both modes using node subprocess."""

    def _eval_native(self, expr):
        """Evaluate expr with CURATOR_NATIVE=true at module level."""
        helpers = _extract_cc_helpers()
        code = helpers + "\nCURATOR_NATIVE = true;\nconsole.log(JSON.stringify(" + expr + "));"
        return self._run_node(code)

    def _eval_standalone(self, expr):
        """Evaluate expr with CURATOR_NATIVE=false at module level."""
        helpers = _extract_cc_helpers()
        code = helpers + "\nCURATOR_NATIVE = false;\nconsole.log(JSON.stringify(" + expr + "));"
        return self._run_node(code)

    def _run_node(self, code):
        result = subprocess.run(
            ["node", "-e", code],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise AssertionError(f"node failed: {result.stderr}")
        import json

        return json.loads(result.stdout.strip())

    def test_standalone_mode_identity(self):
        """ccApiPath returns path unchanged when CURATOR_NATIVE is false."""
        result = self._eval_standalone('ccApiPath("/api/batches")')
        assert result == "/api/batches"

    def test_native_mode_maps_correctly(self):
        """ccApiPath("/api/batches") -> "/api/curator/batches" when native."""
        result = self._eval_native('ccApiPath("/api/batches")')
        assert result == "/api/curator/batches"

    def test_native_mode_maps_ai_routes(self):
        result = self._eval_native('ccApiPath("/api/ai-curate/jobs")')
        assert result == "/api/curator/ai-curate/jobs"

    def test_standalone_mode_leaves_ai_routes_unchanged(self):
        result = self._eval_standalone('ccApiPath("/api/ai-curate/jobs")')
        assert result == "/api/ai-curate/jobs"

    def test_no_double_prefix(self):
        """ccApiPath returns already-prefixed paths unchanged in native mode."""
        result = self._eval_native('ccApiPath("/api/curator/batches")')
        assert result == "/api/curator/batches"

    def test_native_mode_preserves_query_string(self):
        result = self._eval_native('ccApiPath("/api/images/b/x?sort=date")')
        assert result == "/api/curator/images/b/x?sort=date"

    def test_thumb_in_standalone(self):
        result = self._eval_standalone('ccThumbUrl("b","f","n.png")')
        assert result == "/thumb/b/f/n.png"

    def test_thumb_in_native(self):
        result = self._eval_native('ccThumbUrl("b","f","n.png")')
        assert result == "/curator/thumb/b/f/n.png"

    def test_thumb_encodes_params(self):
        result = self._eval_standalone('ccThumbUrl("my batch","inbox","image (1).png")')
        assert "%20" in result
        assert "(" in result

    def test_image_in_standalone(self):
        result = self._eval_standalone('ccImageUrl("b","f","n.png")')
        assert result == "/image/b/f/n.png"

    def test_image_in_native(self):
        result = self._eval_native('ccImageUrl("b","f","n.png")')
        assert result == "/curator/image/b/f/n.png"


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
        """Create a minimal extension package under tmp_path."""
        pkg = tmp_path / "test_pkg"
        pkg.mkdir()
        py_dir = pkg / "py"
        py_dir.mkdir()
        (py_dir / "curator_manager.py").write_text(curator_manager_content, encoding="utf-8")

        init_src = (REPO_ROOT / "__init__.py").read_text(encoding="utf-8")
        init_src = init_src.replace(
            'Path(__file__).parent / "py" / "curator_manager.py"',
            f'Path(r"{pkg.as_posix()}") / "py" / "curator_manager.py"',
        )
        (pkg / "__init__.py").write_text(init_src, encoding="utf-8")
        return pkg

    @pytest.fixture(autouse=True)
    def _clean_caches(self):
        """Clear ComfyUI mock modules that leak across tests."""
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
            "test_pkg_e.__init__",
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
            sys.modules.pop("test_pkg_e", None)
            sys.modules.pop("py.curator_manager", None)

    def test_arbitrary_non_server_error_propagates(self, tmp_path):
        self._assert_propagates(tmp_path, "nonexistent_module_xyz")

    def test_aiohttp_missing_propagates(self, tmp_path):
        self._assert_propagates(tmp_path, "nonexistent_aiohttp_lib")

    def test_jinja2_missing_propagates(self, tmp_path):
        self._assert_propagates(tmp_path, "nonexistent_jinja2_lib")


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------


class TestModeSelection:
    def test_curator_html_declares_native(self):
        html = (REPO_ROOT / "templates" / "curator.html").read_text(encoding="utf-8")
        assert "window.CURATOR_NATIVE = true" in html

    def test_index_html_is_standalone(self):
        html = (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        assert "CURATOR_NATIVE" not in html

    def test_state_js_detects_native_mode(self):
        source = read_frontend_js()
        assert "const CURATOR_NATIVE" in source
        assert "window.CURATOR_NATIVE" in source

    def test_helpers_defined(self):
        source = read_frontend_js()
        for name in ("ccApiPath", "ccThumbUrl", "ccImageUrl"):
            assert f"function {name}(" in source, f"missing: {name}"
