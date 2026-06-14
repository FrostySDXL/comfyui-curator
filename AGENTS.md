# AGENTS.md

**Purpose:** Operator-focused web application for reviewing generated images with optional AI-assisted scoring. **Status:** Actively maintained. **Audience:** AI agents and single-operator maintainers. **Last Updated:** 2026-06-13

## Quickstart

- Read `README.md` first.
- Use the virtual environment at `.venv/`.
- Entrypoints: `app.py` (Flask web UI + API), `curate.py` (CLI scoring).
- New non-AI backend logic -> `image_curator/`. New AI logic -> `ai_curate/`.
- Frontend is `templates/index.html` + ordered vanilla scripts under `static/js/` + split CSS files under `static/css/`.
- Verification: `python scripts/run_all.py` (default) or `--quick` for fast loops.
- Do not commit code that fails `ruff check` or `ruff format --check` on touched paths.

## What This Repo Provides

- **Batch filesystem workflow:** inbox/shortlisted/finals/rejects folders under `IMAGE_CURATOR_BATCHES/<batch>/`. Counts, metadata, auto-import from ComfyUI outputs.
- **Web review UI:** Asset-manager style batch sidebar, compact workspace toolbar, center thumbnail grid, right AI sidebar. Drag/drop moves, multi-select/Select All, undo toast, keyboard shortcuts, background polling.
- **Lightbox viewer:** Full-image review with zoom, PNG generation metadata inspection (`M` toggle), scored-image navigation (`[`/`]`), keyboard folder moves (`S`/`F`/`R`).
- **Favorites workflow:** One-click favorites update batch and universal scope, with a favorites-only filter and virtual All Favorites sidebar view.
- **Prompt history:** Manual PNG metadata prompt indexes with searchable/copyable Prompt History modal and staleness warning.
- **AI-assisted scoring:** Vision-LLM evaluation against element checklists via OpenAI-compatible `/v1/chat/completions`. Optional auto-move of top-N images. The AI sidebar has Inspect / Score / Runs tabs, run comparison, and contextual image inspection.
- **CLI headless scoring:** Same pipeline available via `curate.py` (dry-run, score-only, or score-and-move).
- **Core philosophy:** Manual curation is authoritative. AI is advisory. Filesystem is the operational truth.

## Key Concepts & Data Flows

```
app.py (Flask, 28 routes)
  ├── image_curator/batch_store.py  ← filesystem ops (create, list, move, counts, import)
  ├── image_curator/png_metadata.py ← PNG text-chunk extraction (Pillow)
  ├── image_curator/favorites.py    ← batch + universal favorites JSON storage
  ├── image_curator/prompt_history.py ← manual PNG prompt index cache
  ├── image_curator/web_validation.py ← route path/batch validation helpers
  ├── image_curator/watcher.py      ← dependency-injected ComfyUI auto-import watcher
  ├── image_curator/media.py        ← thumbnail cache/generation helpers
  ├── ai_curate/config.py           ← env-backed constants, paths, caps
  ├── ai_curate/elements.py         ← prompt parsing + element extraction + quality checklists
  ├── ai_curate/job_validation.py   ← AI curation submit payload validation
  ├── ai_curate/client.py           ← VisionClient (raw urllib -> /v1/chat/completions)
  ├── ai_curate/scoring.py          ← image enumeration + scoring loop
  ├── ai_curate/worker.py           ← scoring worker orchestration core
  ├── ai_curate/queue.py            ← FIFO single-worker job queue (threading)
  ├── ai_curate/storage.py          ← run history JSON persistence (atomic .tmp writes)
  └── ai_curate/models.py           ← JobState, ImageResult, CurationRun, RunTotals

curate.py (CLI)
  └── ai_curate/  (same pipeline, no queue — synchronous scoring in-process)

Frontend (templates/index.html + ordered static/js/*.js + static/css/*.css)
  └── app.py API routes (fetch-based, vanilla JS, no framework)
```

