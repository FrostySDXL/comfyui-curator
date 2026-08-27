"""Generate and validate the native ComfyUI template from the Flask template."""

from __future__ import annotations

import argparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "templates" / "index.html"
OUTPUT_PATH = REPO_ROOT / "templates" / "curator.html"
NATIVE_MARKER = "<script>window.CURATOR_NATIVE = true;</script>"


def transform(source: str) -> str:
    """Apply the two deterministic transforms used by the native template."""
    if NATIVE_MARKER in source:
        raise ValueError("source template already contains the native mode marker")
    source = source.replace("/static/", "/curator_static/")
    first_script = source.find('<script src="')
    if first_script < 0:
        raise ValueError('source template has no ordered script tag (<script src=")')
    return source[:first_script] + NATIVE_MARKER + "\n    " + source[first_script:]


def check(source_path: Path = SOURCE_PATH, output_path: Path = OUTPUT_PATH) -> bool:
    """Check generated output without writing either file."""
    if not source_path.is_file():
        print(
            f"Template generation check failed: source missing: {source_path}; "
            "run python scripts/generate_curator_template.py --write"
        )
        return False
    if not output_path.is_file():
        print(
            f"Template generation check failed: output missing: {output_path}; "
            "run python scripts/generate_curator_template.py --write"
        )
        return False
    try:
        expected = transform(source_path.read_text(encoding="utf-8"))
        actual = output_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Template generation check failed: {exc}")
        return False
    if actual != expected:
        print(
            "Template generation check failed: output stale: "
            f"{output_path}; run python scripts/generate_curator_template.py --write"
        )
        return False
    print("Template generation check passed")
    return True


def write(source_path: Path = SOURCE_PATH, output_path: Path = OUTPUT_PATH) -> bool:
    """Write generated output only when bytes differ; return whether it changed."""
    generated = transform(source_path.read_text(encoding="utf-8"))
    if output_path.is_file():
        try:
            if output_path.read_bytes() == generated.encode("utf-8"):
                return False
        except OSError:
            pass
    output_path.write_bytes(generated.encode("utf-8"))
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="Validate output without writing")
    modes.add_argument("--write", action="store_true", help="Write the generated output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check:
        return 0 if check() else 1
    try:
        changed = write()
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Template generation failed: {exc}")
        return 1
    print(f"Generated {OUTPUT_PATH}" if changed else f"Already current: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
