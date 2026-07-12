"""ComfyUI Curator native extension for the image curation workspace."""

CuratorManager = None

if __package__:
    try:
        from .py.curator_manager import CuratorManager
    except ModuleNotFoundError as exc:
        # ComfyUI's server module is intentionally absent in standalone tests.
        if exc.name != "server":
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