- **Single source of truth:** Filesystem under `IMAGE_CURATOR_BATCHES/<batch>/`.
- **AI run history:** `<batch>/ai-curate/runs/<run_id>.json` + `<batch>/ai-curate/latest.json` pointer.
- **State file:** `IMAGE_CURATOR_STATE` (default `~/.config/image-curator/state.json`). Stores active batch.

## Key Files & Responsibilities

| Category | Key Files / Folders | Role |
|----------|---------------------|------|
| **Entrypoints** | `app.py` | Flask API (28 routes) + web UI serving + AI worker threads + auto-import watcher |
| | `curate.py` | CLI entrypoint for headless scoring (argparse, no queue) |
| **Non-AI Backend** | `image_curator/batch_store.py` | Batch creation, folder layout, file moves, counts, import, state persistence |
| | `image_curator/png_metadata.py` | ComfyUI/A1111 PNG text-chunk extraction (prompt, seed, sampler, CFG, LoRAs, etc.) |
| | `image_curator/favorites.py` | Batch/universal favorites storage, toggle helper, universal favorite resolution |
| | `image_curator/prompt_history.py` | Manual prompt-history cache builder from PNG metadata |
| | `image_curator/web_validation.py` | Path traversal and existing-batch validation helpers used by app route wrappers |
| | `image_curator/watcher.py` | Dependency-injected ComfyUI output watcher used by app-level `ImageWatcher` wrapper |
| | `image_curator/media.py` | Thumbnail cache key/freshness helpers and WebP generation |
| | `image_curator/README.md` | Module-scoped agent startup guide (layout, contracts, gotchas) |
| **AI Backend** | `ai_curate/config.py` | Env-backed constants: `BATCHES_DIR`, `COMFYUI_OUTPUT`, `DEFAULT_BASE_URL`, `DEFAULT_TOP_N` (15), `TOP_N_CAP` (100), `ELEMENT_CAP` (12) |
| | `ai_curate/README.md` | Module-scoped agent startup guide (pipeline, internal contracts, gotchas) |
| | `ai_curate/elements.py` | Prompt auto-extraction, explicit element building, quality baseline checks |
| | `ai_curate/job_validation.py` | Web AI job payload validation with app-injected dependencies |
| | `ai_curate/models.py` | `JobState` enum, `ImageResult` (per-image score), `CurationRun`, `RunTotals` |
| | `ai_curate/client.py` | `VisionClient`: base64 encode + POST to `/v1/chat/completions` (raw urllib) |
| | `ai_curate/scoring.py` | `find_images`, `build_scoring_prompt`, `score_images` loop |
| | `ai_curate/worker.py` | AI scoring worker core for scoring, cancellation, optional top-N moves, and queue completion |
| | `ai_curate/queue.py` | `QueueManager`: FIFO single-worker job queue with cancel support |
| | `ai_curate/storage.py` | `RunStorage`: atomic JSON persistence for run history |
| **Frontend** | `templates/index.html` | Single-page Flask template (Jinja2, server-injected model list) |
| | `static/js/state.js`, `dom-utils.js`, `api.js`, `sidebar.js`, `batches.js`, `grid.js`, `favorites.js`, `moves.js`, `lightbox.js`, `metadata.js`, `prompts.js`, `ai.js`, `polling.js`, `events.js`, `bootstrap.js` | Ordered classic browser scripts; vanilla JS, imperative, no framework/build step |
| | `static/js/app.js` | Compatibility stub pointing to the split files |
| | `static/css/base.css`, `sidebar.css`, `layout.css`, `grid.css`, `lightbox.css`, `modals.css`, `prompts.css`, `toast.css`, `ai.css`, `responsive.css` | Browser-loaded split styling in template order (dark theme, flexbox + CSS grid) |
| | `static/css/app.css` | Temporary full compatibility stylesheet for raw-text tests; not browser-loaded by `templates/index.html` |
| | `static/README.md` | Module-scoped agent startup guide (global state, function groups, API calls, gotchas) |
| **Tests** | `tests/unit/` | Isolated logic plus source-scraping frontend-invariant tests |
| | `tests/component/` | In-process multi-module (Flask route contracts, AI worker lifecycle) |
| | `tests/integration/` | Full HTTP + filesystem workflow (Flask test client, real files) |
| | `tests/README.md` | Module-scoped agent startup guide (layers, fixtures, markers, coverage gaps) |
| **Scripts** | `scripts/run_all.py` | Multi-tool verification runner (ruff, compileall, pytest, mypy, JS syntax, git diff) |
| | `scripts/README.md` | Module-scoped agent startup guide (verification modes) |
| **Config** | `pyproject.toml` | Build system, ruff, mypy configuration |
| | `pytest.ini` | Test markers (`unit`, `component`, `integration`) and paths |
| | `.env.example` | Documented environment variable reference (never read `.env` directly) |
| **Deployment** | `image-curator.service.example` | Templated systemd unit (use this, not the production service file) |
| **Guidance** | `README.md`, `CONTRIBUTING.md`, `AGENTS.md` | Operator docs, contributor workflow, agent startup |
| **Generated** | `.thumbs/`, `<batch>/ai-curate/runs/`, `<batch>/ai-curate/latest.json`, `__pycache__/`, `*.egg-info/` | **Do not edit.** Created at runtime. |

