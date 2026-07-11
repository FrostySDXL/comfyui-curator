# ComfyUI Curator Native Extension Port Specification

**Status:** Architecture and migration specification
**Created:** 2026-07-10
**Scope:** Port the current standalone `comfyui-curator` Flask application into a native ComfyUI extension/custom-node package.
**Primary references:** current `comfyui-curator` repo, local `ComfyUI-Lora-Manager` clone, local `comfyui-starchart` clone, local `ComfyUI-Manager` clone, and targeted official Comfy Registry/Manager web research.

## 1. Executive Summary

The recommended port is a **hybrid native ComfyUI extension**:

- **Full-page Curator UI** launched from ComfyUI, following the successful `ComfyUI-Lora-Manager` pattern.
- **PromptServer/aiohttp backend routes** replacing Flask route handlers.
- **Existing Curator Python backend modules** retained as reusable service logic where possible.
- **Existing vanilla frontend** reused initially with URL-prefix changes, rather than rewritten into a framework.
- **Optional custom nodes** added after the native UI/routes are stable.
- **ComfyUI Manager / Registry-compatible package metadata** added through `pyproject.toml`, `WEB_DIRECTORY`, and standard extension exports.

Do not force the curation workspace into the graph canvas. The Curator UI is grid/lightbox/sidebar-heavy and should remain a dedicated page reachable from ComfyUI via a menu/action-bar button, similar to Lora-Manager's `/loras` page.

Recommended first proof of concept:

```text
1. Native extension entrypoint loads in ComfyUI.
2. ComfyUI action-bar/menu button opens /curator.
3. /curator renders the Curator shell.
4. /api/curator/health returns JSON.
5. /api/curator/batches and basic image/thumb routes work.
6. No watcher or AI worker starts by default.
```

## 2. Evidence Sources and Confidence

### 2.1 Local repositories inspected

| Repo | Local path | Purpose |
|---|---|---|
| Current Curator | `D:\projects\comfyui-curator` | Source application being ported. |
| Lora-Manager | `D:\projects\ComfyUI-Lora-Manager` | Primary extension architecture pattern to emulate. |
| StarChart | `D:\projects\comfyui-starchart` | Pinned ComfyUI internals and extension facts. |
| ComfyUI-Manager | `D:\projects\ComfyUI-Manager` | Manager scanner/install behavior for empty node mappings. |

### 2.2 Web sources consulted

Minimal web research was performed only for current Registry/Manager publication questions. Sources:

- `https://docs.comfy.org/registry/specifications`
- `https://docs.comfy.org/registry/publishing`
- `https://docs.comfy.org/registry/standards`
- `https://docs.comfy.org/custom-nodes/backend/lifecycle`
- `https://github.com/Comfy-Org/ComfyUI-Manager`
- `https://github.com/Comfy-Org/registry-backend`
- `https://github.com/Comfy-Org/comfy-cli`

### 2.3 StarChart pinned baseline

StarChart local docs identify the current pinned baseline as:

```text
ComfyUI core: v0.26.0, commit f6c162ddcfbd7eefb39c06fe5b8d4c46e8d09f40
ComfyUI frontend: v1.47.5, commit e604c85b88cc3eb5f6c07063aba2cbb536fd8e85
Snapshot date: 2026-06-26
```

Source: `D:\projects\comfyui-starchart\README.md`.

## 3. Current Curator Architecture to Preserve

Current Curator is a local-first, single-operator Flask app for reviewing generated images. The filesystem is the source of truth.

### 3.1 Entrypoints

| File | Role |
|---|---|
| `app.py` | Flask web UI, API routes, watcher setup, AI worker thread lifecycle. |
| `curate.py` | CLI/headless AI scoring entrypoint. |

### 3.2 Backend modules

| Module | Role in current app | Port recommendation |
|---|---|---|
| `image_curator/batch_store.py` | Batch creation, folder layout, image moves, counts, pending import, active state. | Keep. Adapt config/path sources. |
| `image_curator/web_validation.py` | Batch/path validation and traversal prevention. | Keep and use from aiohttp routes. |
| `image_curator/media.py` | Thumbnail cache naming/freshness/generation. | Keep. Consider `asyncio.to_thread` later for generation. |
| `image_curator/png_metadata.py` | PNG text chunk / prompt metadata extraction. | Keep. |
| `image_curator/favorites.py` | Batch and universal favorites stores. | Keep. |
| `image_curator/publish.py` | Metadata-stripped/watermarked public derivatives and external export root operations. | Keep. Preserve derivative-only safety. |
| `image_curator/prompt_history.py` | Manual prompt-history cache build/load/staleness. | Keep. |
| `image_curator/watcher.py` | Polling auto-import watcher for ComfyUI output. | Keep logic, change lifecycle. Default disabled. |
| `ai_curate/*` | AI scoring client, queue, worker, storage, models, validation. | Keep core. Port HTTP layer. |

### 3.3 Frontend modules

Current frontend is classic browser JS and split CSS:

```text
templates/index.html
static/js/state.js
static/js/dom-utils.js
static/js/api.js
static/js/sidebar.js
static/js/batches.js
static/js/grid.js
static/js/favorites.js
static/js/publish.js
static/js/moves.js
static/js/lightbox.js
static/js/metadata.js
static/js/prompts.js
static/js/ai-*.js
static/js/polling.js
static/js/modals.js
static/js/keyboard.js
static/js/events.js
static/js/bootstrap.js
static/css/*.css
```

Port recommendation:

- Reuse initially.
- Introduce one API base prefix constant, e.g. `API_BASE = "/api/curator"`.
- Update static paths to `/curator_static/...`.
- Keep frontend behavior and route response shapes stable during the first migration.

## 4. ComfyUI Extension Surfaces

StarChart's extension-point guidance separates ComfyUI extension work across these surfaces:

| Surface | Use for Curator? | Notes |
|---|---:|---|
| JavaScript extension hooks | Yes | Add menu/action-bar button, settings, optional UI notifications. |
| Custom routes | Yes | Main API surface replacing Flask. |
| Server callback hooks | Maybe later | Useful only if importing outputs from prompt submissions directly. Not needed for initial port. |
| Runtime messages / WebSocket events | Optional | Use for best-effort AI/watcher progress notifications. HTTP remains source of truth. |
| Custom nodes | Optional/later | Useful for workflow integration, not required for curation UI. |

