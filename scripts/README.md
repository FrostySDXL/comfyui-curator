# scripts -- Guidance

**One-sentence purpose:** Local development, maintenance, and verification scripts for the project.

**Role in the Project:** Provides the `run_all.py` verification runner used as the standard check suite across all modules. Not production runtime -- that belongs in `app.py`, `curate.py`, or `ai_curate/`.

## Verification runner

Use `run_all.py` for standard local checks:

```bash
python scripts/run_all.py
```

Common modes:

- `python scripts/run_all.py` — default suite (ruff format check, ruff lint, compileall, unit/component/integration tests, JS syntax for ordered `static/js/*.js` files, cross-file duplicate declaration check, git diff check)
- `python scripts/run_all.py --full` — full check suite including mypy type checking
- `python scripts/run_all.py --quick` — fast edit-loop checks
- `python scripts/run_all.py --format` — apply Ruff formatting (this is the **only** mode that mutates files; all other modes are verification-only)
- `python scripts/run_all.py --skip-js` — skip JavaScript syntax and duplicate-declaration checks only when Node is unavailable and the change is not frontend-related
- `python scripts/run_all.py --quiet` — suppress per-check command echo (useful for log sharing)

When adding new test layers or verification tools, update `run_all.py`, its unit tests, and the verification docs in the same change.

The JavaScript checks use the same ordered classic-script list as the browser load order. They run `node --check` for each existing `static/js/*.js` split file and a cross-file duplicate top-level `let`/`const` declaration check so classic scripts do not fail at page load.

## Local browser fixture

Use `setup_local_browser_fixture.py` to create disposable batches and sample
PNG files for manual UI testing without touching real curation data:

```bash
python scripts/setup_local_browser_fixture.py
```

The fixture creates two batches, sample PNG files with prompt metadata, one
pending fake ComfyUI import, and an active `manual-test` batch. By default it
writes under ignored `tmp/local-browser-fixture/`.

The script prints shell-specific environment variables and an `app.py` launch
command. On PowerShell, the launch sequence is:

```powershell
.venv\Scripts\python.exe scripts\setup_local_browser_fixture.py

$env:IMAGE_CURATOR_BATCHES="tmp\local-browser-fixture\batches"
$env:IMAGE_CURATOR_COMFYUI="tmp\local-browser-fixture\comfyui-outputs"
$env:IMAGE_CURATOR_STATE="tmp\local-browser-fixture\state.json"
$env:IMAGE_CURATOR_HOST="127.0.0.1"
$env:IMAGE_CURATOR_PORT="5000"
.venv\Scripts\python.exe app.py
```

Then open `http://127.0.0.1:5000`. Delete `tmp/local-browser-fixture/` when you
want a clean manual-testing reset.

After launching, see `CONTRIBUTING.md` for the manual UI/API verification
checklist.

## Thumbnail benchmark harness

`benchmark_thumbnails.py` is an optional manual performance harness for the
thumbnail grid and its caches. It is Firefox-first, supports an explicit Chrome
comparison, and injects all browser instrumentation at runtime. It does not
change production frontend code or thumbnail-loading behavior and is not part
of `run_all.py`.

Install the optional dependencies in the repository virtual environment:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[benchmark]"
```

With native ComfyUI running at its default URL, run the headed Firefox suite:

```powershell
.venv\Scripts\python.exe scripts\benchmark_thumbnails.py
```

Common variants:

```powershell
# Serialized Firefox smoke test
.venv\Scripts\python.exe scripts\benchmark_thumbnails.py --browser firefox --sizes 100 --headless

# Firefox followed by Chrome; any requested browser failure makes the command nonzero
.venv\Scripts\python.exe scripts\benchmark_thumbnails.py --browser all --sizes 100 500

# Offline driver paths; browser binary paths can be overridden the same way
.venv\Scripts\python.exe scripts\benchmark_thumbnails.py --firefox-driver C:\tools\geckodriver.exe
.venv\Scripts\python.exe scripts\benchmark_thumbnails.py --browser chrome --chrome-driver C:\tools\chromedriver.exe
```

When an explicit driver is absent, Selenium Manager resolves the matching
driver and may need network access. The defaults use Firefox at
`C:\Program Files\Mozilla Firefox\firefox.exe` and Chrome at
`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`. Edge is not
supported.

Native mode resolves the batch root from the dedicated local settings endpoint
without printing or saving the settings response. Standalone mode cannot safely
discover its root, so the running app must already use an explicit temporary
root beneath `--output-root` and the same path must be passed to the harness:

```powershell
New-Item -ItemType Directory -Force -Path "tmp\thumbnail-benchmarks" | Out-Null
$root = (Resolve-Path "tmp\thumbnail-benchmarks").Path
$batchRoot = Join-Path $root "standalone-batches"
New-Item -ItemType Directory -Force -Path $batchRoot | Out-Null
$env:IMAGE_CURATOR_BATCHES=$batchRoot
$env:IMAGE_CURATOR_STATE=(Join-Path $root "standalone-state.json")
$env:IMAGE_CURATOR_PORT="5000"
.venv\Scripts\python.exe app.py

