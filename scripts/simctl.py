"""Wrapper around xcrun simctl for iOS Simulator management."""

import re
import subprocess
from typing import Optional


PREFERRED_DEVICE = "iPhone 17 Pro"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Run an xcrun simctl command and return the result."""
    cmd = ["xcrun", "simctl"] + args
    print(f"[simctl] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and result.stderr.strip():
        print(f"[simctl] stderr: {result.stderr.strip()}")
    return result


def get_booted_udid() -> Optional[str]:
    """Return the UDID of a currently booted simulator, or None."""
    result = _run(["list", "devices", "booted"])
    if result.returncode != 0:
        print("[simctl] Failed to list booted devices")
        return None

    # Match lines like:  iPhone 17 Pro (UDID) (Booted)
    pattern = re.compile(r"\s+.+\(([0-9A-F-]{36})\)\s+\(Booted\)")
    for line in result.stdout.splitlines():
        m = pattern.search(line)
        if m:
            udid = m.group(1)
            print(f"[simctl] Found booted simulator: {udid}")
            return udid

    print("[simctl] No booted simulator found")
    return None


def list_available() -> list[dict]:
    """List all available iPhone simulators.

    Returns list of dicts with keys: name, udid, state.
    """
    result = _run(["list", "devices", "available"])
    if result.returncode != 0:
        print("[simctl] Failed to list available devices")
        return []

    # Match lines like:  iPhone 17 Pro (50ADC92B-...) (Shutdown)
    pattern = re.compile(
        r"\s+(iPhone[^(]+?)\s+\(([0-9A-F-]{36})\)\s+\((\w+)\)"
    )
    devices = []
    for line in result.stdout.splitlines():
        m = pattern.search(line)
        if m:
            devices.append({
                "name": m.group(1).strip(),
                "udid": m.group(2),
                "state": m.group(3),
            })

    print(f"[simctl] Found {len(devices)} available iPhone simulator(s)")
    return devices


def boot_simulator(udid: Optional[str] = None) -> Optional[str]:
    """Boot a simulator and return its UDID.

    If udid is provided, boot that specific simulator.
    Otherwise, prefer PREFERRED_DEVICE, then fall back to first available iPhone.
    Returns the UDID on success, None on failure.
    """
    if udid is None:
        devices = list_available()
        if not devices:
            print("[simctl] No available iPhone simulators found")
            return None

        # Prefer the designated device
        target = None
        for d in devices:
            if d["name"] == PREFERRED_DEVICE:
                target = d
                break

        if target is None:
            target = devices[0]
            print(f"[simctl] Preferred device not found, using {target['name']}")

        # Already booted
        if target["state"] == "Booted":
            print(f"[simctl] {target['name']} already booted: {target['udid']}")
            return target["udid"]

        udid = target["udid"]
        print(f"[simctl] Selected {target['name']} ({udid})")

    print(f"[simctl] Booting simulator {udid}...")
    result = _run(["boot", udid])
    if result.returncode != 0:
        # "Unable to boot device in current state: Booted" is not a real error
        if "Booted" in result.stderr:
            print(f"[simctl] Simulator {udid} was already booted")
            return udid
        print(f"[simctl] Failed to boot simulator {udid}")
        return None

    print(f"[simctl] Successfully booted {udid}")
    return udid


def shutdown_simulator(udid: str) -> bool:
    """Shutdown a simulator by UDID. Returns True on success."""
    print(f"[simctl] Shutting down simulator {udid}...")
    result = _run(["shutdown", udid])
    if result.returncode != 0:
        if "current state: Shutdown" in result.stderr:
            print(f"[simctl] Simulator {udid} was already shut down")
            return True
        print(f"[simctl] Failed to shut down simulator {udid}")
        return False

    print(f"[simctl] Successfully shut down {udid}")
    return True


def ensure_booted() -> Optional[str]:
    """Ensure a simulator is booted. Returns its UDID, or None on failure."""
    udid = get_booted_udid()
    if udid:
        return udid

    print("[simctl] No booted simulator, attempting to boot one...")
    return boot_simulator()
