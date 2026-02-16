# iOS Agent Runner

CLI-driven iOS Simulator automation framework using IDB + simctl.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Prerequisites
- macOS with Xcode (full, not just CommandLineTools)
- `xcode-select -s /Applications/Xcode.app/Contents/Developer`
- `brew install idb-companion`

### Optional OCR Dependencies
- OpenAI vision extraction:
  - `pip install openai`
  - set `OPENAI_API_KEY` in `.env` or `~/.env`
- Local macOS Vision OCR:
  - `pip install pyobjc-framework-Cocoa pyobjc-framework-Vision`

If optional OCR dependencies are missing, the MCP server still starts and the OCR tools return a clear capability error.

## Usage

```bash
# Dump accessibility tree
python main.py --dump-tree

# Tap + type + screenshot
python main.py --tap-text "Search" --type-text "openai.com" --screenshot

# Custom app
python main.py --bundle-id com.apple.Preferences --dump-tree
```

### Agent Runs with Safe Mode + Resume

```bash
# Safe mode on by default
python main.py --goal "Open Settings and read Wi-Fi status" --max-steps 20

# Pause after 5 steps, then resume
python main.py --goal "Open Settings and inspect Bluetooth" --stop-after-step 5
python main.py --resume-run-id run_20260216T000000Z_abc12345

# Inspect persisted runs
python main.py --list-runs
python main.py --replay-run run_20260216T000000Z_abc12345
```

Persisted run artifacts are stored in `_artifacts/runs/<run_id>/`:
- `state.json` — latest run snapshot
- `events.jsonl` — step-by-step telemetry
- `report.html` — generated dashboard (optional)

### Dry-Run Validation + HTML Report

```bash
python main.py --dry-run-run-id run_20260216T000000Z_abc12345
python main.py --render-report run_20260216T000000Z_abc12345
```

Latest-run helpers:

```bash
python main.py --dry-run-latest
python main.py --render-latest-report
```

### Local Simulator Smoke Check

```bash
python scripts/smoke_simulator.py
```

This verifies simulator boot/connect, tree dump, screenshot capture, and key MCP helper tools without running the paid autonomous loop.

## Architecture

```
main.py              CLI orchestrator
scripts/
  simctl.py          Simulator boot/detect via xcrun simctl
  idbwrap.py         IDB + simctl fallback for app interaction
  screen_mapper.py   Accessibility tree parser/normalizer
  navigator.py       Fuzzy text match + tap + self-correction
  screenshot.py      Screenshot capture to _artifacts/
_artifacts/          Output screenshots
```

## MCP Runtime Health

`mcp_server.py` exposes `ios_runtime_health`, which reports whether optional OCR paths are available at runtime.

Additional MCP run-state tools:
- `ios_list_runs`
- `ios_replay_run`