# In a second PowerShell window
.venv\Scripts\python.exe scripts\benchmark_thumbnails.py --mode standalone `
  --url http://127.0.0.1:5000 --batch-root tmp\thumbnail-benchmarks\standalone-batches `
  --sizes 100
```

Each browser/size case gets unique A/B batches, deterministic PNG aliases, a
new server-side `.thumbs` cache, and an isolated browser profile. The small B
companion is activated and loaded before instrumentation; the untouched A batch
is selected only after timings are cleared, making A the measured cold load. A
versioned recovery manifest is written before batch creation. Batch cleanup
requires all of these checks: the manifest root equals the live runtime root,
the batch is a direct child of that root, it is not a symlink, and its ownership
marker exactly matches the manifest run and batch. Missing or mismatched markers
are refused. The previously active batch is restored in a `finally` block;
disabled state is restored through the API as an empty batch name.

Reports, deterministic seed fixtures, and manifests default to a unique
directory under ignored `tmp/thumbnail-benchmarks/`. Temporary browser profiles
are removed after WebDriver exits. Profile cleanup requires a regular manifest
inside a direct child run directory whose name matches the manifest run ID, and
refuses symlinked or escaping profile paths. Cleanup failures are recorded and
make the command nonzero. `--keep-fixtures` retains benchmark batches only; it
never retains browser profiles. Seed fixtures remain with the report because
they are harmless, ignored, and useful for run provenance. Recover retained or
interrupted batches and profiles from manifests with:

```powershell
.venv\Scripts\python.exe scripts\benchmark_thumbnails.py --cleanup
```

The JSON report contains versioned raw phase metrics and `summary.md` contains a
compact comparison. Phases cover cold load (with three intermediate measurement
checkpoints: first viewport settled, partial controlled traversal, and full
traversal), controlled scroll, warm reload, A-to-B-to-A switching, and restored
sidebar width changes. Each checkpoint records loaded image count, thumbnail
request count, live blob count and bytes, DOM node count, browser RSS, frame
intervals, long-task metrics where available, and server `.thumbs` file count
and bytes.

The full traversal checkpoint and the warm reload and A-B-A phases all use a
controlled full traversal readiness gate (viewport settle with expected-count
guard, region-by-region deterministic traversal, and traversal readiness
verification) instead of requiring all thumbnail elements to reach terminal
state. This is compatible with production approach-only loading where distant
thumbnails remain pending until the region is approached.

Each batch selection in warm reload and A-B-A gets its own viewport settle
operation producing a per-batch first_viewport_ms.  A-B-A traversal order is
companion-batch then primary-batch, and Resource Timing remains cumulative
across both traversals because instrumentation is installed once before the
switches. The primary readiness retains total switch elapsed_ms while
preserving its own first_viewport_ms separately.  Traversal-unavailable,
frame-capped, unsettled, or incomplete states produce ready=false and
actionable phase warnings without hanging for the global timeout.

Shared metrics use
Resource Timing, in-page cache/DOM evaluation, animation-frame intervals,
psutil browser-process RSS, and `.thumbs` file sizes. Cache hits are explicitly
a `transferSize == 0 && encodedBodySize > 0` heuristic. Blob compressed bytes
come from a transparent, one-time page-realm wrapper around
`URL.createObjectURL` and `URL.revokeObjectURL`. WebDriver installs that wrapper
through a temporary inline script, then removes the script element. The page
realm records actual `Blob.size` values and removes successfully revoked URLs
without refetching blobs. A hidden benchmark-only DOM element exposes JSON
measurement snapshots across Firefox's WebDriver sandbox boundary; it contains
no paths or settings. Repeated phase installation resets timings and long tasks
without rewrapping URL methods or discarding live observed blobs. A reload gets
a fresh document, bridge, and wrapper. Companion blobs created before
instrumentation are intentionally excluded; the measured primary batch is
selected after wrapping and is fully observed. Missing, blocked, or malformed
bridge state makes blob and long-task metrics unavailable with a reason rather
than failing the benchmark. Other unsupported metrics likewise remain
null/unavailable and are never silently substituted.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
