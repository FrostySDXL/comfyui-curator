# AGENTS.md

**Purpose:** Operator-focused web application for reviewing generated images with optional AI-assisted scoring. **Status:** Actively maintained. **Audience:** AI agents and single-operator maintainers. **Last Updated:** 2026-08-29

## Quickstart

- Read `README.md` first.
- Use the virtual environment at `.venv/`.
- Entrypoints: `__init__.py` (ComfyUI custom-node), `app.py` (Flask web UI + API), `curate.py` (CLI scoring).
- New non-AI backend logic -> `image_curator/`. New AI logic -> `ai_curate/`.
- Frontend is `templates/index.html` + ordered vanilla scripts under `static/js/` + split CSS files under `static/css/`.
- Verification: `python scripts/run_all.py` (default) or `--quick` for fast loops.
- Do not commit code that fails `ruff check` or `ruff format --check` on touched paths.

## What This Repo Provides

- **Batch filesystem workflow:** inbox/shortlisted/finals/rejects folders under `IMAGE_CURATOR_BATCHES/<batch>/`. Counts, metadata, operator-triggered Import All from ComfyUI outputs.
- **Web review UI:** Asset-manager style batch sidebar, compact workspace toolbar, center thumbnail grid, unified right inspector. Drag/drop moves, multi-select/Select All, durable Undo / History plus undo toast, progressive contextual shortcut hints, keyboard shortcuts, background polling.
- **Lightbox viewer:** Full-media review with zoom, PNG generation metadata plus adjacent JSON sidecars (`M` toggle), scored-image navigation (`[`/`]`), keyboard folder moves (`S`/`F`/`R`), linked/unlinked side-by-side comparison, a bounded selection-derived candidate tray, Pin A candidate walking, pair advancement, and A/B split.
- **Favorites workflow:** One-click favorites update batch and universal scope, with a favorites-only filter and virtual All Favorites sidebar view.
- **Public posting prep:** Selected originals export to metadata-stripped, optionally watermarked generated copies in `<batch>/public/`, with batch Public and virtual All Public views plus derivative-only copy/move/delete actions and export-root destination browsing/history.
- **Prompt history:** Manual PNG metadata prompt indexes with searchable/copyable Prompt History modal and staleness warning.
- **Library search:** Shared Images / Prompt groups modal. Images searches filenames,
  PNG generation metadata, and bounded adjacent JSON sidecar keys/values across a
  folder, batch, or all batches using rebuildable per-batch caches. Applied searches
  expose query/scope/source chips, and index status reports readiness, age, and count
  while preserving the filesystem as authoritative.
- **AI-assisted scoring:** Vision-LLM evaluation against element checklists via OpenAI-compatible `/v1/chat/completions`. Optional auto-move of top-N images. The AI sidebar has Inspect / Score / Runs tabs, run comparison, contextual image inspection, an explicit score-cutoff preview/apply flow, and bounded partial-failure evidence.
- **CLI headless scoring:** Same pipeline available via `curate.py` (dry-run, score-only, or score-and-move).
- **Core philosophy:** Manual curation is authoritative. AI is advisory. Filesystem is the operational truth.

## Key Concepts & Data Flows

