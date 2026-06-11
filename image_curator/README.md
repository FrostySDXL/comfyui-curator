# image_curator -- Guidance

**One-sentence purpose:** Shared non-AI backend support for batch filesystem operations and ComfyUI PNG generation metadata extraction.

**Role in the Project:** Called by `app.py` (Flask) and `curate.py` (CLI) for all filesystem-bound operations (batch creation, file moves, counts, import, state persistence) and PNG metadata inspection. Contains no AI logic.

## What This Module Does

- **Batch filesystem management** (`batch_store.py`): Creates batch folders, lists/enumerates images, moves files between workflow folders, imports from ComfyUI output, manages active-batch state file.
- **PNG metadata extraction** (`png_metadata.py`): Reads ComfyUI/A1111 PNG text chunks with Pillow, parses generation parameters (prompt, seed, sampler, CFG, LoRAs, etc.).

The two modules are independent -- neither imports the other.

## Key Concepts

### Callers and What They Use

```
app.py ──> batch_store (nearly all functions: create, list, move, counts, import, state)
       ──> png_metadata.extract_png_metadata (Flask route for metadata inspection)

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
- `.thumbs/` -- thumbnail cache (managed by `app.py`)
- `ai-curate/` -- AI run history (managed by `ai_curate/storage.py`)

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
- **Verification:** After changes in this directory, run:
  ```bash
  python -m pytest tests/unit/test_batch_store.py tests/unit/test_png_metadata.py -v
  python -m pytest tests/integration/test_image_metadata_api.py tests/integration/test_import_all_pending.py -v
  ```

## Key Files & Responsibilities

| File | Lines | Role |
|------|-------|------|
| `batch_store.py` | 280 | Batch filesystem ops: `create_batch`, `get_batches`, `get_batch_folder`, `get_images` (sortable by date/name/shuffle), `get_batch_counts`, `get_all_counts`, `get_batch_metadata`, `get_all_batch_metadata`, `get_pending_count`, `import_all_pending`, `move_image`, `move_images`, `load_state`/`save_state` (atomic JSON), `_validate_name` (path traversal guard), `_collision_safe_name` (dedup on import). |
| `png_metadata.py` | 153 | `extract_png_metadata(path)` -- opens PNG with Pillow, reads `image.text` dictionary, parses generation parameters. Top-level keys: `has_metadata`, `source`, `parameters` (nested dict with `prompt`, `negative_prompt`, `seed`, `steps`, `sampler`, `cfg_scale`, `width`/`height`, `model`, `model_hash`, `version`, `clip_skip`), `loras` (list of `{name, weight, hash}`), `raw_keys` (list of chunk key names), `raw_parameters`, `workflow_available`, `workflow_size`. Also exports `parse_parameters()` (public but currently unused externally). |

## Agent Instructions

- For filesystem work (batch creation, moves, imports, counts): read `batch_store.py`.
- For PNG metadata work (parameter extraction, LoRA parsing): read `png_metadata.py`.
- The two modules are fully independent -- knowing one does not require reading the other.
- `batch_store.get_images()` gracefully handles files deleted between `iterdir()` and `stat()` (catches `FileNotFoundError`/`OSError`).
- `batch_store.get_batch_metadata()` computes `modified_at` from directory mtimes only (not file mtimes). Hidden directories (`.` prefix) like `.thumbs/` are excluded, but `ai-curate/` is NOT hidden and its mtime IS included in the result.

## Gotchas & Common Pitfalls

- **`_collision_safe_name` has no locking:** If two processes import simultaneously, both could see `exists() == False` and one file would overwrite. Low risk for single-user operation.
- **LoRA hash is always `None`:** `_parse_loras()` hardcodes `"hash": None`. The field exists in the return schema but is never populated.
- **Workflow JSON is size-only:** `extract_png_metadata` returns `workflow_available: bool` and `workflow_size: int` but not the workflow JSON content itself. Callers needing the full workflow must re-read the file.
- **No delete operations in batch_store:** Reject cleanup (deleting files from `rejects/`) is handled directly in `app.py`, not via batch_store.
- **Thumbnail cache is NOT in this module:** Thumbnail generation and caching live in `app.py`. `batch_store` only provides the image listing that thumbnails are built from.
- **`get_batch_metadata` includes `ai-curate/` mtime:** The AI run-history directory's mtime contributes to batch `modified_at` for recent-first sorting, even though AI-curate is not a workflow folder.

**Completion Standard:** For any task in this directory, include files changed, commands run (unit tests for the touched module), and verification that callers in `app.py` or `curate.py` are not broken.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
