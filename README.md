# comfyui-curator

Operator-focused desktop tool for reviewing generated images, organizing
them into batch workflow folders, and optionally running vision-LLM scoring
before manual selection. Single-user, local-first, filesystem-backed.

## What it does

- **Batch review UI** -- asset-manager style batch sidebar, compact workspace
  toolbar, center thumbnail grid, folder tabs (inbox / shortlisted / finals /
  rejects), sort/favorites/AI controls, and persistent thumbnail density modes.
  Drag images between folders, multi-select or Select All for bulk moves, undo
  toast for the last operation.
- **Lightbox viewer** -- full-size image review with zoom, keyboard
  navigation, scored-image jumps, PNG generation metadata (prompt,
  seed, sampler, CFG, LoRAs), and two-image comparison from selected images.
- **Favorites** -- one-click stars persist favorites at both batch and
  universal scope, with a favorites-only filter and All Favorites sidebar view.
- **Public posting prep** -- selected originals can be exported as
  metadata-stripped, optionally watermarked copies under each batch's `public/`
  folder, with batch Public and virtual All Public views for generated copies.
- **Prompt history** -- manually build per-batch prompt indexes from PNG
  metadata, then search, copy, and inspect prompt groups from a header modal.
- **Auto-import from ComfyUI** -- background watcher moves new outputs into
  the active batch inbox. One-click manual import also available.
- **AI-assisted scoring (optional)** -- sends images to a local vision LLM
  to check for prompt elements and quality baselines. The AI sidebar includes a
  contextual image inspector plus Inspect / Score / Runs tabs. Scores are
  advisory; manual curation is authoritative.
- **Run history and comparison** -- scored runs are saved per-batch.
  Compare two runs to see which images gained or lost points.
- **CLI scoring** -- `python curate.py --batch my-batch --prompt "a cat"`
  for headless workflows.

## Quickstart

Requires Python 3.10 or newer.

```bash
git clone https://github.com/FrostySDXL/comfyui-curator.git
cd comfyui-curator
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

`requirements.txt` is the convenience install file. Use
`requirements-lock.txt` when you need the pinned dependency set.

The repository is named `comfyui-curator`; the Python package, service
template, and default local paths use `image-curator`.

## Configuration

Copy `.env.example` to `.env`. Key variables:

Core path:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMAGE_CURATOR_BATCHES` | `~/image-curator/batches` | Main library containing batch folders and their `inbox/`, `shortlisted/`, `finals/`, `rejects/`, and generated `public/` folders |
| `IMAGE_CURATOR_PUBLIC_EXPORTS` | (unset) | Optional safe root for copying/moving generated public copies to another filesystem location; when unset, external public copy/move actions are disabled |
| `IMAGE_CURATOR_STATE` | `~/.config/image-curator/state.json` | Runtime state file that remembers the active batch |

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
| `IMAGE_CURATOR_TIMEOUT` | `120` | Vision LLM request timeout in seconds |
| `IMAGE_CURATOR_HOST` | `127.0.0.1` | Bind address |
| `IMAGE_CURATOR_PORT` | `5000` | Port |

See `.env.example` for the full commented reference.

## Basic workflow

1. Create or select a batch.
2. Add generated images to `<batch>/inbox/`, or use **Import All** to pull from
   `IMAGE_CURATOR_COMFYUI`.
3. Review images in the grid or lightbox, then move keepers to `shortlisted` or
   `finals` and rejects to `rejects`.
4. Mark favorites and build Prompt History when you want searchable prompt
   groups.
5. Prepare public copies when you need metadata-stripped, optionally watermarked
   posting files. Originals remain in the review folders.
6. Optionally run AI scoring against a local OpenAI-compatible vision model;
   scores are advisory.

Set `IMAGE_CURATOR_ENABLE_WATCHER=true` only when you want new files in
`IMAGE_CURATOR_COMFYUI` imported automatically into the active batch.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | Open batch sidebar if closed, then focus batch search |
| `Ctrl+K` | Open batch sidebar if closed, then focus and select batch search |
| `Esc` | Contextual: clear search, close lightbox, close modal |
| `Ctrl+Z` | Undo last move (while toast is active) |
| `Ctrl+A` | Select all images in current folder (not in lightbox) |
| `Select All` button | Toggle selection for all currently visible thumbnails |
| `U` | Toggle batch sidebar |
| `F` | Toggle favorites-only filter |
| `P` | Open Prompt History |
| `B` | Toggle AI score badges when an AI run is available |
| `V` | Toggle score-based sort when an AI run is available |
| `I` | Toggle AI sidebar |

### Lightbox

| Key | Action |
|-----|--------|
| `←` `→` | Previous / next image |
| `[` `]` | Previous / next scored image |
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
| `C` | Pin active image for sticky compare |
| `Esc` | Close lightbox |

When exactly two review-folder images are selected, **Compare in Lightbox**
opens a side-by-side comparison. Click a pane to make it active, or press `C`
to pin the active image and compare it against other images with Left/Right.

## UI behavior

- Sidebar state and thumbnail density persist across sessions.
- Background polling avoids interrupting lightbox review, drag/drop, and resize
  interactions.
- Public copies are generated derivatives only; originals stay in their review
  folders.
- Prompt history indexes are manual caches. Rebuild after significant curation
  sessions or when the modal reports a stale image count.
- The header Help button shows keybindings and workflow notes.

## Security

Binds to `127.0.0.1` by default. No built-in authentication -- sufficient
for single-user local use. For remote access, place behind a reverse proxy
with auth (nginx, Caddy, etc.). Read `SECURITY.md` for related guidance.

## ComfyUI extension

The repository includes a ComfyUI integration shell described in
`COMFYUI_EXTENSION_PORT_SPEC.md`:

- `__init__.py` -- ComfyUI custom-node entrypoint with `WEB_DIRECTORY`,
  `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS`.
- `py/curator_manager.py` -- registers `/curator` (Jinja2-rendered page),
  `/curator_static` (shared static asset mount), and `/api/curator/health`.
- `web/comfyui/top_menu_extension.js` -- ComfyUI action-bar button that
  opens `/curator`.
- `templates/curator.html` -- native page template derived from `index.html`
  with `/curator_static/` paths and `window.CURATOR_NATIVE = true`.
- Shared frontend URL helpers (`ccApiPath`, `ccThumbUrl`, `ccImageUrl` in
  `static/js/state.js`) switch between `/api`/`/thumb`/`/image` and
  `/api/curator`/`/curator/thumb`/`/curator/image` based on the native flag.

The native route surface is limited to `/curator`, `/curator_static`, and
`/api/curator/health`. Curation APIs, settings, watcher control, and AI
lifecycle are provided by the standalone Flask application (`app.py`).

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
- **License:** MIT -- see `LICENSE`.