```
app.py (Flask routes) ← standalone, fully supported
  ├── image_curator/batch_store.py  ← filesystem ops (create, list, move, counts, import)
  ├── image_curator/png_metadata.py ← PNG text-chunk extraction (Pillow)
  ├── image_curator/sidecar_metadata.py ← bounded adjacent JSON discovery/display + paired lifecycle helpers
  ├── image_curator/favorites.py    ← batch + universal favorites JSON storage
  ├── image_curator/publish.py      ← public derivative creation/list/copy/move/delete
  ├── image_curator/prompt_history.py ← manual PNG prompt index cache
  ├── image_curator/search_index.py ← rebuildable typed-media + sidecar search cache/query
  ├── image_curator/search_index_jobs.py ← shared cancellable search-index job lifecycle for Flask/native
  ├── image_curator/web_validation.py ← route path/batch validation helpers
  ├── image_curator/media.py        ← typed poster/hover-preview cache and fallback helpers
  ├── image_curator/folder_index.py ← immutable background revisions, pages, O(1) lookup
  ├── image_curator/move_history.py ← durable manual review-move receipts and newest-first undo
  ├── ai_curate/config.py           ← env-backed constants, paths, caps
  ├── ai_curate/elements.py         ← prompt parsing + element extraction + quality checklists
  ├── ai_curate/job_validation.py   ← AI curation submit payload validation
  ├── ai_curate/routes.py           ← AI curation Flask Blueprint routes
  ├── ai_curate/client.py           ← VisionClient (raw urllib -> /v1/chat/completions)
  ├── ai_curate/scoring.py          ← image enumeration + scoring loop
  ├── ai_curate/worker.py           ← scoring worker orchestration core
  ├── ai_curate/queue.py            ← FIFO single-worker job queue (threading)
  ├── ai_curate/storage.py          ← run history JSON persistence (atomic .tmp writes + filesystem containment)
  ├── ai_curate/models.py           ← JobState, ImageResult, CurationRun, RunTotals
  └── ai_curate/native_lifecycle.py ← native AI lifecycle: idempotent startup, submission gate, worker tracking, permanent shutdown

curate.py (CLI)
  └── ai_curate/  (same pipeline, no queue — synchronous scoring in-process)

ComfyUI native extension
  ├── __init__.py                     ← ComfyUI custom-node entrypoint, WEB_DIRECTORY
  ├── py/curator_manager.py           ← registers native page, static mount, health, foundation routes, and AI lifecycle hooks
  ├── image_curator/native_settings.py ← locked atomic native config store and persisted/env/default resolution
  ├── image_curator/native_routes.py  ← aiohttp batch/image/move/delete/favorites/public/prompt-history foundation adapter
  ├── image_curator/native_ai_routes.py ← aiohttp AI curation route adapter (/api/curator/ai-curate/*) using NativeAiLifecycle
  ├── web/comfyui/top_menu_extension.js ← action-bar button opening /curator
  └── templates/curator.html          ← native page template (derived from index.html)

Frontend (shared static/js/*.js + static/css/*.css)
  ├── templates/index.html  ← standalone page (Flask, /static/ paths)
  ├── static/js/activity-center.js ← shared background-work state, rendering, retry/cancel hooks, and operation adapters
  └── templates/curator.html ← native page (ComfyUI, /curator_static/ paths, CURATOR_NATIVE flag)
```

- **Single source of truth:** Filesystem under `IMAGE_CURATOR_BATCHES/<batch>/`.
- **Generated public copies:** `<batch>/public/` contains posting derivatives; originals remain in review folders.
- **AI run history:** `<batch>/ai-curate/runs/<run_id>.json` + `<batch>/ai-curate/latest.json` pointer.
- **State file:** `IMAGE_CURATOR_STATE` (default `~/.config/image-curator/state.json`). Stores active batch.

## Key Files & Responsibilities