Evidence:

- `D:\projects\comfyui-starchart\src\content\docs\hooks\extension-points.md`
- `D:\projects\comfyui-starchart\examples\extensions\minimal-route-registration\routes.py`
- `D:\projects\comfyui-starchart\examples\custom-nodes\example-5-full-extension-package\README.md`

## 5. Lora-Manager Patterns to Reuse

`ComfyUI-Lora-Manager` is the main structural reference.

### 5.1 Native entrypoint

Observed in `D:\projects\ComfyUI-Lora-Manager\__init__.py`:

- Exports `NODE_CLASS_MAPPINGS`.
- Sets `WEB_DIRECTORY = "./web/comfyui"`.
- Initializes backend services.
- Calls `LoraManager.add_routes()` on import.

Curator should use the same pattern.

### 5.2 Backend route/static registration

Observed in `D:\projects\ComfyUI-Lora-Manager\py\lora_manager.py`:

- Uses `PromptServer.instance.app`.
- Registers static paths, e.g. `/loras_static`.
- Registers page/API routes.
- Adds startup/shutdown lifecycle hooks.

Curator equivalent:

```text
/curator
/curator_static
/api/curator/*
```

### 5.3 Full-page UI route

Observed files:

- `py/routes/lora_routes.py`
- `py/routes/base_model_routes.py`
- `py/routes/model_route_registrar.py`
- `py/routes/handlers/model_handlers.py`
- `templates/loras.html`
- `templates/base.html`

Pattern:

- Jinja environment uses `FileSystemLoader(config.templates_path)`.
- Page handler renders a template and returns `web.Response(..., content_type="text/html")`.
- Route registrar binds `GET /{prefix}` to page handler.

Curator can either:

1. keep Jinja template rendering for fastest migration, or
2. make the UI fully static and reduce native-mode dependencies.

Fastest path: keep Jinja initially.

### 5.4 ComfyUI top-menu/action-bar button

Observed in `D:\projects\ComfyUI-Lora-Manager\web\comfyui\top_menu_extension.js`:

- Imports `app` from `../../scripts/app.js`.
- Calls `app.registerExtension(...)`.
- Uses `actionBarButtons` for newer frontend versions.
- Has a fallback that attaches a `ComfyButtonGroup` near the settings group.
- Opens `/loras` in a new window/tab.

Curator should add a button that opens `/curator`.

### 5.5 Frontend settings

Observed in `D:\projects\ComfyUI-Lora-Manager\web\comfyui\settings.js`:

- Registers settings via `app.registerExtension({ settings: [...] })`.
- Reads UI settings through `app.extensionManager.setting.get(...)`.
- These are mostly frontend/client preferences.

Important finding: local evidence did **not** show automatic bridging between ComfyUI frontend settings and Lora-Manager backend operational config. Lora-Manager separately owns backend settings through `/api/lm/settings` and a backend settings manager.

Curator should do the same split:

- ComfyUI settings for client/UI preferences.
- Curator backend config routes/files for operational settings and secrets.

## 6. Recommended Native Package Layout

Recommended initial layout:

```text
ComfyUI-Curator/
  __init__.py
  pyproject.toml
  requirements.txt
  README.md
  LICENSE

  py/
    __init__.py
    curator_manager.py
    settings.py
    lifecycle.py
    routes/
      __init__.py
      page_routes.py
      batch_routes.py
      image_routes.py
      favorites_routes.py
      publish_routes.py
      prompt_history_routes.py
      ai_routes.py
    nodes/
      __init__.py
      send_to_curator.py
      load_curated_image.py

  image_curator/
    batch_store.py
    favorites.py
    media.py
    png_metadata.py
    prompt_history.py
    publish.py
    watcher.py
    web_validation.py

  ai_curate/
    client.py
    config.py
    elements.py
    job_validation.py
    models.py
    queue.py
    scoring.py
    storage.py
    worker.py

  templates/
    curator.html

  static/
    css/
    js/
    images/

  web/
    comfyui/
      top_menu_extension.js
      settings.js
```

Notes:

- Keep root-level `app.py` and `curate.py` only if maintaining standalone compatibility in the same repo.
- If this becomes a dedicated `ComfyUI-Curator` repo, decide whether standalone Flask remains in scope.
- For a Manager-installed custom node package, `__init__.py` and `WEB_DIRECTORY` must live at the package root.

## 7. Entrypoint Skeleton

Recommended first version:

```python
# __init__.py

try:
    from .py.curator_manager import CuratorManager
except Exception:
    CuratorManager = None

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
```

Manager research found empty mappings are acceptable for UI-only extensions in ComfyUI-Manager. See Section 15.

Later, optional nodes can be added:

```python
from .py.nodes.send_to_curator import SendToCurator
from .py.nodes.load_curated_image import LoadCuratedImage

NODE_CLASS_MAPPINGS = {
    "Curator Send Image": SendToCurator,
    "Curator Load Image": LoadCuratedImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Curator Send Image": "Curator: Send Image",
    "Curator Load Image": "Curator: Load Image",
}
```

## 8. Route Manager Skeleton

```python
# py/curator_manager.py

from pathlib import Path

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape
from server import PromptServer

from .lifecycle import CuratorLifecycle
from .routes import register_curator_api_routes
from .settings import get_curator_settings


class CuratorManager:
    _registered = False

    @classmethod
    def add_routes(cls) -> None:
        if cls._registered:
            return
        cls._registered = True

        prompt_server = PromptServer.instance
        app = prompt_server.app

        root = Path(__file__).resolve().parents[1]
        static_path = root / "static"
        template_path = root / "templates"

        app.router.add_static("/curator_static", static_path)

        env = Environment(
            loader=FileSystemLoader(str(template_path)),
            autoescape=select_autoescape(["html", "xml"]),
        )

        async def curator_page(_request):
            settings = get_curator_settings()
            template = env.get_template("curator.html")
            html = template.render(
                available_models=settings.available_models,
                default_model=settings.default_model,
            )
            return web.Response(text=html, content_type="text/html")

        app.router.add_get("/curator", curator_page)
        app.router.add_get("/api/curator/health", lambda _request: web.json_response({"ok": True}))

        register_curator_api_routes(app)

        lifecycle = CuratorLifecycle()
        app.on_startup.append(lifecycle.startup)
        app.on_shutdown.append(lifecycle.shutdown)
```

