"""Validation helpers for AI curation web job submissions."""

from collections.abc import Callable


def validate_ai_curate_request(
    data: dict,
    *,
    get_batches: Callable[[], list[str]],
    default_model: str,
    default_top_n: int,
    top_n_cap: int,
    element_cap: int,
    allowed_source_folders: set[str],
    allowed_dest_folders: set[str],
) -> tuple[dict | None, tuple[dict[str, str], int] | None]:
    """Validate an AI curation job submission payload."""
    batch_value = data.get("batch", "")
    if not isinstance(batch_value, str):
        return None, ({"error": "batch must be a string"}, 400)
    batch = batch_value.strip()
    if not batch:
        return None, ({"error": "batch is required"}, 400)
    if batch not in get_batches():
        return None, ({"error": f"batch '{batch}' does not exist"}, 400)

    prompt_value = data.get("prompt", "")
    if not isinstance(prompt_value, str):
        return None, ({"error": "prompt must be a string"}, 400)
    prompt = prompt_value.strip()

    source_folder = data.get("source_folder", "inbox")
    if not isinstance(source_folder, str):
        return None, ({"error": "source_folder must be a string"}, 400)
    if source_folder not in allowed_source_folders:
        return None, (
            {"error": f"source_folder must be one of {sorted(allowed_source_folders)}"},
            400,
        )

    elements = data.get("elements")
    if not elements or not isinstance(elements, list) or not any(elements):
        return None, ({"error": "elements is required (at least one element)"}, 400)
    if len(elements) > element_cap:
        return None, ({"error": f"too many elements (max {element_cap})"}, 400)
    elements = [str(e).strip() for e in elements if str(e).strip()]
    if not elements:
        return None, ({"error": "elements must contain at least one non-empty entry"}, 400)

    quality_flags = data.get("quality_flags")
    if quality_flags is not None and not isinstance(quality_flags, list):
        return None, ({"error": "quality_flags must be a list of strings"}, 400)

    top_n = data.get("top_n", default_top_n)
    try:
        top_n = int(top_n)
    except (ValueError, TypeError):
        return None, ({"error": "top_n must be an integer"}, 400)
    if top_n < 1 or top_n > top_n_cap:
        return None, ({"error": f"top_n must be between 1 and {top_n_cap}"}, 400)

    move_enabled = bool(data.get("move_enabled", False))
    destination_folder = data.get("destination_folder")
    if destination_folder is not None and not isinstance(destination_folder, str):
        return None, ({"error": "destination_folder must be a string"}, 400)
    if move_enabled:
        if not destination_folder or destination_folder not in allowed_dest_folders:
            return None, (
                {
                    "error": f"destination_folder is required when move_enabled and must be one of {sorted(allowed_dest_folders)}"
                },
                400,
            )

    supplied_model = data.get("model")
    if supplied_model is not None and not isinstance(supplied_model, str):
        return None, ({"error": "model must be a string"}, 400)
    model_value = supplied_model or default_model or ""
    if not isinstance(model_value, str):
        return None, ({"error": "model must be a string"}, 400)
    model = model_value.strip()
    if not model:
        return None, (
            {"error": "model is required — set IMAGE_CURATOR_MODEL or pass model in request"},
            400,
        )

    params = {
        "batch": batch,
        "prompt": prompt,
        "source_folder": source_folder,
        "elements": elements,
        "quality_flags": quality_flags,
        "top_n": top_n,
        "move_enabled": move_enabled,
        "destination_folder": destination_folder if move_enabled else None,
        "model": model,
    }
    return params, None