## Decision Tree

| Task | Read | Verify |
|------|------|--------|
| UI layout, shortcuts, lightbox, sidebars | `static/README.md` then `templates/index.html`, relevant `static/js/*.js`, relevant `static/css/*.css` files | Manual browser smoke test; `python scripts/run_all.py --quick` |
| Flask API or batch filesystem behavior | `image_curator/README.md` then `app.py`, matching frontend calls in relevant `static/js/*.js`, integration/component tests | `python -m pytest tests/integration/ tests/component/ -v` |
| AI scoring, queueing, run history | `ai_curate/README.md` then `ai_curate/`, `curate.py`, unit tests | `python -m pytest tests/unit/test_client.py tests/unit/test_scoring.py tests/unit/test_queue.py tests/unit/test_storage.py tests/unit/test_elements.py tests/unit/test_models.py tests/unit/test_config.py -v` |
| PNG metadata extraction | `image_curator/README.md` then `image_curator/png_metadata.py`, unit test | `python -m pytest tests/unit/test_png_metadata.py -v` |
| Favorites or prompt history | `image_curator/README.md` then `image_curator/favorites.py`, `image_curator/prompt_history.py`, app routes, frontend calls | `python -m pytest tests/unit/test_favorites.py tests/unit/test_prompt_history.py tests/integration/test_favorites_api.py tests/integration/test_prompt_history_api.py -v` |
| Docs or repo organization | `README.md`, `CONTRIBUTING.md`, this file | `python scripts/run_all.py --skip-js` |
| Deployment assumptions | `image-curator.service.example`, `app.py` constants, `ai_curate/config.py` | Review env vars in `.env.example` |

## Mission

Maintain a fast operator-facing curation workflow for generated images with optional AI-assisted scoring, without making AI the source of truth.

## Non-goals

- Public packaging polish
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
- Header Help modal content, keyboard shortcuts, and sidebar toggle labels
- Lightbox PNG metadata route shape, toggle shortcut (`M`), and displayed field set
- Batch and AI sidebar button labels as stateful operator-facing cues, not static text
- Workspace toolbar control IDs/order, density controls, Select All behavior, and thumbnail state classes
- AI run history labels, compare controls, and image inspector as operator-facing compatibility surfaces
- Favorites API shapes, favorites filter button, All Favorites sidebar entry, and lightbox/thumb star behavior
- Prompt History modal controls, prompt-history API shapes, and manual cache file semantics

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
- Preserve the right-sidebar AI Curate layout and image inspector unless the task explicitly changes them
- Preserve the header control cluster order and semantics unless the task explicitly changes them
- Preserve the expected sidebar-toggle label behavior (`Show` / `Hide`) unless the task explicitly changes it
- Preserve keyboard-first flow for search, selection, AI toggles, sorting, and lightbox review
- Prefer human-readable AI run labels over raw internal run IDs in operator-facing selectors when possible
- Be careful with polling, drag state, and lightbox interactions so background refresh does not interrupt the operator
- Verify the browser flow manually
- Update tests if behavior meaningfully changed