Notes:

- Use an idempotent `_registered` guard, matching StarChart's minimal route example and common custom-node defensive practice.
- The inline lambda for `/api/curator/health` is illustrative; actual code should use an async handler.
- Do not register routes under generic `/api/*`; namespace all Curator routes under `/api/curator/*`.

## 9. Frontend ComfyUI Button Skeleton

```javascript
// web/comfyui/top_menu_extension.js
import { app } from "../../scripts/app.js";

const CURATOR_PATH = "/curator";
const TOOLTIP = "Open Curator";

function openCurator(event) {
  const url = `${window.location.origin}${CURATOR_PATH}`;

  if (event?.shiftKey) {
    window.open(url, "_blank", "width=1400,height=900,resizable=yes,scrollbars=yes");
    return;
  }

  window.open(url, "_blank");
}

app.registerExtension({
  name: "ComfyUICurator.TopMenu",

  setup() {
    this.aboutPageBadges = [
      {
        label: "ComfyUI Curator",
        url: "https://github.com/FrostySDXL/comfyui-curator",
        icon: "pi pi-images",
      },
    ];
  },

  actionBarButtons: [
    {
      icon: "icon-[lucide--images] size-4",
      tooltip: TOOLTIP,
      onClick: openCurator,
    },
  ],
});
```

Compatibility note:

- Lora-Manager includes a fallback using `ComfyButton`/`ComfyButtonGroup` if the frontend version does not support `actionBarButtons`.
- Curator can start with `actionBarButtons` if targeting the pinned/current frontend, then add fallback if needed.

## 10. Settings and State Design

### 10.1 Two-layer settings model

Use two settings layers:

1. **Backend operational config** owned by Curator.
2. **ComfyUI frontend settings** for UI-only preferences.

Do not rely on ComfyUI frontend settings for server-owned secrets or watcher startup.

### 10.2 Backend config path

Recommended storage:

```text
folder_paths.get_system_user_directory("curator")/config.json
folder_paths.get_system_user_directory("curator")/state.json
```

Evidence from StarChart pinned `folder_paths.py`:

- `get_user_directory()` returns ComfyUI user directory.
- `get_system_user_directory(name="system")` returns an internal system user directory such as `user/__curator`.
- Public user directories intentionally block system users prefixed with `__`.

This is a better fit than platformdirs for a ComfyUI-native extension because Curator state should move with the ComfyUI install/user directory.

### 10.3 Backend config shape

Recommended initial schema:

```json
{
  "version": 1,
  "batch_root": "",
  "import_source": "",
  "watcher_enabled": false,
  "ai": {
    "endpoint": "http://127.0.0.1:8080/v1",
    "model": "",
    "api_key": "",
    "timeout_seconds": 120
  },
  "public_export_root": ""
}
```

Recommended defaults:

| Setting | Default |
|---|---|
| `batch_root` | `<folder_paths.get_system_user_directory("curator")>/batches` |
| `import_source` | `folder_paths.get_output_directory()` |
| `watcher_enabled` | `false` |
| `ai.endpoint` | Current Curator default if applicable, otherwise local OpenAI-compatible endpoint. |
| `ai.model` | blank until configured or migrated. |
| `ai.api_key` | blank; mask on GET. |
| `ai.timeout_seconds` | current Curator default if found, otherwise conservative numeric default. |
| `public_export_root` | blank/disabled. |

Backend settings routes:

```text
GET  /api/curator/settings
POST /api/curator/settings
```

Security behavior:

- Do not return API keys directly.
- Return booleans such as `ai_api_key_set: true`.
- Support clearing secrets explicitly.
- Keep env vars as higher-priority runtime override only if desired.

### 10.4 Environment variable migration

Map current standalone `.env` variables into native config during first startup or through a migration command. Do not read `.env` directly from the extension unless explicitly supporting standalone mode.

| Existing/current intent | Native config target |
|---|---|
| `IMAGE_CURATOR_BATCHES` | `batch_root` |
| `IMAGE_CURATOR_COMFYUI` / ComfyUI output path equivalent | `import_source` |
| `IMAGE_CURATOR_ENABLE_WATCHER` | `watcher_enabled` |
| LLM base URL variable | `ai.endpoint` |
| LLM model variable | `ai.model` |
| LLM API key variable | `ai.api_key` |
| LLM timeout variable | `ai.timeout_seconds` |
| `IMAGE_CURATOR_PUBLIC_EXPORTS` | `public_export_root` |
| `IMAGE_CURATOR_STATE` | one-time migration source only; future state should use native `state.json`. |

### 10.5 Frontend settings

Use `app.registerExtension({ settings: [...] })` only for UI preferences:

```javascript
// web/comfyui/settings.js
import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "ComfyUICurator.Settings",
  settings: [
    {
      id: "curator.open_in_new_tab",
      name: "Open Curator in new tab",
      type: "boolean",
      defaultValue: true,
      category: ["Curator", "UI", "Open behavior"],
    },
    {
      id: "curator.poll_interval_seconds",
      name: "Curator UI polling interval",
      type: "slider",
      attrs: { min: 1, max: 10, step: 1 },
      defaultValue: 2,
      category: ["Curator", "UI", "Polling"],
    },
  ],
});
```

Operational settings such as `batch_root`, `watcher_enabled`, and AI credentials should be managed through the Curator page using `/api/curator/settings`, not through ComfyUI's generic frontend settings store.

## 11. Filesystem and Batch Strategy

### 11.1 Batch layout to preserve

Current layout remains the compatibility contract:

