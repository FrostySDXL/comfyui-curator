"""ComfyUI Curator native extension for the image curation workspace."""

from typing import Any

CuratorManager: Any = None

if __package__:
    try:
        from .py.curator_manager import CuratorManager as _CuratorManager
    except ModuleNotFoundError as exc:
        # ComfyUI's server module is intentionally absent in isolated tests.
        if exc.name != "server":
            raise
    else:
        CuratorManager = _CuratorManager

NODE_CLASS_MAPPINGS: dict[str, Any] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}
WEB_DIRECTORY = "./web/comfyui"

if CuratorManager is not None:
    CuratorManager.add_routes()

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
