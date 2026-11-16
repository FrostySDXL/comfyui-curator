# tests -- Guidance

**One-sentence purpose:** Automated verification split by proof strength: unit (isolated logic), component (multi-module in-process), integration (real HTTP + filesystem).

**Role in the Project:** Gates correctness claims for the native ComfyUI adapter, shared core, CLI, and frontend source contracts. There is no Flask or standalone server layer; do not reintroduce one.

## What This Module Does

- **Unit tests** (`unit/`): isolated logic plus Python source-scraping frontend invariants and Node-VM lifecycle harnesses. No HTTP server.
- **Component tests** (`component/`): in-process native aiohttp adapter contracts with mocked aiohttp responses, native AI lifecycle, shared worker/queue/storage, and symlink recovery.
- **Integration tests** (`integration/`): real aiohttp application served on an ephemeral loopback port, exercised by a synchronous HTTP client with real filesystem effects.

## Key Concepts

### Test Layers

| Layer | Directory | What It Exercises | Run Command |
|-------|-----------|-------------------|-------------|
| Unit | `tests/unit/` | Isolated functions, models, parsing, native settings, frontend source/JS lifecycle, scripts. | `.venv/bin/python -m pytest tests/unit -v` |
| Component | `tests/component/` | Native route adapters, AI lifecycle/worker cancellation, workflow constraints, exchange jobs, symlink recovery. | `.venv/bin/python -m pytest tests/component -m component -v` |
| Integration | `tests/integration/` | Real native HTTP + real files: batches/images/metadata/moves, favorites, imports, publish/public, prompt history, search jobs, media ranges, AI job lifecycle. | `.venv/bin/python -m pytest tests/integration -m integration -v` |

### Pytest Markers

Defined in `pytest.ini`: `unit`, `component`, `integration`. `scripts/run_all.py` uses explicit paths rather than marker expressions.

### Shared Fixtures (`conftest.py`)

| Fixture | Scope | What It Sets Up |
|---------|-------|-----------------|
| `native_settings` | function | `NativeCuratorSettings` rooted at `tmp_path/batches`, `tmp_path/comfyui-outputs`, and `tmp_path/state.json`. |
| `native_service` | function | Real `NativeCuratorService` over `native_settings`; closes on teardown. |
| `client` | function | Real aiohttp app with `register_native_routes`, served on `127.0.0.1:0`, wrapped by a synchronous urllib client exposing `.get/.post/.request`, `.status_code`, `.get_json()`, `.json`, `.text`, `.data`, `.mimetype`. |
| `ai_lifecycle` | function | Started `NativeAiLifecycle` with `vl-scorer` configured and `_launch_worker` disabled for deterministic jobs. |
| `ai_client` | function | Real HTTP app with both foundation and `/api/curator/ai-curate/*` routes plus `test-batch`; depends on `ai_lifecycle`. |
| `create_batch` | function | Callable that creates a batch under the fixture root and returns its path. |
| `make_file` | function | Callable `_touch(path, content=b"x")` -- creates parent dirs, writes bytes. |
| `sample_image_names` | function | Shared list: `["img_b.png", "img_a.png", "preview.webp"]` |

**Hermetic environment:** `conftest.py` strips inherited `IMAGE_CURATOR_*` variables and neutralizes `dotenv.load_dotenv` before test modules import, so tests never read the operator's `.env` or write live configuration paths.

### Test Isolation Patterns

- **`tmp_path`** for every filesystem operation; never touch real batch libraries.
- **`monkeypatch`** for settings, module paths, and subprocess environment.
- **`unittest.mock.patch`** for network calls (`urllib.request.urlopen`, `VisionClient`) and scoring.
- **Explicit settings mutation** (e.g. `settings.public_export_root = ...`) for native route behavior.
- **Helper factories** in test modules: `_setup_batch()`, `_submit_run()`, `_write_png()`, `_editable_request()`.

### Frontend Test Pattern