| Category | Key Files / Folders | Role |
|----------|---------------------|------|
| **Entrypoints** | `app.py` | Flask API + web UI serving + AI worker threads |
| | `curate.py` | CLI entrypoint for headless scoring (argparse, no queue) |
| **Non-AI Backend** | `image_curator/batch_store.py` | Batch creation, folder layout, file moves, counts, import, state persistence |
| | `image_curator/png_metadata.py` | ComfyUI/A1111 PNG text-chunk extraction (prompt, seed, sampler, CFG, LoRAs, etc.) |
| | `image_curator/sidecar_metadata.py` | Prefers `asset.ext.json` then `asset.json`, safely parses bounded JSON without type coercion, and keeps the selected sidecar paired through moves/deletion |
| | `image_curator/favorites.py` | Batch/universal favorites storage, toggle helper, universal favorite resolution |
| | `image_curator/publish.py` | Metadata-stripped optional-watermark public copy creation, public listing, external copy/move/delete under configured export root |
| | `image_curator/prompt_history.py` | Manual prompt-history cache builder from PNG metadata |
| | `image_curator/search_index.py` | Per-batch typed-media search index, bounded JSON sidecar flattening, AND-token query, stale-folder detection |
| | `image_curator/search_index_jobs.py` | Shared cancellable search-index jobs with one active build per pinned root+batch, atomic cancellation safety, bounded terminal retention, and shutdown joins |
| | `image_curator/web_validation.py` | Path traversal and existing-batch validation helpers used by app route wrappers |
| | `image_curator/media.py` | Thumbnail cache key/freshness helpers and WebP generation |
| | `image_curator/README.md` | Module-scoped agent startup guide (layout, contracts, gotchas) |
| **Native Extension** | `__init__.py` | ComfyUI custom-node entrypoint; exposes `NODE_CLASS_MAPPINGS`, `WEB_DIRECTORY`, `NODE_DISPLAY_NAME_MAPPINGS`; loads `CuratorManager` via importlib (tolerates missing `server` module for standalone compatibility) |
| | `py/curator_manager.py` | Registers `/curator`, `/curator_static`, health, and native foundation routes on `PromptServer`; idempotent `_registered` guard |
| | `image_curator/native_settings.py`, `image_curator/native_routes.py` | Resolve ComfyUI-owned paths and provide namespaced settings, batch/state/import, image, metadata, thumbnail, original, single-image move, multi-image move, delete-rejects, favorites, public publish/export, listing, destination browsing, copy/move/delete, and prompt history build/rebuild/load/staleness/aggregate routes without Flask lifecycle imports |
| | `image_curator/native_ai_routes.py` | Aiohttp route adapters for `/api/curator/ai-curate/*` using `NativeAiLifecycle`; validates, submits, lists, gets, cancels jobs and serves batch run history, latest runs, and element history |
| | `web/comfyui/top_menu_extension.js` | ComfyUI action-bar button that opens `/curator` in a new tab |
| | `templates/curator.html` | Native page template derived from `index.html`; `/curator_static/` paths, `window.CURATOR_NATIVE = true`; must stay synchronized with `index.html` |
| **AI Backend** | `ai_curate/config.py` | Env-backed constants: `BATCHES_DIR`, `COMFYUI_OUTPUT`, `DEFAULT_BASE_URL`, `DEFAULT_TOP_N` (15), `TOP_N_CAP` (100), `ELEMENT_CAP` (12) |
| | `ai_curate/README.md` | Module-scoped agent startup guide (pipeline, internal contracts, gotchas) |
| | `ai_curate/elements.py` | Prompt auto-extraction, explicit element building, quality baseline checks |
| | `ai_curate/routes.py` | Flask Blueprint for `/api/ai-curate/*` routes with app-injected queue/storage/lifecycle dependencies |
| | `ai_curate/job_validation.py` | Web AI job payload validation with app-injected dependencies |
| | `ai_curate/models.py` | `JobState` enum, `ImageResult` (per-image score), `CurationRun`, `RunTotals` |
| | `ai_curate/client.py` | `VisionClient`: base64 encode + POST to `/v1/chat/completions` (raw urllib) |
| | `ai_curate/scoring.py` | `find_images`, `build_scoring_prompt`, `score_images` loop |
| | `ai_curate/worker.py` | AI scoring worker core for scoring, cancellation, optional top-N moves, and queue completion |
| | `ai_curate/queue.py` | `QueueManager`: FIFO single-worker job queue with cancel support |
| | `ai_curate/storage.py` | `RunStorage`: atomic JSON persistence for run history with filesystem containment (symlink rejection, path-escaping prevention, non-regular-file rejection) |
| | `ai_curate/native_lifecycle.py` | `NativeAiLifecycle`: native AI lifecycle manager with idempotent startup, permanent-shutdown state machine, submission gate, worker thread tracking, public `submit_job()`, and batch-folder containment |
| **Frontend** | `templates/index.html` | Single-page Flask template (Jinja2, server-injected model list) |
| | `templates/curator.html` | Native ComfyUI template derived from `index.html` with `/curator_static/` paths and `CURATOR_NATIVE` flag; must stay synchronized with `index.html` |
| | `static/js/state.js`, `dom-utils.js`, `api.js`, `sidebar.js`, `batches.js`, `grid.js`, `favorites.js`, `publish.js`, `selection.js`, `moves.js`, `lightbox.js`, `metadata.js`, `prompts.js`, `ai-*.js`, `ai.js`, `polling.js`, `modals.js`, `combobox.js`, `keyboard.js`, `events.js`, `bootstrap.js` | Ordered classic browser scripts; vanilla JS, imperative, no framework/build step; `state.js` includes `ccApiPath`/`ccThumbUrl`/`ccImageUrl` helpers for dual-mode (standalone Flask vs native ComfyUI) URL construction |
| | `static/js/app.js` | Compatibility stub pointing to the split files |
| | `static/css/base.css`, `sidebar.css`, `layout.css`, `grid.css`, `lightbox.css`, `modals.css`, `prompts.css`, `toast.css`, `ai.css`, `responsive.css` | Browser-loaded split styling in template order (dark theme, flexbox + CSS grid) |
| | `static/README.md` | Module-scoped agent startup guide (global state, function groups, API calls, gotchas) |
| **Tests** | `tests/unit/` | Isolated logic plus source-scraping frontend-invariant tests |
| | `tests/component/` | In-process multi-module (Flask route contracts, AI worker lifecycle) |
| | `tests/integration/` | Full HTTP + filesystem workflow (Flask test client, real files) |
| | `tests/README.md` | Module-scoped agent startup guide (layers, fixtures, markers, coverage gaps) |
| **Scripts** | `scripts/run_all.py` | Multi-tool verification runner (ruff, compileall, pytest, mypy, JS syntax, git diff) |
| | `scripts/README.md` | Module-scoped agent startup guide (verification modes) |
| **Config** | `pyproject.toml` | Build system, Comfy Registry package metadata, ruff, and mypy configuration |
| | `pytest.ini` | Test markers (`unit`, `component`, `integration`) and paths |
| | `.env.example` | Documented environment variable reference (never read `.env` directly) |
| **Deployment** | `image-curator.service.example` | Templated systemd unit (use this, not the production service file) |
| **Guidance** | `README.md`, `CONTRIBUTING.md`, `AGENTS.md` | Operator docs, contributor workflow, agent startup |
| **Generated** | `.thumbs/`, `.previews/`, `<batch>/search-index.json`, `<batch>/ai-curate/runs/`, `<batch>/ai-curate/latest.json`, `__pycache__/`, `*.egg-info/` | **Do not edit.** Created at runtime. |

