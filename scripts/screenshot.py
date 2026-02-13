"""Capture iOS Simulator screenshots via xcrun simctl."""

import json
import os
import re
import subprocess
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_output_dir(output_dir: str) -> str:
    return os.path.join(_PROJECT_ROOT, output_dir)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sanitize_label(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", label)


def capture(udid: str, output_dir: str = "_artifacts/") -> str | None:
    """Capture a simulator screenshot.

    Returns the absolute path to the saved PNG, or None on failure.
    """
    resolved_dir = _resolve_output_dir(output_dir)
    os.makedirs(resolved_dir, exist_ok=True)

    filename = f"screenshot_{_timestamp()}.png"
    dest = os.path.join(resolved_dir, filename)

    try:
        subprocess.run(
            ["xcrun", "simctl", "io", udid, "screenshot", dest],
            check=True,
            capture_output=True,
        )
        print(f"[screenshot] saved {dest}")
        return dest
    except subprocess.CalledProcessError as exc:
        print(f"[screenshot] capture failed: {exc.stderr.decode().strip()}")
        return None


def capture_with_label(
    udid: str, label: str, output_dir: str = "_artifacts/"
) -> str | None:
    """Capture a screenshot with a descriptive label baked into the filename."""
    resolved_dir = _resolve_output_dir(output_dir)
    os.makedirs(resolved_dir, exist_ok=True)

    safe_label = _sanitize_label(label)
    filename = f"screenshot_{safe_label}_{_timestamp()}.png"
    dest = os.path.join(resolved_dir, filename)

    try:
        subprocess.run(
            ["xcrun", "simctl", "io", udid, "screenshot", dest],
            check=True,
            capture_output=True,
        )
        print(f"[screenshot] saved {dest}")
        return dest
    except subprocess.CalledProcessError as exc:
        print(f"[screenshot] capture failed: {exc.stderr.decode().strip()}")
        return None


def save_tree_json(elements: list[dict], label: str, output_dir: str = "_artifacts/") -> str | None:
    """Save accessibility tree JSON alongside the screenshot PNG.

    Returns path to saved JSON file.
    """
    resolved_dir = _resolve_output_dir(output_dir)
    os.makedirs(resolved_dir, exist_ok=True)

    safe_label = _sanitize_label(label)
    filename = f"tree_{safe_label}_{_timestamp()}.json"
    dest = os.path.join(resolved_dir, filename)

    try:
        with open(dest, "w") as f:
            json.dump(elements, f, indent=1)
        print(f"[screenshot] saved tree {dest}")
        return dest
    except (OSError, TypeError) as exc:
        print(f"[screenshot] tree save failed: {exc}")
        return None
