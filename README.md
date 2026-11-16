# comfyui-curator

Operator-focused desktop tool for reviewing generated images, organizing
them into batch workflow folders, and optionally running vision-LLM scoring
before manual selection. Single-user, local-first, filesystem-backed.

## What it does

- **Batch review UI** -- asset-manager style batch sidebar, stable local folder
  stage rail (inbox / shortlisted / finals / rejects), compact workspace toolbar,
  center thumbnail grid, sort/favorites/AI controls, and persistent thumbnail density modes.
  Drag images between folders, multi-select or Select All for bulk moves, and
  reopen recent manual moves from **Undo / History** after the toast disappears.
- **Lightbox viewer** -- full-size image review with zoom, keyboard
  navigation, scored-image jumps, PNG generation metadata (prompt,
  seed, sampler, CFG, LoRAs), adjacent JSON sidecars, and two-image comparison
  from selected images.
- **Compare candidates** -- a compact selection tray keeps up to six still-image
  candidates visible, supports ordering/removal, skips non-still media, and
  compares the first two without discarding the wider selection.
- **Shortcut learning** -- small per-context hints teach grid, selection,
  lightbox, and compare keys progressively; each context can be dismissed and
  the complete reference remains in Help.
- **Typed media review** -- PNG/JPG/JPEG/WebP stills, animated GIFs, MP4 video,
  and MP3 audio share the filesystem workflow. The grid uses WebP posters;
  GIF/video hover previews are optional, and video/audio play in the lightbox.
- **Favorites** -- one-click stars persist favorites at both batch and
  universal scope, with a favorites-only filter and All Favorites sidebar view.
- **Public posting prep** -- selected originals can be exported as
  metadata-stripped, optionally watermarked copies under each batch's `public/`
  folder, with batch Public and virtual All Public views for generated copies.
- **Prompt history** -- manually build per-batch prompt indexes from PNG
  metadata, then search, copy, and inspect prompt groups from a header modal.
- **Library search** -- a shared Images / Prompt groups modal searches filenames,
  PNG generation fields, and bounded adjacent JSON sidecar keys and values in the
  current folder, current batch, or all batches. Per-batch search indexes are
  local rebuildable snapshots with explicit readiness, age, and item-count
  status; the filesystem remains authoritative. Images queries can become
  persistent workspace filters with visible query, scope, and source chips so
  grid and lightbox review remain inside the matching set until the operator
  edits or clears the filter. Pending workspace-search applies are cancelled
  by closing Search, changing
  its query/scope/tab, or navigating away; late results do not reclaim the view.
- **Import from ComfyUI** -- one-click **Import All** moves available outputs
  and adjacent JSON sidecars into the selected batch inbox. A lightweight
  one-second status check enables the always-visible control when safe regular
  media files arrive. Collision-safe renames and partial failures are reported
  in Activity, and files that could not be moved remain pending for retry.
- **AI-assisted scoring (optional)** -- sends images to a local vision LLM
  to check for prompt elements and quality baselines. The unified right
  inspector layers Overview, Metadata, and AI Evidence; its AI Evidence view
  retains the Inspect / Score / Runs workflows. Scores are advisory; manual
  curation is authoritative.
- **Run history and comparison** -- scored runs are saved per-batch.
  Compare two runs to see which images gained or lost points.
- **CLI scoring** -- `python curate.py --batch my-batch --prompt "a cat"`
  for headless workflows.

## Quickstart

The ComfyUI native extension is the supported web UI. The `curate.py` CLI
remains for headless scoring. Upgrading an existing standalone installation?
Follow [MIGRATION.md](MIGRATION.md) -- batches, Undo history, favorites, and AI
run history stay in place.

### ComfyUI native extension

Recommended for ComfyUI users. Provides the full curation workflow inside
ComfyUI without a separate server process.

