# PLAN

## Objective
- Platform hardening pass for `ios-agent-runner`: improve reliability, optional dependency handling, and test coverage so the agent stack is safer to run unattended.

## Repo Map Notes
- `mcp_server.py`: currently imports OCR modules eagerly; can fail startup if optional deps are missing.
- `scripts/idbwrap.py`: scroll fallback path does not perform a real drag gesture.
- `scripts/agent_loop.py`: no guard/retry around Anthropic API call in main loop.
- `scripts/intel.py`: date filtering uses string comparison; fragile for non-normalized timestamps.
- `tests/`: currently only `tests/test_intel.py`; no coverage for runtime reliability paths.

## Plan (checklist)
- [x] Discovery of current code, constraints, and handoff state
- [x] Define hardening scope and update this plan
- [x] Implement optional capability loading in `mcp_server.py` + OCR modules
- [x] Fix action reliability in `scripts/idbwrap.py` and LLM-call resilience in `scripts/agent_loop.py`
- [x] Improve timestamp filtering robustness in `scripts/intel.py`
- [x] Add/extend tests for new behaviors
- [x] Run full verification and update handoff result files

## Progress Log
- Re-read `AGENTS.md`, `_handoff/codex/TICKET.md`, `_handoff/codex/PLAN.md`, `README.md`, and `CLAUDE.md`.
- Reviewed key modules for reliability/ops gaps:
  - `scripts/idbwrap.py`
  - `scripts/agent_loop.py`
  - `scripts/intel.py`
  - `mcp_server.py`
  - `scripts/local_ocr.py`
  - `scripts/vision_extract.py`
- Confirmed baseline status before edits:
  - Existing tests: `python -m pytest -v` => all passing (16 tests).
  - Known operational risks: optional dependency crashes, weak scroll fallback, unhandled API-call failures, timestamp string-compare filtering.
- Implemented capability-aware OCR loading:
  - `mcp_server.py` now lazy-loads optional modules and returns clear JSON errors when unavailable.
  - Added MCP tool `ios_runtime_health` for runtime capability visibility.
  - `scripts/local_ocr.py` and `scripts/vision_extract.py` now expose `is_available()` and fail gracefully when dependencies/config are missing.
- Implemented reliability hardening:
  - `scripts/idbwrap.py` scroll fallback now executes AppleScript drag instead of click-only fallback.
  - `scripts/agent_loop.py` now retries model calls with exponential backoff and returns structured failure after retry exhaustion.
  - `_execute_tool` now checks action return values and reports `FAILED` states deterministically.
- Improved intel search correctness:
  - `scripts/intel.py` now parses ISO-ish timestamps into epoch seconds before filtering by `since`.
- Added new unit tests:
  - `tests/test_runtime_hardening.py`
  - `tests/test_optional_ocr.py`
  - `tests/test_mcp_server_optional.py`
  - plus new timestamp-filter regression test in `tests/test_intel.py`.
- Verification:
  - `source .venv/bin/activate && python -m pytest -v --tb=short` => `29 passed, 1 warning`.
  - `source .venv/bin/activate && python -c "import mcp_server; print('mcp_server import ok')"` => success.
  - `source .venv/bin/activate && python -c "from scripts import local_ocr, vision_extract; print(local_ocr.is_available()); print(vision_extract.is_available())"` => both available in current environment.

## Commands Run
- `pwd && ls -la /Users/stephengodman/ios-agent-runner`
- `ls -la /Users/stephengodman/ios-agent-runner/_handoff/codex`
- `sed -n '1,220p' /Users/stephengodman/ios-agent-runner/AGENTS.md`
- `sed -n '1,260p' /Users/stephengodman/ios-agent-runner/_handoff/codex/PLAN.md`
- `sed -n '1,260p' /Users/stephengodman/ios-agent-runner/_handoff/codex/TICKET.md`
- `sed -n '1,260p' /Users/stephengodman/ios-agent-runner/README.md`
- `cd /Users/stephengodman/ios-agent-runner && rg --files`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,260p' scripts/idbwrap.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '260,520p' scripts/idbwrap.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,320p' scripts/intel.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,260p' scripts/agent_loop.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '260,620p' scripts/agent_loop.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '620,980p' scripts/agent_loop.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,320p' mcp_server.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '320,680p' mcp_server.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,260p' scripts/local_ocr.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,260p' scripts/vision_extract.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '260,520p' scripts/vision_extract.py`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,260p' requirements.txt`
- `cd /Users/stephengodman/ios-agent-runner && sed -n '1,320p' CLAUDE.md`
- `cd /Users/stephengodman/ios-agent-runner && xcrun simctl io help` (failed in sandbox environment)
- `cd /Users/stephengodman/ios-agent-runner && xcrun simctl help io` (failed in sandbox environment)
- `apply_patch` (update `_handoff/codex/PLAN.md`)
- `apply_patch` (update `scripts/local_ocr.py`)
- `apply_patch` (update `scripts/vision_extract.py`)
- `apply_patch` (update `mcp_server.py`)
- `apply_patch` (update `scripts/idbwrap.py`)
- `apply_patch` (update `scripts/agent_loop.py`)
- `apply_patch` (update `scripts/intel.py`)
- `apply_patch` (create `tests/test_runtime_hardening.py`)
- `apply_patch` (create `tests/test_optional_ocr.py`)
- `apply_patch` (create `tests/test_mcp_server_optional.py`)
- `apply_patch` (update `tests/test_intel.py`)
- `apply_patch` (update `README.md`)
- `cd /Users/stephengodman/ios-agent-runner && source .venv/bin/activate && python -m pytest -v --tb=short`
- `cd /Users/stephengodman/ios-agent-runner && source .venv/bin/activate && python -c "import mcp_server; print('mcp_server import ok')"`
- `cd /Users/stephengodman/ios-agent-runner && source .venv/bin/activate && python -c "from scripts import local_ocr, vision_extract; print('local_ocr:', local_ocr.is_available()); print('vision_extract:', vision_extract.is_available())"`
- `cd /Users/stephengodman/ios-agent-runner && git status --short`
- `cd /Users/stephengodman/ios-agent-runner && (append progress lines to `_handoff/codex/LOG.txt`)`

## Files Changed
- `README.md`
- `_handoff/codex/PLAN.md`
- `mcp_server.py`
- `scripts/agent_loop.py`
- `scripts/idbwrap.py`
- `scripts/intel.py`
- `scripts/local_ocr.py`
- `scripts/vision_extract.py`
- `tests/test_intel.py`
- `tests/test_mcp_server_optional.py`
- `tests/test_optional_ocr.py`
- `tests/test_runtime_hardening.py`

## Remaining Work / Next Actions
- None for this hardening pass.
