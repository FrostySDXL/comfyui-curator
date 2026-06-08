# comfyui-curator

**Last Updated:** 2026-06-01

Operator-focused web application and curation toolkit for reviewing generated images, organizing them into batches, and running optional vision-LLM-assisted scoring before manual selection.

This is a single-user curation tool, not a polished public package or multi-tenant service.

## Primary goals

- Provide a fast manual batch-review UI for generated images
- Support auto-import from ComfyUI outputs into the active batch
- Add optional AI-assisted curation without replacing manual judgment
- Keep batch file movement, run history, and operator workflows explicit and auditable

## Non-goals

- Public API stability beyond documented internal contracts
- Multi-user access or role-based permissions
- Generic image management for arbitrary media libraries
- Turning AI scoring into the authoritative source of truth
- Hiding filesystem behavior behind opaque abstractions

## Current contracts to treat carefully

- Flask API routes used by the frontend
- Batch folder layout under `BATCHES_DIR/<batch>/` (default `~/image-curator/batches/<batch>/`)
- AI run-history layout under `BATCHES_DIR/<batch>/ai-curate/`
- Runtime state file location (default `~/.config/image-curator/state.json`)
- CLI behavior in `curate.py` while it still exists as an entrypoint
- `image-curator.service.example` template expectations
- Header Help modal content, keyboard shortcuts, and sidebar toggle labels
- Lightbox PNG metadata route shape, toggle shortcut, and displayed field set

## Current feature set

This README is the canonical feature inventory. Keep operator-facing behavior here synchronized with `AGENTS.md` and the in-app Help modal when shortcuts or primary workflows change.

### Batch and filesystem workflow

- Batch data lives under `IMAGE_CURATOR_BATCHES/<batch>/` (default `~/image-curator/batches/<batch>/`).
- New batches create four folders: `inbox`, `shortlisted`, `finals`, and `rejects`.
- Supported image extensions are `.png`, `.jpg`, `.jpeg`, and `.webp`.
- Batch counts cover each workflow folder and drive sidebar/tab badges.
- Batch metadata includes modified time for recent-first sorting.
- Runtime active-batch state is stored at `IMAGE_CURATOR_STATE` (default `~/.config/image-curator/state.json`) and is ignored by git.
- Reject cleanup removes rejected images and matching cached thumbnails.

### Import and auto-import

- ComfyUI output root is `IMAGE_CURATOR_COMFYUI` (default `~/image-curator/comfyui-outputs`).
- The auto-import watcher starts only when the output directory exists.
- The active batch is selected separately from the currently viewed batch.
- New ComfyUI images are auto-moved into the active batch `inbox` by a background watcher.
- Operators can manually import all pending ComfyUI output images into the selected active batch.
- The header quick action can set the currently viewed batch as the auto-import target.

### Web UI review workflow

- Layout is a left batch sidebar, center image grid, and right AI Curate sidebar.
- The batch sidebar includes search, A-Z/count/recent sorting, per-batch image totals, and AI-history indicators.
- The center grid supports thumbnail browsing, lazy image loading, incremental DOM updates, and selected-image styling.
- Folder tabs support drag/drop moves between `inbox`, `shortlisted`, `finals`, and `rejects`.
- Multi-select supports click selection, shift-range selection, `Ctrl/Cmd+A`, and an action bar for bulk moves.
- Move operations show a short-lived undo toast that can restore the last move while active.
- Background polling refreshes batches, images, and AI run data but avoids interrupting active lightbox, drag, select, or resize interactions.

### Lightbox review

- Clicking an unselected thumbnail opens the full-size image lightbox.
- Lightbox navigation supports previous/next image, keyboard moves to review folders, and close-on-escape.
- Zoom controls support `+`, `-`, `0`, and Ctrl+wheel.
- PNG generation metadata can be toggled in the lightbox with `M` when embedded metadata is available.
- The metadata panel shows model, seed, size, steps, sampler, CFG, Clip skip, full positive prompt, full negative prompt, LoRA tags, raw `parameters`, and workflow availability.
- When an AI run is selected, the lightbox can show score details, missing elements, and previous/next scored-image navigation.

### PNG generation metadata

- API route `GET /api/image-metadata/<batch>/<folder>/<filename>` returns best-effort embedded PNG generation metadata for the original image file.
- Metadata extraction lives in `image_curator/png_metadata.py` and reads PNG text chunks with Pillow.
- The route returns `has_metadata: false` for non-PNG images or PNGs without text chunks instead of failing the lightbox flow.
- Full workflow JSON is reported as available with its size, but it is not rendered inline in the lightbox metadata panel.

