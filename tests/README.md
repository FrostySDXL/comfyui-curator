# tests -- Guidance

**One-sentence purpose:** Automated verification split by proof strength: unit (isolated logic), component (multi-module in-process), integration (full HTTP + filesystem).

**Role in the Project:** Gate all claims of correctness. Run before committing and as part of `scripts/run_all.py`. Organized by how much of the system each layer exercises.

## What This Module Does

- **Unit tests** (`unit/`): Pure logic checks with no I/O, no network, no Flask. Uses `tmp_path`, `monkeypatch`, and `unittest.mock` for isolation.
- **Component tests** (`component/`): In-process tests crossing 2--4 module boundaries (Flask test client + real queue + real storage). Uses `app_module` fixture.
- **Integration tests** (`integration/`): Full HTTP cycle through Flask routes with real filesystem side effects. Uses `app_module` fixture + `test_client()`.

## Key Concepts

### Test Layers

| Layer | Directory | What It Exercises | Run Command |
|-------|-----------|-------------------|-------------|
| Unit | `tests/unit/` | Isolated functions, models, constants, parsing. No Flask, no files beyond `tmp_path`. Includes native extension entrypoint and static UI compatibility tests. | `python -m pytest tests/unit -v` |
| Component | `tests/component/` | Flask route contracts (status codes, JSON shapes), AI worker lifecycle (cancel timing), queue+storage integration. | `python -m pytest tests/component -m component -v` |
| Integration | `tests/integration/` | Full API submission/status/cancel/history flows, metadata API, import-all API. Flask test client + real file I/O. | `python -m pytest tests/integration -m integration -v` |
| Native extension (focused) | `tests/unit/test_native_curator_settings.py`, `tests/component/test_native_curator_api.py`, `tests/component/test_native_ai_curate_api.py`, `tests/unit/test_comfyui_extension.py`, `test_comfyui_static_ui.py` | Host path resolution, aiohttp adapter contracts, entrypoint exports, route registration, template parity, URL helpers, and native AI lifecycle/shutdown/storage-containment. Mock host modules; no real ComfyUI server. | `python -m pytest tests/unit/test_native_curator_settings.py tests/component/test_native_curator_api.py tests/component/test_native_ai_curate_api.py tests/unit/test_comfyui_extension.py tests/unit/test_comfyui_static_ui.py -v` |

### Pytest Markers

Defined in `pytest.ini`:
- `unit` -- isolated logic checks
- `component` -- in-process multi-module
- `integration` -- Flask/API/filesystem workflow

Applied via `@pytest.mark.component`, `@pytest.mark.integration`, or `pytestmark = pytest.mark.component` at module level. `scripts/run_all.py` uses explicit paths rather than marker expressions.

### Shared Fixtures (`conftest.py`)

| Fixture | Scope | What It Sets Up |
|---------|-------|-----------------|
| `app_module` | function | Imports `app`, monkeypatches `BATCHES_DIR`, `COMFYUI_OUTPUT`, `STATE_FILE` to `tmp_path` subdirs, and sets `TESTING=True`. |
| `client` | function | Returns `app_module.app.test_client()` -- a Flask test client. |
| `sample_image_names` | function | Shared list: `["img_b.png", "img_a.png", "preview.webp"]` |
| `make_file` | function | Callable `_touch(path, content=b"x")` -- creates parent dirs, writes bytes. |

### Test Isolation Patterns

- **`tmp_path`** (pytest built-in) for all filesystem operations -- never writes to real directories.
- **`monkeypatch`** for module-level path overrides (`BATCHES_DIR`, `COMFYUI_OUTPUT`, `STATE_FILE`).
- **`unittest.mock.patch`** for network calls (`urllib.request.urlopen`) and heavy modules (`VisionClient`, `score_images`).
- **`capsys`** for CLI stdout/stderr assertions.
- **`SystemExit` exception catching** for CLI exit code tests.
- **Helper factories** in test files: `_make_job()`, `_make_completed_run()`, `_setup_batch()`, `write_png()`.

