"""Dry-run validation for persisted autonomous runs.

Validates a stored run without touching the simulator:
- policy compliance (safe mode)
- required artifact file existence (screenshots/trees if recorded)
"""

import os

from scripts import run_state
from scripts.safe_mode import SafeModePolicy


def validate_run(run_id: str, strict: bool = False) -> dict:
    """Validate a run and return a machine-readable report."""
    state = run_state.load_state(run_id)
    if state is None:
        return {"run_id": run_id, "ok": False, "errors": [f"run '{run_id}' not found"]}

    safe_mode = bool(state.get("safe_mode", True))
    policy = SafeModePolicy() if safe_mode else SafeModePolicy.disabled()

    policy_cfg = state.get("policy", {}) if isinstance(state.get("policy", {}), dict) else {}
    if policy_cfg.get("allow_tap_xy") is True:
        policy.allow_tap_xy = True
    allowed_prefixes = policy_cfg.get("allowed_bundle_prefixes")
    if isinstance(allowed_prefixes, list) and allowed_prefixes:
        policy.allowed_bundle_prefixes = tuple(str(x) for x in allowed_prefixes)

    errors: list[str] = []
    warnings: list[str] = []

    history = state.get("history", [])
    if not isinstance(history, list):
        history = []

    counts = {
        "steps": 0,
        "policy_blocks": 0,
        "policy_violations": 0,
        "missing_screenshots": 0,
        "missing_trees": 0,
    }

    for row in history:
        if not isinstance(row, dict):
            continue
        counts["steps"] += 1
        tool = str(row.get("tool", ""))
        params = row.get("params", {})
        if not isinstance(params, dict):
            params = {}

        # Internal bookkeeping steps aren't policy actions.
        if tool.startswith("_"):
            continue

        allowed, reason = policy.validate_action(tool, params)
        if not allowed:
            counts["policy_violations"] += 1
            msg = f"step {row.get('step')}: policy violation for '{tool}': {reason}"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)

        result = str(row.get("result", ""))
        if result.startswith("POLICY BLOCKED"):
            counts["policy_blocks"] += 1

        screenshot_path = str(row.get("screenshot_path", "") or "")
        if screenshot_path:
            if not os.path.exists(screenshot_path):
                counts["missing_screenshots"] += 1
                errors.append(f"step {row.get('step')}: missing screenshot_path: {screenshot_path}")
        elif strict:
            warnings.append(f"step {row.get('step')}: no screenshot_path recorded")

        tree_path = str(row.get("tree_path", "") or "")
        if tree_path:
            if not os.path.exists(tree_path):
                counts["missing_trees"] += 1
                errors.append(f"step {row.get('step')}: missing tree_path: {tree_path}")
        elif strict:
            warnings.append(f"step {row.get('step')}: no tree_path recorded")

    ok = not errors
    return {
        "run_id": run_id,
        "ok": ok,
        "safe_mode": safe_mode,
        "status": state.get("status", "unknown"),
        "goal": state.get("goal", ""),
        "bundle_id": state.get("bundle_id", ""),
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
    }
