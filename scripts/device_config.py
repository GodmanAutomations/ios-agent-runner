"""device_config.py - Runtime screen dimension detection for iOS simulators."""

import json
import subprocess
import sys
from dataclasses import dataclass

# Known screen dimensions (points) by simctl device type suffix.
# Source: Apple Human Interface Guidelines / Simulator specs.
_KNOWN_DIMENSIONS: dict[str, tuple[int, int, int]] = {
    # (width, height, scale)
    "iPhone-17-Pro": (402, 874, 3),
    "iPhone-17-Pro-Max": (440, 956, 3),
    "iPhone-17": (402, 874, 3),
    "iPhone-Air": (420, 912, 3),
    "iPhone-16e": (390, 844, 3),
    "iPhone-16-Pro": (402, 874, 3),
    "iPhone-16-Pro-Max": (440, 956, 3),
    "iPhone-16": (393, 852, 3),
    "iPhone-16-Plus": (430, 932, 3),
    "iPhone-15-Pro": (393, 852, 3),
    "iPhone-15-Pro-Max": (430, 932, 3),
    "iPhone-15": (393, 852, 3),
    "iPhone-15-Plus": (430, 932, 3),
    "iPhone-14-Pro": (393, 852, 3),
    "iPhone-14-Pro-Max": (430, 932, 3),
    "iPhone-14": (390, 844, 3),
    "iPhone-14-Plus": (428, 926, 3),
    "iPhone-13-Pro": (390, 844, 3),
    "iPhone-13-Pro-Max": (428, 926, 3),
    "iPhone-13": (390, 844, 3),
    "iPhone-13-mini": (375, 812, 3),
    "iPhone-SE-3rd-generation": (375, 667, 2),
}

_cache: dict[str, "DeviceConfig"] = {}


def _log(msg: str) -> None:
    print(f"[device_config] {msg}", file=sys.stderr)


@dataclass(frozen=True)
class DeviceConfig:
    """Screen geometry for an iOS simulator device."""

    width: int
    height: int
    scale: int
    center_x: int
    center_y: int
    swipe_delta: int

    @staticmethod
    def from_dimensions(width: int, height: int, scale: int = 3) -> "DeviceConfig":
        """Build a DeviceConfig from raw width/height/scale."""
        return DeviceConfig(
            width=width,
            height=height,
            scale=scale,
            center_x=width // 2,
            center_y=height // 2,
            swipe_delta=int(height * 0.35),
        )


def _device_type_for_udid(udid: str) -> str | None:
    """Look up device type string via simctl list devices -j."""
    try:
        result = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "-j"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for runtime, devices in data.get("devices", {}).items():
            for dev in devices:
                if dev.get("udid") == udid:
                    # deviceTypeIdentifier looks like:
                    # com.apple.CoreSimulator.SimDeviceType.iPhone-15-Pro
                    dt = dev.get("deviceTypeIdentifier", "")
                    suffix = dt.rsplit(".", 1)[-1] if "." in dt else ""
                    return suffix
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        pass
    return None


def _detect_via_idb(udid: str, idb_path: str | None = None) -> tuple[int, int, int] | None:
    """Try idb describe to get screen dimensions."""
    if idb_path is None:
        return None
    try:
        result = subprocess.run(
            [idb_path, "describe", "--udid", udid, "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        info = json.loads(result.stdout)
        dims = info.get("screen_dimensions", {})
        w = dims.get("width")
        h = dims.get("height")
        density = dims.get("density")
        if w and h:
            scale = density if density else 3
            # idb reports pixel dimensions; convert to points
            return (w // scale, h // scale, scale)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        pass
    return None


def detect(udid: str, idb_path: str | None = None) -> DeviceConfig:
    """Detect screen dimensions for a simulator UDID. Caches per UDID."""
    if udid in _cache:
        return _cache[udid]

    # Strategy 1: simctl device type → known dimensions lookup
    device_type = _device_type_for_udid(udid)
    if device_type and device_type in _KNOWN_DIMENSIONS:
        w, h, s = _KNOWN_DIMENSIONS[device_type]
        _log(f"Detected {device_type}: {w}x{h} @{s}x (simctl lookup)")
        cfg = DeviceConfig.from_dimensions(w, h, s)
        _cache[udid] = cfg
        return cfg

    # Strategy 2: idb describe
    dims = _detect_via_idb(udid, idb_path)
    if dims:
        w, h, s = dims
        _log(f"Detected {w}x{h} @{s}x (idb describe)")
        cfg = DeviceConfig.from_dimensions(w, h, s)
        _cache[udid] = cfg
        return cfg

    # Fallback: 390x844 (iPhone 14 Pro / 13 Pro baseline)
    _log("WARNING: Could not detect screen dimensions, using 390x844 default")
    cfg = DeviceConfig.from_dimensions(390, 844, 3)
    _cache[udid] = cfg
    return cfg
