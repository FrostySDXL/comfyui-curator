"""Scoring worker orchestration for AI curation jobs.

The queue object passed to ``run_scoring_worker_inner`` must expose the app-facing
QueueManager methods used here: ``fail_job``, ``is_cancel_requested``,
``finalize_cancelled``, and ``complete_job``. The Flask lifecycle helpers that
remain in ``app.py`` also rely on ``submit``, ``list_jobs``, ``cancel``, and
``get_job``.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_curate.models import RunTotals


def run_scoring_worker_inner(
    *,
    run_id: str,
    run: Any,
    queue: Any,
    client: Any,
    build_element_list_func: Callable,
    get_batch_folder: Callable[[str, str], Path],
    find_images_func: Callable,
    score_images_func: Callable,
    move_image_func: Callable[[Path, Path], bool],
    logger: Any,
) -> None:
    """Execute scoring, optional moves, cancellation, and queue completion."""
    elements = build_element_list_func(run.elements, run.quality_flags)
    run.elements = elements

    image_dir = get_batch_folder(run.batch, run.source_folder)
    image_paths = find_images_func(image_dir)

    if not image_paths:
        queue.fail_job(run_id, error_message="No images found in source folder")
        return

    def cancel_check() -> bool:
        return queue.is_cancel_requested(run_id)

    progress_counter = {"scored": 0, "failed": 0}

    def on_progress(index, total, result) -> None:
        if result.failed:
            progress_counter["failed"] += 1
        else:
            progress_counter["scored"] += 1

    results, total_images = score_images_func(
        image_dir=image_dir,
        elements=elements,
        client=client,
        model=run.model,
        progress_callback=on_progress,
        cancel_check=cancel_check,
    )

    if queue.is_cancel_requested(run_id):
        queue.finalize_cancelled(run_id)
        return

    scored = [r for r in results if not r.failed]
    failed = [r for r in results if r.failed]

    moved = 0
    if run.move_enabled and run.destination_folder:
        if queue.is_cancel_requested(run_id):
            queue.finalize_cancelled(run_id)
            return

        scored.sort(key=lambda r: r.score, reverse=True)
        top_results = scored[: run.top_n]

        dest_dir = get_batch_folder(run.batch, run.destination_folder)
        dest_dir.mkdir(parents=True, exist_ok=True)

        for result in top_results:
            if queue.is_cancel_requested(run_id):
                break
            src_path = image_dir / result.filename
            dst_path = dest_dir / result.filename
            if move_image_func(src_path, dst_path):
                result.moved_to = str(dst_path)
                moved += 1
            else:
                logger.warning("AI curate move failed for %s", result.filename)

    totals = RunTotals(
        images=total_images,
        scored=len(scored),
        failed=len(failed),
        moved=moved,
    )

    if queue.is_cancel_requested(run_id):
        if moved > 0:
            queue.finalize_cancelled(run_id, results=results, totals=totals)
            return
        queue.finalize_cancelled(run_id)
        return

    if not queue.complete_job(run_id, results=results, totals=totals):
        queue.finalize_cancelled(run_id)