1. Clone or copy this repository into ComfyUI's `custom_nodes` folder.
   The custom-node folder must be named `comfyui-curator`:
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/FrostySDXL/comfyui-curator.git comfyui-curator
   ```

2. Install required dependencies in ComfyUI's Python environment:
   ```bash
   # Windows (embedded Python)
   cd ComfyUI\custom_nodes\comfyui-curator
   ..\..\python_embeded\python.exe -m pip install -r requirements.txt

   # Linux / macOS (system or venv Python)
   cd ComfyUI/custom_nodes/comfyui-curator
   pip install -r requirements.txt
   ```

3. Restart ComfyUI.

4. Use the Curator action-bar button or open `/curator`.

Native settings, batch paths, import source, and AI model configuration are
managed through the header **Settings** modal inside the Curator page. See
[Configuration](#configuration) for path defaults, Docker guidance, and
environment fallbacks.

### CLI scoring

`curate.py` runs the same scoring pipeline headlessly from a normal Python
environment (Python 3.10 or newer) and still loads `.env`.

```bash
git clone https://github.com/FrostySDXL/comfyui-curator.git
cd comfyui-curator
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

# Optional: copy .env.example to .env to configure the batch root and model
python curate.py --batch my-batch --prompt "a cat on a rooftop" --dry-run
python curate.py --batch my-batch --prompt "a cat on a rooftop" --move --dest shortlisted
```

The CLI reads `IMAGE_CURATOR_BATCHES` for the batch root and scores images that
already sit in a batch folder (default `inbox/`); it has no import step, so copy
or save the files you want scored into `IMAGE_CURATOR_BATCHES/<batch>/inbox/`
first. Pulling fresh ComfyUI outputs is a native workflow: use **Import All** in
the Curator page, configured through Settings (with `IMAGE_CURATOR_COMFYUI` as
its environment fallback).

Runtime dependencies are Jinja2 (renders the native page), Pillow (metadata,
derivatives, and cache generation), and python-dotenv (CLI `.env` loading);
`aiohttp` and ComfyUI's host modules come from ComfyUI itself. `requirements.txt`
is the convenience install file; use `requirements-lock.txt` when you need the
pinned dependency set. For development, install `requirements-dev.txt`: it
includes `requirements-dev.in`, which adds `aiohttp` for the real native HTTP
tests plus pytest, Ruff, and mypy. `requirements-dev-lock.txt` is the
reproducible dev build resolved on the minimum supported Python 3.10.

FFmpeg is optional but recommended for GIF/MP4 hover previews and embedded
MP3/MP4 artwork extraction. Install `ffmpeg` on `PATH`, or set
`IMAGE_CURATOR_FFMPEG` to its absolute executable path. Missing or failing
FFmpeg never removes originals: the grid uses a deterministic audio/video tile,
and hover preview requests return an unavailable response while normal review
continues.

The repository, Python distribution, Registry package, and expected custom-node
folder are named `comfyui-curator`. Internal Python modules, environment
variables, and existing local configuration paths retain their established
`image_curator` / `IMAGE_CURATOR_*` / `image-curator` names.

## Configuration

Native ComfyUI mode configures everything from the header **Settings** modal. It
persists operational settings in the Curator system-user directory as
`config.json`, and saved values take precedence over environment fallbacks and
ComfyUI-owned defaults. API keys are never returned by the settings API and can
be replaced or explicitly cleared. Import All remains an explicit operator
action. The modal shows the effective batch root, import source, and public
export root, so the resolved paths are never guesswork.

Native path defaults are inside ComfyUI's Curator system-user directory. In a
Docker deployment, every path in Settings and every path supplied through an
environment fallback is interpreted inside the container. To use host data,
mount the host directory into the container and configure Curator with the
container-side path. For example:

```yaml
services:
  comfyui:
    volumes:
      - /host/image-curator/batches:/data/curator-batches
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      IMAGE_CURATOR_BATCHES: /data/curator-batches
```

A host-only path such as `/mnt/storage/batches` is not visible unless that path
is mounted into the container. Without an override, native mode uses
`<ComfyUI system user directory>/curator/batches`, which works inside the
container but must be mounted if its contents should survive container removal.

Docker also has a separate network namespace. An LLM URL using `localhost`
targets the ComfyUI container itself. To reach a model server on the Docker host,
use `http://host.docker.internal:<port>`; Linux deployments require the
`host.docker.internal:host-gateway` mapping shown above. Use a Compose service
name for a model server in another container on the same Docker network.

