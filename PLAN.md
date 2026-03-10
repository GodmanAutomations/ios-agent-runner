# PLAN — ios-agent-runner

## Objective

Add a local-model-first provider strategy for the autonomous runner so non-costly tool-calling loops can run on local Qwen by default, with explicit Anthropic fallback support.

## Deliverables

- Add provider configuration in `scripts/agent_loop.py`:
  - `AGENT_LOOP_PROVIDER`/`--provider` support (`local_qwen`, `anthropic`)
  - robust call adapters for Anthropic tool API and OpenAI-compatible local tool-calling
  - automatic provider fallback telemetry for each run
- Update run-state schema to persist provider metadata and fallback metrics.
- Add CLI and MCP flags for provider selection and fallback behavior.
- Update README and usage notes with local LLM setup.

## Work Checklist

- [x] Add provider normalization + local model call adapter in `scripts/agent_loop.py`.
- [x] Thread provider/fallback options through `scripts/agent_loop.run`.
- [x] Add CLI `--provider` and `--no-fallback` flags in `main.py`.
- [x] Add MCP `provider` + `allow_fallback` args on `ios_run_goal`.
- [x] Update README guidance around `.env` config and provider behavior.
- [x] Update run-state persistence to track chosen provider and fallback usage.
- [ ] Add a focused test for provider normalization and OpenAI-tool payload conversion (non-executable in this pass, optional).

## Objective

Add an "ops digest" command that turns the existing integrations (Notion/Linear/Sentry/Figma),
local machine health, and repo status into one repeatable report.

This is meant to answer: "what is possible now that the keys + agents exist?"

## Deliverables

- `scripts/ops_digest.py`
  - Generates a Markdown + JSON report under `~/.claude/projects/-Users-stephengodman/memory/`
  - Smoke-checks:
    - integrations (Notion/Linear/Sentry/Figma)
    - git status across core repos
    - tailscale peer visibility
    - adb device list (read-only; do not disrupt existing ADB sessions)
    - pi5 ssh reachability (non-interactive check; no prompts)
    - launchagents + mcp server config sanity
  - Optional:
    - publish report to Notion (create a page)
    - create a Linear issue when the digest finds problems
- `scripts/notion_control_hub.py`
  - Creates a multi-page Notion “Stephen Control Hub” from local project docs + memory files
  - Requires a parent Notion page shared with the `Ios Agent Runner` integration (page URL accepted)
- `tests/test_ops_digest.py`
  - Pure parsing tests + minimal smoke test with monkeypatches (no network).

## Verification

- `source .venv/bin/activate && pytest tests/ -v --tb=short`
- `python scripts/ops_digest.py --no-network` (local-only run)
- `python scripts/notion_control_hub.py --parent-url '<url>' --publish`
