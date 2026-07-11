# image_curator -- Guidance

**One-sentence purpose:** Shared non-AI backend support for batch filesystem operations, web validation, media cache helpers, and ComfyUI PNG generation metadata extraction.

**Role in the Project:** Called by `app.py` (Flask) and `curate.py` (CLI) for filesystem-bound operations (batch creation, file moves, counts, import, state persistence), PNG metadata inspection, non-AI web validation, and thumbnail cache helpers. Contains no AI logic.

## What This Module Does

- **Batch filesystem management** (`batch_store.py`): Creates batch folders, lists/enumerates images, moves files between workflow folders, imports from ComfyUI output, manages active-batch state file.
- **PNG metadata extraction** (`png_metadata.py`): Reads ComfyUI/A1111 PNG text chunks with Pillow, parses generation parameters (prompt, seed, sampler, CFG, LoRAs, etc.).
- **Favorites persistence** (`favorites.py`): Stores batch-scoped and universal favorite image records with atomic JSON writes.
- **Public derivative workflow** (`publish.py`): Creates metadata-stripped optional-watermark copies under `<batch>/public/`, lists public images, and copy/move/delete generated public copies under a configured export root.
- **Prompt history indexing** (`prompt_history.py`): Builds manual prompt indexes from PNG metadata, deduplicated by normalized prompt/negative prompt. Safety: rejects symlinked review stages and resolves-containment escapes during build/count; rejects symlinked and non-regular cache entries during load; aggregate loading silently omits batches with unsafe caches.
- **Web validation** (`web_validation.py`): Path traversal guard and existing-batch validation helpers used by Flask route wrappers.
- **Media cache helpers** (`media.py`): Thumbnail cache path/freshness checks and WebP thumbnail generation.
- **Native ComfyUI foundation** (`native_settings.py`, `native_routes.py`): Host-owned path resolution plus namespaced aiohttp adapters for batch/image reads, state, import, metadata, media serving, moves, reject deletion, favorites, public workflows, and prompt-history build/load/staleness/aggregate operations.

Modules are responsibility-scoped; keep AI-specific validation and worker orchestration in `ai_curate/`.

## Key Concepts

### Callers and What They Use

```
app.py ──> batch_store (nearly all functions: create, list, move, counts, import, state)
       ──> png_metadata.extract_png_metadata (Flask route for metadata inspection)
       ──> favorites (favorite toggles, batch filter data, universal favorites)
       ──> publish (public derivative export/list/copy/move/delete routes)
       ──> prompt_history (manual prompt index build/load routes)
       ──> web_validation (safe path and existing-batch route wrappers)
       ──> media (thumbnail cache/generation helpers)

curate.py ──> batch_store.move_image (single-file moves in --move mode)

ai_curate/config.py ──> batch_store.IMAGE_EXTENSIONS (re-exported to avoid duplication)
```

### Batch Layout (batch_store.py)

Each batch is a directory under `BATCHES_DIR/<batch_name>/` containing four workflow folders:
- `inbox/` -- new/imported images awaiting review
- `shortlisted/` -- operator-kept images
- `finals/` -- operator-finalized images
- `rejects/` -- operator-rejected images

Additional runtime directories (NOT managed by batch_store):
- `.thumbs/` -- thumbnail cache (route lives in `app.py`; cache path/generation helpers live in `media.py`)
- `ai-curate/` -- AI run history (managed by `ai_curate/storage.py`)
- `.favorites.json` -- batch favorites; root-level `.favorites.json` stores universal favorites
- `prompt-history.json` -- manual PNG prompt-history cache per batch
- `public/` -- generated posting derivatives; originals remain in review folders

### Supported Image Extensions

`.png`, `.jpg`, `.jpeg`, `.webp` -- defined in `IMAGE_EXTENSIONS` set (line 17 of batch_store.py).

### State File

Location: `IMAGE_CURATOR_STATE` env var, default `~/.config/image-curator/state.json`.
Format: JSON object. Default: `{"active_batch": null}`.
Written atomically via `.tmp` + `os.replace()`.

## Constraints & Hard Rules