## Decision Tree

| Task | Read | Verify |
|------|------|--------|
| UI layout, shortcuts, lightbox, sidebars | `static/README.md` then `templates/index.html`, relevant `static/js/*.js`, relevant `static/css/*.css` files | Manual browser smoke test; `python scripts/run_all.py --quick` |
| Flask API or batch filesystem behavior | `image_curator/README.md` then `app.py`, matching frontend calls in relevant `static/js/*.js`, integration/component tests | `python -m pytest tests/integration/ tests/component/ -v` |
| AI scoring, queueing, run history | `ai_curate/README.md` then `ai_curate/`, `curate.py`, unit tests | `python -m pytest tests/unit/test_client.py tests/unit/test_scoring.py tests/unit/test_queue.py tests/unit/test_storage.py tests/unit/test_elements.py tests/unit/test_models.py tests/unit/test_config.py -v` |
| PNG metadata extraction | `image_curator/README.md` then `image_curator/png_metadata.py`, unit test | `python -m pytest tests/unit/test_png_metadata.py -v` |
| Favorites or prompt history | `image_curator/README.md` then `image_curator/favorites.py`, `image_curator/prompt_history.py`, app routes, frontend calls | `python -m pytest tests/unit/test_favorites.py tests/unit/test_prompt_history.py tests/integration/test_favorites_api.py tests/integration/test_prompt_history_api.py -v` |
| Library/media metadata search | `image_curator/README.md`, `image_curator/search_index.py`, `sidecar_metadata.py`, `static/js/prompts.js`, both route adapters | `python -m pytest tests/unit/test_search_index.py tests/integration/test_search_api.py tests/component/test_native_curator_api.py -v` |
| Public posting prep | `image_curator/README.md` then `image_curator/publish.py`, app routes, `static/js/publish.js`, public-view frontend paths | `python -m pytest tests/unit/test_publish.py tests/integration/test_publish_api.py tests/unit -k frontend -v` |
| Docs or repo organization | `README.md`, `CONTRIBUTING.md`, this file | `python scripts/run_all.py --skip-js` |
| Deployment assumptions | `image-curator.service.example`, `app.py` constants, `ai_curate/config.py` | Review env vars in `.env.example` |

