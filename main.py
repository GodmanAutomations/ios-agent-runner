#!/usr/bin/env python3
"""iOS Agent Runner - CLI orchestrator for simulator automation.

Usage:
    python main.py --dump-tree
    python main.py --tap-text "Search" --type-text "openai.com" --screenshot
    python main.py --bundle-id com.apple.Preferences --dump-tree
"""

import argparse
import json
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from scripts import simctl, idbwrap, screen_mapper, navigator, run_state, screenshot
from scripts.device_config import DeviceConfig, detect

# Safari search bar alternatives for self-correction
SAFARI_ALTERNATIVES = [
    "Address",
    "Search or enter website name",
    "URL",
    "Search or Type URL",
    "Address and Search",
]


def log(msg: str) -> None:
    print(f"[main] {msg}", file=sys.stderr)


def boot_and_connect() -> tuple[str, DeviceConfig]:
    """Boot a simulator and connect idb. Returns (UDID, DeviceConfig) or exits."""
    log("Ensuring simulator is booted...")
    udid = simctl.ensure_booted()
    if not udid:
        print("FATAL: Could not boot any simulator", file=sys.stderr)
        sys.exit(1)
    log(f"Simulator UDID: {udid}")

    # Give the sim a moment to finish boot
    time.sleep(2)

    log("Connecting idb...")
    idbwrap.connect(udid)

    config = detect(udid)
    log(f"Screen: {config.width}x{config.height} @{config.scale}x")
    return udid, config


def do_dump_tree(udid: str, bundle_id: str) -> list[dict]:
    """Launch app, dump accessibility tree, return flattened elements."""
    log(f"Launching {bundle_id}...")
    idbwrap.launch_app(udid, bundle_id)
    time.sleep(3)  # Wait for app to render

    log("Dumping accessibility tree...")
    raw = idbwrap.describe_all(udid)
    if not raw:
        log("WARNING: Empty accessibility tree")
        return []

    tree = screen_mapper.parse_tree(raw)
    elements = screen_mapper.flatten_elements(tree)
    log(f"Found {len(elements)} UI elements")
    return elements


def do_tap(udid: str, tap_text: str, elements: list[dict]) -> list[dict]:
    """Tap an element by text with self-correction. Returns refreshed elements."""
    log(f"Attempting to tap: '{tap_text}'")
    success = navigator.tap_element(tap_text, elements, idbwrap, udid)

    if not success:
        log("Primary tap failed, entering self-correction loop...")
        success, matched, reasoning = navigator.retry_with_alternatives(
            tap_text,
            SAFARI_ALTERNATIVES,
            elements,
            idbwrap,
            udid,
            screen_mapper,
        )
        if success:
            log(f"Self-correction succeeded: {reasoning}")
        else:
            print(f"WARNING: Tap failed for '{tap_text}' and all alternatives", file=sys.stderr)
            print(f"Reasoning: {reasoning}", file=sys.stderr)
            return elements

    time.sleep(1)

    # Re-dump tree after tap (UI may have changed)
    log("Re-dumping tree after tap...")
    raw = idbwrap.describe_all(udid)
    if raw:
        tree = screen_mapper.parse_tree(raw)
        elements = screen_mapper.flatten_elements(tree)
    return elements


def do_type(udid: str, text: str) -> None:
    """Type text into the currently focused field."""
    log(f"Typing: '{text}'")
    idbwrap.type_text(udid, text)
    time.sleep(1)


def do_screenshot(udid: str) -> str | None:
    """Capture screenshot and return path."""
    log("Capturing screenshot...")
    path = screenshot.capture(udid)
    if path:
        log(f"Screenshot saved: {path}")
    else:
        log("WARNING: Screenshot capture failed")
    return path