### AI curation backend

- Shared AI logic lives in `ai_curate/` and is used by both Flask routes and `curate.py`.
- The active vision client calls an OpenAI-compatible `/v1/chat/completions` endpoint, intended for llama-swap/llama.cpp routing.
- Defaults are configured in `ai_curate/config.py` and `app.py`, and can be overridden by environment variables:
  - `IMAGE_CURATOR_BATCHES` — root for batch storage (default `~/image-curator/batches`)
  - `IMAGE_CURATOR_COMFYUI` — ComfyUI output directory (default `~/image-curator/comfyui-outputs`)
  - `IMAGE_CURATOR_ENABLE_WATCHER` — enable background auto-import watcher (default `false`, set to `true` to enable)
  - `IMAGE_CURATOR_STATE` — active-batch state file (default `~/.config/image-curator/state.json`)
  - `IMAGE_CURATOR_HOST` — bind address for the web UI (default `127.0.0.1`)
  - `IMAGE_CURATOR_PORT` — port for the web UI (default `5000`)
  - `IMAGE_CURATOR_LLM_URL` — vision LLM endpoint URL (default `http://localhost:8080`)
  - `IMAGE_CURATOR_MODEL` — model name/alias (default empty; accepts comma-separated list e.g. `vl-scorer,qwen-vl` to populate a dropdown; first entry is the default)
  - `IMAGE_CURATOR_TIMEOUT` — request timeout in seconds (default `120`)
  - `IMAGE_CURATOR_API_KEY` — optional Bearer token sent to the vision LLM endpoint; leave empty or unset when the server does not require auth
- Copy `.env.example` to `.env` to configure your environment at a glance.
- Default `top_n` is `15`, capped at `100`.
- Element count is capped at `12`.
- Prompt extraction detects shot/framing terms and appends baseline quality checks.
- Explicit elements override auto-extraction but still append baseline quality checks.

### AI curation job flow

- API route `POST /api/ai-curate/preview-elements` previews extracted or explicit elements without scoring.
- API route `POST /api/ai-curate/jobs` submits a score-only or score-and-move job.
- API route `GET /api/ai-curate/jobs` lists in-memory jobs.
- API route `GET /api/ai-curate/jobs/<run_id>` returns a job by ID.
- API route `POST /api/ai-curate/jobs/<run_id>/cancel` requests cancellation.
- The queue permits one running job at a time and queues additional jobs FIFO.
- Job states are `queued`, `running`, `cancelling`, `completed`, `failed`, and `cancelled`.
- Cancellation during scoring discards partial results and does not persist run history.
- Move mode is explicit; score-only is the default.
- Move-enabled jobs only move top-N non-failed images after scoring completes.

### AI run history and comparison

- Run history is stored under `BATCHES_DIR/<batch>/ai-curate/`.
- Completed and failed runs are written as `runs/<run-id>.json`.
- Pure cancellations (cancel before or during scoring) are not persisted.
- Cancellations during the move phase, after at least one file has been moved, are persisted as a partial audit trail so the operator can see which files were moved before the cancel landed.
- `latest.json` points to the most recent persisted run.
- Batch run history is exposed via `GET /api/ai-curate/batches/<batch>/runs`.
- Individual historical runs are exposed via `GET /api/ai-curate/batches/<batch>/runs/<run_id>`.
- The latest run for a batch is available at `GET /api/ai-curate/batches/<batch>/runs/latest`.
- The UI uses human-readable run labels when metadata is available.
- The operator can select a run, compare it against latest or another run from the same batch, and inspect changed scores, failure flips, and image-set differences.
- AI overlays, AI filters, and score sorting are scoped to the selected batch/run.

