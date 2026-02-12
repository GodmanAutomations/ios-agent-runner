#!/usr/bin/env python3
"""MCP server wrapper for ios-agent-runner.

Exposes the iOS simulator agent as tools callable from Claude Code
via the Model Context Protocol (stdio transport).

Sample config for ~/.claude/mcp_servers.json:

    {
      "mcpServers": {
        "ios-agent": {
          "command": "/Users/stephengodman/ios-agent-runner/.venv/bin/python",
          "args": ["/Users/stephengodman/ios-agent-runner/mcp_server.py"],
          "cwd": "/Users/stephengodman/ios-agent-runner"
        }
      }
    }

Run standalone:  python mcp_server.py
"""

import json
import os
import sys
import time

# Ensure project root is on sys.path so scripts/ imports work
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from scripts import agent_loop, idbwrap, screen_mapper, screenshot, simctl

# ---------------------------------------------------------------------------
# Lazy simulator connection
# ---------------------------------------------------------------------------

_udid: str | None = None


def _ensure_simulator() -> str:
    """Boot and connect to the simulator on first call. Returns UDID."""
    global _udid
    if _udid is not None:
        return _udid

    udid = simctl.ensure_booted()
    if not udid:
        raise RuntimeError("Could not boot any iOS simulator")

    time.sleep(2)
    idbwrap.connect(udid)
    _udid = udid
    return _udid


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ios-agent",
    instructions="iOS Simulator automation — run goals, capture screenshots, dump accessibility trees",
)


@mcp.tool()
def ios_run_goal(
    goal: str,
    bundle_id: str = "com.apple.mobilesafari",
    max_steps: int = 20,
) -> str:
    """Run the autonomous agent loop with a plain-English goal.

    The agent reads the screen, reasons about what to do, takes an action,
    and repeats until the goal is achieved or max_steps is reached.

    Args:
        goal: Plain-English description of what to accomplish on the simulator.
        bundle_id: App bundle ID to launch (default: Safari).
        max_steps: Maximum number of agent iterations (default: 20).

    Returns:
        JSON string with keys: success, steps, summary, history.
    """
    udid = _ensure_simulator()
    result = agent_loop.run(
        goal=goal,
        udid=udid,
        bundle_id=bundle_id,
        max_steps=max_steps,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def ios_screenshot() -> str:
    """Capture a screenshot of the current iOS simulator screen.

    Returns:
        Path to the saved PNG screenshot file.
    """
    udid = _ensure_simulator()
    path = screenshot.capture(udid)
    if not path:
        raise RuntimeError("Screenshot capture failed")
    return path


@mcp.tool()
def ios_dump_tree(bundle_id: str = "com.apple.mobilesafari") -> str:
    """Dump the current accessibility tree of the simulator screen.

    Launches the specified app (if not already running) and returns a
    JSON representation of all visible UI elements.

    Args:
        bundle_id: App bundle ID to inspect (default: Safari).

    Returns:
        JSON accessibility tree with element types, labels, and frames.
    """
    udid = _ensure_simulator()

    idbwrap.launch_app(udid, bundle_id)
    time.sleep(2)

    raw = idbwrap.describe_all(udid)
    if not raw:
        return json.dumps([])

    tree = screen_mapper.parse_tree(raw)
    elements = screen_mapper.flatten_elements(tree)

    compact = []
    for el in elements:
        entry = {"type": el.get("type", "Unknown")}
        for key in ("label", "name", "value", "title"):
            if el.get(key):
                entry[key] = el[key]
        if el.get("frame"):
            f = el["frame"]
            if f.get("width", 0) > 0 or f.get("height", 0) > 0:
                entry["frame"] = f
        compact.append(entry)

    return json.dumps(compact, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
