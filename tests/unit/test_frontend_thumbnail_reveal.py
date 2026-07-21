import re
from pathlib import Path

from tests.unit.frontend_source import extract_function_body, read_frontend_js


def _rule_body(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert match, selector
    return match.group("body")


def test_thumbnail_reveal_separates_opacity_and_transform_timing() -> None:
    css = Path("static/css/grid.css").read_text(encoding="utf-8")
    image_rule = _rule_body(css, ".thumb img")

    assert "transition: opacity 0.8s ease-in-out, transform 0.4s ease-out;" in image_rule
    assert "opacity: 0;" in image_rule
    assert "transform: scale(0.97);" in image_rule
    assert "opacity: 1;" in _rule_body(css, ".thumb img.loaded")
    assert "transform: scale(1);" in _rule_body(css, ".thumb img.loaded")
    assert "transform: scale(1.04);" in _rule_body(css, ".thumb:hover img")


def test_reduced_motion_still_minimizes_thumbnail_transitions() -> None:
    css = Path("static/css/base.css").read_text(encoding="utf-8")
    reduced_motion = re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(?P<body>.*)\}\s*$",
        css,
        re.DOTALL,
    )

    assert reduced_motion
    assert "*, *::before, *::after" in reduced_motion.group("body")
    assert "transition-duration: 0.01ms !important;" in reduced_motion.group("body")


def test_retained_thumbnail_lifecycle_never_resets_loaded_state() -> None:
    js = read_frontend_js()
    update_thumb = extract_function_body(js, "function updateThumbElement(thumb, img, index)")
    update_grid = extract_function_body(js, "function updateGrid()")
    set_density = extract_function_body(js, "function setGridDensity(density)")

    assert "classList.remove('loaded')" not in js
    assert "imageEl.dataset.thumbnailCacheKey !== thumbnailCacheKey" in update_thumb
    assert "gridThumbMap.get(img.name)" in update_grid
    assert "createThumbElement()" in update_grid
    assert "loaded" not in set_density
