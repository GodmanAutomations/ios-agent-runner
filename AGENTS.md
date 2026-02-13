# iOS Agent Runner — Codex Instructions

## Project Overview
Autonomous iOS Simulator automation framework. Python 3.12, venv at `.venv/`.
Uses `fb-idb` and `xcrun simctl` to control an iOS simulator.
Has an intel pipeline that captures, classifies, and persists data from every screen.

## Key Files
- `scripts/intel.py` — Classification, extraction, persistence, search
- `scripts/vision_extract.py` — Batch OCR via OpenAI gpt-4o-mini vision
- `scripts/photo_sweep.py` — Dumb screenshot sweep (no AI, just swipe+capture)
- `scripts/agent_loop.py` — Autonomous agent loop (Claude-powered)
- `scripts/screenshot.py` — Screenshot capture + paired JSON tree dumps
- `mcp_server.py` — MCP server exposing tools to Claude Code
- `~/.ulan/ios_intel.json` — JSONL findings store (append-only)
- `~/.claude/projects/-Users-stephengodman/memory/ios-discoveries.md` — Memory file

## Working Conventions
- Python 3.12 type hints, 4-space indent, double quotes
- Always activate venv: `source .venv/bin/activate`
- Tests: none yet (priority candidate for you to build)
- Env vars in `.env` at project root (loaded via python-dotenv)

## Codex Workflow
1. Read PLAN.md for current state
2. Update PLAN.md with your approach
3. Execute the task
4. Run verification
5. Write RESULT.md
6. Create DONE.flag

## Forbidden
- Do NOT modify `.env` or any file containing API keys
- Do NOT push to git without explicit instruction
- Do NOT run the agent loop (it costs Anthropic API credits)
