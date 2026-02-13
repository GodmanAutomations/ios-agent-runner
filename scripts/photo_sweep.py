"""photo_sweep.py - Dumb sweep of Photos app: open, navigate to photos, swipe+screenshot N times.

No AI. No API calls. Just a for loop that captures everything.
Run the intel extraction pass separately afterward.
"""

import sys
import time

from scripts import idbwrap, screenshot, simctl, screen_mapper
from scripts.device_config import detect


def _log(msg: str) -> None:
    print(f"[sweep] {msg}", file=sys.stderr)


def _get_elements(udid: str) -> list[dict]:
    """Dump and flatten the accessibility tree."""
    raw = idbwrap.describe_all(udid)
    tree = screen_mapper.parse_tree(raw)
    return screen_mapper.flatten_elements(tree)


def _get_labels(elements: list[dict]) -> list[str]:
    """Extract all labels from elements."""
    return [el.get("label") or el.get("name") or "" for el in elements if el.get("label") or el.get("name")]


def _tap_element(udid: str, elements: list[dict], label_text: str) -> bool:
    """Find element by label and tap its center. Returns True if found."""
    for el in elements:
        if el.get("label") == label_text:
            frame = el.get("frame", {})
            x = int(frame.get("x", 0) + frame.get("width", 0) / 2)
            y = int(frame.get("y", 0) + frame.get("height", 0) / 2)
            idbwrap.tap(udid, x, y)
            return True
    return False


def _is_fullscreen_photo(elements: list[dict]) -> bool:
    """Check if we're in full-screen photo view."""
    labels = _get_labels(elements)
    return "Photo chooser" in labels or "Delete" in labels


def _is_collections_root(elements: list[dict]) -> bool:
    """Check if we're at the Collections root with album tiles."""
    labels = _get_labels(elements)
    return "Recently Saved" in labels or "Favorites" in labels


def _navigate_to_fullscreen(udid: str) -> bool:
    """From any state, navigate to a full-screen photo view. Returns True on success."""
    for attempt in range(10):
        elements = _get_elements(udid)
        labels = _get_labels(elements)

        # Already in full-screen photo view
        if _is_fullscreen_photo(elements):
            _log("Already in full-screen photo view")
            return True

        # In a photo grid (has Image "Photo" tiles)
        photos = [el for el in elements if el.get("type") == "Image" and "Photo" in (el.get("label") or "")]
        if photos:
            _log(f"In photo grid with {len(photos)} photos — tapping first")
            frame = photos[0].get("frame", {})
            x = int(frame.get("x", 0) + frame.get("width", 0) / 2)
            y = int(frame.get("y", 0) + frame.get("height", 0) / 2)
            idbwrap.tap(udid, x, y)
            time.sleep(1.5)
            continue

        # At Collections root — tap Recently Saved
        if _is_collections_root(elements):
            _log("At Collections root — tapping Recently Saved")
            if _tap_element(udid, elements, "Recently Saved"):
                time.sleep(2)
                continue
            # Fallback to Favorites
            if _tap_element(udid, elements, "Favorites"):
                time.sleep(2)
                continue

        # In some nested view — try Back button
        if _tap_element(udid, elements, "Back"):
            _log("Tapping Back...")
            time.sleep(1)
            continue

        # Unknown state — try pressing Home and relaunching
        _log(f"Unknown state (attempt {attempt + 1}), pressing Home...")
        idbwrap.press_home(udid)
        time.sleep(1)
        idbwrap.launch_app(udid, "com.apple.mobileslideshow")
        time.sleep(3)

    _log("ERROR: Could not navigate to full-screen photo view")
    return False


def sweep(count: int = 50, start_delay: float = 4.0) -> list[str]:
    """Open Photos, navigate to a photo, swipe left + screenshot N times.

    Returns list of screenshot paths captured.
    """
    udid = simctl.ensure_booted()
    if not udid:
        _log("No simulator booted")
        return []

    idbwrap.connect(udid)
    config = detect(udid)
    _log(f"Simulator: {udid} ({config.width}x{config.height} @{config.scale}x)")

    # Launch Photos (or resume it)
    _log("Launching Photos app...")
    idbwrap.launch_app(udid, "com.apple.mobileslideshow")
    time.sleep(start_delay)

    # Navigate to full-screen photo view
    if not _navigate_to_fullscreen(udid):
        return []

    paths: list[str] = []

    # Sweep: screenshot current, swipe left to next
    for i in range(1, count + 1):
        _log(f"--- Photo {i}/{count} ---")

        # Capture current photo
        path = screenshot.capture_with_label(udid, f"sweep_{i:03d}_photo")
        if path:
            paths.append(path)

        # Swipe left to next (older) photo
        idbwrap.scroll(udid, "left", config=config)
        time.sleep(0.8)

    _log(f"Sweep complete: {len(paths)} screenshots captured")
    return paths


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sweep Photos app screenshots")
    parser.add_argument("-n", "--count", type=int, default=50, help="Number of photos to capture")
    args = parser.parse_args()

    paths = sweep(count=args.count)
    print(f"\nCaptured {len(paths)} screenshots:")
    for p in paths:
        print(f"  {p}")
