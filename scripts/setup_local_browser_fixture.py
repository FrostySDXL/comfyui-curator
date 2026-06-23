"""Create disposable local data for manual browser testing.

The fixture is intentionally stored under ``tmp/`` by default so it stays out
of real curation libraries and is already ignored by git.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, PngImagePlugin


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


def _parameters_text(
    prompt: str,
    *,
    negative_prompt: str = "extra fingers, warped hands, low detail, watermark",
    seed: int = 123456,
    steps: int = 28,
    sampler: str = "DPM++ 2M SDE Karras",
    cfg_scale: float = 6.5,
    size: tuple[int, int] = (640, 480),
    model: str = "fixture-vision-sdxl",
) -> str:
    return (
        f"{prompt}\n"
        f"Negative prompt: {negative_prompt}\n"
        f"Steps: {steps}, Sampler: {sampler}, CFG scale: {cfg_scale}, Seed: {seed}, "
        f"Size: {size[0]}x{size[1]}, Model hash: FIXTURE42, Model: {model}, "
        "Clip skip: 2, Version: local-browser-fixture"
    )


def _write_png(
    path: Path,
    color: tuple[int, int, int],
    prompt: str,
    *,
    label: str | None = None,
    seed: int = 123456,
    size: tuple[int, int] = (640, 480),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("parameters", _parameters_text(prompt, seed=seed, size=size))
    metadata.add_text(
        "prompt",
        json.dumps(
            {
                "fixture": True,
                "seed": seed,
                "positive": prompt,
                "notes": "Synthetic local browser fixture metadata.",
            }
        ),
    )
    metadata.add_text(
        "workflow",
        json.dumps({"nodes": [{"type": "FixturePrompt", "prompt": prompt}], "seed": seed}),
    )
    image = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(image)
    title = label or path.stem.replace("_", " ")
    draw.rectangle((16, 16, min(size[0] - 16, 420), 78), fill=(12, 14, 18))
    draw.text((28, 30), title[:42], fill=(236, 240, 245))
    draw.text((28, 52), f"seed {seed}", fill=(154, 166, 180))
    image.save(path, pnginfo=metadata)


def _write_public_png(path: Path, color: tuple[int, int, int], label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (512, 512), color=color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 420, 512, 512), fill=(15, 17, 22))
    draw.text((28, 448), label[:46], fill=(238, 241, 246))
    image.save(path)


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
        "studio portrait, blue jacket, soft rim light <lora:editorial-lighting:0.8>",
        label="Portrait A",
        seed=101001,
    )
    _write_png(
        batches_dir / "manual-test" / "inbox" / "landscape_b.png",
        (40, 130, 180),
        "wide cinematic landscape, mountains, sunrise",
        label="Landscape B",
        seed=101002,
        size=(768, 432),
    )
    _write_png(
        batches_dir / "manual-test" / "inbox" / "product_tabletop_c.png",
        (176, 116, 58),
        "tabletop product photo, ceramic headphones, warm studio reflection",
        label="Product Tabletop",
        seed=101003,
        size=(640, 640),
    )
    _write_png(
        batches_dir / "manual-test" / "inbox" / "character_turnaround_d.png",
        (82, 94, 170),
        "character design turnaround, tactical coat, neutral gray background",
        label="Character Turnaround",
        seed=101004,
    )
    _write_png(
        batches_dir / "manual-test" / "inbox" / "macro_botanical_e.png",
        (56, 142, 112),
        "macro botanical study, dew on glass petals, shallow depth of field",
        label="Macro Botanical",
        seed=101005,
        size=(512, 768),
    )
    _write_png(
        batches_dir / "manual-test" / "shortlisted" / "shortlisted_c.png",
        (70, 150, 90),
        "shortlisted test image, green lighting",
        label="Shortlisted C",
        seed=102001,
    )
    _write_png(
        batches_dir / "manual-test" / "shortlisted" / "shortlisted_environment_f.png",
        (38, 108, 112),
        "moody interior environment, brass desk lamp, rain-streaked windows",
        label="Shortlisted Environment",
        seed=102002,
    )
    _write_png(
        batches_dir / "manual-test" / "finals" / "final_d.png",
        (200, 170, 70),
        "final selection test image, gold background",
        label="Final D",
        seed=103001,
    )
    _write_png(
        batches_dir / "manual-test" / "finals" / "final_square_g.png",
        (190, 96, 96),
        "final square album cover, red silk fabric, centered chrome emblem",
        label="Final Square",
        seed=103002,
        size=(640, 640),
    )
    _write_png(
        batches_dir / "manual-test" / "rejects" / "reject_soft_h.png",
        (92, 92, 92),
        "reject candidate, soft focus face, visible composition issue",
        label="Reject Soft",
        seed=104001,
    )
    _write_png(
        batches_dir / "second-batch" / "inbox" / "alternate_a.png",
        (180, 80, 80),
        "alternate batch image, red background",
        label="Alternate A",
        seed=201001,
    )
    _write_png(
        batches_dir / "second-batch" / "inbox" / "alternate_wide_b.png",
        (68, 98, 150),
        "alternate wide frame, blue industrial skyline, late evening haze",
        label="Alternate Wide",
        seed=201002,
        size=(800, 450),
    )
    _write_png(
        batches_dir / "second-batch" / "shortlisted" / "alternate_shortlisted_c.png",
        (126, 88, 162),
        "alternate shortlisted portrait, violet neon key light",
        label="Alt Shortlisted",
        seed=202001,
    )
    _write_png(
        comfyui_dir / "pending_import.png",
        (90, 90, 90),
        "pending import image from fake comfyui output",
        label="Pending Import",
        seed=301001,
    )
    _write_png(
        comfyui_dir / "pending_import_metadata.png",
        (118, 90, 42),
        "second pending import, metadata validation sample, amber rim light",
        label="Pending Metadata",
        seed=301002,
    )
    _write_public_png(
        batches_dir / "manual-test" / "public" / "final_d-public.png",
        (188, 152, 62),
        "final_d public copy",
    )
    _write_public_png(
        batches_dir / "second-batch" / "public" / "alternate_a-public.png",
        (164, 70, 70),
        "alternate_a public copy",
    )

    (batches_dir / "manual-test" / ".favorites.json").write_text(
        json.dumps({"images": ["final_d.png", "portrait_a.png"]}, indent=2),
        encoding="utf-8",
    )
    (batches_dir / ".favorites.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "batch": "manual-test",
                        "filename": "final_d.png",
                        "added_at": "2026-06-13T00:00:00+00:00",
                    },
                    {
                        "batch": "manual-test",
                        "filename": "portrait_a.png",
                        "added_at": "2026-06-13T00:01:00+00:00",
                    },
                    {
                        "batch": "second-batch",
                        "filename": "alternate_a.png",
                        "added_at": "2026-06-13T00:02:00+00:00",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
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