```text
<batch-root>/<batch>/
  inbox/
  shortlisted/
  finals/
  rejects/
  public/
  ai-curate/
    runs/
    latest.json
  prompt-history.json
  .favorites.json
```

Generated/cache files to preserve and keep ignored:

```text
.thumbs/
.favorites.json
prompt-history.json
ai-curate/runs/*.json
ai-curate/latest.json
public/
```

### 11.2 Import source

Default import source should be ComfyUI's output folder:

```python
import folder_paths

default_import_source = folder_paths.get_output_directory()
```

Evidence:

- StarChart pinned `folder_paths.py` defines `output_directory` and `get_output_directory()`.
- ComfyUI core uses folder paths throughout server/image handling.

### 11.3 Active state

Move active batch state to native `state.json`:

```json
{
  "active_batch": "example-batch"
}
```

State is operational and server-owned. It should not be stored in browser-only settings.

## 12. Route Migration Inventory

All existing Flask routes should be migrated to aiohttp under namespaced routes. Preserve response shapes unless intentionally versioning the API.

### 12.1 Route prefix mapping

Recommended mapping:

| Current Flask route | Native route |
|---|---|
| `/` | `/curator` |
| `/api/batches` | `/api/curator/batches` |
| `/api/active-batch` | `/api/curator/active-batch` |
| `/api/import-all` | `/api/curator/import-all` |
| `/api/images/<batch>/<folder>` | `/api/curator/images/{batch}/{folder}` |
| `/api/image-metadata/<batch>/<folder>/<filename>` | `/api/curator/image-metadata/{batch}/{folder}/{filename}` |
| `/api/move` | `/api/curator/move` |
| `/api/move-batch` | `/api/curator/move-batch` |
| `/api/delete-rejects/<batch>` | `/api/curator/delete-rejects/{batch}` |
| `/api/favorites` | `/api/curator/favorites` |
| `/api/favorites/<batch>` | `/api/curator/favorites/{batch}` |
| `/api/publish/export` | `/api/curator/publish/export` |
| `/api/public` | `/api/curator/public` |
| `/api/public/destinations` | `/api/curator/public/destinations` |
| `/api/public/<batch>` | `/api/curator/public/{batch}` |
| `/api/public/copy` | `/api/curator/public/copy` |
| `/api/public/move` | `/api/curator/public/move` |
| `/api/public/delete` | `/api/curator/public/delete` |
| `/api/prompt-history/<batch>/build` | `/api/curator/prompt-history/{batch}/build` |
| `/api/prompt-history/<batch>` | `/api/curator/prompt-history/{batch}` |
| `/api/prompt-history` | `/api/curator/prompt-history` |
| `/thumb/<batch>/<folder>/<filename>` | `/curator/thumb/{batch}/{folder}/{filename}` |
| `/image/<batch>/<folder>/<filename>` | `/curator/image/{batch}/{folder}/{filename}` |
| `/api/ai-curate/*` | `/api/curator/ai-curate/*` or `/api/curator/ai/*` |

Recommendation: use `/api/curator/ai-curate/*` for lowest frontend migration risk, or `/api/curator/ai/*` if accepting broader frontend edits.

### 12.2 Foundation/page routes

Current:

- `GET /` in `app.py` renders `templates/index.html` with `available_models` and `default_model`.

Native:

- `GET /curator` renders `templates/curator.html` or static HTML.
- Static assets served under `/curator_static`.
- Add `GET /api/curator/health` for smoke testing.

### 12.3 Batch/import/state routes

Current routes:

| Route | Behavior |
|---|---|
| `GET /api/batches` | Returns batches, active batch, counts, metadata, pending count. |
| `POST /api/batches` | Creates batch from JSON `{name}`. |
| `POST /api/active-batch` | Sets active batch from JSON `{batch}`. |
| `POST /api/import-all` | Imports pending images into target batch and resets watcher seen state. |

Implementation notes:

- Replace Flask `request.json` with `await request.json()`.
- Preserve batch name validation.
- Preserve pending count behavior.
- `import-all` should still call watcher reset if watcher exists.

### 12.4 Image/thumb/metadata routes

Current routes:

| Route | Behavior |
|---|---|
| `GET /api/images/<batch>/<folder>` | Returns image list with `name`, `size`, `favorite`; supports sort/order query. |
| `GET /api/image-metadata/<batch>/<folder>/<filename>` | Returns PNG metadata JSON. |
| `GET /thumb/<batch>/<folder>/<filename>` | Serves/generated cached WebP thumbnail. |
| `GET /image/<batch>/<folder>/<filename>` | Serves original image. |

Preserve:

- batch existence check.
- `folder` must be one of normal batch folders or `public` for view-only routes.
- path traversal blocking via resolved path relative to base.
- `public/` viewability.
- thumbnail cache path format from `media.py`: `<folder>__<stem>.webp`.
- thumbnail response MIME: `image/webp`.
- cache header: `public, max-age=3600, immutable`.

Recommended aiohttp image skeleton:

```python
async def serve_image(request):
    path = resolve_curator_media_path(request)
    response = web.FileResponse(path)
    response.headers["Cache-Control"] = "public, max-age=3600, immutable"
    return response
```

Recommended aiohttp thumbnail skeleton:

```python
async def serve_thumb(request):
    source = resolve_curator_media_path(request)
    cache = thumbnail_cache_path(batch_root, batch, folder, filename)

    if not thumbnail_is_fresh(cache, source, THUMB_SIZE):
        # Consider asyncio.to_thread for this call after the first port works.
        generate_thumbnail(source, cache, THUMB_SIZE)

    response = web.FileResponse(cache, headers={"Content-Type": "image/webp"})
    response.headers["Cache-Control"] = "public, max-age=3600, immutable"
    return response
```

### 12.5 Moves/delete routes

Current routes:

| Route | Behavior |
|---|---|
| `POST /api/move` | Move one file between curation folders. |
| `POST /api/move-batch` | Move many files; returns moved/skipped. |
| `POST /api/delete-rejects/<batch>` | Deletes rejects and matching thumbnail cache files. |

Preserve:

