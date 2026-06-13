# comfyui-curator

Operator-focused desktop tool for reviewing generated images, organizing
them into batch workflow folders, and optionally running vision-LLM scoring
before manual selection. Single-user, local-first, filesystem-backed.

## What it does

- **Batch review UI** -- left sidebar with searchable batch list, center
  thumbnail grid, folder tabs (inbox / shortlisted / finals / rejects).
  Drag images between folders, multi-select for bulk moves, undo toast for
  the last operation.
- **Lightbox viewer** -- full-size image review with zoom, keyboard
  navigation, scored-image jumps, and PNG generation metadata (prompt,
  seed, sampler, CFG, LoRAs).
- **Favorites** -- one-click stars persist favorites at both batch and
  universal scope, with a favorites-only filter and All Favorites sidebar view.
- **Prompt history** -- manually build per-batch prompt indexes from PNG
  metadata, then search, copy, and inspect prompt groups from a header modal.
- **Auto-import from ComfyUI** -- background watcher moves new outputs into
  the active batch inbox. One-click manual import also available.
- **AI-assisted scoring (optional)** -- sends images to a local vision LLM
  to check for prompt elements and quality baselines. Scores are advisory;
  manual curation is authoritative.
- **Run history and comparison** -- scored runs are saved per-batch.
  Compare two runs to see which images gained or lost points.
- **CLI scoring** -- `python curate.py --batch my-batch --prompt "a cat"`
  for headless workflows.

## Quickstart

```bash
git clone https://github.com/FrostySDXL/comfyui-curator.git
cd image-curator
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

# Optional: copy .env.example to .env to configure paths and model
python app.py
```

Opens at `http://127.0.0.1:5000`. Most users only need
`IMAGE_CURATOR_BATCHES`: create a batch, then save or copy images into
`IMAGE_CURATOR_BATCHES/<batch>/inbox/`. If ComfyUI writes somewhere else,
configure `IMAGE_CURATOR_COMFYUI` as an optional import source.

## Local browser testing

Use the disposable fixture script when you want to test the UI locally without
pointing at your real image library or another machine:

```powershell
.venv\Scripts\python.exe scripts\setup_local_browser_fixture.py

$env:IMAGE_CURATOR_BATCHES="tmp\local-browser-fixture\batches"
$env:IMAGE_CURATOR_COMFYUI="tmp\local-browser-fixture\comfyui-outputs"
$env:IMAGE_CURATOR_STATE="tmp\local-browser-fixture\state.json"
$env:IMAGE_CURATOR_ENABLE_WATCHER="false"
$env:IMAGE_CURATOR_HOST="127.0.0.1"
$env:IMAGE_CURATOR_PORT="5000"
.venv\Scripts\python.exe app.py
```

Then open `http://127.0.0.1:5000`. The fixture creates two batches, sample
PNG files with prompt metadata, one pending fake ComfyUI import, and an active
`manual-test` batch. It lives under ignored `tmp/`, so delete the fixture folder
whenever you want a clean manual-testing reset.

## Configuration

Copy `.env.example` to `.env`. Key variables:

Core path:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMAGE_CURATOR_BATCHES` | `~/image-curator/batches` | Main library containing batch folders and their `inbox/`, `shortlisted/`, `finals/`, and `rejects/` folders |

Optional import source:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMAGE_CURATOR_COMFYUI` | `~/image-curator/comfyui-outputs` | Folder to import images from when ComfyUI outputs outside your batch inboxes |
| `IMAGE_CURATOR_ENABLE_WATCHER` | `false` | Automatically move new images from `IMAGE_CURATOR_COMFYUI` into the active batch inbox |

Other settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMAGE_CURATOR_LLM_URL` | `http://localhost:8080` | Vision LLM endpoint |
| `IMAGE_CURATOR_MODEL` | (empty) | Model name (comma-separated for dropdown) |
| `IMAGE_CURATOR_API_KEY` | (empty) | Bearer token if your LLM requires auth |
| `IMAGE_CURATOR_HOST` | `127.0.0.1` | Bind address |
| `IMAGE_CURATOR_PORT` | `5000` | Port |

Use **Import All** for manual imports from `IMAGE_CURATOR_COMFYUI`. Set
`IMAGE_CURATOR_ENABLE_WATCHER=true` only if you want that import to happen
automatically.

Scoring defaults: top-N = 15 (cap 100), max elements = 12. Quality
baseline checks for anatomy and artifacts are appended automatically.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus batch search |
| `Ctrl+K` | Focus and select batch search |
| `Esc` | Contextual: clear search, close lightbox, close modal |
| `Ctrl+Z` | Undo last move (while toast is active) |
| `Ctrl+A` | Select all images in current folder |
| `U` | Toggle batch sidebar |
| `F` | Toggle favorites-only filter |
| `B` | Toggle AI score badges |
| `V` | Toggle score-based sort |
| `I` | Toggle AI sidebar |

### Lightbox

| Key | Action |
|-----|--------|
| `←` `→` | Previous / next image |
| `[` `]` | Previous / next scored image |
| `M` | Toggle PNG metadata panel |
| `S` | Move to shortlisted |
| `F` | Move to finals |
| `Shift+F` | Toggle favorite for current image |
| `R` | Move to rejects |
| `+` `-` | Zoom in / out |
| `0` | Reset zoom |
| `Ctrl+wheel` | Zoom |
| `Esc` | Close lightbox |

## UI behavior

- AI sidebar width, open state, and panel collapse persist across sessions.
- Batch sidebar open state persists across sessions.
- AI badges and score filtering reset when switching to a batch with no
  active run.
- Favorite toggles update both the current batch and the universal favorites
  list; the All Favorites sidebar count refreshes during batch polling.
- The All Favorites view is virtual: thumbnails show batch labels and
  lightbox moves use each image's source batch and folder.
- Prompt history indexes are manual caches. Rebuild after significant curation
  sessions or when the modal reports a stale image count.
- Background polling pauses during lightbox, drag, or resize so your
  review isn't interrupted.
- The header Help button shows keybindings and workflow notes.

## Security

Binds to `127.0.0.1` by default. No built-in authentication -- sufficient
for single-user local use. For remote access, place behind a reverse proxy
with auth (nginx, Caddy, etc.). Read `SECURITY.md` for related guidance.

## Limitations

AI scoring runs in a single background thread. One job at a time; others
queue FIFO. Designed for single-user operation, not concurrent scoring.

## Development verification

Use `python scripts/run_all.py` before sharing changes. The runner checks
Python formatting/linting/tests, JavaScript syntax, git diff whitespace, and
the split CSS file list/order loaded by `templates/index.html`.

## More

- **Contributing:** `CONTRIBUTING.md` -- verification, dependency
  management, change playbooks, repo structure.
- **Agent guidance:** `AGENTS.md` -- startup instructions for AI agents
  working in this repo, plus per-directory READMEs in `ai_curate/`,
  `image_curator/`, `static/`, `tests/`, and `scripts/`.
- **License:** MIT -- see `LICENSE`.