### API reference

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Web UI |
| `/api/batches` | GET | List all batches, active batch, counts, metadata |
| `/api/batches` | POST | Create a new batch |
| `/api/active-batch` | POST | Set the active batch |
| `/api/import-all` | POST | Import pending ComfyUI images into a batch |
| `/api/images/<batch>/<folder>` | GET | List images in a batch folder<br>`?sort=date|name|shuffle&order=asc|desc` |
| `/api/image-metadata/<batch>/<folder>/<filename>` | GET | Extract embedded PNG metadata |
| `/api/move` | POST | Move a single image between folders |
| `/api/move-batch` | POST | Bulk move images between folders |
| `/api/delete-rejects/<batch>` | POST | Delete all images in the rejects folder |
| `/thumb/<batch>/<folder>/<filename>` | GET | Serve thumbnail (WebP, cached) |
| `/image/<batch>/<folder>/<filename>` | GET | Serve full-size image |
| `/api/ai-curate/preview-elements` | POST | Preview scoring elements from a prompt |
| `/api/ai-curate/jobs` | GET | List in-memory AI curation jobs |
| `/api/ai-curate/jobs` | POST | Submit a new AI curation job |
| `/api/ai-curate/jobs/<run_id>` | GET | Get job status |
| `/api/ai-curate/jobs/<run_id>/cancel` | POST | Cancel a queued or running job |
| `/api/ai-curate/batches/<batch>/runs` | GET | List historical runs for a batch |
| `/api/ai-curate/batches/<batch>/runs/latest` | GET | Get the most recent run for a batch |
| `/api/ai-curate/batches/<batch>/runs/<run_id>` | GET | Get a specific historical run |

### CLI compatibility

`curate.py` remains a root-level CLI entrypoint. It delegates scoring, element
extraction, client calls, and storage to `ai_curate/`.

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--prompt` | yes* | — | Prompt description to evaluate against |
| `--panel` | no | — | Deprecated alias for `--prompt` (prints warning) |
| `--batch` | **yes** | — | Image Curator batch name |
| `--images` | no | batch inbox | Image directory to score |
| `--top` | no | 15 | Number of top images to shortlist |
| `--model` | no | env or `""` | Vision model alias |
| `--elements` | no | auto-extracted | Comma-separated elements (overrides auto-extraction) |
| `--dry-run` | no | — | Show extracted elements and exit without scoring |
| `--move` | no | — | Move top-scoring images to destination after scoring |
| `--dest` | no | `shortlisted` | Destination folder when `--move` is set |
| `--source` | no | `inbox` | Source folder within the batch |

\* Either `--prompt` or `--panel` is required.

## Current repo layout

- `app.py` — current Flask entrypoint for the web UI
- `curate.py` — current CLI entrypoint for image scoring workflows
- `image_curator/` — shared non-AI support code, currently batch filesystem/state helpers
- `ai_curate/` — shared AI scoring, queue, client, and run-history logic
- `templates/` — Flask HTML templates
- `static/` — frontend JS/CSS assets
- `tests/` — automated verification split by proof strength
- `fixtures/` — controlled sample inputs for tests and local verification
- `scripts/` — helper scripts for developer/operator workflows
- `image-curator.service.example` — templated systemd unit for deployment
- `.env.example` — configuration template
- `LICENSE` — MIT License
- `requirements.in` / `requirements-dev.in` — source-of-truth dependency declarations
- `requirements.txt` / `requirements-dev.txt` — convenience installable copies
- `requirements-lock.txt` / `requirements-dev-lock.txt` — pinned reproducible builds

## Repo structure rules

- Root-level entrypoints remain active for now: `app.py` and `curate.py`
- New feature logic should avoid piling more unrelated behavior into `app.py`
- Reusable non-AI backend logic should be added under `image_curator/`
- Reusable AI-related logic should be added under `ai_curate/`
- `templates/` owns HTML structure only
- `static/js/` owns browser behavior and API calls
- `static/css/` owns presentation only
- `tests/unit/` is for pure logic checks
- `tests/component/` is for in-process multi-module checks
- `tests/integration/` is for Flask/API/filesystem workflow checks
- `fixtures/` is for controlled sample inputs used in tests and smoke verification
- `scripts/` is for local helper scripts, not production runtime logic

## Change boundaries

- If you change route JSON, update the frontend caller and integration tests
- If you change batch layout assumptions, update every path consumer and verify manual workflows
- If you change AI scoring semantics, update tests plus any operator-facing explanation of defaults
- If you change documented features, update this README, `AGENTS.md`, and the in-app Help modal when applicable

## Mental model

1. `app.py` exposes the operator UI and API routes
2. frontend assets in `static/` drive the browser workflow
3. shared non-AI backend logic belongs in `image_curator/`
4. shared AI backend logic belongs in `ai_curate/`
5. filesystem state under batch folders remains the operational truth
6. tests prove isolated logic first, then integrated behavior

## Current operator UI notes

- The main review surface is the image grid in the center pane.
- Batch navigation remains in the left sidebar.
- The header exposes stateful batch and AI sidebar controls (`Show` / `Hide`),
  `Help`, and the current `Set as Auto-import` action.
- AI Curate lives in a toggleable right sidebar.
- The AI sidebar width, open state, and panel collapsed state persist in
  local storage.
- The left batch sidebar open state also persists in local storage.
- AI badges and AI filtering are batch-scoped display state and should reset
  when switching to a batch with no active or historical AI run.
- AI run history should use human-readable date/time labels when run metadata
  is available instead of exposing raw run IDs as the primary label.
- Operators should be able to compare the selected AI run against any other run
  from the same batch, not only the latest run.
- Background polling should not interrupt active review interactions such as
  lightbox navigation, drag operations, or sidebar resizing.
- The in-app Help button should stay current with keybindings and major
  operator workflow notes.

## Keyboard shortcuts

- `/` — open the batch sidebar if needed, then focus batch search
- `Ctrl+K` / `Cmd+K` — open the batch sidebar if needed, then focus and
  select batch search
- `Esc` — context-dependent: in batch search clears search; in
  lightbox closes lightbox; in Help modal closes Help
- `Ctrl+Z` / `Cmd+Z` — undo last move while undo toast is active
- `Ctrl+A` / `Cmd+A` — select all images in the current folder (not in lightbox)
- `U` — toggle the batch sidebar
- `B` — toggle AI badges when an AI run is available
- `V` — toggle score sort when an AI run is available
- `I` — toggle the AI sidebar

## In-app help

- The header Help button opens a modal with keybindings, lightbox shortcuts,
  and a short operator-oriented service summary.
- If keybindings or primary workflow behavior changes, update both the Help
  modal and this README in the same change.

### Lightbox shortcuts

- `Left` / `Right` — previous or next image
- `[` / `]` — previous or next scored image
- `M` — toggle embedded PNG generation metadata when available
- `S` — move to shortlisted
- `F` — move to finals
- `R` — move to rejects
- `+` / `-` — zoom in or out
- `0` — reset zoom
- `Esc` — close lightbox

The lightbox also supports Ctrl+wheel zoom.

## Security model

- The default bind address is `127.0.0.1` (localhost only). Set `IMAGE_CURATOR_HOST` to change this.
- There is no built-in authentication. For single-user local operation this is sufficient.
- For remote access, place Image Curator behind a reverse proxy with auth (nginx, Caddy, etc.) rather than adding auth to the application itself. Example nginx snippet:

  ```
  location / {
      auth_basic "Image Curator";
      auth_basic_user_file /etc/nginx/.htpasswd;
      proxy_pass http://127.0.0.1:5000;
  }
  ```

## Limitations

- AI scoring runs in a single background thread inside Flask. Only one job runs at a time; additional jobs queue FIFO. This is intentional for single-user operation and not designed for concurrent multi-user scoring.

## Local setup

**Prerequisites:** Python 3.10+ and pip.

```bash
# Clone and set up
git clone https://github.com/FrostySDXL/image-curator.git
cd image-curator
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate
# Activate (Linux / macOS)
source .venv/bin/activate