- source/destination folder validation.
- safe path checks.
- no-op `move-batch` can return HTTP 200 with `success:false` and skipped count.
- thumbnail cleanup when deleting rejects.

### 12.6 Favorites routes

Current routes:

| Route | Behavior |
|---|---|
| `GET /api/favorites` | Returns universal favorites as resolved entries. |
| `POST /api/favorites` | Toggles favorite by `{batch, filename}`. |
| `GET /api/favorites/<batch>` | Returns batch favorite filenames. |
| `POST /api/favorites/<batch>` | Toggles batch favorite by `{filename}`. |

Preserve:

- one-click favorite updates both batch and universal scopes.
- frontend sentinel `__favorites__` remains frontend-only and is never a real batch.

### 12.7 Public publish routes

Current routes:

| Route | Behavior |
|---|---|
| `POST /api/publish/export` | Creates metadata-stripped/watermarked public derivatives. |
| `GET /api/public` | Lists all public derivatives as `{public:[...]}`. |
| `GET /api/public/<batch>` | Lists batch public derivatives as an array directly. |
| `GET /api/public/destinations` | Lists export-root directories. |
| `POST /api/public/copy` | Copies public derivatives to configured export root. |
| `POST /api/public/move` | Moves public derivatives to configured export root. |
| `POST /api/public/delete` | Deletes public derivatives. |

Preserve:

- `public/` is generated derivative output, not a normal curation stage.
- public copy/move/delete operate only on derivatives.
- external destinations must stay under configured export root.
- response shape mismatch is intentional: `/api/public` wraps, `/api/public/<batch>` returns array.

### 12.8 Prompt history routes

Current routes:

| Route | Behavior |
|---|---|
| `POST /api/prompt-history/<batch>/build` | Builds prompt index synchronously. |
| `GET /api/prompt-history/<batch>` | Loads cached index; optional stale check. |
| `GET /api/prompt-history` | Loads all cached indices. |

Preserve:

- manual build only.
- staleness check compares total image count only.
- prompt image references remain display-only in the current UI behavior.

### 12.9 AI routes

Current Blueprint prefix: `/api/ai-curate` from `ai_curate/routes.py`.

Routes:

| Current route | Behavior |
|---|---|
| `POST /api/ai-curate/preview-elements` | Builds/truncates element list. |
| `POST /api/ai-curate/jobs` | Validates and submits scoring job; returns `CurationRun`, status 201. |
| `GET /api/ai-curate/jobs` | Lists in-memory jobs. |
| `GET /api/ai-curate/jobs/<run_id>` | Returns job status. |
| `POST /api/ai-curate/jobs/<run_id>/cancel` | Requests cancellation. |
| `GET /api/ai-curate/batches/<batch>/runs` | Lists persisted run ids. |
| `GET /api/ai-curate/batches/<batch>/runs/latest` | Returns latest persisted run. |
| `GET /api/ai-curate/batches/<batch>/runs/<run_id>` | Returns persisted run. |
| `GET /api/ai-curate/batches/<batch>/element-history` | Returns recent element history. |

Preserve `CurationRun.to_dict()` shape:

```json
{
  "run_id": "...",
  "batch": "...",
  "source_folder": "inbox",
  "destination_folder": "shortlisted",
  "move_enabled": false,
  "prompt": "...",
  "elements": [],
  "quality_flags": [],
  "model": "...",
  "top_n": 15,
  "status": "...",
  "created_at": "...",
  "completed_at": "...",
  "totals": {
    "images": 0,
    "scored": 0,
    "failed": 0,
    "moved": 0
  },
  "results": [],
  "error_message": null
}
```

Important frontend contract:

- `score >= 0` means scored.
- `score < 0` means failed/unscored.
- `normalized_score` must exist.
- `details` is expected to be displayable.

## 13. Aiohttp Conversion Notes

Common Flask-to-aiohttp conversions:

```python
# Flask
data = request.json or {}
return jsonify(payload), 201

# aiohttp
try:
    data = await request.json()
except Exception:
    data = {}
return web.json_response(payload, status=201)
```

```python
# Flask
abort(404, description="not found")

# aiohttp option
return web.json_response({"error": "not found"}, status=404)
```

Prefer explicit JSON responses over raising generic exceptions so response shapes remain stable for the frontend.

For file responses:

```python
response = web.FileResponse(path)
response.headers["Cache-Control"] = "public, max-age=3600, immutable"
return response
```

Evidence:

- Lora-Manager preview handler uses `web.FileResponse` and notes it handles range/content headers/sendfile behavior.
- ComfyUI core `/view` uses `web.FileResponse` for files.

## 14. Lifecycle Design

### 14.1 Current Curator lifecycle

Current `app.py`:

- watcher opt-in through env flag.
- watcher is a daemon polling thread.
- AI workers are daemon threads.
- shutdown uses `atexit` and signal handlers.
- running/queued AI jobs are cancelled on shutdown.
- worker join timeout is bounded.

Current `image_curator/watcher.py`:

- tracks seen files.
- polls output directory.
- waits for file size stability.
- moves new image files into active batch inbox.

Current `ai_curate/queue.py`:

- single-worker FIFO queue.
- queued jobs can be cancelled directly.
- running jobs become `CANCELLING` and rely on cooperative checks.

Current `ai_curate/scoring.py` and `ai_curate/client.py`:

- cancellation is checked between images.
- LLM request uses blocking `urllib.request.urlopen(..., timeout=...)`.
- long calls cannot be interrupted until timeout.

### 14.2 Native lifecycle recommendation

Create one service object:

```python
class CuratorLifecycle:
    async def startup(self, app):
        ...

    async def shutdown(self, app):
        ...
```

Register it:

```python
app.on_startup.append(lifecycle.startup)
app.on_shutdown.append(lifecycle.shutdown)
```

Evidence:

- Lora-Manager registers startup/shutdown on `PromptServer.instance.app`.
- ComfyUI server uses aiohttp `web.Application`, so `on_startup` / `on_shutdown` are the appropriate lifecycle surfaces.

### 14.3 Watcher recommendation

Default:

```text
watcher_enabled = false
```

Preferred native behavior:

