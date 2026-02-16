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
import importlib
from types import ModuleType

# Ensure project root is on sys.path so scripts/ imports work
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
load_dotenv(os.path.expanduser("~/.env"))  # OpenAI key lives here

from scripts import agent_loop, dry_run, idbwrap, intel, run_report, run_state, screen_mapper, screenshot, simctl
from scripts import photo_sweep

_OPTIONAL_MODULE_CACHE: dict[str, tuple[ModuleType | None, str | None]] = {}


def _load_optional_module(module_name: str) -> tuple[ModuleType | None, str | None]:
    """Import an optional module once and cache the outcome."""
    cached = _OPTIONAL_MODULE_CACHE.get(module_name)
    if cached is not None:
        return cached

    try:
        module = importlib.import_module(module_name)
        result = (module, None)
    except Exception as exc:
        result = (None, str(exc))

    _OPTIONAL_MODULE_CACHE[module_name] = result
    return result


def _optional_feature_status(module_name: str) -> tuple[bool, str]:
    """Return availability status for an optional feature module."""
    module, error = _load_optional_module(module_name)
    if module is None:
        return False, error or "module import failed"

    check = getattr(module, "is_available", None)
    if callable(check):
        try:
            available, detail = check()
            return bool(available), str(detail)
        except Exception as exc:
            return False, f"capability check failed: {exc}"

    return True, "ok"

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
    safe_mode: bool = True,
    allow_tap_xy: bool = False,
    stop_after_step: int = 0,
    resume_run_id: str = "",
) -> str:
    """Run the autonomous agent loop with a plain-English goal.

    The agent reads the screen, reasons about what to do, takes an action,
    and repeats until the goal is achieved or max_steps is reached.

    Args:
        goal: Plain-English description of what to accomplish on the simulator.
        bundle_id: App bundle ID to launch (default: Safari).
        max_steps: Maximum number of agent iterations (default: 20).
        safe_mode: Enable policy guardrails (default: true).
        allow_tap_xy: Allow coordinate taps in safe mode (default: false).
        stop_after_step: Pause run after N steps (default: 0 disabled).
        resume_run_id: Resume an existing paused run ID (default: "").

    Returns:
        JSON string with keys: success, steps, summary, history.
    """
    udid = _ensure_simulator()
    result = agent_loop.run(
        goal=goal,
        udid=udid,
        bundle_id=bundle_id,
        max_steps=max_steps,
        safe_mode=safe_mode,
        allow_tap_xy=allow_tap_xy,
        stop_after_step=(stop_after_step if stop_after_step > 0 else None),
        resume_run_id=(resume_run_id or None),
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


@mcp.tool()
def ios_search_findings(query: str = "", category: str = "") -> str:
    """Search all iOS runner discoveries by keyword or category.

    Categories: network_config, device_settings, credentials, av_config,
    app_ui, photo_gallery, text_content

    Returns all matching findings (no limit).
    """
    results = intel.search_findings(query=query or None, category=category or None)
    return json.dumps(results, indent=2)


@mcp.tool()
def ios_recent_findings(count: int = 20) -> str:
    """Get the most recent iOS runner discoveries.

    Returns the last N findings with full details.
    """
    all_findings = intel.load_all_findings()
    recent = all_findings[-count:] if count < len(all_findings) else all_findings
    return json.dumps(recent, indent=2)


@mcp.tool()
def ios_runtime_health() -> str:
    """Report runtime capability status for optional OCR features."""
    vision_ok, vision_detail = _optional_feature_status("scripts.vision_extract")
    local_ok, local_detail = _optional_feature_status("scripts.local_ocr")

    return json.dumps({
        "python": sys.version.split()[0],
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "features": {
            "vision_extract": {
                "available": vision_ok,
                "detail": vision_detail,
            },
            "local_ocr": {
                "available": local_ok,
                "detail": local_detail,
            },
        },
    }, indent=2)


@mcp.tool()
def ios_list_runs(limit: int = 20) -> str:
    """List recent persisted autonomous runs."""
    return json.dumps(run_state.list_runs(limit=limit), indent=2)


@mcp.tool()
def ios_replay_run(run_id: str) -> str:
    """Replay stored telemetry/events for a run."""
    return json.dumps(run_state.replay_run(run_id), indent=2)


@mcp.tool()
def ios_dry_run_validate(run_id: str, strict: bool = False) -> str:
    """Validate a stored run without touching the simulator."""
    return json.dumps(dry_run.validate_run(run_id, strict=strict), indent=2)


@mcp.tool()
def ios_render_run_report(run_id: str) -> str:
    """Render an HTML report for a stored run and return its path."""
    path = run_report.render_run_report(run_id)
    if not path:
        return json.dumps({"error": "report render failed", "run_id": run_id}, indent=2)
    return json.dumps({"run_id": run_id, "report_path": path}, indent=2)


@mcp.tool()
def ios_sweep_photos(count: int = 50) -> str:
    """Sweep through Photos app, screenshotting each photo.

    Opens Photos, navigates to Recently Saved, taps the first photo,
    then swipes left and screenshots N times. No AI, no API calls.

    Args:
        count: Number of photos to capture (default: 50).

    Returns:
        JSON with list of screenshot paths captured.
    """
    paths = photo_sweep.sweep(count=count)
    return json.dumps({"captured": len(paths), "paths": paths}, indent=2)


@mcp.tool()
def ios_extract_photos(pattern: str = "screenshot_sweep_*_photo_*.png", limit: int = 0) -> str:
    """OCR all sweep screenshots via OpenAI vision and save findings to intel store.

    Reads PNGs from _artifacts/, sends each to gpt-4o-mini for text extraction,
    then feeds results through the intel pipeline. Free on OpenAI plan.

    Args:
        pattern: Glob pattern for sweep PNGs (default: all sweep photos).
        limit: Max images to process (0 = all).

    Returns:
        JSON summary of extraction results.
    """
    import glob as globmod

    module, module_error = _load_optional_module("scripts.vision_extract")
    if module is None:
        return json.dumps({
            "error": "Vision extraction unavailable",
            "detail": module_error or "module import failed",
        }, indent=2)

    feature_ok, feature_detail = _optional_feature_status("scripts.vision_extract")
    if not feature_ok:
        return json.dumps({
            "error": "Vision extraction unavailable",
            "detail": feature_detail,
        }, indent=2)

    artifacts_dir = os.path.join(_PROJECT_ROOT, "_artifacts")
    full_pattern = os.path.join(artifacts_dir, pattern)
    images = sorted(globmod.glob(full_pattern))

    if not images:
        return json.dumps({"error": f"No images found matching: {full_pattern}"})

    if limit > 0:
        images = images[:limit]

    results = module.process_batch(images, delay=0.3)

    ok = sum(1 for r in results if r.get("status") == "ok")
    failed = sum(1 for r in results if r.get("status") == "failed")
    empty = sum(1 for r in results if r.get("status") == "empty")

    return json.dumps({
        "processed": len(results),
        "extracted": ok,
        "failed": failed,
        "empty": empty,
        "results": results,
    }, indent=2)


@mcp.tool()
def ios_sweep_and_extract(count: int = 50) -> str:
    """Full pipeline: sweep Photos app then OCR everything. One command does it all.

    1. Opens Photos, swipes through N photos capturing screenshots
    2. Sends all captures through OpenAI vision for text extraction
    3. Feeds extracted text into intel pipeline for classification + persistence

    All findings saved to ~/.ulan/ios_intel.json and memory file.
    Uses OpenAI (free) for vision, no Anthropic API calls.

    Args:
        count: Number of photos to sweep (default: 50).

    Returns:
        JSON summary with sweep + extraction results.
    """
    module, module_error = _load_optional_module("scripts.vision_extract")
    if module is None:
        return json.dumps({
            "error": "Vision extraction unavailable",
            "detail": module_error or "module import failed",
        }, indent=2)

    feature_ok, feature_detail = _optional_feature_status("scripts.vision_extract")
    if not feature_ok:
        return json.dumps({
            "error": "Vision extraction unavailable",
            "detail": feature_detail,
        }, indent=2)

    # Step 1: Sweep
    paths = photo_sweep.sweep(count=count)
    if not paths:
        return json.dumps({"error": "Sweep captured no photos"})

    # Step 2: Extract
    results = module.process_batch(paths, delay=0.3)

    ok = sum(1 for r in results if r.get("status") == "ok")
    failed = sum(1 for r in results if r.get("status") == "failed")

    return json.dumps({
        "sweep_count": len(paths),
        "extracted": ok,
        "failed": failed,
        "total_findings": len(intel.load_all_findings()),
        "results": results,
    }, indent=2)


@mcp.tool()
def ios_local_ocr(pattern: str = "screenshot_sweep_*_photo_*.png") -> str:
    """OCR all sweep screenshots using local macOS Vision framework. No API calls, instant.

    Runs Apple's on-device text recognition (~0.3s/image). Processes only
    unprocessed photos (skips anything already in the intel store).

    Args:
        pattern: Glob pattern for PNGs in _artifacts/ (default: all sweep photos).

    Returns:
        JSON summary of extraction results.
    """
    import glob as globmod

    module, module_error = _load_optional_module("scripts.local_ocr")
    if module is None:
        return json.dumps({
            "error": "Local OCR unavailable",
            "detail": module_error or "module import failed",
        }, indent=2)

    feature_ok, feature_detail = _optional_feature_status("scripts.local_ocr")
    if not feature_ok:
        return json.dumps({
            "error": "Local OCR unavailable",
            "detail": feature_detail,
        }, indent=2)

    artifacts_dir = os.path.join(_PROJECT_ROOT, "_artifacts")
    full_pattern = os.path.join(artifacts_dir, pattern)
    images = sorted(globmod.glob(full_pattern))

    if not images:
        return json.dumps({"error": f"No images found matching: {full_pattern}"})

    # Skip already-processed
    existing = intel.load_all_findings()
    processed = {os.path.abspath(f.get("screenshot_path", "")) for f in existing if f.get("screenshot_path")}
    images = [p for p in images if os.path.abspath(p) not in processed]

    if not images:
        return json.dumps({"message": "All images already processed", "total_findings": len(existing)})

    import time
    start = time.time()
    results = module.process_batch(images)
    elapsed = time.time() - start

    ok = sum(1 for r in results if r.get("status") == "ok")
    empty = sum(1 for r in results if r.get("status") == "empty")

    return json.dumps({
        "processed": len(results),
        "extracted": ok,
        "empty": empty,
        "elapsed_seconds": round(elapsed, 1),
        "per_image_seconds": round(elapsed / max(len(results), 1), 2),
        "total_findings": len(intel.load_all_findings()),
    }, indent=2)


@mcp.tool()
def ios_sweep_and_ocr(count: int = 50) -> str:
    """Full pipeline: sweep Photos app then LOCAL OCR. One command, zero API calls.

    1. Opens Photos, swipes through N photos capturing screenshots
    2. Runs macOS Vision OCR locally (~0.3s/image, no network)
    3. Feeds extracted text into intel pipeline for classification + persistence

    All findings saved to ~/.ulan/ios_intel.json and memory file.

    Args:
        count: Number of photos to sweep (default: 50).

    Returns:
        JSON summary with sweep + OCR results.
    """
    import time

    module, module_error = _load_optional_module("scripts.local_ocr")
    if module is None:
        return json.dumps({
            "error": "Local OCR unavailable",
            "detail": module_error or "module import failed",
        }, indent=2)

    feature_ok, feature_detail = _optional_feature_status("scripts.local_ocr")
    if not feature_ok:
        return json.dumps({
            "error": "Local OCR unavailable",
            "detail": feature_detail,
        }, indent=2)

    # Step 1: Sweep
    paths = photo_sweep.sweep(count=count)
    if not paths:
        return json.dumps({"error": "Sweep captured no photos"})

    # Step 2: Local OCR
    start = time.time()
    results = module.process_batch(paths)
    elapsed = time.time() - start

    ok = sum(1 for r in results if r.get("status") == "ok")
    empty = sum(1 for r in results if r.get("status") == "empty")

    return json.dumps({
        "sweep_count": len(paths),
        "extracted": ok,
        "empty": empty,
        "ocr_seconds": round(elapsed, 1),
        "total_findings": len(intel.load_all_findings()),
        "results": results,
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
