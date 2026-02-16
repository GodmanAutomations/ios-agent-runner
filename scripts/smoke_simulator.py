#!/usr/bin/env python3
"""Local simulator smoke harness for ios-agent-runner.

Runs non-destructive checks against a booted simulator:
- simulator boot/connect
- app launch + tree dump
- screenshot capture
- MCP helper tools (`ios_runtime_health`, `ios_dump_tree`, `ios_screenshot`)

Does NOT run the autonomous goal loop.
"""

import json
import os
import sys
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts import idbwrap, screen_mapper, screenshot, simctl


def _log(msg: str) -> None:
    print(f"[smoke] {msg}", file=sys.stderr)


def run(bundle_id: str = "com.apple.Preferences") -> tuple[bool, dict]:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bundle_id": bundle_id,
        "checks": {},
        "errors": [],
    }

    udid = simctl.ensure_booted()
    if not udid:
        report["errors"].append("no simulator could be booted")
        return False, report
    report["udid"] = udid
    report["checks"]["booted"] = True

    report["checks"]["idb_connect"] = bool(idbwrap.connect(udid))

    launched = idbwrap.launch_app(udid, bundle_id)
    report["checks"]["launch_app"] = bool(launched)
    if not launched:
        report["errors"].append(f"failed to launch {bundle_id}")
        return False, report

    raw = idbwrap.describe_all(udid)
    tree = screen_mapper.flatten_elements(screen_mapper.parse_tree(raw)) if raw else []
    report["checks"]["tree_elements"] = len(tree)
    if not tree:
        report["errors"].append("empty accessibility tree after app launch")

    shot = screenshot.capture_with_label(udid, "smoke_check")
    report["checks"]["screenshot_saved"] = bool(shot and os.path.exists(shot))
    report["screenshot_path"] = shot or ""
    if not report["checks"]["screenshot_saved"]:
        report["errors"].append("screenshot capture failed")

    try:
        import mcp_server

        health = json.loads(mcp_server.ios_runtime_health())
        mcp_tree = json.loads(mcp_server.ios_dump_tree(bundle_id=bundle_id))
        mcp_shot = mcp_server.ios_screenshot()
        report["checks"]["mcp_runtime_health"] = bool(health.get("features"))
        report["checks"]["mcp_dump_tree_elements"] = len(mcp_tree)
        report["checks"]["mcp_screenshot_saved"] = bool(mcp_shot and os.path.exists(mcp_shot))
        if not report["checks"]["mcp_screenshot_saved"]:
            report["errors"].append("mcp screenshot tool failed")
        if not report["checks"]["mcp_dump_tree_elements"]:
            report["errors"].append("mcp dump_tree returned empty list")
    except Exception as exc:
        report["errors"].append(f"mcp tool checks failed: {exc}")

    ok = not report["errors"]
    report["ok"] = ok
    return ok, report


def main() -> int:
    ok, report = run()
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