- Start watcher only if config enables it and import source exists.
- Keep active batch requirement.
- Keep size-stability check.
- Store task/thread handle.
- Stop on shutdown.
- Avoid daemon thread if possible.

Implementation options:

1. Keep current watcher thread initially, but make it non-daemon and lifecycle-managed.
2. Later convert to an async polling task with `asyncio.create_task`.
3. Longer-term improvement: import known completed outputs from ComfyUI execution events rather than polling/moving arbitrary output files.

### 14.4 AI worker recommendation

Initial native design:

- Keep `QueueManager` and run-history storage.
- Keep one active worker.
- If keeping blocking urllib client, run worker in a tracked `ThreadPoolExecutor(max_workers=1)` or explicit tracked thread.
- Do not use unmanaged daemon threads.
- On shutdown:
  - stop accepting new jobs.
  - cancel queued jobs.
  - mark running job as cancelling.
  - wait bounded time.
  - do not promote next jobs.

Progress/notifications:

- Keep HTTP polling endpoints as source of truth.
- Optionally send ComfyUI websocket events through `PromptServer.instance.send_sync`:

```text
curator_ai_job_update
curator_ai_progress
curator_watcher_status
curator_imported_image
```

Use websocket events only as notifications. Persisted run history and HTTP status remain authoritative.

## 15. Empty `NODE_CLASS_MAPPINGS` and Manager Compatibility

Local `ComfyUI-Manager` source gives a strong answer for Manager behavior.

### 15.1 Manager accepts empty mappings

Evidence from `D:\projects\ComfyUI-Manager\scanner.py`:

- `extract_nodes_enhanced(...)` documents empty dict detection for UI-only extensions.
- `_fallback_empty_dict_detector(...)` detects:
  - `NODE_CLASS_MAPPINGS = {}`
  - `NODE_CLASS_MAPPINGS={}`
- It describes this as:
  - UI-only extensions.
  - logging only.
- It does not raise errors or mark unsupported.

Evidence from `D:\projects\ComfyUI-Manager\glob\manager_core.py`:

- install/update paths do not validate non-empty node mappings:
  - `repo_install(...)`
  - `gitclone_install(...)`
  - `cnr_install(...)`
  - `repo_update(...)`
  - `unified_update(...)`

Evidence from `D:\projects\ComfyUI-Manager\__init__.py`:

- Manager itself exports `NODE_CLASS_MAPPINGS = {}`.

### 15.2 Practical implication

This is defensible for Curator:

```python
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./web/comfyui"
```

However, empty mappings produce no node names for Manager's extension-node map unless supplemented by:

- `node_list.json`,
- `nodename_pattern`, or
- at least one actual custom node.

Recommendation:

- Use empty mappings for the first UI/route-first port if desired.
- Add a real utility node later for workflow integration and discoverability.

### 15.3 Registry caveat

Local Manager evidence is definitive for Manager scanning/install/list/update behavior. It does not fully prove live Registry backend acceptance because Registry backend validation is external. Web research did not find an official rule rejecting empty mappings. Treat live Registry acceptance as likely but still worth testing with `comfy node publish` dry-run/validation when ready.

## 16. Manager / Registry Packaging

### 16.1 Current official publication path

Preferred path:

```text
Comfy Registry -> ComfyUI Manager
```

Publication options:

- `comfy node publish`
- `Comfy-Org/publish-node-action@main`

Legacy path still exists:

- PR to Manager `custom-node-list.json`

Manager v3.3.2+ supports `registry.comfy.org`, so Registry should be the target.

### 16.2 Required / important metadata

Required or important fields from current docs:

```toml
[project]
name = "..."
version = "..."

[project.urls]
Repository = "..."

[tool.comfy]
PublisherId = "..."
```

Recommended optional fields:

```toml
description = "..."
license = { file = "LICENSE" }
requires-python = ">=3.10"
dependencies = [...]

[tool.comfy]
DisplayName = "..."
Icon = "..."
Banner = "..."
requires-comfyui = "..."
includes = [...]
```

Version must be semantic `X.Y.Z`.

### 16.3 `requires-comfyui` format

Confirmed format:

```toml
[tool.comfy]
requires-comfyui = ">=1.0.0"
```

Supported operators:

```text
< > <= >= ~= <> !=
```

Ranges are allowed:

```toml
requires-comfyui = ">=1.0.0,<2.0.0"
```

Frontend compatibility can be expressed as a dependency:

```toml
dependencies = [
  "comfyui-frontend-package>=1.20.0"
]
```

Exact minimum versions should be chosen after testing against the actual target ComfyUI/frontend APIs.

### 16.4 Publisher/icon/banner

- `PublisherId`:
  - created on `registry.comfy.org`.
  - globally unique.
  - immutable.
  - must match `[tool.comfy].PublisherId`.
- `Icon`:
  - SVG/PNG/JPG/GIF supported.
  - docs conflict on size: one source says max `400x400` square; another example says max `800x400`.
  - Use a square `400x400` PNG/SVG to be safe.
- `Banner`:
  - SVG/PNG/JPG/GIF supported.
  - recommended aspect ratio: `21:9`.

### 16.5 Recommended `pyproject.toml`

Use a package name that does not redundantly include `ComfyUI` if following Registry naming guidance. Candidate names:

- `image-curator`
- `curator`
- `comfyui-curator`

Web research suggested docs discourage package names that include `ComfyUI`, but final naming is a product/discoverability decision and package names are immutable after registry creation.

Conservative draft:

```toml
[project]
name = "image-curator"
version = "0.1.0"
description = "ComfyUI image curation workspace with batch review and optional AI-assisted scoring."
license = { file = "LICENSE" }
requires-python = ">=3.10"
dependencies = [
  "Pillow",
]

[project.urls]
Repository = "https://github.com/FrostySDXL/comfyui-curator"
"Bug Tracker" = "https://github.com/FrostySDXL/comfyui-curator/issues"

[tool.comfy]
PublisherId = "FrostySDXL"
DisplayName = "ComfyUI Curator"
Icon = "https://raw.githubusercontent.com/FrostySDXL/comfyui-curator/main/assets/icon.png"
Banner = "https://raw.githubusercontent.com/FrostySDXL/comfyui-curator/main/assets/banner.png"
requires-comfyui = ">=1.0.0"
```

