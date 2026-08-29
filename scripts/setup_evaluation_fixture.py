"""Generate the deterministic evaluation fixture for the section-10 redesign.

The fixture implements the test-batch requirements of ``UI_UX_REDESIGN_RESEARCH.md``
section 10: a small mixed-media culling batch, a large revisioned-paging batch, and
all of the representative operator states (favorites, AI run history, sidecars,
stale indexes, failed thumbnails). It is deterministic under a fixed seed and is
stored under ``tmp/`` by default so it stays out of real curation libraries.

The search/prompt indexes are produced by the real builders in
``image_curator``; their embedded timestamps and file mtimes are then normalized
so the whole fixture is byte-reproducible under a fixed seed.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, PngImagePlugin

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai_curate.models import CurationRun, ImageResult, JobState, RunTotals  # noqa: E402
from image_curator import prompt_history  # noqa: E402
from image_curator import search_index  # noqa: E402

BATCH_CULLING = "eval-culling"
BATCH_PAGING = "eval-paging"
DEFAULT_ROOT = Path("tmp") / "evaluation-fixture"
DEFAULT_SEED = 20260829

NEAR_DUP_PAIR_COUNT = 10
PUBLIC_COUNT = 5
SIDECAR_COUNT = 30
STALE_COUNT = 12
TRANSPORT_MARKERS = ("mp4", "mp4", "mp3", "mp3")
PROGRESS_INTERVAL = 5000
FIXED_BUILT_AT = "2026-08-29T00:00:00+00:00"

TOKEN_GROUPS = (
    "golden harbor",
    "cyberpunk alley",
    "watercolor botany",
    "brutalist fog",
    "desert rally",
    "inked wildlife",
)
GROUP_COLORS = (
    (216, 154, 66),
    (70, 42, 162),
    (64, 150, 112),
    (92, 98, 106),
    (198, 130, 54),
    (40, 44, 48),
)
IMAGE_SIZES = (
    (640, 480),
    (480, 640),
    (512, 512),
    (1024, 432),
    (768, 768),
    (800, 450),
)
PAGING_SIZE = (64, 48)

DEFAULT_NEGATIVE = "extra fingers, warped hands, low detail, watermark"


@dataclass(frozen=True)
class EvaluationFixtureResult:
    root: Path
    batches_dir: Path
    comfyui_dir: Path
    state_file: Path
    host: str
    port: int
    seed: int
    small_count: int
    large_count: int
    skip_large: bool
    counts: dict[str, int]
    directory_counts: dict[str, int]
    total_files: int
    disk_bytes: int
    elapsed_seconds: float

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
                f'$env:IMAGE_CURATOR_HOST="{self.host}"',
                f'$env:IMAGE_CURATOR_PORT="{self.port}"',
            ]
        if shell == "cmd":
            return [
                f"set IMAGE_CURATOR_BATCHES={self.batches_dir}",
                f"set IMAGE_CURATOR_COMFYUI={self.comfyui_dir}",
                f"set IMAGE_CURATOR_STATE={self.state_file}",
                f"set IMAGE_CURATOR_HOST={self.host}",
                f"set IMAGE_CURATOR_PORT={self.port}",
            ]
        raise ValueError("shell must be 'powershell' or 'cmd'")


def _parameters_text(
    prompt: str,
    *,
    negative_prompt: str = DEFAULT_NEGATIVE,
    seed: int,
    size: tuple[int, int],
) -> str:
    return (
        f"{prompt}\n"
        f"Negative prompt: {negative_prompt}\n"
        f"Steps: 28, Sampler: DPM++ 2M SDE Karras, CFG scale: 6.5, Seed: {seed}, "
        f"Size: {size[0]}x{size[1]}, Model hash: FIXTURE42, Model: fixture-vision-sdxl, "
        "Clip skip: 2, Version: evaluation-fixture"
    )


def _encode_png(
    color: tuple[int, int, int],
    prompt: str,
    *,
    seed: int,
    size: tuple[int, int],
    label: str = "",
) -> bytes:
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("parameters", _parameters_text(prompt, seed=seed, size=size))
    metadata.add_text(
        "prompt",
        json.dumps(
            {
                "fixture": True,
                "seed": seed,
                "positive": prompt,
                "generator": "setup_evaluation_fixture",
            }
        ),
    )
    metadata.add_text(
        "workflow",
        json.dumps({"nodes": [{"type": "FixturePrompt", "prompt": prompt}], "seed": seed}),
    )
    image = Image.new("RGB", size, color=color)
    if label:
        draw = ImageDraw.Draw(image)
        box_bottom = min(size[1] - 8, 52)
        draw.rectangle((8, 8, min(size[0] - 8, 300), box_bottom), fill=(12, 14, 18))
        draw.text((16, 14), label[:40], fill=(236, 240, 245))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=metadata)
    return buffer.getvalue()


def _pooled_png(
    pool: dict[tuple[object, ...], bytes],
    color: tuple[int, int, int],
    prompt: str,
    *,
    seed: int,
    size: tuple[int, int],
    label: str = "",
) -> bytes:
    key = (size, color, prompt, seed, label)
    data = pool.get(key)
    if data is None:
        data = _encode_png(color, prompt, seed=seed, size=size, label=label)
        pool[key] = data
    return data


def _save_plain(path: Path, ext: str, color: tuple[int, int, int], size: tuple[int, int]) -> None:
    image = Image.new("RGB", size, color=color)
    if ext == "jpg":
        image.save(path, format="JPEG")
    elif ext == "webp":
        image.save(path, format="WEBP")
    elif ext == "gif":
        image.save(path, format="GIF")
    else:
        raise ValueError(f"unsupported plain-image extension: {ext}")


def _vary_color(base: tuple[int, int, int], index: int) -> tuple[int, int, int]:
    red, green, blue = base
    return (
        (red + (index * 7 + 3) % 40 - 20) % 256,
        (green + (index * 11 + 5) % 40 - 20) % 256,
        (blue + (index * 13 + 7) % 40 - 20) % 256,
    )


def _image_prompt(group: int, index: int) -> str:
    return f"{TOKEN_GROUPS[group]}, deterministic variant {index}, sharp focus, high detail"


def _pair_prompt(group: int, pair_index: int) -> str:
    return f"{TOKEN_GROUPS[group]}, near-duplicate study pair {pair_index}, identical framing"


def _interleave_types(non_pair_png: int, jpg: int, webp: int, gif: int) -> list[str]:
    pools = {"png": non_pair_png, "jpg": jpg, "webp": webp, "gif": gif}
    keys = ("png", "jpg", "webp", "gif")
    sequence: list[str] = []
    while any(pools[key] > 0 for key in keys):
        for key in keys:
            if pools[key] > 0:
                sequence.append(key)
                pools[key] -= 1
    return sequence


def _external_favorites_sidecar(index: int) -> dict[str, object]:
    return {
        "category": "external_favorites",
        "subcategory": "post" if index % 2 == 0 else "favorite",
        "tags": " ".join(TOKEN_GROUPS[index % 6].split()) + " external",
        "favorite_id": 900000 + index,
        "total": 1000 + index,
        "id": f"{700000 + index}",
        "post_id": f"{800000 + index}",
        "artist": f"artist_{index}",
        "site": "example",
    }


def _generic_sidecar(index: int, seed: int) -> dict[str, object]:
    return {
        "category": "batch",
        "rating": f"{index % 6}",
        "source": "comfyui",
        "seed": f"{seed + index}",
        "notes": "generic flat metadata sidecar",
        "generator": "setup_evaluation_fixture",
    }


def _count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.iterdir() if path.is_file() and not path.is_symlink())


def _dir_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _count_root_files(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += 1
        except OSError:
            continue
    return total


def _write_favorites(batches_dir: Path, batch_filenames: list[str]) -> None:
    batch_dir = batches_dir / BATCH_CULLING
    (batch_dir / ".favorites.json").write_text(
        json.dumps({"images": batch_filenames}, indent=2), encoding="utf-8"
    )
    universal = [
        {"batch": BATCH_CULLING, "filename": name, "added_at": f"2026-08-29T00:00:{i:02d}+00:00"}
        for i, name in enumerate(batch_filenames[:8])
    ]
    (batches_dir / ".favorites.json").write_text(
        json.dumps({"images": universal}, indent=2), encoding="utf-8"
    )


def _build_ai_runs(batch_dir: Path, filenames: list[str]) -> None:
    ai_dir = batch_dir / "ai-curate"
    runs_dir = ai_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_a_results = []
    for index, name in enumerate(filenames[:20]):
        if index >= 18:
            run_a_results.append(
                ImageResult(
                    filename=name,
                    score=-1,
                    total=0,
                    failed=True,
                    error_message="vision model timeout",
                )
            )
        else:
            run_a_results.append(
                ImageResult(
                    filename=name,
                    score=(index * 7 + 2) % 11,
                    total=10,
                    details={0: "element matched", 1: "element partial", 2: "quality ok"},
                )
            )
    run_a = CurationRun(
        run_id="eval-run-complete",
        batch=BATCH_CULLING,
        source_folder="inbox",
        destination_folder="shortlisted",
        move_enabled=True,
        prompt="evaluation run A positive prompt",
        elements=["golden harbor", "composition", "sharp focus", "lighting"],
        quality_flags=["sharp", "no watermark", "correct framing"],
        model="fixture-vision-sdxl",
        top_n=15,
        status=JobState.COMPLETED,
        created_at="2026-08-28T10:00:00+00:00",
        completed_at="2026-08-28T10:02:00+00:00",
        totals=RunTotals(images=20, scored=18, failed=2, moved=0),
        results=run_a_results,
    )

    run_b_results = []
    for index, name in enumerate(filenames[:10]):
        if index >= 5:
            run_b_results.append(
                ImageResult(
                    filename=name,
                    score=-1,
                    total=0,
                    failed=True,
                    error_message="cancelled before scoring",
                )
            )
        else:
            run_b_results.append(
                ImageResult(
                    filename=name,
                    score=(index * 3) % 11,
                    total=10,
                    details={0: "element matched"},
                )
            )
    run_b = CurationRun(
        run_id="eval-run-cancelled",
        batch=BATCH_CULLING,
        source_folder="inbox",
        destination_folder=None,
        move_enabled=False,
        prompt="evaluation run B prompt",
        elements=["cyberpunk alley", "composition"],
        quality_flags=["sharp"],
        model="fixture-vision-sdxl",
        top_n=15,
        status=JobState.CANCELLED,
        created_at="2026-08-28T11:00:00+00:00",
        completed_at="2026-08-28T11:01:00+00:00",
        totals=RunTotals(images=10, scored=5, failed=5, moved=0),
        results=run_b_results,
        error_message="cancelled by operator during scoring",
    )

    for run in (run_a, run_b):
        (runs_dir / f"{run.run_id}.json").write_text(
            json.dumps(run.to_dict(), indent=2), encoding="utf-8"
        )
    (ai_dir / "latest.json").write_text(
        json.dumps({"run_id": run_b.run_id}, indent=2), encoding="utf-8"
    )


def _generate_culling_batch(
    batches_dir: Path,
    small_count: int,
    seed: int,
    pool: dict[tuple[object, ...], bytes],
) -> tuple[dict[str, int], list[str]]:
    counts: dict[str, int] = {
        "png": 0,
        "jpg": 0,
        "webp": 0,
        "gif": 0,
        "mp4": 0,
        "mp3": 0,
        "sidecar": 0,
        "corrupt": 0,
        "zero": 0,
        "stale": 0,
        "public": 0,
        "runs": 0,
    }
    batch_dir = batches_dir / BATCH_CULLING
    inbox = batch_dir / "inbox"
    for folder in ("inbox", "shortlisted", "finals", "rejects", "public"):
        (batch_dir / folder).mkdir(parents=True, exist_ok=True)

    png = int(small_count * 0.85)
    jpg = int(small_count * 0.08)
    webp = int(small_count * 0.04)
    gif = int(small_count * 0.02)
    png += small_count - (png + jpg + webp + gif)

    pair_start = 100
    pair_end = pair_start + NEAR_DUP_PAIR_COUNT * 2
    non_pair_png = png - NEAR_DUP_PAIR_COUNT * 2
    type_sequence = iter(_interleave_types(non_pair_png, jpg, webp, gif))

    media_names: list[str] = []
    png_names: list[str] = []
    for index in range(small_count):
        if pair_start <= index < pair_end:
            ext = "png"
            pair_index = (index - pair_start) // 2
            is_second = (index - pair_start) % 2 == 1
        else:
            ext = next(type_sequence)
        name = f"eval_cull_{index + 1:04d}.{ext}"
        group = index % 6
        size = IMAGE_SIZES[index % len(IMAGE_SIZES)]
        if ext == "png" and pair_start <= index < pair_end:
            pair_index = (index - pair_start) // 2
            is_second = (index - pair_start) % 2 == 1
            color = GROUP_COLORS[group]
            if is_second:
                color = (color[0], (color[1] + 2) % 256, color[2])
            file_seed = seed + 100000 + pair_index * 2 + (1 if is_second else 0)
            prompt = _pair_prompt(group, pair_index)
            label = f"pair {pair_index + 1}{'b' if is_second else 'a'}"
            (inbox / name).write_bytes(
                _pooled_png(pool, color, prompt, seed=file_seed, size=size, label=label)
            )
            counts["png"] += 1
        elif ext == "png":
            color = _vary_color(GROUP_COLORS[group], index)
            file_seed = seed + index
            prompt = _image_prompt(group, index)
            (inbox / name).write_bytes(
                _pooled_png(
                    pool, color, prompt, seed=file_seed, size=size, label=f"{index + 1:04d}"
                )
            )
            counts["png"] += 1
        else:
            _save_plain(inbox / name, ext, _vary_color(GROUP_COLORS[group], index), size)
            counts[ext] += 1
        media_names.append(name)
        if ext == "png":
            png_names.append(name)

    for offset, ext in enumerate(TRANSPORT_MARKERS, start=small_count + 1):
        name = f"eval_cull_{offset:04d}.{ext}"
        (inbox / name).write_bytes(f"fixture {ext} transport marker\n".encode("utf-8"))
        counts[ext] += 1
        media_names.append(name)

    (inbox / "eval_cull_corrupt.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"not a decodable png payload"
    )
    (inbox / "eval_cull_zero.png").write_bytes(b"")
    counts["corrupt"] += 1
    counts["zero"] += 1

    for index, media_name in enumerate(media_names[:SIDECAR_COUNT]):
        sidecar_path = inbox / f"{Path(media_name).stem}.json"
        if index < 15:
            payload = _external_favorites_sidecar(index)
        else:
            payload = _generic_sidecar(index, seed)
        sidecar_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        counts["sidecar"] += 1

    _write_favorites(batches_dir, png_names[:12])
    _build_ai_runs(batch_dir, png_names)
    counts["runs"] = 2

    for index in range(PUBLIC_COUNT):
        image = Image.new("RGB", (256, 256), color=GROUP_COLORS[index % 6])
        image.save(batch_dir / "public" / f"eval_public_{index + 1}.png")
        counts["public"] += 1

    return counts, png_names


def _add_stale_images(
    inbox: Path,
    seed: int,
    pool: dict[tuple[object, ...], bytes],
) -> None:
    for index in range(STALE_COUNT):
        group = index % 6
        name = f"eval_cull_stale_{index:02d}.png"
        prompt = f"{TOKEN_GROUPS[group]}, stale addition {index}"
        (inbox / name).write_bytes(
            _pooled_png(
                pool,
                GROUP_COLORS[group],
                prompt,
                seed=seed + 900000 + index,
                size=(480, 360),
                label=f"stale {index}",
            )
        )


def _generate_paging_batch(
    batches_dir: Path,
    large_count: int,
    seed: int,
    pool: dict[tuple[object, ...], bytes],
) -> int:
    inbox = batches_dir / BATCH_PAGING / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for index in range(large_count):
        group = index % 6
        name = f"eval_page_{index + 1:06d}.png"
        (inbox / name).write_bytes(
            _pooled_png(
                pool,
                GROUP_COLORS[group],
                f"{TOKEN_GROUPS[group]}, paging sample",
                seed=seed + group,
                size=PAGING_SIZE,
            )
        )
        if (index + 1) % PROGRESS_INTERVAL == 0:
            print(f"  paging: {index + 1}/{large_count} files", flush=True)
    return large_count


def _determinize_indexes(batches_dir: Path) -> None:
    prompt_path = batches_dir / BATCH_CULLING / "prompt-history.json"
    search_path = batches_dir / BATCH_CULLING / "search-index.json"
    prompt_index = json.loads(prompt_path.read_text(encoding="utf-8"))
    prompt_index["built_at"] = FIXED_BUILT_AT
    prompt_path.write_text(json.dumps(prompt_index, indent=2), encoding="utf-8")

    index = json.loads(search_path.read_text(encoding="utf-8"))
    index["built_at"] = FIXED_BUILT_AT
    for folder_state in index.get("source_state", {}).values():
        folder_state["mtime_ns"] = 0
    for item in index.get("items", []):
        item["mtime"] = 0
    search_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def create_fixture(
    root: Path,
    *,
    small_count: int = 800,
    large_count: int = 30000,
    seed: int = DEFAULT_SEED,
    skip_large: bool = False,
    host: str = "127.0.0.1",
    port: int = 5000,
) -> EvaluationFixtureResult:
    root = Path(root)
    batches_dir = root / "batches"
    comfyui_dir = root / "comfyui-outputs"
    state_file = root / "state.json"

    started = time.perf_counter()
    pool: dict[tuple[object, ...], bytes] = {}

    batches_dir.mkdir(parents=True, exist_ok=True)
    comfyui_dir.mkdir(parents=True, exist_ok=True)

    counts, _png_names = _generate_culling_batch(batches_dir, small_count, seed, pool)
    inbox = batches_dir / BATCH_CULLING / "inbox"

    prompt_history.build_prompt_index(batches_dir, BATCH_CULLING)
    search_index.build_search_index(batches_dir, BATCH_CULLING)
    _determinize_indexes(batches_dir)

    _add_stale_images(inbox, seed, pool)
    counts["stale"] = STALE_COUNT

    if not skip_large:
        counts["paging"] = _generate_paging_batch(batches_dir, large_count, seed, pool)

    state_file.write_text(json.dumps({"active_batch": BATCH_CULLING}), encoding="utf-8")

    tracked_dirs = {
        batches_dir / BATCH_CULLING / "inbox",
        batches_dir / BATCH_CULLING / "shortlisted",
        batches_dir / BATCH_CULLING / "finals",
        batches_dir / BATCH_CULLING / "rejects",
        batches_dir / BATCH_CULLING / "public",
        batches_dir / BATCH_CULLING / "ai-curate" / "runs",
    }
    if not skip_large:
        tracked_dirs.add(batches_dir / BATCH_PAGING / "inbox")
    directory_counts = {
        str(directory.relative_to(root).as_posix()): _count_files(directory)
        for directory in sorted(tracked_dirs)
    }

    manifest = {
        "version": 1,
        "seed": seed,
        "small_count": small_count,
        "large_count": large_count,
        "skip_large": skip_large,
        "built_at": FIXED_BUILT_AT,
        "directory_counts": directory_counts,
    }
    (root / "fixture-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    elapsed = time.perf_counter() - started
    return EvaluationFixtureResult(
        root=root,
        batches_dir=batches_dir,
        comfyui_dir=comfyui_dir,
        state_file=state_file,
        host=host,
        port=port,
        seed=seed,
        small_count=small_count,
        large_count=large_count,
        skip_large=skip_large,
        counts=counts,
        directory_counts=directory_counts,
        total_files=_count_root_files(root),
        disk_bytes=_dir_size(root),
        elapsed_seconds=elapsed,
    )


def _json_load(path: Path) -> tuple[bool, str]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, str(exc)
    return True, ""


def verify_fixture(root: Path) -> tuple[bool, list[str]]:
    root = Path(root)
    problems: list[str] = []

    manifest_path = root / "fixture-manifest.json"
    if not manifest_path.is_file():
        return False, ["fixture-manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, [f"fixture-manifest.json is not valid JSON: {exc}"]

    for relative, expected in manifest.get("directory_counts", {}).items():
        directory = root / relative
        if not directory.is_dir():
            problems.append(f"{relative}: directory missing")
            continue
        actual = _count_files(directory)
        if actual != expected:
            problems.append(f"{relative}: expected {expected} files, found {actual}")

    state_file = root / "state.json"
    if not state_file.is_file():
        problems.append("state.json is missing")
    else:
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("active_batch") != BATCH_CULLING:
                problems.append(f"state.json active_batch is {state.get('active_batch')!r}")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            problems.append(f"state.json is not valid JSON: {exc}")

    culling = root / "batches" / BATCH_CULLING
    for rel in ("inbox", "shortlisted", "finals", "rejects", "public"):
        if not (culling / rel).is_dir():
            problems.append(f"{BATCH_CULLING}/{rel}: directory missing")

    for rel in (".favorites.json", "prompt-history.json", "search-index.json"):
        ok, reason = _json_load(culling / rel)
        if not ok:
            problems.append(f"{BATCH_CULLING}/{rel}: not valid JSON ({reason})")
    ok, reason = _json_load(root / "batches" / ".favorites.json")
    if not ok:
        problems.append(f"batches/.favorites.json: not valid JSON ({reason})")

    runs_dir = culling / "ai-curate" / "runs"
    run_files = sorted(runs_dir.glob("*.json")) if runs_dir.is_dir() else []
    if len(run_files) != 2:
        problems.append(f"ai-curate/runs: expected 2 run files, found {len(run_files)}")
    for run_file in run_files:
        ok, reason = _json_load(run_file)
        if not ok:
            problems.append(f"ai-curate/runs/{run_file.name}: not valid JSON ({reason})")
    latest_ok, latest_reason = _json_load(culling / "ai-curate" / "latest.json")
    if not latest_ok:
        problems.append(f"ai-curate/latest.json: not valid JSON ({latest_reason})")

    corrupt = culling / "inbox" / "eval_cull_corrupt.png"
    if not corrupt.is_file():
        problems.append("eval_cull_corrupt.png is missing")
    else:
        try:
            with Image.open(corrupt) as image:
                image.verify()
            problems.append("eval_cull_corrupt.png is unexpectedly decodable")
        except Exception:
            pass

    return not problems, problems


def _format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _print_summary(result: EvaluationFixtureResult, shell: str) -> None:
    print("Evaluation fixture ready")
    print(f"- Fixture root: {result.root}")
    print(f"- Batches: {result.batches_dir}")
    print(f"- State file: {result.state_file}")
    print(f"- Seed: {result.seed}")
    print(
        f"- Small batch ({BATCH_CULLING}): {result.small_count} media images "
        f"(+ {len(TRANSPORT_MARKERS)} transport + 2 corrupt/zero + "
        f"{SIDECAR_COUNT} sidecars + {STALE_COUNT} stale)"
    )
    if result.skip_large:
        print(f"- Large batch ({BATCH_PAGING}): skipped (--skip-large)")
    else:
        print(f"- Large batch ({BATCH_PAGING}): {result.large_count} tiny PNGs")
    print("- Category counts:")
    for key, value in sorted(result.counts.items()):
        print(f"    {key}: {value}")
    print(f"- Total files: {result.total_files}")
    print(f"- Approx disk usage: {_format_bytes(result.disk_bytes)}")
    print(f"- Elapsed: {result.elapsed_seconds:.1f}s")
    print("")
    print(f"Run these commands in {shell} before starting the app:")
    for line in result.env_lines(shell):
        print(line)
    print(".venv\\Scripts\\python.exe app.py")
    print("")
    print(f"Native note: point the ComfyUI native settings batch root at {result.batches_dir}")


def _safe_remove_root(root: Path) -> None:
    resolved = Path(root).resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.cwd().resolve():
        raise SystemExit(f"refusing to remove unsafe root: {resolved}")
    if resolved.is_dir() and any(resolved.iterdir()):
        if not (resolved / "fixture-manifest.json").is_file():
            raise SystemExit(
                f"refusing to remove {resolved}: directory is non-empty and has no "
                "fixture-manifest.json, so it does not look like a fixture root"
            )
    shutil.rmtree(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="Fixture root directory. Default: tmp/evaluation-fixture",
    )
    parser.add_argument("--large-count", type=int, default=30000, help="Large batch file count")
    parser.add_argument("--small-count", type=int, default=800, help="Small batch image count")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the app launch command")
    parser.add_argument("--port", type=int, default=5000, help="Port for the app launch command")
    parser.add_argument(
        "--shell",
        choices=("powershell", "cmd"),
        default="powershell",
        help="Shell syntax to print for environment variables",
    )
    parser.add_argument(
        "--skip-large",
        action="store_true",
        help="Generate only the small culling batch (used by tests and smoke runs)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and rebuild an existing fixture root",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Re-check an existing fixture's structure/counts instead of generating",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.verify:
        ok, problems = verify_fixture(args.root)
        if ok:
            print(f"PASS: fixture at {args.root} matches its manifest")
            return 0
        print(f"FAIL: fixture at {args.root} failed verification")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    root = Path(args.root)
    if root.exists() and not args.force:
        print(
            f"refusing to run: {root} already exists (use --force to replace it)", file=sys.stderr
        )
        return 2
    if root.exists():
        _safe_remove_root(root)

    result = create_fixture(
        root,
        small_count=args.small_count,
        large_count=args.large_count,
        seed=args.seed,
        skip_large=args.skip_large,
        host=args.host,
        port=args.port,
    )
    _print_summary(result, args.shell)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
