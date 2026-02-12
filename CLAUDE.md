# iOS Agent Runner

Autonomous iOS Simulator automation framework. Uses Claude (Anthropic API) as the reasoning engine to control an iOS simulator through natural language goals. The agent reads the screen via accessibility trees, decides what to do, executes actions via IDB/simctl, and loops until the goal is met.

## Tech Stack

- Python 3.12 (venv at `.venv/`)
- `anthropic` SDK - Claude API for agent reasoning (model: `claude-sonnet-4-5-20250929`)
- `fb-idb` - Facebook's iOS Development Bridge for simulator interaction
- `xcrun simctl` - Apple's simulator CLI (fallback for all idb operations)
- `thefuzz` (with `rapidfuzz` speedup) - fuzzy text matching for UI elements
- `mcp` (FastMCP) - Model Context Protocol server for Claude Code integration
- `python-dotenv` - environment variable loading

## Prerequisites

- macOS with full Xcode installed (not just CommandLineTools)
- `xcode-select -s /Applications/Xcode.app/Contents/Developer`
- `brew install idb-companion`
- An iOS simulator available (prefers "iPhone 17 Pro")

## Setup

```bash
cd ~/ios-agent-runner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables

- `ANTHROPIC_API_KEY` - Required. Set in `.env` at project root. Loaded via `python-dotenv`.

## Running

### CLI mode (manual actions)
```bash
python main.py --dump-tree
python main.py --tap-text "Search" --type-text "openai.com" --screenshot
python main.py --bundle-id com.apple.Preferences --dump-tree
```

### Agent mode (autonomous goal execution)
```bash
python main.py --goal "Open Safari and search for weather in Austin"
python main.py --goal "Open Settings and turn on Dark Mode" --max-steps 25
```

### MCP server (for Claude Code integration)
```bash
python mcp_server.py
```

MCP config for `~/.claude/mcp_servers.json`:
```json
{
  "mcpServers": {
    "ios-agent": {
      "command": "/Users/stephengodman/ios-agent-runner/.venv/bin/python",
      "args": ["/Users/stephengodman/ios-agent-runner/mcp_server.py"],
      "cwd": "/Users/stephengodman/ios-agent-runner"
    }
  }
}
```

MCP tools exposed: `ios_run_goal`, `ios_screenshot`, `ios_dump_tree`.

## Tests

No tests exist yet. Priority candidates for unit tests:
- `scripts/screen_mapper.py` - frame parsing, tree flattening (pure functions, no simulator needed)
- `scripts/navigator.py` - fuzzy matching logic (`find_element`, `find_candidates`)

## Architecture

```
main.py                  CLI orchestrator (argparse). Routes to manual actions or agent_loop.
mcp_server.py            MCP server (FastMCP, stdio transport). Exposes 3 tools.
scripts/
  agent_loop.py          Core agent loop. Calls Claude with tool_use, executes actions, loops.
                         Includes stuck detection (tree hashing) and auto-recovery.
  simctl.py              Simulator management via xcrun simctl. Boot, shutdown, list devices.
  idbwrap.py             IDB wrapper with simctl/AppleScript fallbacks for every operation.
                         Handles: tap, type, scroll, key press, home, app launch, describe-all.
  screen_mapper.py       Parses accessibility trees (JSON or indented text) into flat element lists.
                         Extracts frames from multiple formats. Core data structure for the project.
  navigator.py           Fuzzy text matching (thefuzz/difflib). find_element, tap_element,
                         retry_with_alternatives (self-correction loop).
  screenshot.py          Screenshot capture via xcrun simctl io. Saves to _artifacts/.
_artifacts/              Output directory for screenshots (gitignored).
```

## Key Patterns

- **Fallback chains**: Every idb operation has a simctl or AppleScript fallback. See `idbwrap.py`.
- **Agent loop**: `agent_loop.run()` is the main entry point. Claude picks one tool per turn. Loop ends on `done`, `fail`, or max steps.
- **Stuck detection**: The agent hashes the accessibility tree each turn. If the tree is identical for 3 consecutive turns, or 3 consecutive tap failures occur, it triggers auto-recovery (scroll, tap Back/Close/Cancel).
- **Vision fallback**: When the accessibility tree has fewer than 3 labeled elements, a screenshot is sent to Claude as a base64 image for visual reasoning.
- **Logging**: All modules log to stderr with bracketed prefixes (`[main]`, `[agent]`, `[idb]`, `[nav]`, `[mapper]`, `[screenshot]`).

## Code Style

- Python 3.12 type hints throughout (`str | None`, `list[dict]`, `tuple[int, int]`)
- No type checker configured (no mypy/pyright config)
- No formatter configured (no ruff/black config). Code uses 4-space indentation, double quotes for strings.
- Docstrings on all public functions (imperative mood, brief)
- Constants at module top level (e.g., `MODEL`, `PREFERRED_DEVICE`, `SYSTEM_PROMPT`, `TOOLS`)
- `_log()` helper in every module, prints to stderr with module prefix
- `_run()` wrapper for subprocess calls in simctl/idbwrap
- Private functions prefixed with underscore
