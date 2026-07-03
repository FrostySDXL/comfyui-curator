# CONTRIBUTING.md

**Last Updated:** 2026-06-13

This repository is operator-maintained. Keep changes minimal, explicit, and easy to verify.

## Read first

- `README.md`
- `AGENTS.md`

## Working rules

- Always use a virtual environment (`.venv/`); never install dependencies globally.
- Prefer small, responsibility-based modules over growing `app.py` indefinitely
- Treat batch folder layout, API JSON, and CLI flags as internal contracts that still require coordinated updates
- Keep AI scoring advisory by default; manual curation remains authoritative
- Do not commit runtime state, generated artifacts, or copied virtual environments

## Where changes go

- Flask routes / web entrypoint: `app.py`
- Shared non-AI backend logic: `image_curator/`
- Shared AI curation logic: `ai_curate/`
- HTML templates: `templates/`
- Frontend behavior and styling: `static/js/`, `static/css/`
- Tests: `tests/unit/`, `tests/component/`, `tests/integration/`
- Internal repo guidance: `README.md`, `AGENTS.md`, `CONTRIBUTING.md`

Avoid adding new production modules at repo root unless they are explicit entrypoints. Prefer `image_curator/`, `ai_curate/`, or another responsibility-based package with docs and tests.

### CSS file map

The browser loads split CSS files directly from `templates/index.html`. Edit the
focused file for the affected surface. See `static/README.md` for the
authoritative CSS file map and frontend asset guidance.

## Verification before claiming completion

Run the narrowest checks that prove the change, then broaden if the surface changed.

Use the shared runner when possible so local verification matches repo expectations and avoids PATH differences for tools like pytest and Ruff:

```bash
python scripts/run_all.py
```

The shared runner includes a CSS asset check that verifies split CSS files exist and match the stylesheet order in `templates/index.html`.

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

`--full` runs the same checks as the default mode plus `mypy` against
`app.py`, `curate.py`, `image_curator/`, `ai_curate/`, `tests/`, and
`scripts/`. It is the only mode that surfaces type errors before a CI
gate catches them. Keep the default mode green for fast edit loops, and
run `--full` before opening a PR.

### Managing dependencies

Edit `requirements.in` (runtime) or `requirements-dev.in` (dev tools), then regenerate:

```bash
pip install pip-tools
pip-compile --output-file=requirements-lock.txt requirements.in
pip-compile --output-file=requirements-dev-lock.txt requirements-dev.in
```

The `-lock.txt` files are the reproducible pinned builds; `requirements.txt` and
`requirements-dev.txt` are hand-maintained convenience install files.

### Fast local checks

```bash
python -m ruff format --check app.py image_curator ai_curate curate.py tests scripts
python -m compileall app.py image_curator ai_curate curate.py
```

### Python tests

```bash
python -m pytest tests/unit
python -m pytest tests/component
python -m pytest tests/integration
```

### Updating `scripts/run_all.py`

Update `scripts/run_all.py` in the same change when adding or changing verification surfaces, including:

- new test directories or test layers
- new frontend assets that need syntax/type/build checks
- new formatting, linting, or static-analysis tools
- new docs or fixture validation scripts that gate completion claims
- changed command paths, package names, or entrypoints

Also update the runner tests in `tests/unit/test_run_all_script.py` so the expected check plan stays explicit. Keep `--format` as the only mode that mutates files; default, quick, and full modes should be verification-only. If a new check requires an external executable, add a clear `requires` guard and document any acceptable skip flag.

### Manual checks for UI/API work

- For a disposable local browser fixture, see `scripts/README.md`. It creates
  ignored sample batches and prints shell-specific environment variables plus
  an `app.py` launch command.
- Start the app locally
- Load at least one test batch
- Verify changed UI controls render and behave correctly
- Verify any changed API route returns expected JSON
- For CSS-only changes, also confirm browser developer tools show no missing CSS file 404s and resize below `900px` to check responsive layout.
- Frontend source-scraping invariants are auto-verified by
  `python scripts/run_all.py --quick`; see `tests/README.md` for the test
  pattern.

## Change playbooks

### If changing API routes

- Read `app.py`
- Check matching frontend calls in the relevant ordered `static/js/*.js` file
- Add or update integration tests
- Update `README.md` or `AGENTS.md` if the contract shape changes

### If changing AI scoring logic

- Read `curate.py` and the relevant module in `ai_curate/`
- Add/update unit tests first where practical
- Verify run history, move rules, and failure handling explicitly

### If changing filesystem layout or batch behavior

- Verify all path assumptions in `app.py` and any scoring/storage module
- Check service/operator assumptions in `image-curator.service.example`
- Document the change in `README.md` and `AGENTS.md`

### If changing documented features or repo structure

- Update `README.md` when operator-visible behavior, compatibility surfaces, ownership boundaries, or cleanup guidance changes
- Check `AGENTS.md`, this file, and the in-app Help modal for duplicated commands, paths, shortcuts, or compatibility surfaces
- If verification expectations change, update `scripts/run_all.py`, `tests/unit/test_run_all_script.py`, README verification notes, and this file together

## Completion standard

When reporting done, include:

- what changed
- which files changed
- which verification commands were run
- what manual verification was performed
- any remaining caveats or follow-up work
