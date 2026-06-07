# tests

Test layers are intentionally split by proof strength.

- `unit/` — isolated logic
- `component/` — in-process interactions across a few modules
- `integration/` — Flask/API/filesystem workflow behavior

Add new tests to the narrowest layer that proves the claim.
