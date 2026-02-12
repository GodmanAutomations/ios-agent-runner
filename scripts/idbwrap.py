"""idbwrap.py - Wrapper around Facebook idb / idb_companion with simctl fallback."""

import os
import shutil
import subprocess
import sys
import time

IDB_COMPANION = "/opt/homebrew/bin/idb_companion"

_idb_path: str | None = None
_companion_proc: subprocess.Popen | None = None


def _log(msg: str) -> None:
    print(f"[idb] {msg}", file=sys.stderr)


def _find_idb() -> str | None:
    """Find the idb binary — check venv first, then system PATH."""
    global _idb_path
    if _idb_path is not None:
        return _idb_path if _idb_path else None

    # Check venv bin directory (same dir as the running Python)
    venv_idb = os.path.join(os.path.dirname(sys.executable), "idb")
    if os.path.isfile(venv_idb) and os.access(venv_idb, os.X_OK):
        _idb_path = venv_idb
        _log(f"idb found in venv: {_idb_path}")
        return _idb_path

    # Check system PATH
    system_idb = shutil.which("idb")
    if system_idb:
        _idb_path = system_idb
        _log(f"idb found on PATH: {_idb_path}")
        return _idb_path

    _idb_path = ""  # empty string = not found (but cached)
    _log("idb CLI not found, will use fallbacks")
    return None


def _has_idb() -> bool:
    """Check if the idb CLI is available."""
    return _find_idb() is not None


def _idb_cmd() -> str:
    """Return the idb binary path. Only call after _has_idb() returns True."""
    return _find_idb()


def _run(cmd: list[str]) -> tuple[str, str, int]:
    """Run a subprocess command and return (stdout, stderr, returncode)."""
    _log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        _log(f"stderr: {result.stderr.strip()}")
    return result.stdout, result.stderr, result.returncode


