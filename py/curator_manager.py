"""Route registration for the Curator native ComfyUI extension."""

from pathlib import Path

from server import PromptServer
from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape


class CuratorManager:
    """Registers Curator page, API, and static routes on the ComfyUI PromptServer."""

    _registered: bool = False

    @classmethod
    def add_routes(cls) -> None:
        """Register /curator, /api/curator/health, and /curator_static routes.

        Idempotent: subsequent calls are no-ops.
        """
        if cls._registered:
            return

        prompt_server = PromptServer.instance
        app = prompt_server.app

        root = Path(__file__).resolve().parents[1]
        static_path = root / "static"

        app.router.add_static("/curator_static", str(static_path))

        # Jinja2 is required and available through Flask or ComfyUI.
        async def curator_page(_request):
            template_path = root / "templates"
            env = Environment(
                loader=FileSystemLoader(str(template_path)),
                autoescape=select_autoescape(["html", "xml"]),
            )
            template = env.get_template("curator.html")
            html = template.render(
                available_models=[],
                default_model="",
            )
            return web.Response(text=html, content_type="text/html")

        app.router.add_get("/curator", curator_page)

        # Health handler
        async def health_handler(_request):
            return web.json_response({"ok": True})

        app.router.add_get("/api/curator/health", health_handler)

        cls._registered = True
