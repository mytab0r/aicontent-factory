# t_2b4f5dec: 401 invalidated oauth handling fix

## Problem
9router returns `HTTP 401: Encountered invalidated oauth token for user` for `codex/gpt-image-1.5`. All covers fall back to `flux-1-schnell` with `cover_source: fallback_model` instead of the intended primary model.

## Root cause
`02_cover.py` retried 401/403/404/408 errors as if they were transient, burning the second size slot on `gpt-image-1.5` before moving to the next model.

## Fix in `pipeline/02_cover.py`
- Added `_AUTH_FAIL = ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 408")` markers.
- Auth failures now `break` out of the size loop immediately and `continue` to the next model (no retry burn).
- 429 with short `reset after Ns` still retries once per size; long reset or second 429 moves to next model.
- `cover_source` path logic: `api` on first-shot success, `retry` when gpt-image succeeds after one 429, `fallback_model` when flux replaces it.

## Test changes in `pipeline/test_cover_429.py`
- Added `t_2b4f5dec` block: 401→flux path (asserts `fallback_model`, 2 gpt calls without retries).
- Added all-401→bank path (asserts `bank`, no placeholder).
- Added all-401+bank-empty→placeholder path (asserts `placeholder` + `qg.fallback_why(d)`).

## Verification
- `py_compile 02_cover.py` → SYNTAX_OK
- `py_compile test_cover_429.py` → SYNTAX_OK
- Runtime test blocked: `ModuleNotFoundError: No module named 'PIL'` on local runner (no pip). CI provides Pillow via pyproject.toml.

## Acceptance
- [x] Code fix: 401/403/404/408 skip retries, fall through to next model
- [x] Test additions for 401 paths
- [x] Log line format `cover_source: api <model>` preserved for primary model success
- [ ] CI green (PR pending — blocked by runner Docker/PIL gap, not by code)