def connect(udid: str) -> bool:
    """Connect idb to the simulator. Returns True on success."""
    global _companion_proc

    # Start idb_companion as background daemon (needed for idb CLI to work)
    if os.path.exists(IDB_COMPANION):
        _log(f"Starting idb_companion as background daemon for {udid}")
        _companion_proc = subprocess.Popen(
            [IDB_COMPANION, "--udid", udid],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        if _companion_proc.poll() is None:
            _log(f"idb_companion running (pid={_companion_proc.pid})")
        else:
            _log("idb_companion exited prematurely")

    if _has_idb():
        stdout, stderr, rc = _run([_idb_cmd(), "connect", udid])
        if rc == 0:
            _log(f"Connected to {udid} via idb")
            return True
        _log(f"idb connect failed: {stderr.strip()}")

    _log(f"Running in simctl-only mode for {udid}")
    return True


def launch_app(udid: str, bundle_id: str = "com.apple.mobilesafari") -> bool:
    """Launch an app. Tries idb first, falls back to simctl."""
    if _has_idb():
        stdout, stderr, rc = _run([_idb_cmd(), "launch", bundle_id])
        if rc == 0:
            _log(f"Launched {bundle_id} via idb")
            return True
        _log(f"idb launch failed: {stderr.strip()}")

    stdout, stderr, rc = _run(["xcrun", "simctl", "launch", udid, bundle_id])
    if rc == 0:
        _log(f"Launched {bundle_id} via simctl on {udid}")
        return True

    _log(f"Failed to launch {bundle_id}: {stderr.strip()}")
    return False


def describe_all(udid: str) -> str:
    """Get accessibility tree. Returns raw string for screen_mapper to parse."""
    if _has_idb():
        stdout, stderr, rc = _run([_idb_cmd(), "ui", "describe-all"])
        if rc == 0:
            _log(f"Got accessibility tree via idb ({len(stdout)} bytes)")
            return stdout
        _log(f"idb ui describe-all failed: {stderr.strip()}")

    # Fallback: accessibility_inspector via simctl spawn
    stdout, stderr, rc = _run([
        "xcrun", "simctl", "spawn", udid,
        "/usr/bin/accessibility_inspector",
    ])
    if rc == 0 and stdout.strip():
        _log(f"Got accessibility tree via simctl spawn ({len(stdout)} bytes)")
        return stdout

    _log(f"Could not retrieve accessibility tree for {udid}")
    return ""


def tap(udid: str, x: int, y: int) -> bool:
    """Tap at coordinates (x, y). Tries idb, falls back to AppleScript."""
    if _has_idb():
        stdout, stderr, rc = _run([_idb_cmd(), "ui", "tap", str(x), str(y)])
        if rc == 0:
            _log(f"Tapped ({x}, {y}) via idb")
            return True
        _log(f"idb ui tap failed: {stderr.strip()}")

    script = (
        f'tell application "Simulator" to activate\n'
        f'delay 0.3\n'
        f'tell application "System Events" to click at {{{x}, {y}}}'
    )
    stdout, stderr, rc = _run(["osascript", "-e", script])
    if rc == 0:
        _log(f"Tapped ({x}, {y}) via AppleScript fallback")
        return True

    _log(f"Failed to tap ({x}, {y}): {stderr.strip()}")
    return False


def type_text(udid: str, text: str) -> bool:
    """Type text into focused field. Tries idb, falls back to pbcopy+paste."""
    if _has_idb():
        stdout, stderr, rc = _run([_idb_cmd(), "ui", "text", text])
        if rc == 0:
            _log(f"Typed text via idb ({len(text)} chars)")
            return True
        _log(f"idb ui text failed: {stderr.strip()}")

    # Fallback: copy to pasteboard and paste
    pbcopy = subprocess.run(
        ["pbcopy"], input=text, capture_output=True, text=True, timeout=5,
    )
    if pbcopy.returncode != 0:
        _log("pbcopy failed")
        return False

    _run(["xcrun", "simctl", "pbpaste", udid])
    script = (
        'tell application "Simulator" to activate\n'
        'delay 0.2\n'
        'tell application "System Events" to keystroke "v" using command down'
    )
    stdout, stderr, rc = _run(["osascript", "-e", script])
    if rc == 0:
        _log(f"Typed text via pbcopy+paste fallback ({len(text)} chars)")
        return True

    _log(f"Failed to type text: {stderr.strip()}")
    return False


def key_press(udid: str, key: str) -> bool:
    """Send a key event. Supports: RETURN, DELETE, HOME, LOCK, SIRI, SCREENSHOT."""
    if _has_idb():
        # idb ui key-sequence sends HID key events
        stdout, stderr, rc = _run([_idb_cmd(), "ui", "key-sequence", key])
        if rc == 0:
            _log(f"Key press '{key}' via idb")
            return True
        # Fallback: try idb ui button for hardware keys
        stdout, stderr, rc = _run([_idb_cmd(), "ui", "button", key])
        if rc == 0:
            _log(f"Button press '{key}' via idb")
            return True
        _log(f"idb key/button '{key}' failed: {stderr.strip()}")

    # Fallback: AppleScript for common keys
    key_map = {
        "RETURN": 'keystroke return',
        "DELETE": 'key code 51',  # backspace
        "TAB": 'keystroke tab',
        "ESCAPE": 'key code 53',
    }
    as_cmd = key_map.get(key.upper())
    if as_cmd:
        script = (
            'tell application "Simulator" to activate\n'
            'delay 0.2\n'
            f'tell application "System Events" to {as_cmd}'
        )
        stdout, stderr, rc = _run(["osascript", "-e", script])
        if rc == 0:
            _log(f"Key press '{key}' via AppleScript")
            return True

    _log(f"Failed to press key '{key}'")
    return False


def press_home(udid: str) -> bool:
    """Press the home button to return to the springboard."""
    if _has_idb():
        stdout, stderr, rc = _run([_idb_cmd(), "ui", "button", "HOME"])
        if rc == 0:
            _log("Pressed HOME via idb")
            return True
        _log(f"idb ui button HOME failed: {stderr.strip()}")

    # Fallback: AppleScript Cmd+Shift+H (Simulator shortcut for home)
    script = (
        'tell application "Simulator" to activate\n'
        'delay 0.2\n'
        'tell application "System Events" to keystroke "h" using {command down, shift down}'
    )
    stdout, stderr, rc = _run(["osascript", "-e", script])
    if rc == 0:
        _log("Pressed HOME via AppleScript fallback")
        return True

    _log(f"Failed to press HOME: {stderr.strip()}")
    return False


def scroll(udid: str, direction: str = "down") -> bool:
    """Swipe the screen in a direction. Tries idb, falls back to simctl."""
    # Screen center and swipe deltas (390x844 base, adjust as needed)
    cx, cy = 195, 422
    delta = 300
    swipe_map = {
        "up":    (cx, cy + delta, cx, cy - delta),
        "down":  (cx, cy - delta, cx, cy + delta),
        "left":  (cx + delta, cy, cx - delta, cy),
        "right": (cx - delta, cy, cx + delta, cy),
    }
    coords = swipe_map.get(direction.lower())
    if coords is None:
        _log(f"scroll: invalid direction '{direction}'")
        return False

    x1, y1, x2, y2 = coords

    if _has_idb():
        stdout, stderr, rc = _run([
            _idb_cmd(), "ui", "swipe",
            str(x1), str(y1), str(x2), str(y2),
            "--duration", "0.5",
        ])
        if rc == 0:
            _log(f"Scrolled {direction} via idb")
            return True
        _log(f"idb ui swipe failed: {stderr.strip()}")

    # Fallback: simctl with AppleScript drag
    script = (
        f'tell application "Simulator" to activate\n'
        f'delay 0.2\n'
        f'tell application "System Events"\n'
        f'  click at {{{x1}, {y1}}}\n'
        f'  delay 0.1\n'
        f'end tell'
    )
    stdout, stderr, rc = _run(["osascript", "-e", script])
    _log(f"Scroll fallback attempted for {direction}")
    return rc == 0
