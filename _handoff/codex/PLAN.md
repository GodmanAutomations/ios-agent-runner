# PLAN

## Objective
- Execute the full productionization roadmap end-to-end:
  1. checkpoint baseline with tag
  2. real simulator smoke harness
  3. CI coverage for tests/imports
  4. run telemetry artifacts
  5. safe mode policy enforcement
  6. planner/executor split with persisted run state and resume/replay

## Plan (checklist)
- [x] Baseline commit + tag (`hardening-v1`)
- [ ] Add simulator smoke harness and run it locally
- [ ] Add CI workflow for tests + startup checks
- [ ] Add telemetry artifact pipeline for each agent run
- [ ] Add safe-mode policy layer and enforcement hooks
- [ ] Refactor agent loop into planner/executor phases with persisted state + resume/replay
- [ ] Add/extend tests for all new behavior
- [ ] Run full verification suite and refresh handoff artifacts

## Progress Log
- Existing hardening work landed and committed as `4e840dd`.
- Baseline checkpoint created: tag `hardening-v1`.
- Beginning phase-2 runtime architecture work on top of tagged baseline.

## Commands Run
- `cd /Users/stephengodman/ios-agent-runner && git add ... && git commit -m "chore(runtime): hardening baseline v1"`
- `cd /Users/stephengodman/ios-agent-runner && git tag -f hardening-v1`
- `cd /Users/stephengodman/ios-agent-runner && (append progress to _handoff/codex/LOG.txt)`

## Files Changed
- `_handoff/codex/PLAN.md`
- `_handoff/codex/LOG.txt`

## Remaining Work / Next Actions
- Build and run simulator smoke harness.
- Implement architecture upgrades and CI.
