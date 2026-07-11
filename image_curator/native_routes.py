"""Aiohttp route adapter for the native Curator foundation."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from image_curator import batch_store, publish
from image_curator.favorites import get_batch_favorite_filenames
from image_curator.media import generate_thumbnail, thumbnail_cache_path, thumbnail_is_fresh
from image_curator.native_settings import NativeCuratorSettings
from image_curator.png_metadata import extract_png_metadata
from image_curator.web_validation import safe_path

THUMB_SIZE = (320, 320)
CACHE_HEADERS = {"Cache-Control": "public, max-age=3600, immutable"}


class NativeCuratorService:
    """Native filesystem dependencies resolved independently of Flask."""

    def __init__(self, settings: NativeCuratorSettings) -> None:
        self.settings = settings

    def batch_exists(self, batch: str) -> bool:
        try:
            batch_store._validate_name(batch, "batch name")
        except (TypeError, ValueError):
            return False
        path = self.settings.batch_root / batch
        return path.is_dir() and not path.is_symlink()

    def resolve_content_directory(self, batch: str, folder: str):
        root = self.settings.batch_root.resolve()
        batch_path = self.settings.batch_root / batch
        if not self.batch_exists(batch) or batch_path.is_symlink():
            raise ValueError("Invalid path")
        real_batch = batch_path.resolve()
        try:
            real_batch.relative_to(root)
        except ValueError as exc:
            raise ValueError("Invalid path") from exc
        content = batch_path / folder
        if content.is_symlink() or not content.is_dir():
            raise ValueError("Invalid path")
        real_content = content.resolve()
        try:
            real_content.relative_to(root)
            real_content.relative_to(real_batch)
        except ValueError as exc:
            raise ValueError("Invalid path") from exc
        return real_content

    def batch_summary_safe(self, batch: str) -> bool:
        """Return whether shared summary helpers can inspect this batch safely."""
        try:
            for folder in batch_store.BATCH_FOLDERS:
                self.resolve_content_directory(batch, folder)
        except ValueError:
            return False

        root = self.settings.batch_root.resolve()
        real_batch = (self.settings.batch_root / batch).resolve()
        ai_dir = self.settings.batch_root / batch / "ai-curate"
        if ai_dir.is_symlink():
            return False
        if ai_dir.exists():
            try:
                real_ai_dir = ai_dir.resolve()
                real_ai_dir.relative_to(root)
                real_ai_dir.relative_to(real_batch)
            except (OSError, ValueError):
                return False
        return True

    def resolve_thumbnail_cache(self, batch: str, folder: str, name: str):
        root = self.settings.batch_root.resolve()
        batch_path = self.settings.batch_root / batch
        if not self.batch_exists(batch) or batch_path.is_symlink():
            raise ValueError("Invalid thumbnail cache path")
        real_batch = batch_path.resolve()
        cache = thumbnail_cache_path(self.settings.batch_root, batch, folder, name)
        cache_parent = cache.parent
        if cache_parent.is_symlink() or cache.is_symlink():
            raise ValueError("Invalid thumbnail cache path")
        cache_parent.mkdir(exist_ok=True)
        if cache_parent.is_symlink() or cache.is_symlink():
            raise ValueError("Invalid thumbnail cache path")
        real_parent = cache_parent.resolve()
        real_cache = cache.resolve()
        try:
            real_batch.relative_to(root)
            real_parent.relative_to(root)
            real_parent.relative_to(real_batch)
            real_cache.relative_to(root)
            real_cache.relative_to(real_batch)
        except ValueError as exc:
            raise ValueError("Invalid thumbnail cache path") from exc
        return real_cache

    def batches_payload(self) -> dict[str, Any]:
        root = self.settings.batch_root
        batches = [
            batch for batch in batch_store.get_batches(root) if self.batch_summary_safe(batch)
        ]
        state_batch = batch_store.load_state(self.settings.state_file).get("active_batch")
        return {
            "batches": batches,
            "active_batch": state_batch if state_batch in batches else None,
            "counts": {batch: batch_store.get_batch_counts(root, batch) for batch in batches},
            "batch_meta": {batch: batch_store.get_batch_metadata(root, batch) for batch in batches},
            "pending_count": batch_store.get_pending_count(self.settings.import_source),
        }


async def _json_body(request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _string_field(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key, "")
    return value if isinstance(value, str) else None


def register_native_routes(app, service: NativeCuratorService) -> None:
    """Register namespaced native foundation routes on an aiohttp application."""

    async def get_settings(_request):
        return web.json_response(service.settings.public_payload())

    async def get_batches(_request):
        return web.json_response(service.batches_payload())

    async def create_batch(request):
        data = await _json_body(request)
        name_value = _string_field(data, "name")
        if name_value is None:
            return web.json_response({"error": "Invalid batch name"}, status=400)
        name = name_value.strip()
        if not name:
            return web.json_response({"error": "Name required"}, status=400)
        if "/" in name or "\\" in name:
            return web.json_response({"error": "Invalid batch name"}, status=400)
        try:
            created = batch_store.create_batch(service.settings.batch_root, name)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if not created:
            return web.json_response({"error": "Batch already exists"}, status=400)
        return web.json_response({"success": True})

    async def set_active_batch(request):
        data = await _json_body(request)
        batch = _string_field(data, "batch")
        if batch is None:
            return web.json_response({"error": "Invalid batch name"}, status=400)
        if batch and not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=400)
        state = batch_store.load_state(service.settings.state_file)
        state["active_batch"] = batch or None
        batch_store.save_state(service.settings.state_file, state)
        return web.json_response({"success": True})

    async def import_all(request):
        data = await _json_body(request)
        batch = _string_field(data, "batch")
        if batch is None:
            return web.json_response({"error": "Invalid batch name"}, status=400)
        if not batch:
            return web.json_response({"error": "Batch required"}, status=400)
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        try:
            service.resolve_content_directory(batch, "inbox")
        except ValueError:
            return web.json_response({"error": "Invalid import destination"}, status=400)
        count = batch_store.import_all_pending(
            service.settings.import_source, service.settings.batch_root, batch
        )
        return web.json_response({"success": True, "count": count})

    async def get_images(request):
        batch = request.match_info["batch"]
        folder = request.match_info["folder"]
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        if folder not in batch_store.BATCH_FOLDERS:
            return web.json_response({"error": "Invalid folder"}, status=400)
        sort_by = request.query.get("sort", "date")
        order = request.query.get("order", "desc")
        if sort_by not in ("date", "name", "shuffle"):
            sort_by = "date"
        if order not in ("asc", "desc"):
            order = "desc"
        try:
            directory = service.resolve_content_directory(batch, folder)
        except ValueError:
            return web.json_response({"error": "Invalid path"}, status=400)
        favorites = get_batch_favorite_filenames(service.settings.batch_root, batch)
        payload = []
        for image in batch_store.get_images(directory, sort_by=sort_by, order=order):
            try:
                if image.is_symlink():
                    continue
                resolved_image = image.resolve()
                resolved_image.relative_to(directory)
                if resolved_image.parent != directory:
                    continue
                size = image.stat().st_size
            except (OSError, ValueError):
                continue
            payload.append({"name": image.name, "size": size, "favorite": image.name in favorites})
        return web.json_response(payload)

    def resolve_media(request):
        batch = request.match_info["batch"]
        folder = request.match_info["folder"]
        name = request.match_info["name"]
        if not service.batch_exists(batch):
            return None, web.json_response({"error": "Batch does not exist"}, status=404)
        if folder not in batch_store.BATCH_FOLDERS and folder != publish.PUBLIC_FOLDER:
            return None, web.json_response({"error": "Invalid folder"}, status=400)
        if not isinstance(name, str) or name.startswith(".") or name.find("\\") >= 0:
            return None, web.json_response({"error": "Invalid path"}, status=400)
        if name.find("/") >= 0:
            return None, web.json_response({"error": "Invalid path"}, status=400)
        if not name.lower().endswith(tuple(batch_store.IMAGE_EXTENSIONS)):
            return None, web.json_response({"error": "Invalid file type"}, status=400)
        try:
            base = service.resolve_content_directory(batch, folder)
        except ValueError:
            return None, web.json_response({"error": "Invalid path"}, status=400)
        if (base / name).is_symlink():
            return None, web.json_response({"error": "Invalid path"}, status=400)
        path, error = safe_path(base, name)
        if error:
            return None, web.json_response({"error": error}, status=400)
        if not path.is_file() or path.is_symlink():
            return None, web.json_response({"error": "File not found"}, status=404)
        return path, None

    async def get_metadata(request):
        path, error_response = resolve_media(request)
        if error_response is not None:
            return error_response
        return web.json_response(extract_png_metadata(path))

    async def serve_image(request):
        path, error_response = resolve_media(request)
        if error_response is not None:
            return error_response
        return web.FileResponse(path, headers=CACHE_HEADERS)

    async def serve_thumbnail(request):
        source, error_response = resolve_media(request)
        if error_response is not None:
            return error_response
        try:
            cache = service.resolve_thumbnail_cache(
                request.match_info["batch"],
                request.match_info["folder"],
                request.match_info["name"],
            )
            if not thumbnail_is_fresh(cache, source, THUMB_SIZE):
                generate_thumbnail(source, cache, THUMB_SIZE)
        except ValueError:
            return web.json_response({"error": "Invalid thumbnail cache path"}, status=400)
        except Exception:
            return web.json_response({"error": "Failed to generate thumbnail"}, status=500)
        return web.FileResponse(
            cache,
            headers={"Content-Type": "image/webp", **CACHE_HEADERS},
        )

    app.router.add_get("/api/curator/settings", get_settings)
    app.router.add_get("/api/curator/batches", get_batches)
    app.router.add_post("/api/curator/batches", create_batch)
    app.router.add_post("/api/curator/active-batch", set_active_batch)
    app.router.add_post("/api/curator/import-all", import_all)
    app.router.add_get("/api/curator/images/{batch}/{folder}", get_images)
    app.router.add_get("/api/curator/image-metadata/{batch}/{folder}/{name}", get_metadata)
    app.router.add_get("/curator/thumb/{batch}/{folder}/{name}", serve_thumbnail)
    app.router.add_get("/curator/image/{batch}/{folder}/{name}", serve_image)