### UI behavior that should stay consistent

- AI overlay toggle and AI filter state are batch-scoped and must not leak across batch switches
- The AI image inspector follows clicked thumbnails and lightbox navigation, and resets across batch switches
- Undo must work for both drag moves and lightbox keyboard moves while the undo toast is active
- Thumbnail updates should prefer incremental DOM updates over full grid rebuilds when possible
- Density classes (`density-compact`, `density-comfortable`, `density-large`) should keep thumbnail sizing stable when sidebars open/close
- The AI sidebar open state and width persist in local storage
- The batch sidebar open state persists in local storage
- Batch-search shortcuts should reopen the batch sidebar before focusing the search input
- The Help modal should reflect current shortcuts and major workflow notes
- AI history should support comparing the selected run against another run from the same batch
- Lightbox supports zoom and scored-image navigation shortcuts
- Lightbox supports a separate AI review panel toggled with `I`
- Lightbox metadata supports the `M` toggle and should keep full prompt/negative prompt inspection available without disrupting image review

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
- **Know your layer:** Unit tests for isolated logic. Component tests for multi-module interactions. Integration tests for full HTTP/filesystem workflows. Manual browser validation for interactive UI changes.
- **Before committing:** `ruff check` and `ruff format --check` must pass on all touched paths.
- **Completion:** State files changed, commands run, manual verification performed, and remaining risk or follow-up work.

## Gotchas

- **`load_dotenv()` before imports:** `app.py` and `curate.py` call `load_dotenv()` before importing `ai_curate` modules so env vars are visible at module import time. The `E402` ruff rule is suppressed for these two files. Do not reorder imports.
- **`--panel` flag is deprecated (curate.py):** Use `--prompt`. `--panel` still works but prints a warning. `--prompt` takes precedence if both are provided.
- **AI worker threads are daemons:** They die with the process. Shutdown tries to join for 5 seconds, then exits.
- **Auto-import watcher defaults to OFF:** Set `IMAGE_CURATOR_ENABLE_WATCHER=true` to enable polling from ComfyUI output.
- **Frontend tests are Python source-scraping:** The `test_frontend_*.py` files regex-scan ordered split JS/CSS sources through `tests/unit/frontend_source.py` for function names and invariants. No headless browser or JS test framework. Browser-only changes need manual verification.
- **Generated files (never edit):** `.thumbs/` (thumbnail cache), `.favorites.json`, `<batch>/prompt-history.json`, `<batch>/ai-curate/runs/` (run history), `<batch>/ai-curate/latest.json`, `__pycache__/`, `*.egg-info/`.
- **Favorites one click updates both scopes:** `toggle_favorite()` writes batch and universal stores; universal view uses `__favorites__` as a frontend sentinel, never as a real batch.
- **Prompt history is manual:** Build/rebuild is synchronous and operator-triggered. Staleness checks compare total image count only.
- **Score < 0 means failed:** `ImageResult.score` defaults to -1 for unscored/failed images. `normalized_score` also returns -1. Frontend checks `score >= 0` to distinguish scored from failed.
- **No CORS headers:** The app binds to `127.0.0.1` by default. For remote access, use a reverse proxy with auth (nginx, Caddy).
- **Thumbnail cache key includes folder name:** `<folder>__<stem>.webp` format prevents same-filename collisions across inbox/shortlisted/finals/rejects.
- **`ELEMENT_CAP` (12) truncation is silent:** `scoring.py` caps elements without logging a warning.

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
