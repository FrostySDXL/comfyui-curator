#!/usr/bin/env python3
"""
curate.py - Vision LLM image curation CLI.

Thin compatibility entrypoint that delegates to the shared ai_curate
backend modules. Replaces the previous Ollama-specific implementation
with llama-swap-compatible scoring.

Usage:
    curate --prompt "wide shot of girl on rooftop at night" --batch scene1
    curate --prompt "close-up of her eyes" --batch scene2 --top 10
    curate --prompt "..." --batch name --move --dest shortlisted

Legacy alias:
    --panel is accepted as an alias for --prompt (deprecated)
"""

from dotenv import load_dotenv

load_dotenv()

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from ai_curate.config import BATCHES_DIR, DEFAULT_MODEL, DEFAULT_TOP_N, TOP_N_CAP, ELEMENT_CAP
from ai_curate.config import ALLOWED_SOURCE_FOLDERS, ALLOWED_DEST_FOLDERS
from ai_curate.elements import extract_elements, build_element_list
from ai_curate.client import VisionClient
from ai_curate.scoring import score_images, find_images
from ai_curate.storage import RunStorage
from ai_curate.models import CurationRun, RunTotals, JobState
from image_curator.batch_store import move_image


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score images against visual elements using a vision model."
    )
    parser.add_argument(
        "--prompt",
        required=False,
        default=None,
        help="Prompt description to evaluate against",
    )
    parser.add_argument(
        "--panel",
        required=False,
        default=None,
        help="(legacy alias for --prompt) Panel description to evaluate against",
    )
    parser.add_argument("--batch", required=True, help="Image Curator batch name")
    parser.add_argument("--images", default=None, help="Image directory (default: batch inbox)")
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Number of top images to shortlist (default: {DEFAULT_TOP_N})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Vision model alias (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--elements",
        default=None,
        help="Comma-separated elements to check (overrides auto-extraction)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show extracted elements and exit without scoring",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Move top-scoring images to destination folder after scoring",
    )
    parser.add_argument(
        "--dest",
        default="shortlisted",
        help="Destination folder for move mode (default: shortlisted)",
    )
    parser.add_argument(
        "--source",
        default="inbox",
        help="Source folder within the batch (default: inbox)",
    )
    args = parser.parse_args()

    # Validate batch name to prevent path traversal
    batch = args.batch.strip()
    if not batch:
        parser.error("--batch is required")
    if "\0" in batch or "/" in batch or "\\" in batch:
        parser.error(
            f"Invalid --batch value '{args.batch}': batch name must not contain "
            "path separators or null bytes"
        )
    if batch in (".", "..") or batch.startswith("."):
        parser.error(f"Invalid --batch value '{args.batch}': batch name is a reserved name")

    # Resolve prompt (support legacy --panel alias)
    prompt = args.prompt or args.panel
    if not prompt:
        parser.error("--prompt is required")

    if args.panel and not args.prompt:
        print("NOTE: --panel is deprecated, use --prompt instead", file=sys.stderr)

    # Validate source and destination folders
    if args.source not in ALLOWED_SOURCE_FOLDERS:
        parser.error(
            f"Invalid source folder '{args.source}'. "
            f"Must be one of: {', '.join(sorted(ALLOWED_SOURCE_FOLDERS))}"
        )
    if args.move and args.dest not in ALLOWED_DEST_FOLDERS:
        parser.error(
            f"Invalid destination folder '{args.dest}'. "
            f"Must be one of: {', '.join(sorted(ALLOWED_DEST_FOLDERS))}"
        )
    if args.move and args.source == args.dest:
        parser.error(
            f"Source and destination folders are both '{args.source}'. "
            "Moving to the same folder is a no-op."
        )

    # Cap top_n
    top_n = min(max(1, args.top), TOP_N_CAP)

    # Extract or parse elements
    if args.elements:
        elements = build_element_list([e.strip() for e in args.elements.split(",") if e.strip()])
    else:
        elements = extract_elements(prompt)

    # Cap elements
    if len(elements) > ELEMENT_CAP:
        print(f"Warning: capping elements from {len(elements)} to {ELEMENT_CAP}", file=sys.stderr)
        elements = elements[:ELEMENT_CAP]

    # Show elements
    print("Checking elements:", file=sys.stderr)
    for i, e in enumerate(elements, 1):
        print(f"  {i}. {e}", file=sys.stderr)
    print(file=sys.stderr)

    if args.dry_run:
        print("Dry run -- exiting without scoring.", file=sys.stderr)
        return

    # Validate model (after dry-run so dry-run works without a model)
    if not args.model:
        parser.error(
            "No model configured. Set IMAGE_CURATOR_MODEL environment variable "
            "or pass --model explicitly. See .env.example for details."
        )

    # Default images dir: batch source folder
    images_dir = args.images or str(BATCHES_DIR / batch / args.source)
    image_dir_path = Path(images_dir)

    # Find images
    images = find_images(image_dir_path)
    if not images:
        print(f"No images found in {images_dir}", file=sys.stderr)
        run = CurationRun(
            batch=batch,
            source_folder=args.source,
            destination_folder=args.dest if args.move else None,
            move_enabled=args.move,
            prompt=prompt,
            elements=elements,
            model=args.model,
            top_n=top_n,
            status=JobState.FAILED,
            error_message=f"No images found in {images_dir}",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        storage = RunStorage()
        storage.save_run(run)
        sys.exit(1)

    print(f"Scoring {len(images)} images with {args.model}...", file=sys.stderr)
    print(file=sys.stderr)

    # Score using the shared client
    client = VisionClient(model=args.model)

    def on_progress(index, total, result):
        if result.failed:
            print(f"[{index + 1}/{total}] {result.filename}  FAILED", file=sys.stderr)
        else:
            print(
                f"[{index + 1}/{total}] {result.filename}  {result.score}/{result.total}",
                file=sys.stderr,
            )

    results, total_images = score_images(
        image_dir=image_dir_path,
        elements=elements,
        client=client,
        model=args.model,
        progress_callback=on_progress,
    )

    # Filter and rank
    scored = [r for r in results if not r.failed]
    scored.sort(key=lambda r: r.score, reverse=True)
    failed = [r for r in results if r.failed]

    # Move phase (only if --move)
    moved = 0
    if args.move:
        shortlist = scored[:top_n]
        dest_dir = Path(BATCHES_DIR) / batch / args.dest
        dest_dir.mkdir(parents=True, exist_ok=True)

        for r in shortlist:
            src_path = image_dir_path / r.filename
            dst_path = dest_dir / r.filename
            if move_image(src_path, dst_path):
                r.moved_to = str(dst_path)
                moved += 1
            else:
                print(f"WARNING: Could not move {r.filename}", file=sys.stderr)

    # Save run history via shared storage
    run = CurationRun(
        batch=args.batch,
        source_folder=args.source,
        destination_folder=args.dest if args.move else None,
        move_enabled=args.move,
        prompt=prompt,
        elements=elements,
        model=args.model,
        top_n=top_n,
        status=JobState.COMPLETED,
        results=results,
        totals=RunTotals(
            images=total_images,
            scored=len(scored),
            failed=len(failed),
            moved=moved,
        ),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )

    storage = RunStorage()
    storage.save_run(run)

    # Print summary
    print(file=sys.stderr)
    print("--- Results ---", file=sys.stderr)
    print(
        f"Total: {total_images} | Scored: {len(scored)} | Failed: {len(failed)} | Moved: {moved}",
        file=sys.stderr,
    )
    if args.move:
        dest_dir = Path(BATCHES_DIR) / batch / args.dest
        print(f"Moved to: {dest_dir}", file=sys.stderr)
    print(f"Run ID: {run.run_id}", file=sys.stderr)

    if scored:
        print(file=sys.stderr)
        print(f"Top 5 (of {len(elements)} elements):", file=sys.stderr)
        for r in scored[:5]:
            missing = []
            for idx in range(1, len(elements) + 1):
                if r.details.get(idx) == "NO":
                    missing.append(elements[idx - 1])
            missing_str = (
                f"  missing: {', '.join(missing)}" if missing else "  all elements present"
            )
            print(f"  {r.filename}  {r.score}/{r.total}{missing_str}", file=sys.stderr)


if __name__ == "__main__":
    main()
