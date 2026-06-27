# ai_curate -- Guidance

**One-sentence purpose:** Shared AI curation backend providing Flask API routes, vision-LLM scoring, job queuing, and run-history persistence for both the web app and the CLI.

**Role in the Project:** Called by `app.py` (Flask, async via `QueueManager`) and `curate.py` (CLI, synchronous in-process). This module owns the complete AI pipeline from element extraction through scoring to on-disk run history.

## What This Module Does

- Extracts or accepts scoring elements from operator prompts.
- Calls an OpenAI-compatible `/v1/chat/completions` endpoint with base64-encoded images.
- Parses YES/NO responses into per-image scores and missing-element details.
- Exposes focused Flask Blueprint routes for AI curation API requests, backed by app-injected queue/storage/lifecycle dependencies.
- Validates web job submissions and queues scoring jobs FIFO with a single-worker constraint, cancel support, and partial-move audit trails.
- Persists completed runs as JSON files under `<batch>/ai-curate/runs/` with a `latest.json` pointer.

## Key Concepts

### Pipeline Flow

```
config.py ──(constants)──> job_validation.py ──(web payload validation)
     │
     └──────> models.py ──(types)──> elements.py ──(prompt parsing)
                                             │
                          client.py ◄───────┘
                             │
                          scoring.py ──(enumeration + loop)
                             │
                    ┌────────┴────────┐
                 worker.py          queue.py
              (app orchestration) (job lifecycle)
                    │                │
                    └──── storage.py ┘
                        (JSON persistence)

routes.py ──(Flask Blueprint)──> app.py-injected queue/storage/lifecycle helpers
```

- **config.py** is the dependency root -- most other modules import constants from it (`elements.py` is the exception; it uses only locally-defined quality checks).
- **client.py** uses raw `urllib`, not `requests`, to avoid an external dependency.
- **routes.py**, **job_validation.py**, **queue.py**, and **worker.py** are used by `app.py` (Flask). `curate.py` calls `scoring.py` + `storage.py` directly.
- **models.py** defines the serializable data types shared by all modules.

### Core Abstractions

| Concept | Defined In | Description |
|---------|------------|-------------|
| `JobState` (enum) | `models.py` | 6 states: `QUEUED`, `RUNNING`, `CANCELLING`, `COMPLETED`, `FAILED`, `CANCELLED` |
| `ImageResult` | `models.py` | Per-image: filename, score, total elements, yes/no details, failed flag, moved_to |
| `CurationRun` | `models.py` | Full job: run_id, batch, elements, results list, totals, timestamps |
| `RunTotals` | `models.py` | Aggregate: images, scored, failed, moved counts |
| `QUALITY_CHECKS` (dict) | `elements.py` | Two baseline checks: "anatomy" and "artifacts" |
| `ELEMENT_PROMPT` (str) | `client.py` | LLM prompt template: "Check if each element is visible... answer YES or NO" |
| `ELEMENT_CAP` (12) | `config.py` | Maximum elements sent to the LLM |

## Constraints & Hard Rules

- **Never:** Call `_promote_next` without holding `_lock`. All public mutation methods (`submit`, `cancel`, `complete_job`, `fail_job`, `finalize_cancelled`) acquire the lock internally -- do not pre-acquire or you will deadlock.
- **Import ordering:** `load_dotenv()` must run before `ai_curate` imports -- see root `AGENTS.md` Gotchas for details.
- **Always:** Pass `cancel_check` callable into `score_images` so scoring loops are interruptible.
- **Always:** Use `RunStorage` for persistence -- never write run files directly.
- **Style:** All I/O-adjacent methods use `try/except` and return structured error results rather than raising exceptions.
- **Verification:** After changes in this directory, run:
  ```bash
  python -m pytest tests/unit/test_client.py tests/unit/test_scoring.py tests/unit/test_queue.py tests/unit/test_storage.py tests/unit/test_elements.py tests/unit/test_models.py tests/unit/test_config.py -v
  ```

## Key Files & Responsibilities

