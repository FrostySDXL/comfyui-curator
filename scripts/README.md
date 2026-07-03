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
$env:IMAGE_CURATOR_ENABLE_WATCHER="false"
$env:IMAGE_CURATOR_HOST="127.0.0.1"
$env:IMAGE_CURATOR_PORT="5000"
.venv\Scripts\python.exe app.py
```

Then open `http://127.0.0.1:5000`. Delete `tmp/local-browser-fixture/` when you
want a clean manual-testing reset.

After launching, see `CONTRIBUTING.md` for the manual UI/API verification
checklist.

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