### Frontend Test Pattern (Special)

The `test_frontend_*.py` files in `tests/unit/` are **Python source-scraping tests** -- they read ordered split JS/CSS sources through `tests/unit/frontend_source.py` and assert on regex matches for function names, code patterns, or the absence of undefined references. There is no headless browser, DOM testing, or JS test framework. These tests catch regressions in function naming and structural invariants but do NOT test interactive behavior.

## Key Files & Responsibilities

| File | Subject Under Test | Key Patterns |
|------|-------------------|--------------|
| `tests/conftest.py` | Shared fixtures | `app_module`, `client`, `make_file`, `sample_image_names` |
| `tests/unit/test_app_helpers.py` | `app.py` -- `load_state`, `save_state`, `create_batch`, `get_images`, compatibility wrappers for `_safe_path`, `_validate_ai_curate_request` | `app_module` fixture, `tmp_path`, app-level wrapper/monkeypatch seam coverage |
| `tests/unit/test_batch_store.py` | `image_curator.batch_store` -- all public functions, 9 `_validate_name` tests | `tmp_path`, `monkeypatch` on `shutil.move` and `Path.stat` |
| `tests/unit/test_client.py` | `ai_curate.client` -- `VisionClient`, `build_score_payload`, `parse_score_response` | `unittest.mock.patch` on `urllib.request.urlopen`, MagicMock |
| `tests/unit/test_config.py` | `ai_curate.config` -- all constants and defaults | `importlib.reload` for env-dependent values |
| `tests/unit/test_curate.py` | `curate.main` -- 11 CLI scenarios | `monkeypatch.setattr("sys.argv")`, `mock.patch` on VisionClient |
| `tests/unit/test_elements.py` | `ai_curate.elements` -- `extract_elements`, `build_element_list`, `get_quality_elements` | Pure functions, no mocking |
| `tests/unit/test_models.py` | `ai_curate.models` -- `JobState`, `ImageResult`, `RunTotals`, `CurationRun` round-trips | Pure unittests, no fixtures |
| `tests/unit/test_png_metadata.py` | `image_curator.png_metadata` -- parsing, missing metadata, malformed input | `PIL.Image.new` + `PngInfo` for test PNGs |
| `tests/unit/test_sidecar_metadata.py` | Adjacent JSON preference, bounded parsing, malformed/symlink safety, type-preserving Rule34 data, combined metadata | `tmp_path`, real JSON files |
| `tests/unit/test_favorites.py` | `image_curator.favorites` -- batch/universal favorite load/save/toggle/resolve | `tmp_path`, real files, JSON shape checks |
| `tests/unit/test_publish.py` | `image_curator.publish` -- public derivative creation, metadata stripping, watermark, public listing, export-root-gated copy/move/delete, symlink-safe file operations | `tmp_path`, Pillow PNG fixtures, real file copies/moves/deletes |
| `tests/unit/test_prompt_history.py` | `image_curator.prompt_history` -- normalization, hash, PNG prompt index build/cache, plus symlink/escape safety rejection | `tmp_path`, `PIL.Image.new` + `PngInfo`, `monkeypatch` for resolve-escape tests |
| `tests/unit/test_web_validation.py` | `image_curator.web_validation` -- path traversal blocking and existing-batch validation | `tmp_path`, pure helper assertions |
| `tests/unit/test_media.py` | `image_curator.media` -- extension-safe poster/preview cache names, freshness, WebP generation, decoder fallback | `tmp_path`, `PIL.Image.new` |
| `tests/unit/test_folder_index.py` | Immutable background folder snapshots, non-blocking initial build, mutation refresh and revision publication | `tmp_path`, real worker threads, bounded waits |
| `tests/unit/test_ai_job_validation.py` | `ai_curate.job_validation` -- AI submit payload validation and defaulting | Pure helper assertions with injected batch/model constants |
| `tests/unit/test_queue.py` | `ai_curate.queue.QueueManager` -- 11 test classes, 30+ tests plus app worker interface coverage | `MagicMock` storage, custom `qm` fixture |
| `tests/unit/test_scoring.py` | `ai_curate.scoring` -- `find_images`, `build_scoring_prompt`, `score_images` | `mock.patch` on VisionClient, cancel-check testing |
| `tests/unit/test_storage.py` | `ai_curate.storage.RunStorage` -- save, load, list, latest, corrupt data, path traversal | `tmp_path`-based `tmp_batches` + `storage` fixtures |
| `tests/unit/test_run_all_script.py` | `scripts/run_all.py` -- build checks, format display, parse args | `importlib.util` dynamic import |
| `tests/unit/test_benchmark_thumbnails.py`, `benchmark_dynamic_traversal_test.js` | Thumbnail benchmark orchestration, report contracts, and executable dynamic traversal/viewport lifecycle | Shared Python WebDriver fake plus Node `vm` browser mock executing JS extracted from the harness |
| `tests/unit/test_frontend_progressive_grid.py`, `progressive_grid_lifecycle_test.js` | Virtual-grid constants/source invariants and executable real-`grid.js` lifecycle | Node DOM mock traversing 30,000 canonical items while enforcing <=500 live thumbs, identity retention, and one hover decoder |
| `tests/unit/test_setup_local_browser_fixture.py` | `scripts/setup_local_browser_fixture.py` -- disposable manual-browser fixture creation and launch env output | `tmp_path`, `importlib.util` dynamic import |
| `tests/unit/test_comfyui_extension.py` | Native `__init__.py` entrypoint, `py/curator_manager.py`, `web/comfyui/top_menu_extension.js` | `importlib`, `MagicMock`, mock modules for `server`, `aiohttp`, `jinja2` |
| `tests/unit/test_comfyui_static_ui.py` | Native template parity, URL centralization, error propagation, page handler context | `frontend_source.read_frontend_js`, `subprocess` (node), `tmp_path`, `MagicMock` |
| `tests/unit/test_native_curator_settings.py` | Native config persistence, precedence, malformed/schema handling, target containment, secret-safe payload, and host defaults | Injected host callables, `tmp_path`, symlink and resolve monkeypatches |
| `tests/unit/test_frontend_native_settings.py` | Native Settings modal fields, secret controls, API wiring, and focus integration | Ordered frontend source invariants |
| `tests/unit/test_frontend_view_menu.py` | Workspace toolbar grouping, View menu semantics, keyboard/focus handling, responsive rules, and script ordering | Ordered frontend source and template invariants |
| `tests/component/test_native_curator_api.py` | Native settings plus legacy/v2 media listings, lightweight polls/pages, typed posters/originals, snapshot bulk move/undo, deletion, favorites, public and prompt-history contracts | Precise aiohttp web mocks, async handler execution, real `tmp_path` files |
| `tests/unit/test_frontend_*.py` | Ordered `static/js/*.js` and `static/css/*.css` sources -- source scanning for function names, invariants, undefined references | `tests/unit/frontend_source.py` helpers + regex assertions |
| `tests/component/test_batch_api.py` | Flask route contracts: batches, images, move, delete-rejects, thumbnails | `client` fixture, PIL image generation |
| `tests/component/test_ai_curate_worker.py` | `app._run_scoring_worker_inner` -- cancel timing (scoring vs move vs race) | Real `QueueManager` + `RunStorage`, patched `score_images` |
| `tests/component/test_workflow_constraints.py` | AI workflow invariants: move-after-scoring, cancel-no-history, failed-never-move | `RunStorage` + `QueueManager` integration |
| `tests/integration/test_ai_curate_api.py` | Full AI API: preview, submit, get, list, cancel, runs, path traversal | `client` fixture, worker thread patched |
| `tests/integration/test_image_metadata_api.py` | `/api/image-metadata` route -- PNG metadata, JSON sidecars on typed media, missing files | `client` fixture, `PngInfo`-rich PNGs, adjacent JSON |
| `tests/integration/test_import_all_pending.py` | `/api/import-all` -- moves available files into the selected batch | `client` fixture, ComfyUI output dir |
| `tests/integration/test_favorites_api.py` | Favorites API -- batch/universal toggles and image response favorite flag | `client` fixture, real temp files |
| `tests/integration/test_publish_api.py` | Public publish API -- export, list, serve/thumbnail public images, copy/move/delete route contracts | `client` fixture, `PIL.Image` PNGs, monkeypatched export root |
| `tests/integration/test_prompt_history_api.py` | Prompt-history API -- build/load/rebuild/staleness/missing cache | `client` fixture, `PngInfo`-rich PNGs |

