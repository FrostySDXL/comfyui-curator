"""Create disposable local data for manual browser testing.

The fixture is intentionally stored under ``tmp/`` by default so it stays out
of real curation libraries and is already ignored by git.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, PngImagePlugin


BATCH_FOLDERS = ("inbox", "shortlisted", "finals", "rejects")
DEFAULT_ROOT = Path("tmp") / "local-browser-fixture"


@dataclass(frozen=True)
class FixtureResult:
    root: Path
    batches_dir: Path
    comfyui_dir: Path
    state_file: Path
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def env_lines(self, shell: str) -> list[str]:
        shell = shell.lower()
        if shell == "powershell":
            return [
                f'$env:IMAGE_CURATOR_BATCHES="{self.batches_dir}"',
                f'$env:IMAGE_CURATOR_COMFYUI="{self.comfyui_dir}"',
                f'$env:IMAGE_CURATOR_STATE="{self.state_file}"',
                '$env:IMAGE_CURATOR_ENABLE_WATCHER="false"',
                f'$env:IMAGE_CURATOR_HOST="{self.host}"',
                f'$env:IMAGE_CURATOR_PORT="{self.port}"',
            ]
        if shell == "cmd":
            return [
                f"set IMAGE_CURATOR_BATCHES={self.batches_dir}",
                f"set IMAGE_CURATOR_COMFYUI={self.comfyui_dir}",
                f"set IMAGE_CURATOR_STATE={self.state_file}",
                "set IMAGE_CURATOR_ENABLE_WATCHER=false",
                f"set IMAGE_CURATOR_HOST={self.host}",
                f"set IMAGE_CURATOR_PORT={self.port}",
            ]
        raise ValueError("shell must be 'powershell' or 'cmd'")


def _write_png(path: Path, color: tuple[int, int, int], prompt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("prompt", prompt)
    metadata.add_text("seed", "123456")
    image = Image.new("RGB", (640, 480), color=color)
    image.save(path, pnginfo=metadata)


def _create_batch_dirs(batches_dir: Path, batch_name: str) -> None:
    for folder in BATCH_FOLDERS:
        (batches_dir / batch_name / folder).mkdir(parents=True, exist_ok=True)


def create_fixture(root: Path, host: str = "127.0.0.1", port: int = 5000) -> FixtureResult:
    root = Path(root)
    batches_dir = root / "batches"
    comfyui_dir = root / "comfyui-outputs"
    state_file = root / "state.json"

    _create_batch_dirs(batches_dir, "manual-test")
    _create_batch_dirs(batches_dir, "second-batch")
    comfyui_dir.mkdir(parents=True, exist_ok=True)

    _write_png(
        batches_dir / "manual-test" / "inbox" / "portrait_a.png",
        (128, 80, 160),
        "studio portrait, blue jacket, soft rim light",
    )
    _write_png(
        batches_dir / "manual-test" / "inbox" / "landscape_b.png",
        (40, 130, 180),
        "wide cinematic landscape, mountains, sunrise",
    )
    _write_png(
        batches_dir / "manual-test" / "shortlisted" / "shortlisted_c.png",
        (70, 150, 90),
        "shortlisted test image, green lighting",
    )
    _write_png(
        batches_dir / "manual-test" / "finals" / "final_d.png",
        (200, 170, 70),
        "final selection test image, gold background",
    )
    _write_png(
        batches_dir / "second-batch" / "inbox" / "alternate_a.png",
        (180, 80, 80),
        "alternate batch image, red background",
    )
    _write_png(
        comfyui_dir / "pending_import.png",
        (90, 90, 90),
        "pending import image from fake comfyui output",
    )

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"active_batch": "manual-test"}), encoding="utf-8")

    return FixtureResult(
        root=root,
        batches_dir=batches_dir,
        comfyui_dir=comfyui_dir,
        state_file=state_file,
        host=host,
        port=port,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="Fixture root directory. Default: tmp/local-browser-fixture",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for the app launch command")
    parser.add_argument("--port", type=int, default=5000, help="Port for the app launch command")
    parser.add_argument(
        "--shell",
        choices=("powershell", "cmd"),
        default="powershell",
        help="Shell syntax to print for environment variables",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = create_fixture(args.root, host=args.host, port=args.port)

    print("Local browser fixture ready")
    print(f"- Fixture root: {result.root}")
    print(f"- Batches: {result.batches_dir}")
    print(f"- Fake ComfyUI output: {result.comfyui_dir}")
    print(f"- State file: {result.state_file}")
    print(f"- Browser URL: {result.url}")
    print("")
    print(f"Run these commands in {args.shell} before starting the app:")
    for line in result.env_lines(args.shell):
        print(line)
    print(".venv\\Scripts\\python.exe app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
