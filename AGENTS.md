# AGENTS.md

**Last Updated:** 2026-06-01

## Quickstart

- This is a public repo for the Image Curator service and related curation tooling.
- Read `README.md` first.
- Use a virtual environment (`.venv/`) for all development work.
- The current live entrypoints are still `app.py` and `curate.py` at repo root.
- New shared non-AI backend logic should prefer `image_curator/` over further expanding root scripts.
- New shared AI backend logic should prefer `ai_curate/`.
- Treat batch filesystem layout and API responses as internal contracts.
- Do not read or expose secrets, tokens, or `.env`-style files if later added.
- Before claiming completion, re-read changed files and report exact verification performed.
- The current operator layout is left batch sidebar, center image grid, right AI sidebar.
- Treat keyboard shortcuts and lightbox review flow as operator-facing compatibility surfaces.
- Treat the lightbox PNG metadata toggle and displayed metadata fields as operator-facing compatibility surfaces.
- Treat the header Help modal content as an operator-facing compatibility surface too.
- Treat batch and AI sidebar button labels as stateful operator-facing cues, not static text.
- Treat AI run history labels and compare controls as operator-facing compatibility surfaces.
- For feature inventory or repo cleanup tasks, read `README.md`, `CONTRIBUTING.md`, and this file before editing.
- `scripts/run_all.py` default mode runs both `ruff format --check` and `ruff check`; do not commit code that fails either on the touched paths.

## Decision tree

- UI layout, shortcuts, lightbox, sidebars: read `templates/index.html`, `static/js/app.js`, `static/css/app.css`, then verify manually.
- Flask API or batch filesystem behavior: read `app.py`, matching frontend calls in `static/js/app.js`, and integration tests.
- AI scoring, queueing, or run history: read `ai_curate/`, `curate.py`, `tests/unit/test_*`, and `tests/integration/test_ai_curate_api.py`.
- Docs or repo organization: read `README.md`, `CONTRIBUTING.md`, and this file.
- Deployment assumptions: read `image-curator.service.example`, `app.py` constants, and `ai_curate/config.py` path/env defaults.

## Mission

Maintain a fast operator-facing curation workflow for generated images with optional AI-assisted scoring, without making AI the source of truth.

## Non-goals

- Public packaging polish
- Public-facing docs site
- Generic DAM/media-library scope
- Silent contract changes to API routes, batch layout, or CLI behavior

## STRICT RULE

- The production `image-curator.service` may contain sensitive information. Never read it. Use `image-curator.service.example` as the reference template instead.

## Repo map

- `app.py` — current Flask app entrypoint and API layer
- `curate.py` — current CLI entrypoint
- `image_curator/` — shared non-AI support code, currently batch filesystem/state helpers
- `ai_curate/` — shared AI scoring, queueing, storage, and related support code
- `templates/` — Flask templates
- `static/` — frontend assets
- `tests/` — unit/component/integration checks
- `scripts/` — helper scripts
- `image-curator.service.example` — templated systemd unit
- `.env.example` — documented environment variable reference
- `pyproject.toml` — project metadata and tool configuration
- `pytest.ini` — pytest marker and test-path configuration
- `LICENSE` — MIT license

## Structure rules

- Root-level entrypoints remain active for now: `app.py` and `curate.py`
- New shared non-AI backend logic should go in `image_curator/`
- New shared AI backend logic should go in `ai_curate/`
- Keep HTML in `templates/`, browser logic in `static/js/`, and styling in `static/css/`
- Put isolated logic tests in `tests/unit/`
- Put in-process multi-module checks in `tests/component/`
- Put Flask/API/filesystem workflow checks in `tests/integration/`
- Keep local helper scripts in `scripts/`

## Public compatibility surfaces

Treat these as stability-sensitive:

- Flask API request/response shapes consumed by the frontend
- Batch directory structure under `BATCHES_DIR/<batch>/` (configured by `IMAGE_CURATOR_BATCHES`)
- AI run-history files under `BATCHES_DIR/<batch>/ai-curate/`
- `curate.py` CLI flags and default behaviors while the CLI remains active
- Runtime state file location (configured by `IMAGE_CURATOR_STATE`)
- `image-curator.service.example` template expectations
- Header Help modal content, keyboard shortcuts, and sidebar toggle labels
- Lightbox PNG metadata route shape, toggle shortcut, and displayed field set

## Task playbooks

### UI change

- Read `templates/index.html`, `static/js/app.js`, and `static/css/app.css`
- Preserve the center grid as the primary review surface
- Preserve the right-sidebar AI Curate layout unless the task explicitly changes it
- Preserve the header control cluster order and semantics unless the task explicitly changes them
- Preserve the expected sidebar-toggle label behavior (`Show` / `Hide`) unless the task explicitly changes it
- Preserve keyboard-first flow for search, selection, AI toggles, sorting, and lightbox review
- Prefer human-readable AI run labels over raw internal run IDs in operator-facing selectors when possible
- Be careful with polling, drag state, and lightbox interactions so background refresh does not interrupt the operator
- Verify the browser flow manually
- Update tests if behavior meaningfully changed

### UI behavior that should stay consistent

- AI overlay toggle and AI filter state are batch-scoped and must not leak across batch switches
- Undo must work for both drag moves and lightbox keyboard moves while the undo toast is active
- Thumbnail updates should prefer incremental DOM updates over full grid rebuilds when possible
- The AI sidebar open state, collapsed state, and width persist in local storage
- The batch sidebar open state persists in local storage
- Batch-search shortcuts should reopen the batch sidebar before focusing the search input
- The Help modal should reflect current shortcuts and major workflow notes
- AI history should support comparing the selected run against another run from the same batch
- Lightbox supports zoom and scored-image navigation shortcuts
- Lightbox metadata supports the `M` toggle and should keep full prompt/negative prompt inspection available without disrupting image review

### API or backend change

- Read `app.py` and related modules in `image_curator/` or `ai_curate/`
- Keep route validation and JSON response contracts synchronized with the frontend
- Add or update integration tests

### Filesystem or run-history change

- Verify all path assumptions
- Confirm runtime artifacts remain ignored by git
- Update `README.md` and `AGENTS.md`

## Verification standard

Use the smallest proof that supports the claim, then broaden if needed:

- Prefer `python scripts/run_all.py` before completion claims unless a narrower verification scope is explicitly justified.
- Use `python scripts/run_all.py --quick` for fast edit-loop checks.
- Use `python scripts/run_all.py --format` only when intentionally applying formatting.
- Syntax/compile checks for touched Python files
- Syntax checks for touched frontend files when applicable
- Unit tests for isolated logic
- Component/integration tests for route or workflow changes
- Manual UI validation for interactive features
- `scripts/run_all.py` does not replace manual browser validation for interactive UI changes.
- When adding new verification surfaces, update `scripts/run_all.py`, `tests/unit/test_run_all_script.py`, `README.md`, and `CONTRIBUTING.md` together.

## Completion standard

Do not say complete without stating:

- files changed
- commands run
- manual verification performed
- remaining risk or deferred follow-up
