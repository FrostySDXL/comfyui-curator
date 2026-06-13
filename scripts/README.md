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

See root `AGENTS.md` for project-wide rules, verification standards, and overall philosophy.