Environment variables are fallbacks, not the primary configuration. The native
extension does not read `.env` files: set these names in ComfyUI's own process
environment (service unit, container environment, or a shell export before
launching ComfyUI) to use them as fallbacks. `curate.py` does load `.env`
through python-dotenv, so a copied `.env` file applies to the CLI only.

Copy `.env.example` to `.env` for CLI runs, or set the same names in ComfyUI's
environment for native fallbacks. Key variables:

Core path:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMAGE_CURATOR_BATCHES` | `~/image-curator/batches` (CLI), `<curator system-user dir>/batches` (native fallback) | Main library containing batch folders and their `inbox/`, `shortlisted/`, `finals/`, `rejects/`, and generated `public/` folders |
| `IMAGE_CURATOR_PUBLIC_EXPORTS` | (unset) | Optional safe root for copying/moving generated public copies to another filesystem location; when unset, native mode falls back to `<curator system-user dir>/public-exports` |

The active batch is stored as `state.json` in the Curator system-user directory
in native mode; there is no environment override for it.

Optional import source:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMAGE_CURATOR_COMFYUI` | ComfyUI's `output` directory (native fallback) | Folder that native **Import All** pulls from when ComfyUI outputs outside your batch inboxes; the CLI does not import |

Other settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMAGE_CURATOR_LLM_URL` | `http://localhost:8080` | Vision LLM endpoint |
| `IMAGE_CURATOR_MODEL` | (empty) | Model name (comma-separated for dropdown) |
| `IMAGE_CURATOR_API_KEY` | (empty) | Bearer token if your LLM requires auth |
| `IMAGE_CURATOR_TIMEOUT` | `120` | Vision LLM request timeout in seconds |
| `IMAGE_CURATOR_FFMPEG` | `ffmpeg` | FFmpeg executable used lazily for typed-media posters and hover-preview MP4 proxies |

Bind address and port are ComfyUI's own: Curator is served by ComfyUI's HTTP
server (for example `python main.py --listen 127.0.0.1 --port 8188`), so there
are no Curator host or port variables.

See `.env.example` for the full commented reference.

## Basic workflow

1. Create or select a batch.
2. Add generated images to `<batch>/inbox/`, or use **Import All** to pull from
   the configured import source (native: Settings; CLI: `IMAGE_CURATOR_COMFYUI`).
3. Review images in the grid or lightbox, then move keepers to `shortlisted` or
   `finals` and rejects to `rejects`.
4. Use Library Search for filename and media-metadata lookup; build Prompt groups
   when you want reusable normalized prompt pairs.
5. Prepare public copies when you need metadata-stripped, optionally watermarked
   posting files. Originals remain in the review folders.
6. Optionally run AI scoring against a local OpenAI-compatible vision model;
   scores are advisory.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | Open batch sidebar if closed, then focus batch search |
| `Ctrl+K` | Open batch sidebar if closed, then focus and select batch search |
| `Esc` | Contextual: clear search, close lightbox, close modal |
| `Ctrl+Z` | Undo last move (while toast is active) |
| `Ctrl+A` | Select all indexed media in the current folder (not in lightbox) |
| `Select All` button | Toggle selection for the current folder; large native folders use a revision-bound server selection |
| `U` | Toggle batch sidebar |
| `F` | Toggle favorites-only filter |
| `P` | Open Library Search on its last-used tab |
| `B` | Toggle AI score badges when an AI run is available |
| `V` | Toggle score-based sort when an AI run is available |
| `I` | Toggle AI sidebar |
| `H` | Toggle animated GIF/MP4 hover previews |

### Lightbox

| Key | Action |
|-----|--------|
| `←` `→` | Previous / next image |
| `[` `]` | Previous / next scored image |
| `Space` | Play / pause the active video |
| `M` | Toggle PNG metadata panel |
| `I` | Toggle lightbox AI review panel |
| `P` | Prepare a public copy for the current image |
| `S` | Move to shortlisted |
| `F` | Move to finals |
| `Shift+F` | Toggle favorite for current image |
| `R` | Move to rejects |
| `+` `-` | Zoom in / out |
| `0` | Reset zoom |
| `Ctrl+wheel` | Zoom around cursor |
| `C` | Pin active image as A for sticky compare; press again to clear Pin A |
| `Alt+Left/Right` | Advance both compare panes together |
| `Esc` | Close lightbox |

