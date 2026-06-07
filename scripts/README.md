# scripts

Helper scripts for local development, maintenance, or verification belong here.

Do not put production runtime logic here if it belongs in `app.py`, `curate.py`, or `ai_curate/`.

## Verification runner

Use `run_all.py` for standard local checks:

```bash
python scripts/run_all.py
```

Common modes:

- `python scripts/run_all.py` — default suite (ruff format check, compileall, unit/component/integration tests, JS syntax, git diff check)
- `python scripts/run_all.py --full` — full check suite including integration tests
- `python scripts/run_all.py --quick` — fast edit-loop checks
- `python scripts/run_all.py --format` — apply Ruff formatting
- `python scripts/run_all.py --skip-js` — skip JavaScript syntax checks only when Node is unavailable and the change is not frontend-related
- `python scripts/run_all.py --quiet` — suppress per-check command echo (useful for log sharing)

When adding new test layers or verification tools, update `run_all.py`, its unit tests, and the verification docs in the same change.
