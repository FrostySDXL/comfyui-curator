# CONTRIBUTING.md

**Last Updated:** 2026-11-15

This repository is operator-maintained. Keep changes minimal, explicit, and easy to verify.

## Read first

- `README.md`
- `AGENTS.md`

## Working rules

- Always use a virtual environment (`.venv/`); never install dependencies globally.
- Prefer small, responsibility-based modules over large entrypoints or new monoliths
- Treat batch folder layout, native API JSON, and CLI flags as internal contracts that still require coordinated updates
- Keep AI scoring advisory by default; manual curation remains authoritative
- Do not commit runtime state, generated artifacts, or copied virtual environments

## Where changes go

- Native web routes: `py/curator_manager.py`, `image_curator/native_routes.py`, `image_curator/native_ai_routes.py`
- Shared non-AI backend logic: `image_curator/`
- Shared AI curation logic: `ai_curate/`
- HTML template: `templates/curator.html` (the only page template)
- Frontend behavior and styling: `static/js/`, `static/css/`
- Manual review-move recovery: `image_curator/move_history.py`, both web route
  adapters, and `static/js/moves.js`. Keep persistence, partial recovery,
  newest-first semantics, and source/sidecar safety covered by executable tests.
- Frontend selection/compare behavior is owned by `static/js/selection.js`;
  filesystem move, undo, drag/drop, and reject deletion behavior remains in
  `static/js/moves.js`. Preserve their ordered classic-script load relationship.
- Native ComfyUI extension: `__init__.py` (entrypoint), `py/curator_manager.py` (registration), `image_curator/native_settings.py` and `image_curator/native_routes.py` (foundation services/routes), `web/comfyui/` (frontend button)
- Tests: `tests/unit/`, `tests/component/`, `tests/integration/`
- Internal repo guidance: `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `MIGRATION.md`

`templates/curator.html` is the only page template; edit it directly. There is
no second template and no generator step to keep synchronized.

Avoid adding new production modules at repo root unless they are explicit entrypoints. Prefer `image_curator/`, `ai_curate/`, or another responsibility-based package with docs and tests.

### CSS file map

The browser loads split CSS files directly from `templates/curator.html`. Edit the
focused file for the affected surface. See `static/README.md` for the
authoritative CSS file map and frontend asset guidance.

## Verification before claiming completion

Run the narrowest checks that prove the change, then broaden if the surface changed.

Use the shared runner when possible so local verification matches repo expectations and avoids PATH differences for tools like pytest and Ruff:

```bash
python scripts/run_all.py
```

The shared runner includes a CSS asset check that verifies split CSS files exist and match the `/curator_static/css/...` stylesheet order in `templates/curator.html`.

During edit loops, use:

```bash
python scripts/run_all.py --quick
```

If formatting is required, apply it explicitly before final verification:

```bash
python scripts/run_all.py --format
```

Only use `--skip-js` when Node is unavailable and the change is not frontend-related. JavaScript verification checks every ordered split file and duplicate top-level declarations across classic scripts.

Add `--quiet` to suppress the per-check command echo (handy when sharing logs, since the echo otherwise shows the absolute path of the active Python interpreter).

### Full verification with mypy

For changes that touch type annotations, public APIs, or shared modules
under `ai_curate/` or `image_curator/`, run the full local check suite
which adds `mypy` to the default plan:

```bash
python scripts/run_all.py --full
```

`--full` runs the same checks as the default mode plus `mypy` against the native
entrypoints (`__init__.py`, `py/`), `curate.py`, `image_curator/`, `ai_curate/`,
`tests/`, and `scripts/`. It is the only mode that surfaces type errors before a CI
gate catches them. Keep the default mode green for fast edit loops, and
run `--full` before opening a PR.

### Managing dependencies

Edit `requirements.in` (runtime) or `requirements-dev.in` (dev tools), then regenerate:

```bash
pip install pip-tools
pip-compile --no-upgrade --output-file=requirements-lock.txt requirements.in
python3.10 -m venv /tmp/curator-lock310
/tmp/curator-lock310/bin/pip install pip-tools
/tmp/curator-lock310/bin/pip-compile --no-upgrade --output-file=requirements-dev-lock.txt requirements-dev.in
```

The `-lock.txt` files are the reproducible pinned builds. `requirements.txt` and
`requirements-dev.txt` are convenience install files that only include their
`.in` source files: `requirements.txt` includes `requirements.in`, and
`requirements-dev.txt` includes `requirements-dev.in`. Do not list packages in
them, or a fresh documented dev install can silently omit `aiohttp` and skip the
real native HTTP tests. `tests/unit/test_dependency_files.py` enforces the
include chain and verifies the locks cover every declared direct requirement.

The dev lock is resolved with the minimum supported interpreter, Python 3.10,
because pip-tools 7.6.2's `pip-compile` has no `--python-version` or
`--python-executable` option. Resolving under an actual 3.10 interpreter applies
`Requires-Python` filtering honestly: for example, multidict 7.2.1 requires
Python >= 3.11, so the 3.10 resolution keeps a compatible multidict pin. Compile
in place so `--no-upgrade` can seed from the existing output pins; do not delete
the lock first. The resulting pins also install on newer Python 3.x runtimes,
where the 3.10-only backports (`async-timeout`, `exceptiongroup`, `tomli`) are
inert. Verify the dev lock on 3.10 before committing:

```bash
/path/to/python3.10 -m pip install --dry-run --ignore-installed \
    --only-binary=:all: -r requirements-dev-lock.txt
