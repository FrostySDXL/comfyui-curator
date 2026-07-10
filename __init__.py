"""ComfyUI Curator -- Native ComfyUI extension for image curation workspace.

py/ is kept as a namespace directory (no __init__.py) to avoid shadowing the
installed `py` library that tools such as pytest depend on.  curator_manager
is loaded explicitly through importlib below.
"""

import importlib.util
from pathlib import Path

CuratorManager = None

_CM_PATH = Path(__file__).parent / "py" / "curator_manager.py"

if _CM_PATH.exists():
    _cm_spec = importlib.util.spec_from_file_location("py.curator_manager", str(_CM_PATH))
    _cm_mod = importlib.util.module_from_spec(_cm_spec)
    if _cm_spec.loader is not None:
        try:
            _cm_spec.loader.exec_module(_cm_mod)
            CuratorManager = _cm_mod.CuratorManager
        except ModuleNotFoundError as e:
            # Only "server" is legitimately absent in standalone mode.
            # Missing aiohttp, jinja2, or any other dependency must propagate
            # as an actionable extension failure.
            if e.name == "server":
                CuratorManager = None
            else:
                raise

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./web/comfyui"

if CuratorManager is not None:
    CuratorManager.add_routes()

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