`tests/unit/test_frontend_*.py` are Python source-scraping tests over the ordered split JS/CSS and `templates/curator.html`, the sole authoritative template. `tests/unit/frontend_source.py` provides the ordered file lists, `read_frontend_js/css`, and `extract_function_body` (which matches the parameter list before locating the body brace, so `options = {}` defaults are safe).

Executable lifecycle harnesses run real scripts under Node with DOM/transport doubles:

- `move_history_lifecycle_test.js`, `state_transitions_lifecycle_test.js`, `media_search_apply_lifecycle_test.js`, `batch_sidebar_peek_lifecycle_test.js`, `progressive_grid_lifecycle_test.js`, `viewport_loader_lifecycle_test.js`, `keyboard_focus_lifecycle_test.js`, `activity_center_lifecycle_test.js`, `compare_candidate_tray_test.js`, `lightbox_navigation_lifecycle_test.js`, `ai_*_test.js`, `thumbnail_cache_policy_test.js`, `import_destination_focus_lifecycle_test.js`.
- Frontend behavior is now native-only: folders always use revision snapshots, 256-item pages, and <=500 live thumbnails; polling without a snapshot is a no-op; there is no `CURATOR_NATIVE` flag or standalone branch.

`tests/unit/test_comfyui_static_ui.py` validates the sole-template structure, page-handler model context, unconditional native URL helpers via Node, asset existence, and no raw `/api`, `/thumb`, or `/image` fetch bypasses.

`tests/unit/test_native_no_flask_import.py` runs in a subprocess that blocks `flask` and `werkzeug`, imports the native routes and AI lifecycle, registers both route sets, starts/shuts down the lifecycle, and asserts the removed web stack was never imported.

### Native Extension Focused Tests

- `tests/unit/test_native_curator_settings.py` -- persisted/env/default precedence, malformed config, containment/secret safety.
- `tests/unit/test_comfyui_extension.py` -- entrypoint exports, route registration, page/static/health wiring.
- `tests/component/test_native_curator_api.py` -- broad adapter contracts: settings, v2 snapshots/pages/polls, media/metadata/range serving, moves/undo/history, favorites, public, prompt history, search jobs, symlink containment, revision invalidation.
- `tests/component/test_native_ai_curate_api.py` -- AI preview/submit/get/list/cancel/runs/elements, lifecycle shutdown, storage containment, settings conflicts.
- `tests/component/test_auto_import_responsiveness.py` -- event-loop responsiveness, pinned settings during root switch, timed shutdown, import-lock isolation.
- `tests/component/test_symlink_root_review.py` -- configured-root alias recovery across restart and refusal of internal links.

## Key Files & Responsibilities

| File | Subject Under Test | Key Patterns |
|------|-------------------|--------------|
| `tests/conftest.py` | Shared native fixtures and hermetic environment | Real aiohttp loopback server, synchronous client, native settings/service/lifecycle |
| `tests/unit/test_batch_store.py` | `image_curator.batch_store` | `tmp_path`, monkeypatched `shutil.move` |
| `tests/unit/test_client.py`, `test_elements.py`, `test_models.py`, `test_queue.py`, `test_scoring.py`, `test_storage.py`, `test_curate.py`, `test_config.py`, `test_ai_job_validation.py` | Shared AI core and CLI | Mocks, real queue/storage, CLI stdout |
| `tests/unit/test_favorites.py`, `test_publish.py`, `test_prompt_history.py`, `test_search_index.py`, `test_sidecar_metadata.py`, `test_media.py`, `test_png_metadata.py`, `test_move_history*.py`, `test_folder_index.py`, `test_web_validation.py` | Shared non-AI core | Real files, Pillow PNGs, containment cases |
| `tests/unit/test_frontend_*.py`, `*.js` | Frontend source and executable lifecycles | Source scraping + Node VM; no browser framework |
| `tests/unit/test_run_all_script.py` | Verification runner | Dynamic import |
| `tests/unit/test_benchmark_thumbnails.py` | Thumbnail benchmark orchestration | Fake WebDriver and Node harness |
| `tests/unit/test_setup_local_browser_fixture.py`, `test_setup_evaluation_fixture.py` | Fixture-script contracts | `tmp_path`, dynamic import |
| `tests/component/test_native_curator_api.py`, `test_native_ai_curate_api.py`, `test_native_real_aiohttp.py` | Native route adapters/lifecycle | Precise aiohttp mocks and real aiohttp smoke |
| `tests/component/test_ai_curate_worker.py` | `ai_curate.worker.run_scoring_worker_inner` cancellation during scoring/move and complete-race | Real `QueueManager` + `RunStorage`, injected scoring/move functions |
| `tests/component/test_workflow_constraints.py` | Move-after-scoring, cancelled-runs-no-history | Real shared queue/storage |
| `tests/integration/test_ai_curate_api.py` | Native AI HTTP API through `NativeAiLifecycle` | Real HTTP, disabled worker launcher, persisted run fixtures |
| `tests/integration/test_favorites_api.py`, `test_image_metadata_api.py`, `test_import_all_pending.py`, `test_prompt_history_api.py`, `test_publish_api.py`, `test_search_api.py`, `test_media_http.py`, `test_native_contract_regressions.py` | Native HTTP and filesystem workflows | Real server, real batches, sidecars, ranges, export roots, MIME/count/404 regressions |