## Mission

Maintain a fast operator-facing curation workflow for generated images with optional AI-assisted scoring, without making AI the source of truth.

## Non-goals

- Public-facing docs site
- Generic DAM/media-library scope
- Silent contract changes to API routes, batch layout, or CLI behavior

## STRICT RULE

- The production `image-curator.service` may contain sensitive information. Never read it. Use `image-curator.service.example` as the reference template instead.

## Public Compatibility Surfaces

Treat these as stability-sensitive:

- Flask API request/response shapes consumed by the frontend
- Batch directory structure under `BATCHES_DIR/<batch>/` (configured by `IMAGE_CURATOR_BATCHES`)
- AI run-history files under `BATCHES_DIR/<batch>/ai-curate/`
- `curate.py` CLI flags and default behaviors while the CLI remains active
- Runtime state file location (configured by `IMAGE_CURATOR_STATE`)
- `image-curator.service.example` template expectations
- Header Help modal content, contextual shortcut-learning copy/dismissal semantics, keyboard shortcuts, and sidebar toggle labels
- Header Activity indicator/panel lifecycle labels and supported Retry/Cancel actions
- Lightbox PNG metadata route shape, toggle shortcut (`M`), and displayed field set
- Batch and AI sidebar button labels as stateful operator-facing cues, not static text
- Workspace toolbar control IDs/order, density controls, Select All behavior, and thumbnail state classes
- AI run history labels, compare controls, bounded candidate-tray ordering/removal/launch behavior, and image inspector as operator-facing compatibility surfaces
- AI score-cutoff preview/apply/clear semantics and partial-failure labels/details
- Favorites API shapes, favorites filter button, All Favorites sidebar entry, and lightbox/thumb star behavior
- Public API shapes, batch `public/` generated-output view, All Public sidebar entry, public action labels, public export-root destination browser/history, and derivative-only safety copy
- Library Search Images / Prompt groups tabs, Images-to-workspace query/scope/source chips and Edit/Clear actions, per-batch index status/age/count labels, cancellable media-index job routes and `cancel_accepted` semantics, Prompt History controls, search and prompt-history API shapes, and manual cache file semantics
- Native extension entrypoint (`__init__.py` exports), `WEB_DIRECTORY`, `/curator` page route, `/curator_static` static mount, and `/api/curator/health` route
- `templates/curator.html` two-transform parity with `index.html` (`/static/` → `/curator_static/` plus `window.CURATOR_NATIVE = true` before ordered scripts)
- Shared frontend `ccApiPath`/`ccThumbUrl`/`ccImageUrl` URL helper behavior and mode-detection through `window.CURATOR_NATIVE`

## Structure Rules

