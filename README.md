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
