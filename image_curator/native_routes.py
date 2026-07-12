"""Aiohttp route adapter for the native Curator foundation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

from . import batch_store, prompt_history, publish
from .favorites import (
    get_batch_favorite_filenames,
    resolve_universal_favorites,
    toggle_favorite,
)
from .media import generate_thumbnail, thumbnail_cache_path, thumbnail_is_fresh
from .native_settings import NativeConfigError, NativeCuratorSettings, SettingsConflictError
from .png_metadata import extract_png_metadata
from .web_validation import safe_path

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
            if not ai_dir.is_dir():
                return False
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

    def resolve_favorite_image(self, batch: str, filename: str):
        """Safely locate an image across review folders for favorite toggling.

        Returns (folder_name, None) when a regular, supported, contained image
        is found.  Returns (None, error_response) with 400 for invalid names /
        extensions / symlinks / directory escapes and 404 when the filename has
        a valid shape but no matching safe image exists.
        """
        if not self.batch_exists(batch):
            return None, web.json_response({"error": "Batch does not exist"}, status=404)
        if not isinstance(filename, str) or not filename.strip():
            return None, web.json_response({"error": "Invalid path"}, status=400)
        if filename.startswith(".") or "\\" in filename or "/" in filename:
            return None, web.json_response({"error": "Invalid path"}, status=400)
        if not filename.lower().endswith(tuple(batch_store.IMAGE_EXTENSIONS)):
            return None, web.json_response({"error": "Invalid file type"}, status=400)
        for folder in batch_store.BATCH_FOLDERS:
            try:
                directory = self.resolve_content_directory(batch, folder)
            except ValueError:
                continue
            candidate = directory / filename
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                candidate.resolve().relative_to(directory)
            except (OSError, ValueError):
                continue
            return folder, None
        return None, web.json_response({"error": "File not found"}, status=404)


async def _json_body(request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _string_field(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key, "")
    return value if isinstance(value, str) else None


def register_native_routes(app, service: NativeCuratorService, lifecycle=None) -> None:
    """Register namespaced native foundation routes on an aiohttp application."""

    async def get_settings(_request):
        return web.json_response(service.settings.editable_payload())

    async def post_settings(request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)
        if not isinstance(data, dict):
            return web.json_response({"error": "Settings body must be an object"}, status=400)
        try:
            payload = (
                lifecycle.update_settings(data)
                if lifecycle is not None
                else service.settings.update(data)
            )
            return web.json_response({"success": True, **payload})
        except NativeConfigError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except SettingsConflictError:
            return web.json_response(
                {"error": "Settings cannot change while AI work is active"}, status=409
            )
        except Exception:
            return web.json_response({"error": "Could not update settings"}, status=500)

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
    app.router.add_post("/api/curator/settings", post_settings)
    app.router.add_get("/api/curator/batches", get_batches)
    app.router.add_post("/api/curator/batches", create_batch)
    app.router.add_post("/api/curator/active-batch", set_active_batch)
    app.router.add_post("/api/curator/import-all", import_all)

    async def move_single(request):
        data = await _json_body(request)
        batch = _string_field(data, "batch")
        filename = _string_field(data, "filename")
        source = _string_field(data, "source")
        destination = _string_field(data, "destination")
        if None in (batch, filename, source, destination):
            return web.json_response({"error": "Missing parameters"}, status=400)
        if not all([batch, filename, source, destination]):
            return web.json_response({"error": "Missing parameters"}, status=400)
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        if source not in batch_store.BATCH_FOLDERS or destination not in batch_store.BATCH_FOLDERS:
            return web.json_response({"error": "Invalid source or destination folder"}, status=400)
        try:
            src_dir = service.resolve_content_directory(batch, source)
            dst_dir = service.resolve_content_directory(batch, destination)
        except ValueError:
            return web.json_response({"error": "Invalid path"}, status=400)
        src_path, src_err = safe_path(src_dir, filename)
        if src_err:
            return web.json_response({"error": src_err}, status=400)
        dst_path, dst_err = safe_path(dst_dir, filename)
        if dst_err:
            return web.json_response({"error": dst_err}, status=400)
        try:
            if src_path.is_symlink():
                return web.json_response({"error": "Invalid path"}, status=400)
            if not src_path.is_file():
                return web.json_response({"error": "File not found"}, status=404)
            if dst_path.is_symlink():
                return web.json_response({"error": "Invalid path"}, status=400)
        except OSError:
            return web.json_response({"error": "Invalid path"}, status=400)
        if not batch_store.move_image(src_path, dst_path):
            return web.json_response({"error": f"Could not move {filename}"}, status=500)
        return web.json_response({"success": True})

    async def move_batch(request):
        data = await _json_body(request)
        batch = _string_field(data, "batch")
        source = _string_field(data, "source")
        destination = _string_field(data, "destination")
        raw_filenames = data.get("filenames", [])
        if not isinstance(raw_filenames, list):
            return web.json_response({"error": "Missing parameters"}, status=400)
        if None in (batch, source, destination):
            return web.json_response({"error": "Missing parameters"}, status=400)
        if not all([batch, source, destination]):
            return web.json_response({"error": "Missing parameters"}, status=400)
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        if source not in batch_store.BATCH_FOLDERS or destination not in batch_store.BATCH_FOLDERS:
            return web.json_response({"error": "Invalid source or destination folder"}, status=400)
        try:
            src_dir = service.resolve_content_directory(batch, source)
            dst_dir = service.resolve_content_directory(batch, destination)
        except ValueError:
            return web.json_response({"error": "Invalid path"}, status=400)
        skipped = 0
        valid_filenames: list[str] = []
        for filename in raw_filenames:
            if not isinstance(filename, str):
                skipped += 1
                continue
            src_path, src_err = safe_path(src_dir, filename)
            if src_err:
                skipped += 1
                continue
            dst_path, dst_err = safe_path(dst_dir, filename)
            if dst_err:
                skipped += 1
                continue
            try:
                if src_path.is_symlink() or not src_path.is_file():
                    skipped += 1
                    continue
                if dst_path.is_symlink():
                    skipped += 1
                    continue
            except OSError:
                skipped += 1
                continue
            valid_filenames.append(filename)
        moved = 0
        if valid_filenames:
            moved, skipped_in_loop = batch_store.move_images(
                source_dir=src_dir,
                names=valid_filenames,
                dest_dir=dst_dir,
            )
            skipped += skipped_in_loop
        if moved == 0 and raw_filenames:
            return web.json_response({"success": False, "moved": 0, "skipped": skipped})
        return web.json_response({"success": True, "moved": moved, "skipped": skipped})

    async def delete_rejects(request):
        batch = request.match_info["batch"]
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        try:
            rejects_dir = service.resolve_content_directory(batch, "rejects")
        except ValueError:
            return web.json_response({"error": "Invalid path"}, status=400)
        count = 0
        failed = 0
        for f in rejects_dir.iterdir():
            if f.suffix.lower() not in batch_store.IMAGE_EXTENSIONS:
                continue
            try:
                if f.is_symlink():
                    continue
            except OSError:
                continue
            try:
                f.unlink()
            except OSError:
                failed += 1
                continue
            cache_file = thumbnail_cache_path(service.settings.batch_root, batch, "rejects", f.name)
            cache_safe = False
            try:
                if not cache_file.is_symlink() and not cache_file.parent.is_symlink():
                    root = service.settings.batch_root.resolve()
                    real_batch = (service.settings.batch_root / batch).resolve()
                    real_cache = cache_file.resolve()
                    real_parent = cache_file.parent.resolve()
                    real_batch.relative_to(root)
                    real_parent.relative_to(root)
                    real_parent.relative_to(real_batch)
                    real_cache.relative_to(root)
                    real_cache.relative_to(real_batch)
                    cache_safe = True
            except (OSError, ValueError):
                pass
            if cache_safe and cache_file.exists():
                try:
                    cache_file.unlink()
                except OSError:
                    pass
            count += 1
        return web.json_response({"success": True, "count": count, "failed": failed})

    app.router.add_get("/api/curator/images/{batch}/{folder}", get_images)
    app.router.add_get("/api/curator/image-metadata/{batch}/{folder}/{name}", get_metadata)
    app.router.add_get("/curator/thumb/{batch}/{folder}/{name}", serve_thumbnail)
    app.router.add_get("/curator/image/{batch}/{folder}/{name}", serve_image)
    app.router.add_post("/api/curator/move", move_single)
    app.router.add_post("/api/curator/move-batch", move_batch)
    app.router.add_post("/api/curator/delete-rejects/{batch}", delete_rejects)

    async def get_batch_favorites(request):
        batch = request.match_info["batch"]
        if batch == "__favorites__":
            return web.json_response({"error": "Batch does not exist"}, status=404)
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        return web.json_response(
            {"filenames": sorted(get_batch_favorite_filenames(service.settings.batch_root, batch))}
        )

    async def post_batch_favorite(request):
        batch = request.match_info["batch"]
        if batch == "__favorites__":
            return web.json_response({"error": "Batch does not exist"}, status=404)
        data = await _json_body(request)
        filename = _string_field(data, "filename")
        if filename is None or not filename.strip():
            return web.json_response({"error": "filename required"}, status=400)
        _folder, error = service.resolve_favorite_image(batch, filename)
        if error is not None:
            return error
        try:
            result = toggle_favorite(service.settings.batch_root, batch, filename)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(result)

    app.router.add_get("/api/curator/favorites/{batch}", get_batch_favorites)
    app.router.add_post("/api/curator/favorites/{batch}", post_batch_favorite)

    async def get_universal_favorites(_request):
        return web.json_response(
            {"favorites": resolve_universal_favorites(service.settings.batch_root)}
        )

    async def post_universal_favorite(request):
        data = await _json_body(request)
        batch = _string_field(data, "batch")
        filename = _string_field(data, "filename")
        if batch is None or not batch.strip():
            return web.json_response({"error": "batch required"}, status=400)
        if batch == "__favorites__":
            return web.json_response({"error": "Batch does not exist"}, status=400)
        if filename is None or not filename.strip():
            return web.json_response({"error": "filename required"}, status=400)
        _folder, error = service.resolve_favorite_image(batch, filename)
        if error is not None:
            return error
        try:
            result = toggle_favorite(service.settings.batch_root, batch, filename)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(result)

    app.router.add_get("/api/curator/favorites", get_universal_favorites)
    app.router.add_post("/api/curator/favorites", post_universal_favorite)

    # -----------------------------------------------------------------------
    # Public derivative routes
    # -----------------------------------------------------------------------

    def _validate_batch_for_public(batch: str) -> web.Response | None:
        if batch in ("__public__", "__favorites__"):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        return None

    def _public_items_payload_native(
        data: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], web.Response | None]:
        items = data.get("items", [])
        if not isinstance(items, list) or not items:
            return [], web.json_response({"error": "items required"}, status=400)
        if any(not isinstance(item, dict) for item in items):
            return [], web.json_response({"error": "items must be objects"}, status=400)
        for item in items:
            batch = item.get("batch")
            filename = item.get("filename") or item.get("name")
            if not isinstance(batch, str) or not batch.strip():
                return [], web.json_response(
                    {"error": "items batch must be a non-empty string"}, status=400
                )
            if not isinstance(filename, str) or not filename.strip():
                return [], web.json_response(
                    {"error": "items filename must be a non-empty string"}, status=400
                )
        return items, None

    def _public_export_root_error_response(
        result: dict[str, Any], action_key: str
    ) -> tuple[dict[str, Any], int] | None:
        if result.get("failed") and not result.get(action_key):
            files = result.get("files") or []
            first_error = files[0].get("error") if files else None
            if first_error == "Public export root is not configured":
                return {"error": first_error, **result}, 400
        return None

    def _public_transfer_status(result: dict[str, Any], action_key: str) -> int:
        if result.get(action_key, 0) == 0 and result.get("failed", 0):
            return 400
        return 200

    def _public_export_root() -> Path | None:
        return service.settings.public_export_root

    async def publish_export(request):
        data = await _json_body(request)
        batch = _string_field(data, "batch")
        if batch is None or not batch.strip():
            return web.json_response({"error": "Invalid batch name"}, status=400)
        err = _validate_batch_for_public(batch)
        if err is not None:
            return err
        folder_raw = data.get("folder", "")
        if not isinstance(folder_raw, str) or not folder_raw.strip():
            return web.json_response({"error": "Invalid folder"}, status=400)
        folder = folder_raw
        filenames = data.get("filenames", [])
        if not isinstance(filenames, list) or not filenames:
            return web.json_response({"error": "filenames required"}, status=400)
        for name in filenames:
            if not isinstance(name, str):
                return web.json_response({"error": "filenames must be strings"}, status=400)
        watermark_raw = data.get("watermark")
        result = publish.create_public_copies(
            service.settings.batch_root,
            batch=batch,
            folder=folder,
            filenames=filenames,
            strip_metadata=bool(data.get("strip_metadata", True)),
            watermark=watermark_raw if isinstance(watermark_raw, dict) else None,
        )
        status = 200 if result.get("exported", 0) > 0 or result.get("failed", 0) == 0 else 400
        return web.json_response(result, status=status)

    async def get_all_public(_request):
        return web.json_response({"public": publish.list_all_public(service.settings.batch_root)})

    async def get_public_destinations(request):
        try:
            result = publish.list_export_directories(
                _public_export_root(),
                path=request.query.get("path", ""),
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc), "directories": []}, status=400)
        return web.json_response(result)

    async def get_batch_public(request):
        batch = request.match_info["batch"]
        err = _validate_batch_for_public(batch)
        if err is not None:
            return err
        return web.json_response(publish.list_batch_public(service.settings.batch_root, batch))

    async def copy_public(request):
        data = await _json_body(request)
        items, err = _public_items_payload_native(data)
        if err is not None:
            return err
        destination_raw = data.get("destination", "")
        if not isinstance(destination_raw, str) or not destination_raw.strip():
            return web.json_response({"error": "destination required"}, status=400)
        result = publish.copy_public_items(
            service.settings.batch_root,
            destination=destination_raw,
            items=items,
            export_root=_public_export_root(),
        )
        export_root_error = _public_export_root_error_response(result, "copied")
        if export_root_error:
            return web.json_response(export_root_error[0], status=export_root_error[1])
        return web.json_response(result, status=_public_transfer_status(result, "copied"))

    async def move_public(request):
        data = await _json_body(request)
        items, err = _public_items_payload_native(data)
        if err is not None:
            return err
        destination_raw = data.get("destination", "")
        if not isinstance(destination_raw, str) or not destination_raw.strip():
            return web.json_response({"error": "destination required"}, status=400)
        result = publish.move_public_items(
            service.settings.batch_root,
            destination=destination_raw,
            items=items,
            export_root=_public_export_root(),
        )
        export_root_error = _public_export_root_error_response(result, "moved")
        if export_root_error:
            return web.json_response(export_root_error[0], status=export_root_error[1])
        return web.json_response(result, status=_public_transfer_status(result, "moved"))

    async def delete_public(request):
        items, err = _public_items_payload_native(await _json_body(request))
        if err is not None:
            return err
        result = publish.delete_public_items(service.settings.batch_root, items=items)
        return web.json_response(result, status=_public_transfer_status(result, "deleted"))

    app.router.add_post("/api/curator/publish/export", publish_export)
    app.router.add_get("/api/curator/public", get_all_public)
    app.router.add_get("/api/curator/public/destinations", get_public_destinations)
    app.router.add_get("/api/curator/public/{batch}", get_batch_public)
    app.router.add_post("/api/curator/public/copy", copy_public)
    app.router.add_post("/api/curator/public/move", move_public)
    app.router.add_post("/api/curator/public/delete", delete_public)

    # -----------------------------------------------------------------------
    # Prompt history routes
    # -----------------------------------------------------------------------

    async def build_prompt_index(request):
        batch = request.match_info["batch"]
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        try:
            return web.json_response(
                prompt_history.build_prompt_index(service.settings.batch_root, batch)
            )
        except ValueError:
            return web.json_response({"error": "Unsafe prompt history path"}, status=400)
        except Exception:
            return web.json_response({"error": "Prompt history build failed"}, status=500)

    async def get_prompt_index(request):
        batch = request.match_info["batch"]
        if not service.batch_exists(batch):
            return web.json_response({"error": "Batch does not exist"}, status=404)
        index = prompt_history.load_prompt_index(service.settings.batch_root, batch)
        if index is None:
            return web.json_response({"error": "prompt history not built"}, status=404)
        if request.query.get("check_stale", "").lower() == "true":
            try:
                current_count = prompt_history.count_prompt_index_images(
                    service.settings.batch_root, batch
                )
            except ValueError:
                return web.json_response({"error": "Unsafe prompt history path"}, status=400)
            index = dict(index)
            index["stale"] = current_count != index.get("image_count")
            index["current_image_count"] = current_count
        return web.json_response(index)

    async def get_all_prompt_indices(_request):
        return web.json_response(
            prompt_history.load_all_prompt_indices(service.settings.batch_root)
        )

    app.router.add_post("/api/curator/prompt-history/{batch}/build", build_prompt_index)
    app.router.add_get("/api/curator/prompt-history/{batch}", get_prompt_index)
    app.router.add_get("/api/curator/prompt-history", get_all_prompt_indices)