Confidence notes:

- `PublisherId = "FrostySDXL"` must match the actual Registry publisher ID.
- `requires-comfyui = ">=1.0.0"` has confirmed syntax but unconfirmed exact minimum.
- Dependency list should be finalized after deciding whether to keep Jinja rendering.

### 16.6 Dependency recommendation

Native extension minimal deps:

```text
Pillow
```

Potentially needed:

```text
jinja2
```

Do not include for native mode unless still required:

```text
Flask
python-dotenv
```

Do not add ComfyUI itself as a dependency.

Dependency decision:

| Dependency | Native port recommendation |
|---|---|
| `Pillow` | Keep for metadata, thumbnails, image processing. |
| `aiohttp` | Use host-provided ComfyUI aiohttp surface; include only if packaging validation requires explicit dependency. |
| `jinja2` | Include if rendering `templates/curator.html` server-side. Omit if UI becomes static. |
| `Flask` | Remove from native path. Keep only for standalone compatibility. |
| `python-dotenv` | Remove from native path. Keep only for standalone compatibility. |

## 17. Optional Custom Nodes

Custom nodes are not required for the first native UI port. They are useful later for workflow integration and Manager discoverability.

Candidate nodes:

### 17.1 `Curator: Send Image`

Purpose:

- Copy or register a generated image into a Curator batch/folder from a workflow.

Risks:

- Moving files during generation can be unsafe.
- Copy is safer than move.

### 17.2 `Curator: Load Curated Image`

Purpose:

- Load an image selected from a batch/folder back into a workflow.

This is likely the safest first node.

### 17.3 `Curator: Batch Selector`

Purpose:

- Select or create a target Curator batch from a workflow.

### 17.4 Node skeleton

```python
class LoadCuratedImage:
    CATEGORY = "curator"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "batch": ("STRING", {"default": ""}),
                "folder": (["inbox", "shortlisted", "finals", "rejects", "public"],),
                "filename": ("STRING", {"default": ""}),
            }
        }

    def load(self, batch, folder, filename):
        # Resolve under batch root, validate folder/path, load image tensor.
        raise NotImplementedError
```

## 18. Implementation Phases

### Phase 0: Repo/package decision

Decide whether:

1. current repo becomes the ComfyUI extension repo, while preserving standalone files, or
2. a new `ComfyUI-Curator` repo is created and shared modules are migrated/copied.

Recommendation: use the current repo initially if it is already named and maintained as Curator, but structure it as Manager-compatible.

### Phase 1: Native shell

Deliverables:

- root `__init__.py`.
- `WEB_DIRECTORY = "./web/comfyui"`.
- `web/comfyui/top_menu_extension.js`.
- `py/curator_manager.py`.
- `GET /curator`.
- `GET /api/curator/health`.
- minimal `pyproject.toml` / `requirements.txt` draft.

Verification:

- Install into ComfyUI `custom_nodes` or symlink locally.
- Start ComfyUI.
- Confirm no import errors.
- Confirm button appears.
- Confirm `/curator` loads.
- Confirm `/api/curator/health` returns JSON.

### Phase 2: Static UI lift

Deliverables:

- copy/rename `templates/index.html` to `templates/curator.html`.
- mount `/curator_static`.
- update CSS/JS paths.
- add API base prefix in frontend.

Verification:

- page loads all assets from ComfyUI.
- browser console has no missing static asset errors.

### Phase 3: Batch/image foundation

Deliverables:

- settings path backend.
- batch root resolution.
- routes:
  - `/api/curator/batches`
  - `/api/curator/active-batch`
  - `/api/curator/images/{batch}/{folder}`
  - `/curator/thumb/{batch}/{folder}/{filename}`
  - `/curator/image/{batch}/{folder}/{filename}`
  - `/api/curator/image-metadata/{batch}/{folder}/{filename}`

Verification:

- batch list visible.
- grid loads thumbnails.
- lightbox opens originals.
- metadata modal works.
- path traversal tests pass.

### Phase 4: Move/favorites/publish/prompt history

Status: Move, favorites, public, and prompt history routes are implemented with automated
tests (2026-07-11). Prompt-history safety tests cover symlink rejection, resolved containment
escapes, non-regular cache entries, and no-mutation rejection paths. Manual curation-flow
verification inside ComfyUI has not been performed and remains explicitly pending.

Deliverables:

- move routes. **[done]**
- delete rejects. **[done]**
- favorites routes. **[done]**
- public publish/export routes. **[done]**
- prompt history routes. **[done]**

Verification:

- existing Flask/API tests adapted to aiohttp route tests where possible.
- manual curation flow works inside ComfyUI. **[pending manual runtime verification]**

### Phase 5: AI scoring

Deliverables:

- port AI routes. **[done]**
- lifecycle-managed queue/worker. **[done -- NativeAiLifecycle with submission gate, worker thread tracking, idempotent startup, permanent-shutdown state machine, public submit_job() entry point. See ai_curate/native_lifecycle.py, image_curator/native_ai_routes.py]**
- run history persistence under batch root. **[done -- RunStorage with filesystem containment validation: symlink rejection, resolved-escaping batch/run/tmp paths, non-regular file rejection, no-mutation-on-rejection guarantees. See ai_curate/storage.py]**
- optional websocket notifications. **[deferred]**

Verification:

- submit/cancel job. **[done -- automated component tests covering submit, list, get, cancel, preview-elements, batch runs, latest run, element history routes]**
- scoring run persists. **[done -- automated unit/component/integration tests for RunStorage save/load/list/latest]**
- history/compare UI works. **[pending manual real-ComfyUI smoke]**
- shutdown does not leave unmanaged daemon threads. **[done -- automated lifecycle tests: shutdown cancels running+queued, post-shutdown submit returns 503, no worker promotion after shutdown, worker threads joined with bounded timeout, repeated shutdown idempotent. Manual real-ComfyUI AI scoring/history/shutdown smoke remains pending.]**

