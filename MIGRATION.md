# MIGRATION.md

**Last Updated:** 2026-11-15

**Audience:** operators upgrading from the removed standalone Flask UI to the
ComfyUI native extension. Read [README.md](README.md) first for feature and
configuration reference.

The standalone Flask web app (`app.py`, `templates/index.html`, the `/api/*`
family of routes, and the systemd service template) has been removed. The native
ComfyUI extension is now the only web UI, and `curate.py` remains the headless
CLI. **Your library and history data need no conversion**: batch folders, the
undo journal, favorites, run history, prompt-history and search caches, and media
caches all stay exactly where they are. Only Curator's own native configuration
and active-batch pointer live somewhere new (see below).

## What changed

| Removed | Replaced by |
|---------|-------------|
| `app.py` Flask server and browser UI | `/curator` page served by the ComfyUI extension |
| `templates/index.html` | `templates/curator.html` (sole page template) |
| `/api/*`, `/thumb/*`, `/preview/*`, `/image/*` | `/api/curator/*`, `/curator/thumb/*`, `/curator/preview/*`, `/curator/image/*` |
| `ai_curate/routes.py` (Flask Blueprint) | `image_curator/native_ai_routes.py` + `ai_curate/native_lifecycle.py` |
| `image-curator.service.example` | ComfyUI is the hosting process; see below |
| Flask runtime dependency | Jinja2 (explicit), Pillow, python-dotenv |
| `templates/index.html` → `curator.html` generation step | Edit `templates/curator.html` directly |

Unchanged: the batch folder layout, the CLI (`curate.py` flags and defaults), the
shared `image_curator/` and `ai_curate/` backends, and the native API response
shapes for batches, moves/undo, favorites, public copies, prompt history, media
search, and AI scoring.

## Your data stays where it is

Nothing in the upgrade rewrites, moves, or deletes library data. Point native
mode at the same batches root and the existing state is used as-is.

| Data | Location | After migration |
|------|----------|-----------------|
| Batches and stages | `<batches-root>/<batch>/{inbox,shortlisted,finals,rejects}/` | Unchanged |
| Generated public copies | `<batch>/public/` | Unchanged (derivatives only) |
| Undo / History journal | `<batches-root>/.curator-undo/history.json` | Preserved and still authoritative; 100 operations / 30 days; never edit by hand |
| Batch favorites | `<batch>/.favorites.json` | Unchanged |
| Universal favorites | `<batches-root>/.favorites.json` | Unchanged |
| AI run history | `<batch>/ai-curate/runs/<run_id>.json` + `latest.json` | Unchanged; older runs still load and compare |
| Prompt history cache | `<batch>/prompt-history.json` | Unchanged; rebuild if the modal reports a stale image count |
| Media search index | `<batch>/search-index.json` | Unchanged and rebuildable; rebuild if reported stale |
| Thumbnail/preview caches | `<batch>/.thumbs/`, `<batch>/.previews/` | Regenerated on demand; safe to delete |
| Active batch pointer | old standalone `state.json` (for example `~/.config/image-curator/state.json`) | **Not migrated.** Native mode stores `state.json` in the Curator system-user directory; reselect your active batch once |
| Native settings | `<curator system-user dir>/config.json` (new) | Created when you first save the Settings modal |

Two details are worth keeping in mind:

- **Undo / History follows the resolved library root.** If you point native mode
  at the same directory (or at the same symlink/junction to it), existing
  history stays available. Do not retarget a library symlink while Curator is
  running, and keep only one curator process against a library.
- **Move recovery is not a backup.** `.curator-undo/history.json` covers manual
  review moves only; imports, deletions, AI moves, and public derivatives are
  not recoverable through it. Keep it with your library backups.

## Migration steps

1. Stop the standalone service before starting native mode, and remove or
   disable any systemd unit that ran `app.py`. Two writers against one library
   can interleave moves and invalidate undo recovery.
2. Install this repository as a ComfyUI custom node. The custom-node folder must
   be named `comfyui-curator`.
3. Install dependencies into ComfyUI's Python environment:

   ```bash
   # Windows (embedded Python)
   ..\..\python_embeded\python.exe -m pip install -r requirements.txt

   # Linux / macOS
   pip install -r requirements.txt
   ```

   This installs Jinja2, Pillow, and python-dotenv. `aiohttp` and ComfyUI's
   `server`/`folder_paths` modules come from ComfyUI itself and are deliberately
   not pinned here.
