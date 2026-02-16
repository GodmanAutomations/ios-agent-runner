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