```

Runtime dependencies are deliberately small: Jinja2 (the native page renderer),
Pillow (metadata, derivatives, and cache generation), and python-dotenv (CLI
`.env` loading). Flask went away with standalone mode; `aiohttp` and ComfyUI's
`server` / `folder_paths` modules come from ComfyUI instead of being pinned here.
Keep `--no-upgrade` when regenerating: the dev lock deliberately stays on the
toolchain the repo was verified with (for example Ruff 0.15.15), because a newer
Ruff's expanded default rule set reports unrelated findings.

### Fast local checks

```bash
python -m ruff format --check __init__.py curate.py image_curator ai_curate py tests scripts
python -m compileall __init__.py curate.py image_curator ai_curate py
```

### Python tests

```bash
python -m pytest tests/unit
python -m pytest tests/component
python -m pytest tests/integration
```

### Native extension tests

```bash
python -m pytest tests/unit/test_native_curator_settings.py tests/component/test_native_curator_api.py tests/component/test_native_ai_curate_api.py tests/unit/test_comfyui_extension.py tests/unit/test_comfyui_static_ui.py tests/unit/test_native_no_flask_import.py -v
```

A manual ComfyUI smoke test is required to claim native extension readiness:
install the package into `ComfyUI/custom_nodes`, start ComfyUI, confirm the
action-bar button appears and `/curator` loads. Native batch/image foundation
routes are namespaced under `/api/curator/*` and `/curator/{thumb,image}/*`.
Use the repeatable route-mode checklist in
[`tests/manual_route_smoke.md`](tests/manual_route_smoke.md) and record the
real browser evidence separately from mocked/in-process test results.

### Comfy Registry package validation

Registry metadata lives in `pyproject.toml`, and `.comfyignore` excludes
development-only files from the published archive. Before preparing a release:

```bash
comfy node validate
comfy node pack
tar -tf node.zip
```

Inspect the archive and confirm it includes the root `__init__.py`, backend
packages, templates, static assets, ComfyUI web extension, branding assets,
requirements, README, MIGRATION.md, and license. Publishing is a separate irreversible step:
do not run `comfy node publish` without explicit release approval, and bump the
semantic version before every published release.

### Updating `scripts/run_all.py`

Update `scripts/run_all.py` in the same change when adding or changing verification surfaces, including:

- new test directories or test layers
- new frontend assets that need syntax/type/build checks
- new formatting, linting, or static-analysis tools
- new docs or fixture validation scripts that gate completion claims
- changed command paths, package names, or entrypoints

Also update the runner tests in `tests/unit/test_run_all_script.py` so the expected check plan stays explicit. Keep `--format` as the only mode that mutates files; default, quick, and full modes should be verification-only. If a new check requires an external executable, add a clear `requires` guard and document any acceptable skip flag.

### Manual checks for UI/API work

- For disposable fixture batches, see `scripts/README.md`. It creates ignored
  sample batches and prints the fixture paths plus optional
  `IMAGE_CURATOR_BATCHES` / `IMAGE_CURATOR_COMFYUI` native fallbacks.
- Start ComfyUI locally and open `/curator`
- Load at least one test batch
- Verify changed UI controls render and behave correctly
- Verify any changed API route returns expected JSON
- For move/undo changes, use the separate disposable-fixture checks in
  `tests/manual_route_smoke.md`, including toast expiry, page reload, server
  restart, snapshot exclusions, and final media/sidecar hash restoration.
- For CSS-only changes, also confirm browser developer tools show no missing CSS file 404s and resize below `900px` to check responsive layout.
- Frontend source-scraping invariants are auto-verified by
  `python scripts/run_all.py --quick`; see `tests/README.md` for the test
  pattern.

## Change playbooks

### If changing API routes

- Read the native adapters (`py/curator_manager.py`, `image_curator/native_routes.py`, `image_curator/native_ai_routes.py`)
- Check matching frontend calls in the relevant ordered `static/js/*.js` file
- Add or update integration tests
- Update `README.md` or `AGENTS.md` if the contract shape changes

### If changing AI scoring logic

- Read `curate.py` and the relevant module in `ai_curate/`
- Add/update unit tests first where practical
- Verify run history, move rules, and failure handling explicitly

### If changing filesystem layout or batch behavior

- Verify all path assumptions in the native adapters and any scoring/storage module
- Document the change in `README.md` and `AGENTS.md`; add operator migration notes to `MIGRATION.md` when data locations or persistence change

### If changing documented features or repo structure

- Update `README.md` when operator-visible behavior, compatibility surfaces, ownership boundaries, or cleanup guidance changes
- Check `AGENTS.md`, this file, and the in-app Help modal for duplicated commands, paths, shortcuts, or compatibility surfaces
- If verification expectations change, update `scripts/run_all.py`, `tests/unit/test_run_all_script.py`, README verification notes, and this file together
- `templates/curator.html` is the only page template; there is no generation step

## Completion standard

When reporting done, include:

- what changed
- which files changed
- which verification commands were run
- what manual verification was performed
- any remaining caveats or follow-up work