Automated scope implemented (2026-07-11):
- Native AI route adapters under `/api/curator/ai-curate/*` matching Flask Blueprint contracts.
- `NativeAiLifecycle`: idempotent startup, permanent shutdown, submission gate, worker thread tracking, public `submit_job()`.
- `RunStorage`: filesystem containment for all read/write paths, symlink rejection, no-mutation-on-rejection.
- Comprehensive lifecycle, storage containment, and route contract tests (58 tests in `tests/component/test_native_ai_curate_api.py`).

Manual real-ComfyUI AI scoring/history/shutdown smoke remains explicitly pending.

### Phase 6: Watcher

Deliverables:

- default disabled watcher setting.
- ComfyUI output folder auto-detection.
- lifecycle-managed watcher.
- status endpoint or UI warning.

Verification:

- manual import works before watcher.
- watcher imports only when enabled and active batch is set.
- no file is moved before size-stability check.

### Phase 7: Optional nodes and registry polish

Deliverables:

- one or more utility nodes.
- icon/banner assets.
- final `pyproject.toml`.
- Registry validation.
- Manager install documentation.

Verification:

- Manager local install.
- `comfy node publish` validation/dry-run if available.
- node appears if added.

## 19. Testing and Verification Strategy

### 19.1 Existing tests to preserve/adapt

Current important tests:

```text
tests/component/test_batch_api.py
tests/integration/test_image_metadata_api.py
tests/unit/test_favorites.py
tests/integration/test_favorites_api.py
tests/unit/test_publish.py
tests/integration/test_publish_api.py
tests/unit/test_prompt_history.py
tests/integration/test_prompt_history_api.py
tests/integration/test_ai_curate_api.py
tests/component/test_ai_curate_worker.py
tests/unit/test_ai_job_validation.py
tests/unit/test_frontend_*.py
```

### 19.2 New test needs

Add tests for:

- settings path resolution with mocked `folder_paths`.
- aiohttp route adapters.
- route prefix generation.
- no route collisions.
- empty `NODE_CLASS_MAPPINGS` import smoke.
- native lifecycle startup/shutdown idempotency.
- worker shutdown no-promote behavior.

### 19.3 Manual ComfyUI smoke test

Required before claiming native extension success:

```text
1. Install/symlink package under ComfyUI custom_nodes.
2. Start ComfyUI.
3. Confirm custom node import has no errors.
4. Confirm Curator button appears.
5. Open /curator.
6. Create/select a batch.
7. Import or point at sample images.
8. Verify thumbnails, lightbox, metadata.
9. Move images between folders.
10. Stop ComfyUI and confirm no shutdown errors.
```

AI and watcher require separate manual smoke tests because they involve long-running work and filesystem movement.

## 20. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Flask route behavior changes during aiohttp port | Frontend breakage | Preserve response shapes; port route-by-route; adapt existing tests. |
| Static path mistakes | UI loads but JS/CSS fail | Use `/curator_static`; verify browser network tab. |
| Path traversal regression | Security/file safety issue | Centralize `safe_path`; add tests for `..` and absolute paths. |
| Moving ComfyUI outputs too early | Corrupt/missing generated outputs | Watcher default disabled; keep size-stability check; prefer completed-output events later. |
| AI cancellation cannot interrupt blocking HTTP call | Shutdown delay | Use short timeouts; tracked executor/thread; async client later. |
| Daemon threads killed mid-write | Corrupt run state or partial file moves | Avoid daemon threads in native lifecycle; bounded graceful shutdown. |
| Registry rejects route-only empty mappings | Publication delay | Manager accepts empty mappings; add utility node if registry validation fails or for discoverability. |
| Secrets in config JSON | Local secret exposure | Mask API keys in GET responses; document local plaintext storage; allow env override. |
| Dependency conflicts | Manager install failure | Keep dependencies minimal; avoid Flask/dotenv in native mode. |
| ComfyUI frontend API changes | Button/settings break | Use StarChart pinned APIs and Lora-Manager fallback pattern. |

## 21. Explicit Open Questions

These do not block proof-of-concept implementation:

1. Exact final package name:
   - `image-curator`, `curator`, `comfyui-curator`, or `ComfyUI-Curator`.
   - Registry names are immutable after creation.
2. Exact minimum `requires-comfyui` version.
   - Syntax is known; minimum should be determined by testing.
3. Whether to keep Flask standalone in the same repo long-term.
4. Whether to keep Jinja rendering or convert Curator UI to fully static HTML/JS.
5. Whether AI client should remain blocking urllib initially or be converted to aiohttp.
6. Whether watcher should remain polling or use ComfyUI execution/output event hooks later.
7. Whether first registry publication should include a utility node to improve discoverability.

## 22. Minimum Native Integration Scope

The minimum native integration consists of the shell and shared static UI:

```text
Goal: Native ComfyUI shell that opens the existing Curator UI.

In scope:
- __init__.py
- py/curator_manager.py
- web/comfyui/top_menu_extension.js
- /curator page route
- /curator_static static mount
- /api/curator/health
- pyproject.toml / requirements.txt draft

Out of scope:
- full route migration
- watcher
- AI scoring
- optional nodes
- Registry publication
```

This keeps the first step small, verifiable, and reversible.

## 23. Quick Reference Decisions

| Topic | Decision |
|---|---|
| UI location | Full-page `/curator`, opened from ComfyUI button. |
| Backend framework | aiohttp routes on `PromptServer`, not Flask. |
| Static assets | `/curator_static/*`. |
| API prefix | `/api/curator/*`. |
| Config location | `folder_paths.get_system_user_directory("curator")`. |
| Batch default root | `<ComfyUI user system curator dir>/batches`. |
| Import source default | `folder_paths.get_output_directory()`. |
| Watcher default | Disabled. |
| AI queue | Keep single-worker semantics; lifecycle-managed. |
| WebSocket | Optional notification layer only. |
| Empty node mappings | Accepted by Manager; likely okay, but add node later for discoverability. |
| First dependency set | `Pillow`; add `jinja2` only if needed. |
| Registry path | Comfy Registry preferred; legacy Manager list is secondary. |
