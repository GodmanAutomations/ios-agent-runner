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
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts import idbwrap, screen_mapper, screenshot, simctl


def _log(msg: str) -> None:
    print(f"[smoke] {msg}", file=sys.stderr)


def _venv_python() -> str | None:
    path = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python")
    return path if os.path.exists(path) else None


def _run_mcp_checks_via_subprocess(bundle_id: str) -> tuple[bool, dict | str]:
    venv_py = _venv_python()
    if not venv_py:
        return False, "no .venv python found"

    code = (
        "import json\n"
        "import mcp_server\n"
        "health = json.loads(mcp_server.ios_runtime_health())\n"
        f"tree = json.loads(mcp_server.ios_dump_tree(bundle_id={bundle_id!r}))\n"
        "shot = mcp_server.ios_screenshot()\n"
        "payload = {\n"
        "  'health': health,\n"
        "  'tree_elements': len(tree),\n"
        "  'screenshot_path': shot,\n"
        "}\n"
        "print('__MCP_JSON_START__')\n"
        "print(json.dumps(payload))\n"
        "print('__MCP_JSON_END__')\n"
    )

    proc = subprocess.run(
        [venv_py, "-c", code],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return False, (proc.stderr.strip() or proc.stdout.strip() or "mcp check subprocess failed")

    marker_start = "__MCP_JSON_START__"
    marker_end = "__MCP_JSON_END__"
    out = proc.stdout
    start = out.find(marker_start)
    end = out.rfind(marker_end)
    if start == -1 or end == -1 or end <= start:
        return False, "mcp check subprocess returned invalid json markers"
    json_text = out[start + len(marker_start):end].strip()
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return False, "mcp check subprocess returned invalid json payload"

    return True, payload


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

    # MCP tool checks: attempt in-process import first, then fall back to venv subprocess.
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
    except Exception:
        ok_sub, payload = _run_mcp_checks_via_subprocess(bundle_id=bundle_id)
        if not ok_sub:
            report["errors"].append(f"mcp tool checks failed: {payload}")
        else:
            report["checks"]["mcp_runtime_health"] = bool(payload["health"].get("features"))
            report["checks"]["mcp_dump_tree_elements"] = int(payload["tree_elements"])
            mcp_shot = payload.get("screenshot_path", "")
            report["checks"]["mcp_screenshot_saved"] = bool(mcp_shot and os.path.exists(mcp_shot))
            if not report["checks"]["mcp_screenshot_saved"]:
                report["errors"].append("mcp screenshot tool failed (subprocess)")
            if not report["checks"]["mcp_dump_tree_elements"]:
                report["errors"].append("mcp dump_tree returned empty list (subprocess)")

    ok = not report["errors"]
    report["ok"] = ok
    return ok, report


def main() -> int:
    ok, report = run()
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