- **Never:** Change `BATCH_FOLDERS` tuple or `IMAGE_EXTENSIONS` set without updating all consumers (app.py, curate.py, ai_curate/config.py, tests).
- **Always:** Use `_validate_name()` before accepting user-supplied batch or file names -- it blocks path traversal (null bytes, `/`, `\`, `.`, `..`, leading dot).
- **Always:** Use `move_image()` for file moves -- it creates destination directories and never raises OSError to callers.
- **Favorites:** Tracking is filename-based within each batch; duplicate filenames across folders are resolved by scanning the standard folders.
- **Prompt history:** Cache builds are manual and synchronous; moving files between folders does not by itself make count-based staleness detection fire.
- **Verification:** After changes in this directory, run:
  ```bash
  python -m pytest tests/unit/test_batch_store.py tests/unit/test_png_metadata.py -v
  python -m pytest tests/integration/test_image_metadata_api.py tests/integration/test_import_all_pending.py -v
  ```

## Key Files & Responsibilities

| File | Role |
|------|------|
| `batch_store.py` | Batch filesystem ops: `create_batch`, `get_batches`, `get_batch_folder`, `get_images` (sortable by date/name/shuffle), `get_batch_counts`, `get_all_counts`, `get_batch_metadata`, `get_all_batch_metadata`, `get_pending_count`, `import_all_pending`, `move_image`, `move_images`, `load_state`/`save_state` (atomic JSON), `_validate_name` (path traversal guard), `_collision_safe_name` (dedup on import). |
| `png_metadata.py` | `extract_png_metadata(path)` -- opens PNG with Pillow, reads `image.text` dictionary, parses generation parameters. Top-level keys: `has_metadata`, `source`, `parameters` (nested dict with `prompt`, `negative_prompt`, `seed`, `steps`, `sampler`, `cfg_scale`, `width`/`height`, `model`, `model_hash`, `version`, `clip_skip`), `loras` (list of `{name, weight, hash}`), `raw_keys` (list of chunk key names), `raw_parameters`, `workflow_available`, `workflow_size`. Also exports `parse_parameters()` (public but currently unused externally). |
| `favorites.py` | `load_favorites`, `save_favorites`, `toggle_favorite`, `get_batch_favorite_filenames`, `resolve_universal_favorites`; uses `_validate_name`, `RLock`, and atomic `.tmp` replacement. |
| `publish.py` | `create_public_copies`, `list_batch_public`, `list_all_public`, `copy_public_items`, `move_public_items`, `delete_public_items`; strips metadata by re-saving with Pillow, applies text watermarks, and confines external destinations to `IMAGE_CURATOR_PUBLIC_EXPORTS`. |
| `prompt_history.py` | `build_prompt_index`, `load_prompt_index`, `load_all_prompt_indices`; scans PNG metadata, strips LoRA tags with `png_metadata.LORA_RE`, hashes normalized prompt pairs, and writes `prompt-history.json` atomically. |
| `web_validation.py` | `safe_path(base, *parts)` blocks traversal/absolute path escape; `require_existing_batch()` validates app-provided batch lists while preserving Flask route response shape. |
| `media.py` | `thumbnail_cache_path()`, `thumbnail_is_fresh()`, and `generate_thumbnail()` for WebP thumbnail cache semantics. |
| `native_settings.py` | Resolves native batch/import/state paths from injected ComfyUI `folder_paths` callables and exposes only non-secret model/UI settings. |
| `native_routes.py` | Registers the native settings, batch/state/import, image-list, metadata, thumbnail, original-image, move, delete-rejects, favorites, public, and prompt-history aiohttp contracts while reusing this package's filesystem helpers. |
| `native_ai_routes.py` | Registers namespaced native AI preview, submit, status, cancellation, run-history, latest-run, and element-history aiohttp contracts using `ai_curate.native_lifecycle.NativeAiLifecycle`. |

## Agent Instructions

- For filesystem work (batch creation, moves, imports, counts): read `batch_store.py`.
- For route path or existing-batch validation: read `web_validation.py` and the app-level wrappers in `app.py`.
- For thumbnail cache/generation behavior: read `media.py` and the `serve_thumbnail` route in `app.py`.
- For PNG metadata work (parameter extraction, LoRA parsing): read `png_metadata.py`.
- `batch_store.get_images()` gracefully handles files deleted between `iterdir()` and `stat()` (catches `FileNotFoundError`/`OSError`).
- `batch_store.get_batch_metadata()` computes `modified_at` from directory mtimes only (not file mtimes). Hidden directories (`.` prefix) like `.thumbs/` are excluded, but `ai-curate/` is NOT hidden and its mtime IS included in the result.

## Gotchas & Common Pitfalls

- **`_collision_safe_name` has no locking:** If two processes import simultaneously, both could see `exists() == False` and one file would overwrite. Low risk for single-user operation.
- **LoRA hash is always `None`:** `_parse_loras()` hardcodes `"hash": None`. The field exists in the return schema but is never populated.
- **Workflow JSON is size-only:** `extract_png_metadata` returns `workflow_available: bool` and `workflow_size: int` but not the workflow JSON content itself. Callers needing the full workflow must re-read the file.
- **No delete operations in batch_store:** Reject cleanup (deleting files from `rejects/`) is handled in `app.py` and `native_routes.py`, not via batch_store.
- **Thumbnail routes still live in `app.py`:** Thumbnail cache path/freshness/generation helpers live in `media.py`. `batch_store` only provides image listing and file moves.
- **`get_batch_metadata` includes `ai-curate/` mtime:** The AI run-history directory's mtime contributes to batch `modified_at` for recent-first sorting, even though AI-curate is not a workflow folder.

**Completion Standard:** For any task in this directory, include files changed, commands run (unit tests for the touched module), and verification that callers in `app.py` or `curate.py` are not broken.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