## Known Coverage Gaps

| Gap | Risk | Notes |
|-----|------|-------|
| No full browser automation in the default suite | **Medium** | Critical grid/lightbox lifecycles execute real JS under Node DOM mocks; native Firefox/Chrome and media playback remain manual/benchmark gates. |
| No real AI client integration test | **Medium** | Worker is always patched/stubbed. No end-to-end test against even a mock LLM endpoint. |
| No native ComfyUI integration test | **Medium** | `test_comfyui_extension.py` uses mock ComfyUI modules. Manual smoke test required: install extension into ComfyUI `custom_nodes`, confirm the action-bar button appears and `/curator` loads. |
| No concurrent/multi-user stress tests | **Low** | QueueManager is single-threaded tested. Intended for single-user operation. |
| No drag-and-drop tests | **Low** | UI has drag-to-move but it's untested. |
| Thumbnail generation logic not deeply tested | **Low** | Route returns 200/404 tested, but WebP conversion correctness and cache eviction are not. |
| Flask error handlers not tested | **Low** | 404/500 custom handler pages are untested. |
| Corrupt state file recovery not tested | **Low** | `load_state` defaults on missing file, but corrupt JSON recovery is not verified. |

## Agent Instructions

- Add new tests to the narrowest layer that proves the claim. Unit tests for pure logic, component for route contracts, integration for full workflows.
- Use `tmp_path` for all filesystem isolation -- never hardcode paths.
- When mocking, prefer `unittest.mock.patch` at the module level (e.g., `patch("ai_curate.scoring.VisionClient")`) over instance patching.
- Frontend tests must regex-scan the ordered split JS sources -- do not convert them to a JS framework without explicit approval (the project intentionally avoids one).
- When adding a new verification surface, update `scripts/run_all.py`, `tests/unit/test_run_all_script.py`, and this README together.
- For parametrized validation tests, follow `test_storage.py`'s `bad_batch` pattern (matrix of bad inputs x methods = many assertions in one test).
- **Native extension tests are mock-based:** `test_comfyui_extension.py` and `test_comfyui_static_ui.py` validate entrypoint structure, route registration, template parity, and URL helper behavior using mock ComfyUI modules. A manual ComfyUI smoke test is required for any claim of native extension readiness.

## Gotchas & Common Pitfalls

- **`app_module` fixture monkeypatches paths:** Any test using `app_module` gets isolated `tmp_path` subdirectories. Do not assume `BATCHES_DIR` resolves to the real filesystem.
- **Integration tests patch the worker thread:** `test_ai_curate_api.py` uses `with patch.object(app_module, "_run_scoring_worker")` to prevent actual scoring. The queue and storage are real; only the worker loop is suppressed.
- **`make_file` is a fixture returning the named function `_touch` (conftest.py:37):** It creates parent directories automatically. File content defaults to `b"x"` -- use explicit content for metadata-rich PNG tests.
- **Marker application varies:** Some files use `pytestmark = pytest.mark.component` at module level; others use `@pytest.mark.component` per function. Both are valid but be consistent within a file.

**Completion Standard:** When adding or changing tests, verify they pass with the layer-appropriate command above, and update this README if a new test file or coverage gap change was introduced.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