def main():
    parser = argparse.ArgumentParser(
        description="iOS Agent Runner - Simulator automation via IDB + simctl"
    )
    parser.add_argument(
        "--bundle-id",
        default="com.apple.mobilesafari",
        help="App bundle ID to launch (default: Safari)",
    )
    parser.add_argument(
        "--dump-tree",
        action="store_true",
        help="Dump the accessibility tree as JSON",
    )
    parser.add_argument(
        "--tap-text",
        type=str,
        help="Tap element matching this text (fuzzy match)",
    )
    parser.add_argument(
        "--type-text",
        type=str,
        help="Type this text after tapping",
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        help="Capture a screenshot",
    )
    parser.add_argument(
        "--goal",
        type=str,
        help="Natural language goal — runs autonomous agent loop",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Max agent loop iterations (default: 20)",
    )
    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="Disable safe-mode policy guardrails in agent mode",
    )
    parser.add_argument(
        "--allow-tap-xy",
        action="store_true",
        help="Allow coordinate taps while in safe mode",
    )
    parser.add_argument(
        "--allow-bundle-prefix",
        action="append",
        default=[],
        help="Additional allowed bundle prefixes for safe mode (repeatable)",
    )
    parser.add_argument(
        "--resume-run-id",
        type=str,
        help="Resume a paused run by run ID",
    )
    parser.add_argument(
        "--stop-after-step",
        type=int,
        default=0,
        help="Pause the run after N steps (0 disables pause)",
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List recent persisted agent runs",
    )
    parser.add_argument(
        "--replay-run",
        type=str,
        help="Replay a persisted run by run ID",
    )
    parser.add_argument(
        "--dry-run-run-id",
        type=str,
        help="Validate a stored run without touching the simulator",
    )
    parser.add_argument(
        "--render-report",
        type=str,
        help="Render an HTML report for a stored run ID",
    )
    parser.add_argument(
        "--render-latest-report",
        action="store_true",
        help="Render an HTML report for the most recent run",
    )
    parser.add_argument(
        "--dry-run-latest",
        action="store_true",
        help="Dry-run validate the most recent run",
    )

    args = parser.parse_args()

    if args.list_runs:
        print(json.dumps(run_state.list_runs(limit=20), indent=2))
        sys.exit(0)

    if args.replay_run:
        print(json.dumps(run_state.replay_run(args.replay_run), indent=2))
        sys.exit(0)

    if args.dry_run_run_id:
        from scripts import dry_run

        report = dry_run.validate_run(args.dry_run_run_id, strict=False)
        print(json.dumps(report, indent=2))
        sys.exit(0 if report.get("ok") else 1)

    if args.render_report:
        from scripts import run_report

        path = run_report.render_run_report(args.render_report)
        if not path:
            print(json.dumps({"error": "report render failed", "run_id": args.render_report}, indent=2))
            sys.exit(1)
        print(json.dumps({"run_id": args.render_report, "report_path": path}, indent=2))
        sys.exit(0)

    if args.render_latest_report:
        from scripts import run_report

        latest = run_state.latest_run_id()
        if not latest:
            print(json.dumps({"error": "no runs found"}, indent=2))
            sys.exit(1)
        path = run_report.render_run_report(latest)
        if not path:
            print(json.dumps({"error": "report render failed", "run_id": latest}, indent=2))
            sys.exit(1)
        print(json.dumps({"run_id": latest, "report_path": path}, indent=2))
        sys.exit(0)

    if args.dry_run_latest:
        from scripts import dry_run

        latest = run_state.latest_run_id()
        if not latest:
            print(json.dumps({"error": "no runs found"}, indent=2))
            sys.exit(1)
        report = dry_run.validate_run(latest, strict=False)
        print(json.dumps(report, indent=2))
        sys.exit(0 if report.get("ok") else 1)

    # Agent mode: --goal bypasses manual flags
    if args.goal or args.resume_run_id:
        from scripts import agent_loop

        udid, config = boot_and_connect()
        result = agent_loop.run(
            goal=args.goal or "",
            udid=udid,
            bundle_id=args.bundle_id,
            max_steps=args.max_steps,
            config=config,
            safe_mode=not args.unsafe,
            resume_run_id=args.resume_run_id or None,
            stop_after_step=(args.stop_after_step if args.stop_after_step > 0 else None),
            allow_tap_xy=args.allow_tap_xy,
            allowed_bundle_prefixes=args.allow_bundle_prefix,
        )
        paused = bool(result.get("paused"))
        status = "PAUSED" if paused else ("SUCCESS" if result["success"] else "FAILED")
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"AGENT {status} in {result['steps']} steps", file=sys.stderr)
        print(f"Summary: {result['summary']}", file=sys.stderr)
        if result.get("run_id"):
            print(f"Run ID: {result['run_id']}", file=sys.stderr)
        if result.get("run_paths"):
            print(f"Run Artifacts: {result['run_paths']['run_dir']}", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)
        if paused:
            sys.exit(0)
        sys.exit(0 if result["success"] else 1)

    # Must specify at least one action
    if not any([args.dump_tree, args.tap_text, args.type_text, args.screenshot]):
        parser.print_help()
        sys.exit(1)

    # --- Orchestration ---
    warnings: list[str] = []

    # Boot + connect
    udid, config = boot_and_connect()

    # Dump tree (always needed if tapping or typing)
    elements = do_dump_tree(udid, args.bundle_id)
    if not elements:
        warnings.append("Accessibility tree was empty — interactions may fail")

    # Dump tree to stdout if requested
    if args.dump_tree:
        json_output = screen_mapper.dump_json(elements)
        print(json_output)

    # Tap
    if args.tap_text:
        elements = do_tap(udid, args.tap_text, elements)

    # Type
    if args.type_text:
        do_type(udid, args.type_text)

    # Screenshot
    screenshot_path = None
    if args.screenshot:
        screenshot_path = do_screenshot(udid)

    # --- Final report ---
    print("\n" + "=" * 60, file=sys.stderr)
    print("BUILD SUCCESS", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    if screenshot_path:
        print(f"Screenshot: {screenshot_path}", file=sys.stderr)

    if elements:
        preview = json.dumps(elements[:5], indent=2).splitlines()[:20]
        print("Accessibility JSON (first 20 lines):", file=sys.stderr)
        for line in preview:
            print(f"  {line}", file=sys.stderr)

    if warnings:
        print(f"\nWarnings ({len(warnings)}):", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)

    print("=" * 60, file=sys.stderr)


if __name__ == "__main__":
    main()