- Root-level entrypoints remain active for now: `app.py` and `curate.py`
- New shared non-AI backend logic goes in `image_curator/`
- New shared AI backend logic goes in `ai_curate/`
- Keep HTML in `templates/`, browser logic in `static/js/`, styling in `static/css/`
- Put isolated logic tests in `tests/unit/`
- Put in-process multi-module checks in `tests/component/`
- Put Flask/API/filesystem workflow checks in `tests/integration/`
- Keep local helper scripts in `scripts/`

## Task Playbooks

### UI change

- Read `templates/index.html`, the relevant ordered `static/js/*.js` files, and the relevant `static/css/*.css` files
- Preserve the center grid as the primary review surface
- Preserve the compact workspace toolbar grouping unless the task explicitly changes it
- Preserve the unified right inspector and its Overview / Metadata / AI Evidence hierarchy unless the task explicitly changes them
- Preserve the header control cluster order and semantics unless the task explicitly changes them
- Preserve the expected sidebar-toggle label behavior (`Show` / `Hide`) unless the task explicitly changes it
- Preserve keyboard-first flow for search, selection, AI toggles, sorting, and lightbox review
- Prefer human-readable AI run labels over raw internal run IDs in operator-facing selectors when possible
- Be careful with polling, drag state, and lightbox interactions so background refresh does not interrupt the operator
- Verify the browser flow manually
- For a disposable test batch with sample images, see `scripts/README.md`.
- Update tests if behavior meaningfully changed

### UI behavior that should stay consistent

- AI overlay toggle and AI filter state are batch-scoped and must not leak across batch switches
- The AI image inspector follows clicked thumbnails and lightbox navigation, and resets across batch switches
- Undo must work for manual drag/toolbar/lightbox moves after toast expiry, reload, and restart; preserve newest-first server operation IDs, conflict reporting, and partial retry. Do not recreate undo by posting reverse filenames.
- Thumbnail updates should prefer incremental DOM updates over full grid rebuilds when possible
- Density classes (`density-compact`, `density-comfortable`, `density-large`) should keep thumbnail sizing stable when sidebars open/close
- The inspector open state and width persist in local storage
- The batch sidebar open state persists in local storage
- Batch-search shortcuts should reopen the batch sidebar before focusing the search input
- The Help modal should reflect current shortcuts and major workflow notes
- AI history should support comparing the selected run against another run from the same batch
- Lightbox supports zoom and scored-image navigation shortcuts; compare supports Sync Pan/Zoom, Pin A candidate walking, pair advancement, and an alternate A/B Split for still images
- Lightbox supports a separate AI review panel toggled with `I`
- Lightbox metadata supports the `M` toggle and should keep full prompt/negative prompt inspection available without disrupting image review
- Library Search stays keyboard-first: `P` opens the last-used Images or Prompt groups tab; the Prompt groups batch filter remains normally tabbable and its custom combobox supports Arrow/Home/End/PageUp/PageDown/Enter/Escape
- Prompt History "Copy pair" copies `prompt\n\nNegative: <negative>` (prompt only when no negative exists); the existing single-prompt copy is preserved as `copy negative` when a negative prompt is present
- Library Search Images can apply folder/batch/all-batches results to a source-qualified workspace filter; stable 500-item API pages load automatically at grid/lightbox boundaries until every match is available, lightbox navigation stays inside it, Clear restores the originating view, and mixed-source bulk selection remains disabled
- Prompt History image references render as folder-grouped chips and are display-only; "Show in grid" / "Open first image" actions are deferred so they can land with the grid/lightbox state work in a separate phase

### API or backend change

- Read `app.py` and related modules in `image_curator/` or `ai_curate/`
- Keep route validation and JSON response contracts synchronized with the frontend
- Add or update integration tests

### Filesystem or run-history change

- Verify all path assumptions
- Confirm runtime artifacts remain ignored by git
- Update `README.md` and `AGENTS.md`

## Agent Instructions