| File | Lines | Role |
|------|-------|------|
| `config.py` | 69 | Env-backed constants (`BATCHES_DIR`, `COMFYUI_OUTPUT`, `DEFAULT_BASE_URL`, `API_KEY`, `DEFAULT_TOP_N`=15, `TOP_N_CAP`=100, `ELEMENT_CAP`=12, `REQUEST_TIMEOUT`=120). Re-exports `IMAGE_EXTENSIONS` from `image_curator.batch_store`. |
| `models.py` | 217 | `JobState(str, Enum)`, `ImageResult` (with `__slots__`, `normalized_score` property, `to_dict`/`from_dict`), `RunTotals`, `CurationRun` (16-field run metadata + results). |
| `elements.py` | 145 | `extract_elements()` (auto-extraction from prompt text), `build_element_list()` (combine explicit + quality), `get_quality_elements()`, shot-type detection regexes. |
| `client.py` | 240 | `VisionClient` class: `encode_image()` (base64, 50 MB limit) + `score_image()` (full call cycle). Module-level: `build_score_payload()` (JSON payload builder), `parse_score_response()` (regex YES/NO parser). |
| `scoring.py` | 119 | `find_images()` (enumerate by extension), `build_scoring_prompt()` (fill template), `score_images()` (main loop with cancel check and progress callback). |
| `queue.py` | 371 | `QueueManager`: `submit`, `cancel`, `complete_job`, `fail_job`, `finalize_cancelled`, `prune`, `is_cancel_requested`, `_promote_next`. FIFO deque, single running job, thread-safe. |
| `storage.py` | 199 | `RunStorage`: `save_run`, `load_run`, `list_runs`, `load_latest`. Atomic writes (`.tmp` + `os.replace`), thread-safe via `RLock`, path-traversal validation. |
| `routes.py` | varies | `create_ai_curate_blueprint()` and `AiCurateRouteContext`; owns `/api/ai-curate/*` Flask routes while app lifecycle globals stay in `app.py`. |
| `job_validation.py` | varies | `validate_ai_curate_request()` validates Flask AI job payloads with injected app dependencies and preserves API error shapes. |
| `worker.py` | varies | `run_scoring_worker_inner()` orchestrates element expansion, image enumeration, scoring, cancellation, optional top-N moves, and queue completion with injected dependencies. |

## Agent Instructions

- Start with `config.py` to understand what env vars drive behavior, then trace the pipeline forward.
- When changing scoring logic: `elements.py` (what is checked) -> `client.py` (how the LLM is called) -> `scoring.py` (how results are collected).
- When changing Flask AI routes: `routes.py` plus the `AiCurateRouteContext` registration in `app.py`.
- When changing Flask AI job submission validation: `job_validation.py` plus the `_validate_ai_curate_request` wrapper in `app.py`.
- When changing Flask AI worker orchestration: `worker.py` plus the `_run_scoring_worker_inner` wrapper in `app.py`.
- When changing job lifecycle: `models.py` (state definitions) -> `queue.py` (state transitions) -> `storage.py` (persistence).
- The `QUALITY_CHECKS` dict (keys: "anatomy", "artifacts") is separate from `QUALITY_ELEMENTS` tuple for backward compat -- `build_element_list` uses the dict path for web UI, the tuple for CLI legacy.
- Cancelled runs are normally ephemeral (not persisted). The exception is partial-move audit trails (if files were moved before cancellation landed).

## Gotchas & Common Pitfalls

- **`ELEMENT_CAP` truncation is silent:** `scoring.py` line 82 caps elements at 12 with no warning logged. If the operator provides 15 elements, 3 are silently dropped.
- **`urllib`, not `requests`:** `client.py` uses `urllib.request.urlopen` directly. Do not add a `requests` import -- the dependency is intentionally avoided.
- **One retry only (client.py):** Transient errors (`URLError`, `socket.timeout`) are retried once. HTTP errors (4xx/5xx) are NOT retried -- a bad URL or API key should surface immediately.
- **Score < 0 means failed:** `ImageResult.score` defaults to -1. `normalized_score` also returns -1 for failed images. The frontend checks `score >= 0`.
- **Storage I/O happens outside the queue lock:** `complete_job` and `fail_job` call `save_run()` outside `self._lock` so disk writes don't block queue operations.
- **`QUALITY_ELEMENTS` tuple vs `QUALITY_CHECKS` dict:** The tuple is a flat list for CLI backward compatibility. The dict is keyed for web UI quality-flag selection. `build_element_list(quality_flags=None)` appends all quality elements (CLI path); `build_element_list(quality_flags=["anatomy"])` appends only selected checks (web UI path).
- **`latest.json` is a pointer, not the data:** It contains only `{"run_id": "..."}`. The full run data is in `runs/<run_id>.json`.

**Completion Standard:** For any task in this directory, include files changed, commands run (unit tests for the touched module), and any downstream impacts on `app.py` or `curate.py` callers.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
