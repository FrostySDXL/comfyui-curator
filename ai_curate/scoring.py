"""
ai_curate.scoring -- Scoring orchestration for AI curation.

Coordinates element extraction, image enumeration, and vision model
scoring into a coherent scoring pipeline.
"""

from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ai_curate.client import VisionClient, ELEMENT_PROMPT
from ai_curate.config import IMAGE_EXTENSIONS
from ai_curate.models import ImageResult


def find_images(directory: Path) -> List[Path]:
    """Find all image files in a directory, sorted by name.

    Args:
        directory: Path to the image directory.

    Returns:
        Sorted list of image Path objects.
    """
    if not directory.is_dir():
        return []
    return sorted(
        [f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    )


def build_scoring_prompt(elements: List[str]) -> str:
    """Build the numbered element prompt text for the vision model.

    Args:
        elements: List of element strings to check.

    Returns:
        Formatted prompt text with numbered elements.

    Raises:
        ValueError: If ``elements`` is empty. An empty list would expand the
            template to a prompt with no numbered lines, and the response
            parser would silently reject every YES/NO answer, so we fail
            fast at the call site instead.
    """
    if not elements:
        raise ValueError("build_scoring_prompt: elements list is empty")
    numbered = "\n".join(
        f"{i + 1}. {e.replace('{', '{{').replace('}', '}}')}" for i, e in enumerate(elements)
    )
    return ELEMENT_PROMPT.format(elements=numbered)


def score_images(
    image_dir: Path,
    elements: List[str],
    client: VisionClient,
    model: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, ImageResult], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[List[ImageResult], int]:
    """Score all images in a directory against the given elements.

    Args:
        image_dir: Directory containing images to score.
        elements: Element strings to check.
        client: VisionClient for model communication.
        model: Optional model override.
        progress_callback: Called after each image with (index, total, result).
        cancel_check: Called before each image; if returns True, stop scoring.

    Returns:
        Tuple of (list of ImageResult, count of images scored before cancellation).
    """
    images = find_images(image_dir)
    from ai_curate.config import ELEMENT_CAP

    if not elements:
        raise ValueError("score_images: elements list is empty")
    if len(elements) > ELEMENT_CAP:
        elements = elements[:ELEMENT_CAP]
    prompt_text = build_scoring_prompt(elements)
    results: List[ImageResult] = []

    for i, img_path in enumerate(images):
        if cancel_check and cancel_check():
            break

        try:
            image_b64 = VisionClient.encode_image(str(img_path))
            content_type = VisionClient.content_type_for(str(img_path))
            score, total, details, err = client.score_image(
                image_b64=image_b64,
                prompt_text=prompt_text,
                elements=elements,
                model=model,
                content_type=content_type,
            )
            result = ImageResult(
                filename=img_path.name,
                score=score,
                total=total,
                details=details,
                failed=(score < 0),
                error_message=err,
            )
        except (OSError, ValueError) as e:
            result = ImageResult(
                filename=img_path.name,
                failed=True,
                error_message=str(e),
            )

        results.append(result)
        if progress_callback:
            progress_callback(i, len(images), result)

    return results, len(results)
