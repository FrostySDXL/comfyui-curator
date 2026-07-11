"""Unit tests for ComfyUI native extension entrypoint and route manager."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_root_init_standalone():
    """Load root __init__.py as a virtual package, standalone mode (no ComfyUI)."""
    init_path = REPO_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "comfyui_curator",
        init_path,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["comfyui_curator"] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        for name in tuple(sys.modules):
            if name == "comfyui_curator" or name.startswith("comfyui_curator."):
                sys.modules.pop(name, None)
    return mod


def _setup_comfyui_mocks():
    """Inject mock ComfyUI modules into sys.modules so curator_manager can import."""
    mock_server = MagicMock()
    mock_prompt_server = MagicMock()
    mock_app = MagicMock()
    mock_router = MagicMock()
    mock_app.router = mock_router
    mock_prompt_server.instance.app = mock_app
    mock_server.PromptServer = mock_prompt_server

    # Build mock aiohttp with proper json_response and Response factories
    mock_web = MagicMock()

    def _mock_json_response(data, **kwargs):
        import json as _json

        resp = MagicMock()
        resp.status = 200
        resp.text = _json.dumps(data)
        resp.content_type = "application/json"
        return resp

    def _mock_response(text="", **kwargs):
        resp = MagicMock()
        resp.status = kwargs.get("status", 200)
        resp.text = text
        resp.content_type = kwargs.get("content_type", "text/html")
        return resp

    mock_web.json_response = _mock_json_response
    mock_web.Response = _mock_response
    mock_web.FileResponse = MagicMock()

    mock_aiohttp = MagicMock()
    mock_aiohttp.web = mock_web

    mock_jinja2 = MagicMock()
    mock_folder_paths = MagicMock()
    mock_folder_paths.get_system_user_directory.return_value = "C:/comfy/user/__curator"
    mock_folder_paths.get_output_directory.return_value = "C:/comfy/output"

    sys.modules["server"] = mock_server
    sys.modules["aiohttp"] = mock_aiohttp
    sys.modules["aiohttp.web"] = mock_web
    sys.modules["jinja2"] = mock_jinja2
    sys.modules["folder_paths"] = mock_folder_paths

    return mock_app, mock_router


def _teardown_comfyui_mocks():
    """Remove injected mock modules."""
    for mod in ["server", "aiohttp", "aiohttp.web", "jinja2", "folder_paths"]:
        sys.modules.pop(mod, None)


class TestRootInitExports:
    """Root __init__.py exposes NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, WEB_DIRECTORY."""

    def test_exports_expected_constants(self):
        mod = _load_root_init_standalone()

        assert mod.NODE_CLASS_MAPPINGS == {}
        assert mod.NODE_DISPLAY_NAME_MAPPINGS == {}
        assert mod.WEB_DIRECTORY == "./web/comfyui"

    def test_node_class_mappings_is_dict_not_none(self):
        mod = _load_root_init_standalone()
        assert mod.NODE_CLASS_MAPPINGS is not None
        assert isinstance(mod.NODE_CLASS_MAPPINGS, dict)

    def test_curator_manager_is_none_when_imports_unavailable(self):
        """CuratorManager is None in standalone mode (no ComfyUI modules)."""
        mod = _load_root_init_standalone()
        assert mod.CuratorManager is None

    def test_all_exports_present_in_standalone_mode(self):
        """Exports list is correct."""
        mod = _load_root_init_standalone()
        assert mod.__all__ == [
            "NODE_CLASS_MAPPINGS",
            "NODE_DISPLAY_NAME_MAPPINGS",
            "WEB_DIRECTORY",
        ]

    def test_curator_manager_imports_and_registers_with_mocks(self):
        """When ComfyUI modules are available, CuratorManager is not None and routes registered."""
        mock_app, mock_router = _setup_comfyui_mocks()

        init_path = REPO_ROOT / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "comfyui_curator",
            init_path,
            submodule_search_locations=[str(REPO_ROOT)],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["comfyui_curator"] = mod
        try:
            spec.loader.exec_module(mod)
            assert mod.CuratorManager is not None
            assert mod.CuratorManager._registered is True
            # Routes were registered during module load.
            curator_routes = [
                c for c in mock_router.add_get.call_args_list if c[0][0] == "/curator"
            ]
            assert len(curator_routes) == 1
            health_routes = [
                c for c in mock_router.add_get.call_args_list if c[0][0] == "/api/curator/health"
            ]
            assert len(health_routes) == 1
        finally:
            for name in tuple(sys.modules):
                if name == "comfyui_curator" or name.startswith("comfyui_curator."):
                    sys.modules.pop(name, None)
            _teardown_comfyui_mocks()

    def test_imports_as_isolated_custom_node_package(self, monkeypatch):
        """Sibling backend modules resolve without adding the extension root to sys.path."""
        _setup_comfyui_mocks()
        root = REPO_ROOT.resolve()
        monkeypatch.setattr(
            sys,
            "path",
            [entry for entry in sys.path if Path(entry or ".").resolve() != root],
        )
        for name in tuple(sys.modules):
            if name == "image_curator" or name.startswith("image_curator."):
                monkeypatch.delitem(sys.modules, name)

        init_path = REPO_ROOT / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "isolated_curator",
            init_path,
            submodule_search_locations=[str(REPO_ROOT)],
        )
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, "isolated_curator", mod)
        try:
            spec.loader.exec_module(mod)
        finally:
            _teardown_comfyui_mocks()

        assert mod.CuratorManager is not None
        assert mod.CuratorManager.__module__ == "isolated_curator.py.curator_manager"
        assert sys.modules["image_curator"] is sys.modules["isolated_curator.image_curator"]


class TestCuratorManagerRoutes:
    """CuratorManager.add_routes() registers /curator, /api/curator/health, /curator_static."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Set up ComfyUI mocks and load curator_manager via importlib."""
        _setup_comfyui_mocks()

        # Load curator_manager as an isolated module — no global py/ package.
        cm_path = REPO_ROOT / "py" / "curator_manager.py"
        spec = importlib.util.spec_from_file_location("py.curator_manager", cm_path)
        self.cm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cm)

        self.mock_app = sys.modules["server"].PromptServer.instance.app
        self.mock_router = self.mock_app.router
        yield
        _teardown_comfyui_mocks()

    def test_add_routes_registers_curator_page(self):
        self.cm.CuratorManager._registered = False
        self.cm.CuratorManager.add_routes()

        # Verify GET /curator was registered
        calls = self.mock_router.add_get.call_args_list
        curator_calls = [c for c in calls if len(c[0]) >= 1 and c[0][0] == "/curator"]
        assert len(curator_calls) >= 1, f"Expected /curator route, got calls: {calls}"

    def test_add_routes_registers_health_endpoint(self):
        self.cm.CuratorManager._registered = False
        self.cm.CuratorManager.add_routes()

        calls = self.mock_router.add_get.call_args_list
        health_calls = [c for c in calls if len(c[0]) >= 1 and c[0][0] == "/api/curator/health"]
        assert len(health_calls) >= 1, f"Expected /api/curator/health route, got calls: {calls}"

    def test_add_routes_registers_native_foundation_endpoints(self):
        self.cm.CuratorManager._registered = False
        self.cm.CuratorManager.add_routes()

        get_paths = {call[0][0] for call in self.mock_router.add_get.call_args_list}
        post_paths = {call[0][0] for call in self.mock_router.add_post.call_args_list}
        assert {
            "/api/curator/settings",
            "/api/curator/batches",
            "/api/curator/images/{batch}/{folder}",
            "/api/curator/image-metadata/{batch}/{folder}/{name}",
            "/curator/thumb/{batch}/{folder}/{name}",
            "/curator/image/{batch}/{folder}/{name}",
        } <= get_paths
        assert {
            "/api/curator/batches",
            "/api/curator/active-batch",
            "/api/curator/import-all",
        } <= post_paths

    def test_add_routes_registers_static_mount(self):
        self.cm.CuratorManager._registered = False
        self.cm.CuratorManager.add_routes()

        self.mock_router.add_static.assert_called_once()
        args = self.mock_router.add_static.call_args[0]
        assert args[0] == "/curator_static"

    def test_add_routes_is_idempotent(self):
        self.cm.CuratorManager._registered = False
        self.cm.CuratorManager.add_routes()

        # Reset mock call tracking but keep same state
        self.mock_router.add_get.reset_mock()
        self.mock_router.add_static.reset_mock()

        # Second call should be a no-op
        self.cm.CuratorManager.add_routes()

        self.mock_router.add_get.assert_not_called()
        self.mock_router.add_static.assert_not_called()

    def test_registered_flag_set_after_first_call(self):
        self.cm.CuratorManager._registered = False
        assert self.cm.CuratorManager._registered is False

        self.cm.CuratorManager.add_routes()

        assert self.cm.CuratorManager._registered is True

    def test_registered_remains_false_when_registration_raises(self):
        """_registered stays False when a route registration raises; retry succeeds."""
        self.cm.CuratorManager._registered = False

        # Make add_static raise on first call
        self.mock_router.add_static.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            self.cm.CuratorManager.add_routes()

        assert self.cm.CuratorManager._registered is False

        # Fix the mock and retry
        self.mock_router.add_static.side_effect = None
        self.mock_router.add_get.reset_mock()
        self.mock_router.add_static.reset_mock()

        self.cm.CuratorManager.add_routes()

        assert self.cm.CuratorManager._registered is True
        self.mock_router.add_static.assert_called_once()
        curator_calls = [
            c for c in self.mock_router.add_get.call_args_list if c[0][0] == "/curator"
        ]
        assert len(curator_calls) >= 1

    def test_health_handler_returns_ok_json(self):
        self.cm.CuratorManager._registered = False
        self.cm.CuratorManager.add_routes()

        # Find the health handler from registered routes
        calls = self.mock_router.add_get.call_args_list
        health_call = next(
            (c for c in calls if len(c[0]) >= 2 and c[0][0] == "/api/curator/health"),
            None,
        )
        assert health_call is not None, "Health route not registered"

        # The second positional arg (or keyword) is the handler
        handler = health_call[0][1] if len(health_call[0]) >= 2 else health_call[1].get("handler")
        assert handler is not None

        import asyncio
        import json

        mock_request = MagicMock()
        result = asyncio.run(handler(mock_request))

        assert result.status == 200
        body = json.loads(result.text)
        assert body == {"ok": True}

    def test_page_handler_returns_html(self):
        self.cm.CuratorManager._registered = False
        self.cm.CuratorManager.add_routes()

        calls = self.mock_router.add_get.call_args_list
        page_call = next(
            (c for c in calls if len(c[0]) >= 2 and c[0][0] == "/curator"),
            None,
        )
        assert page_call is not None, "Curator page route not registered"

        handler = page_call[0][1] if len(page_call[0]) >= 2 else page_call[1].get("handler")
        assert handler is not None

        import asyncio

        mock_request = MagicMock()
        result = asyncio.run(handler(mock_request))

        assert result.status == 200
        assert "text/html" in result.content_type

    def test_page_handler_template_failure_propagates(self):
        """Template errors are not caught -- they propagate as exceptions."""
        # Get the real TemplateNotFound from the installed jinja2 package,
        # not the mock injected by _setup.
        _mock_jinja2 = sys.modules.pop("jinja2", None)
        import jinja2 as _real_jinja2

        sys.modules["jinja2"] = _mock_jinja2
        TemplateNotFound = _real_jinja2.TemplateNotFound

        # Reset and re-register so the handler closure captures our patched jinja2
        self.cm.CuratorManager._registered = False
        self.mock_router.add_get.reset_mock()
        self.mock_router.add_static.reset_mock()

        # Cause jinja2 Environment.get_template to raise TemplateNotFound
        mock_env = MagicMock()
        mock_env.get_template.side_effect = TemplateNotFound("curator.html")

        self.cm.Environment = MagicMock(return_value=mock_env)

        self.cm.CuratorManager.add_routes()

        calls = self.mock_router.add_get.call_args_list
        page_call = next(
            (c for c in calls if len(c[0]) >= 2 and c[0][0] == "/curator"),
            None,
        )
        assert page_call is not None

        handler = page_call[0][1] if len(page_call[0]) >= 2 else page_call[1].get("handler")

        import asyncio

        mock_request = MagicMock()
        with pytest.raises(TemplateNotFound):
            asyncio.run(handler(mock_request))


class TestTopMenuExtensionJS:
    """web/comfyui/top_menu_extension.js source invariants."""

    def _read_js(self):
        path = REPO_ROOT / "web" / "comfyui" / "top_menu_extension.js"
        assert path.exists(), f"Missing: {path}"
        return path.read_text(encoding="utf-8")

    def test_imports_from_scripts_app(self):
        js = self._read_js()
        assert 'import { app } from "../../scripts/app.js"' in js

    def test_registers_extension(self):
        js = self._read_js()
        assert "app.registerExtension({" in js

    def test_has_action_bar_buttons(self):
        js = self._read_js()
        assert "actionBarButtons" in js

    def test_opens_curator_path(self):
        js = self._read_js()
        assert '"/curator"' in js

    def test_extension_has_name(self):
        js = self._read_js()
        assert 'name: "ComfyUICurator.TopMenu"' in js