- **Start:** Read this file, then use the Decision Tree to locate the right files for your task. Check for per-directory `README.md` files (`ai_curate/`, `image_curator/`, `static/`, `tests/`, `scripts/`) -- each has module-scoped startup guidance: architecture, contracts, gotchas, and verification commands specific to that directory.
- **Never:** Read `image-curator.service` (use `.example`). Read `.env` files. Commit secrets or tokens.
- **Always:** Use `.venv/`. Run `python scripts/run_all.py --quick` after changes. Re-read changed files before claiming completion.
- **Template source rule:** Edit `templates/index.html`, then run
  `.venv\Scripts\python.exe scripts\generate_curator_template.py --write` and
  commit both shipped templates; the runner's template check is read-only.
- **Know your layer:** Unit tests for isolated logic. Component tests for multi-module interactions. Integration tests for full HTTP/filesystem workflows. Manual browser validation for interactive UI changes.
- **Before committing:** `ruff check` and `ruff format --check` must pass on all touched paths.
- **Completion:** State files changed, commands run, manual verification performed, and remaining risk or follow-up work.

## Gotchas

- **`load_dotenv()` before imports:** `app.py` and `curate.py` call `load_dotenv()` before importing `ai_curate` modules so env vars are visible at module import time. The `E402` ruff rule is suppressed for these two files. Do not reorder imports.
- **`--panel` flag is deprecated (curate.py):** Use `--prompt`. `--panel` still works but prints a warning. `--prompt` takes precedence if both are provided.
- **AI worker threads are daemons:** They die with the process. Shutdown tries to join for 5 seconds, then exits.
- **Frontend tests are Python source-scraping:** The `test_frontend_*.py` files regex-scan ordered split JS/CSS sources through `tests/unit/frontend_source.py` for function names and invariants. No headless browser or JS test framework. Browser-only changes need manual verification.
- **Generated files (never edit):** `.thumbs/` (poster cache), `.previews/` (hover proxies), `.favorites.json`, `<batch>/prompt-history.json`, `<batch>/search-index.json`, `<batch>/ai-curate/runs/` (run history), `<batch>/ai-curate/latest.json`, `__pycache__/`, `*.egg-info/`.
- **Favorites one click updates both scopes:** `toggle_favorite()` writes batch and universal stores; universal view uses `__favorites__` as a frontend sentinel, never as a real batch.
- **Public copies are generated derivatives:** `public/` is not a normal curation stage. Do not move originals when preparing, copying, moving, or deleting public copies. External copy/move requires `IMAGE_CURATOR_PUBLIC_EXPORTS`; the destination browser lists directories only under that configured export root.
- **Prompt history is manual:** Build/rebuild is synchronous and operator-triggered. Staleness checks compare total image count only.
- **Media search-index builds:** The legacy synchronous build route remains compatible, while the frontend uses the shared asynchronous job lifecycle. Jobs are pinned to the root at submission, cancellable cooperatively, preserve a prior valid index on cancellation, and expose truthful terminal states. A cancel response with `cancel_accepted: false` means the build is finishing and the Activity Center must remain actionable/running.
- **Score < 0 means failed:** `ImageResult.score` defaults to -1 for unscored/failed images. `normalized_score` also returns -1. Frontend checks `score >= 0` to distinguish scored from failed.
- **No CORS headers:** The app binds to `127.0.0.1` by default. For remote access, use a reverse proxy with auth (nginx, Caddy).
- **Media cache keys include folder and source extension:** `<folder>__<stem>--<ext>.webp|.mp4` prevents folder and same-stem cross-format collisions.
- **Typed-media boundaries:** Review/favorites/moves/reject deletion and general media search accept PNG/JPG/JPEG/WebP/GIF/MP4/MP3. AI scoring and public derivatives remain still-only; Prompt History remains PNG-only. Adjacent JSON sidecars are auxiliary (never listed independently), searchable through the media index, and follow imports, review moves/undo, and reject cleanup.
- **External-favorites sidecar schema:** Flat objects may use
  `category: "external_favorites"`; `subcategory` is `post` or `favorite`;
  `tags` is whitespace-delimited; numeric-looking API
  values generally remain strings while `favorite_id`/`total` may be integers.
  Preserve those source types in backend responses.