When exactly two review-folder images are selected, **Compare in Lightbox**
opens a side-by-side comparison. Click a pane to make it active, or press `C`
to pin the active image as A and walk candidate B with Left/Right. Use
Alt+Left/Right to advance both panes together; compare controls also expose
linked/unlinked Sync Pan/Zoom and an optional A/B Split for still images.

## UI behavior

- **Undo / History** retains manual review-folder moves across page reloads and
  server restarts. Undo works newest-first across batches within the configured
  library; `Ctrl+Z` uses the latest eligible move. The toast is only a shortcut,
  not the recovery deadline. History retains up to 100 operations for 30 days
  under `<batches-root>/.curator-undo/history.json`; keep this runtime file with
  library backups and do not edit it manually. Conflicting or changed files are
  not overwritten; incomplete recovery remains visible for retry. This is move
  recovery, not a backup or recycle bin: imports, deletion, AI moves, and public
  preparation/export are not covered, and there is no Redo.
  Run only one curator process against a given library and avoid external file
  changes during moves. Safe manual transfers require same-filesystem hardlink
  support; unsupported/cross-device transfers fail without an overwrite fallback.
  Interrupted, ambiguous pair transfers retain recovery evidence but may require
  manual repair. Content hashing and very large histories add disk work; the
  journal is capped at 256 MiB and 100,000 members per operation.
  The configured batches root may be a symlink or Windows directory junction
  to an existing library, including one on an external drive. Move history uses
  its resolved target; links inside the library are not granted that trust.
  Do not retarget the root link while Curator is running.
- Sidebar state and thumbnail density persist across sessions.
- Changing review scope clears the previous inspector target and selection.
  Inspector identity includes the source batch and folder, and native snapshot
  Select All/exclusions update the Overview count immediately.
- Lightbox videos autoplay and loop by default. Disable both together from
  **View → Autoplay + loop lightbox videos**; the preference persists locally.
- Background polling avoids interrupting lightbox review, drag/drop, and resize
  interactions. Import readiness uses a separate lightweight one-second poll;
  native batch summaries refresh every ten seconds.
- The header Activity center consolidates import, folder snapshot/thumbnail,
  prompt and media index, public export, and AI scoring status without blocking
  the grid. Failed or partial work retains supported Retry actions, and AI runs
  retain their existing cancellation path.
- AI Evidence previews how a score cutoff divides the loaded run before the
  operator applies it to the grid. Partial runs retain scored/failed totals and
  a bounded list of failed filenames and reasons.
- Native paged-folder lightbox moves advance to the next remaining image at the
  same review position instead of closing; the lightbox closes only when the
  folder has no remaining items.
- JSON sidecars named `asset.ext.json` (preferred) or `asset.json` follow media
  through import, review-folder moves, undo, and reject cleanup. The lightbox
  shows recognized external-favorites sidecars as structured fields,
  space-delimited tag chips, safe links, and raw JSON. Unknown structures remain
  one formatted block.
- Native real-folder views use immutable revisioned snapshots, 256-item pages,
  and row virtualization. At most 500 thumbnail elements are live even for a
  30,000-item folder; unchanged polls return only revision/count metadata.
- Public copies are generated derivatives only; originals stay in their review
  folders.
- Prompt history indexes are manual caches. Rebuild after significant curation
  sessions or when the modal reports a stale image count.
- Media search indexes cover every reviewable media type and both PNG chunks and
  adjacent JSON sidecars. Folder mutations mark an index stale; rebuild manually
  after editing an existing sidecar's contents in place.