4. Restart ComfyUI and open `/curator` (or the Curator action-bar button).
5. Open the header **Settings** modal and set the paths to your existing data:
   - **Batch root** — your current batches root, for example
     `/mnt/storage/image-curator/batches`. Without an override, native mode
     uses `<curator system-user dir>/batches`, which is *not* your old library.
   - **Import source** — your current ComfyUI outputs directory (native mode
     otherwise defaults to ComfyUI's own `output` directory).
   - **Public export root** — the old `IMAGE_CURATOR_PUBLIC_EXPORTS` value, or
     disable public export if you do not use it. Native mode otherwise defaults
     to `<curator system-user dir>/public-exports`.
   - **AI scoring** — LLM base URL, model list, request timeout, and the API key.
     API keys are never returned by the settings API, so re-enter the key once;
     it can be replaced or explicitly cleared later.
6. Save, then verify:
   - batches and per-stage counts match the old UI;
   - **Undo / History** lists earlier manual moves;
   - favorites, including All Favorites, still resolve;
   - AI **Runs** shows existing per-batch run history;
   - Prompt History and Library Search load, or rebuild their caches if flagged
     stale.
7. Select your active batch once (the state pointer location changed).
8. Optional cleanup: delete the old virtual environment and `.env` if you do not
   use the CLI; keep the library, `.curator-undo/`, and any batch-local JSON
   files.

## Settings vs environment

Native mode resolves configuration in this order:

1. values saved in the Curator header **Settings** modal
   (`<curator system-user dir>/config.json`);
2. environment variables in the ComfyUI process (`IMAGE_CURATOR_*`);
3. ComfyUI-owned defaults.

The Settings modal shows the effective batch root, import source, and public
export root, so you can confirm what native mode actually resolved. ComfyUI
resolves the system-user directory through
`folder_paths.get_system_user_directory("curator")` (typically under ComfyUI's
`user` directory, and `config.json` plus `state.json` live inside it).

Two constraints matter when moving environment-based configuration across:

- **`.env` files are not read by the native extension.** There is no
  `load_dotenv()` on the ComfyUI import path, so a copied `.env` no longer
  affects the web UI. Put fallback variables in ComfyUI's own process
  environment instead (service unit, container environment, or an exported
  shell variable before launching ComfyUI).
- **`.env` still works for the CLI.** `curate.py` calls `load_dotenv()` before
  importing `ai_curate`, so `.env` remains valid for headless runs only.

Defaults also differ between the two entry points:

| Setting | Native default | CLI / env default |
|---------|----------------|-------------------|
| Batch root | `<curator system-user dir>/batches` | `IMAGE_CURATOR_BATCHES`, else `~/image-curator/batches` |
| Import source | ComfyUI's `output` directory | not used by the CLI; `IMAGE_CURATOR_COMFYUI` is the native fallback |
| Public export root | `<curator system-user dir>/public-exports` | not used by the CLI |
| Active batch state | `<curator system-user dir>/state.json` | not used by the CLI |
| LLM URL / model / timeout | Settings, then `IMAGE_CURATOR_LLM_URL` / `IMAGE_CURATOR_MODEL` / `IMAGE_CURATOR_TIMEOUT` | same variables (via `.env` or the shell) |
| API key | Settings, then `IMAGE_CURATOR_API_KEY` | same variable (via `.env` or the shell) |

`IMAGE_CURATOR_HOST` and `IMAGE_CURATOR_PORT` are gone. Curator is served by
ComfyUI's HTTP server, so bind address and port are ComfyUI's own options (for
example `python main.py --listen 127.0.0.1 --port 8188`). Native Curator adds no
authentication; for remote access, place ComfyUI behind a reverse proxy with
auth.

## Scripted or bookmarked clients

If you scripted against the old server, replace the prefixes:

| Old | New |
|-----|-----|
| `GET /api/batches` and other `/api/*` routes | `/api/curator/*` (namespace documented in `README.md` and `AGENTS.md`) |
| `/thumb/<batch>/<folder>/<name>` | `/curator/thumb/...` |
| `/preview/<batch>/<folder>/<name>` | `/curator/preview/...` |
| `/image/<batch>/<folder>/<name>` | `/curator/image/...` |
| `/` or `/static/...` page assets | `/curator` and `/curator_static/...` |

The CLI surface is unchanged: `curate.py` keeps its flags, defaults, and the
deprecated `--panel` alias.

## Rollback

The previous implementation remains in git history. Checking out the revision
before the removal restores `app.py` and the standalone UI against the same
library layout — no data conversion is needed in either direction. Keep
`<batches-root>/.curator-undo/` with your backups; it is recovery state, not a
rebuildable cache.

## Post-migration checklist

- [ ] ComfyUI restarted; `/curator` page loads with assets and no 404s
- [ ] Action-bar Curator button opens the page
- [ ] Batch root, import source, and public export root correct in Settings
- [ ] Stage counts match the pre-migration library
- [ ] Undo / History shows prior operations and a test move can be undone
- [ ] Favorites (batch and All Favorites) resolve
- [ ] AI Runs shows prior runs; a scoring job can be submitted and cancelled
- [ ] Prompt History and Library Search load or rebuild successfully
- [ ] Standalone service stopped and removed from startup