- **Large native folders:** Native real-folder views use immutable background revisions, 256-item pages, lightweight polls, and <=500 live thumbnails. Snapshot Select All is revision plus exclusions and undo is tokenized server-side.
- **Durable move history:** `<batches-root>/.curator-undo/history.json` is generated recovery state, not a rebuildable cache. Never edit it manually. `image_curator/move_history.py` backs `/api/move-history` and operation-token undo in both adapters; retention is 100 operations / 30 days. It covers manual review moves only, not imports, deletions, AI moves, or public derivatives. Read `tests/unit/test_move_history_review.py` for independent recovery acceptance cases.
- **Configured library links:** The batches root may be an operator-configured symlink or directory junction to an existing library. Resolve and pin that trusted root for manual move recovery; do not extend that trust to links inside batches or the journal. Do not retarget the configured link during operation. See `tests/component/test_symlink_root_review.py` for alias/restart/containment acceptance checks.
- **`ELEMENT_CAP` (12) truncation is silent:** `scoring.py` caps elements without logging a warning.
- **Native extension scope:** Native settings, batch/image/thumbnail foundation routes, curation mutations, favorites, public workflow, prompt history, media search, and AI scoring lifecycle are namespaced under `/api/curator/*` and `/curator/{thumb,image}/*`. Native AI uses a lifecycle-owned queue with bounded shutdown.
- **Native public export root default:** `NativeCuratorSettings.from_host_paths()` resolves a ComfyUI-owned `public-exports` directory under the curator system user directory (`<system_dir>/public-exports`). The editable path appears only in the dedicated local-operator settings response, not general page or batch payloads.
- **Native settings:** `<system_dir>/config.json` is the normal native source. Persisted values precede environment fallbacks and ComfyUI-owned defaults. The dedicated settings endpoint returns editable paths and API-key set status, never the key; saves support explicit replacement and clearing and are rejected while AI work is active.
- **curator.html must stay synchronized with index.html:** After editing
  `index.html`, run `.venv\Scripts\python.exe scripts\generate_curator_template.py --write`.
  The transforms are `/static/` → `/curator_static/` and inserting
  `window.CURATOR_NATIVE = true` before the first `<script src="...">`.
- **Shared frontend mode detection:** `static/js/state.js` checks `window.CURATOR_NATIVE === true` to select API paths, thumb URLs, and image URLs. Do not remove or rename `CURATOR_NATIVE` without updating both templates and all URL helpers.

## Verification Standard

Use the smallest proof that supports the claim, then broaden if needed:

| Scope | Command |
|-------|---------|
| Fast edit-loop | `python scripts/run_all.py --quick` |
| Standard local | `python scripts/run_all.py` |
| Full with mypy | `python scripts/run_all.py --full` |
| Format only | `python scripts/run_all.py --format` |
| Skip JS checks | `python scripts/run_all.py --skip-js` |
| Suppress command echo | `python scripts/run_all.py --quick --quiet` |
| Unit tests only | `python -m pytest tests/unit -v` |
| Component tests only | `python -m pytest tests/component -m component -v` |
| Integration tests only | `python -m pytest tests/integration -m integration -v` |
| Syntax/compile | `python -m compileall app.py curate.py image_curator ai_curate` |

`scripts/run_all.py` does not replace manual browser validation for interactive UI changes.

When adding new verification surfaces, update `scripts/run_all.py`, `tests/unit/test_run_all_script.py`, `README.md`, and `CONTRIBUTING.md` together.

## Completion Standard

Do not say complete without stating:

- files changed
- commands run
- manual verification performed
- remaining risk or deferred follow-up