# Install dependencies (use requirements-dev.txt for contributing, requirements.txt for runtime only)
pip install -r requirements-dev.txt

# Optional: create .env from the example template
cp .env.example .env        # Linux / macOS
copy .env.example .env      # Windows

# Run
python app.py
```

The `.env` file is optional but recommended — `python-dotenv` loads it at startup
so you can configure paths, host, and model without environment variables.

## Verification tiers

- Standard local verification (default):
  - `python scripts/run_all.py` — runs ruff format check, ruff lint, compileall, unit/component/integration tests, JS syntax, and a git diff sanity check
- Full verification suite including mypy type checking:
  - `python scripts/run_all.py --full`
- Fast edit-loop verification:
  - `python scripts/run_all.py --quick`
- Apply Ruff formatting:
  - `python scripts/run_all.py --format`
- Skip frontend syntax checks only when Node is unavailable and the change is not frontend-related:
  - `python scripts/run_all.py --skip-js`
- Suppress the per-check command echo (useful when sharing logs, since the echo otherwise shows the absolute path of the active Python interpreter):
  - `python scripts/run_all.py --quick --quiet`
- Manual UI smoke tests are still required for interactive browser changes.

## Internal docs

- `CONTRIBUTING.md` — contributor workflow and verification expectations
- `AGENTS.md` — startup guidance for future agents working in this repo

## License

MIT License — see [LICENSE](LICENSE).
