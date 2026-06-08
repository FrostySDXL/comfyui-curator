"""
ai_curate.elements -- Extract and manage visual scoring elements from prompts.

Moved from curate.py. Renames manga-specific terminology:
  - "panel" -> "prompt" (the function still works with panel-style input)
  - Quality elements are configurable defaults, not hardcoded assumptions.
"""

import re
from typing import Dict, List, Optional

# Named optional elements that operators can toggle per-run.
# Keys are stable identifiers; values are the full element text
# sent to the scoring model.  The UI surfaces these as checkboxes
# so operators choose which (if any) apply to this run.
QUALITY_CHECKS: Dict[str, str] = {
    "anatomy": "Clean anatomy (no extra fingers, extra limbs, or broken body parts)",
    "artifacts": "No visual artifacts, glitches, or garbled text",
}

# Legacy: all quality elements as a flat tuple.
# Used by the CLI (curate.py) and for backward-compatible
# build_element_list() calls that omit quality_flags.
QUALITY_ELEMENTS: tuple[str, ...] = tuple(QUALITY_CHECKS.values())

# Shot-type detection patterns (order matters: longest match first)
_SHOT_TYPES = [
    ("extreme close-up", "Extreme close-up framing"),
    ("close-up", "Close-up framing (face/detail focused)"),
    ("wide shot", "Wide shot framing (full scene visible)"),
    ("medium shot", "Medium shot framing (waist-up)"),
    ("low angle", "Low angle camera perspective"),
    ("high angle", "High angle camera perspective"),
    ("bird's eye", "Bird's eye view perspective"),
    ("over-the-shoulder", "Over-the-shoulder framing"),
]

# Delimiters for splitting prompt text into fragments.
# Comma splitting uses \s{2,} (two+ spaces) to avoid fragmenting
# noun phrases like "tall, dark-haired warrior".
_FRAGMENT_DELIMITERS = re.compile(
    r"\s*[-\u2013]\s+|\s*,\s{2,}|\s+with\s+|\s+and\s+|\s+adorned\s+with\s+|\s+dressed\s+in\s+"
)

# Leading articles and pronouns to strip
_ARTICLE_PATTERN = re.compile(r"^(a|an|the|she|he|they|her|his|their)\s+", re.IGNORECASE)

# Fragments that are just pronouns/connectors (drop these)
_NOISE_FRAGMENTS = frozenset(
    {"she", "he", "they", "it", "the", "a", "an", "is", "are", "is dressed in"}
)

# Shot-type prefix pattern for stripping
_SHOT_PREFIX_PATTERN = re.compile(
    r"^(wide|medium|close[- ]?up|extreme|low|high|bird|over)[^\-\u2013]*[\-\u2013]\s*",
    re.IGNORECASE,
)


def get_quality_elements(selected_keys: Optional[List[str]] = None) -> List[str]:
    """Return quality element strings for the named checkboxes selected.

    Args:
        selected_keys: List of QUALITY_CHECKS keys to include,
            or None/empty list for none.

    Returns:
        List of element strings (may be empty).
    """
    if not selected_keys:
        return []
    return [QUALITY_CHECKS[k] for k in selected_keys if k in QUALITY_CHECKS]


def extract_elements(prompt: str) -> List[str]:
    """Extract visual elements from a prompt description.

    Works with both general image prompts and legacy manga panel descriptions.
    Always appends QUALITY_ELEMENTS at the end.

    Args:
        prompt: Free-text description of the desired image content.

    Returns:
        List of element strings to score against.
    """
    if not prompt or not prompt.strip():
        return list(QUALITY_ELEMENTS)

    elements: List[str] = []

    # Detect shot type
    desc_lower = prompt.lower()
    for shot_key, shot_element in _SHOT_TYPES:
        if re.search(rf"\b{re.escape(shot_key)}\b", desc_lower):
            elements.append(shot_element)
            break

    # Strip shot-type prefix from the remaining text
    clean = _SHOT_PREFIX_PATTERN.sub("", prompt).strip()

    # Split on sentence boundaries first
    sentences = re.split(r"\.\s+", clean)

    for sentence in sentences:
        fragments = _FRAGMENT_DELIMITERS.split(sentence)
        for frag in fragments:
            frag = frag.strip().rstrip(".")
            # Strip leading articles/pronouns
            frag = _ARTICLE_PATTERN.sub("", frag).strip()
            if len(frag) < 3:
                continue
            if frag.lower() in _NOISE_FRAGMENTS:
                continue
            elements.append(frag)

    # Append quality baseline
    elements.extend(QUALITY_ELEMENTS)

    return elements


def build_element_list(
    explicit_elements: List[str],
    quality_flags: Optional[List[str]] = None,
) -> List[str]:
    """Build a scoring element list from explicit user-provided elements.

    When *quality_flags* is None (the default for CLI backward compat),
    ALL quality elements are appended.  When *quality_flags* is an
    explicit list (from the web UI), only the named checks are appended.

    Args:
        explicit_elements: User-supplied element strings.
        quality_flags: QUALITY_CHECKS keys to include, or None for all.

    Returns:
        Combined list of user elements plus selected quality elements.
    """
    result = list(explicit_elements)
    if quality_flags is None:
        result.extend(QUALITY_ELEMENTS)
    else:
        result.extend(get_quality_elements(quality_flags))
    return result