- **Filter Workspace** turns the active Library Search query into a temporary
  source-qualified review collection. A compact bar keeps the query, scope,
  count, Edit search, and Clear filter visible; lightbox navigation remains
  inside the filtered set. Large result sets load in stable 500-item pages as
  the grid or lightbox reaches the loaded boundary, so every indexed match
  remains reviewable without increasing the 500-element live-thumbnail cap.
  Single-image lightbox moves remain available, while ambiguous mixed-source
  bulk selection is disabled.
- The header Help button shows keybindings and workflow notes.

## Security

Curator runs inside ComfyUI and is served by ComfyUI's HTTP server, so the bind
address and port are ComfyUI's own. Curator adds no authentication of its own --
sufficient for single-user local use. For remote access, put ComfyUI behind a
reverse proxy with auth (nginx, Caddy, etc.). Read `SECURITY.md` for related
guidance.

## ComfyUI extension

The repository includes a native ComfyUI integration:

- `__init__.py` -- ComfyUI custom-node entrypoint with `WEB_DIRECTORY`,
  `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS`.
- `py/curator_manager.py` -- registers `/curator`, `/curator_static`, health,
  and the namespaced native batch/image foundation.
- `image_curator/native_settings.py` -- resolves ComfyUI-owned batch, import,
  state, and persistent native configuration without the removed Flask stack.
- `image_curator/native_routes.py` -- aiohttp adapter for settings, batches,
  active state, manual import, revisioned/paged media lists, metadata, posters,
  previews, range-capable originals,
  single-image moves, multi-image moves, reject deletion, favorites
  (batch/universal toggles and All Favorites resolution), and public
  publish/export, listing, destination browsing, and copy/move/delete.
- `image_curator/native_ai_routes.py` and `ai_curate/native_lifecycle.py` --
  namespaced AI job, cancellation, and run-history routes with a lifecycle-owned
  single-worker queue and bounded shutdown.
- `web/comfyui/top_menu_extension.js` -- ComfyUI action-bar button that
  opens `/curator`.
- `templates/curator.html` -- the sole page template, served at `/curator` with
  `/curator_static/` asset paths and rendered server-side with Jinja2
  (available models and default model).
- Shared frontend URL helpers (`ccApiPath`, `ccThumbUrl`, `ccImageUrl`, and
  `ccPreviewUrl` in `static/js/state.js`) build the native URLs
  (`/api/curator`, `/curator/thumb`, `/curator/preview`, `/curator/image`).
- Selection and compare-candidate ownership lives in the ordered
  `static/js/selection.js` module; `static/js/moves.js` retains drag/drop,
  filesystem moves, undo, and reject deletion. Both modules intentionally
  share the mutable globals in `state.js`.
- `GET` and `POST /api/curator/settings` back the native-only Settings modal;
  editable paths are returned only by this dedicated local-operator endpoint.

Native foundation routes use `/api/curator/*`; media uses
`/curator/thumb/*`, `/curator/preview/*`, and `/curator/image/*`. Real-folder
transport uses `/api/curator/v2/folders/*` snapshot, poll, and item pages.
Single-image moves, multi-image
moves with durable operation-token undo, reject deletion, favorites
(batch/universal toggles, All Favorites), and public publish/export, listing,
destination browsing, copy/move/delete, prompt history, media search index/query,
and AI scoring lifecycle
are now native. Import All provides the explicit output-import workflow.

## Limitations

AI scoring runs in a single background thread. One job at a time; others
queue FIFO. Designed for single-user operation, not concurrent scoring.

## More

- **Contributing:** `CONTRIBUTING.md` -- verification, dependency
  management, change playbooks, repo structure.
- **Development scripts:** `scripts/README.md` -- verification runner modes and
  disposable local browser fixture setup.
- **Agent guidance:** `AGENTS.md` -- startup instructions for AI agents
  working in this repo, plus per-directory READMEs in `ai_curate/`,
  `image_curator/`, `static/`, `tests/`, and `scripts/`.
- **Upgrading:** `MIGRATION.md` -- standalone Flask removal, preserved library
  and Undo/History data, and native settings versus CLI environment variables.
- **Page template:** `templates/curator.html` is the single authoritative
  template; edit it directly. There is no second template to synchronize and no
  generator step.
- **License:** MIT -- see `LICENSE`.