## Known Coverage Gaps

| Gap | Risk | Notes |
|-----|------|-------|
| No full browser automation in the default suite | **Medium** | Real JS lifecycles run under Node DOM doubles; native Firefox/Chrome and media playback remain manual/benchmark gates. |
| No real AI client integration test | **Medium** | Worker is always stubbed; no end-to-end mock LLM endpoint. |
| No native ComfyUI process integration test | **Medium** | Routes/lifecycle are tested through a real aiohttp adapter and mocked host modules, but installing into a live ComfyUI process remains a manual smoke test. |
| No standalone Flask coverage | **By design** | `app.py`, `ai_curate/routes.py`, Flask request shapes, and the standalone template were removed. |
| No concurrent/multi-user stress tests | **Low** | Single-user design. |
| Drag-and-drop gestures not automated | **Low** | Handler-level tests plus manual smoke only. |
| FFmpeg media generation depth | **Low** | Dirty poster/preview fallbacks tested; encoder quality/eviction not. |
| Corrupt native config recovery | **Low** | Malformed config fallback/warning is covered; no migration from older undocumented shapes. |

## Agent Instructions

- Add new tests to the narrowest layer that proves the claim. Use the native HTTP `client` for full workflow/API behavior, and shared-module unit tests for pure logic.
- Never create an `app`/Flask fixture or shim. Import the native adapter directly or use `native_settings`/`native_service`/`client`.
- Use `tmp_path` for all filesystem isolation.
- Frontend tests must scan `templates/curator.html` and the ordered split JS sources; do not add a JS framework.
- When adding a verification surface, update `scripts/run_all.py`, `tests/unit/test_run_all_script.py`, and this README together.
- Keep tests hermetic: do not read `.env`, the production service file, or the live ambient `IMAGE_CURATOR_*` environment.

## Gotchas & Common Pitfalls

- **`client` is a real HTTP client, not Flask's test client:** responses expose `.status_code`, `.get_json()`/`.json`, `.data`, `.text`, `.mimetype`, and case-insensitive headers; use `json_body=` and `query_string=` keyword arguments.
- **aiohttp is a development dependency:** install `requirements-dev.txt` (or the dev lock) to run real native HTTP tests outside ComfyUI. Production uses ComfyUI's host-provided aiohttp; isolated environments without it skip the real HTTP fixtures and media-contract module before importing native adapters.
- **AI jobs stay deterministic:** `ai_lifecycle` disables `_launch_worker`, so submitted jobs remain running/queued until tests inspect them.
- **Settings are live:** route handlers read `service.settings` per request, so mutating `native_settings` affects subsequent HTTP calls.
- **Hermetic module state:** some tests mock `sys.modules` for ComfyUI host modules. Prefer subprocess probes (as the no-Flask test does) when checking real import availability.
- **`extract_function_body`** matches the parameter list first; pass the real signature (including `options = {}`) and it returns the whole body.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
