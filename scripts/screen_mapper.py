"""screen_mapper.py - Parse idb/simctl accessibility trees into flat UI element lists.

Accepts raw output from `idb ui describe-all` or `simctl accessibility` and
normalizes it into a flat list of dicts suitable for element lookup and tap
coordinate calculation.
"""

import json
import re
import sys


_PREFIX = "[mapper]"


def _log(msg: str) -> None:
    print(f"{_PREFIX} {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Frame / rect parsing
# ---------------------------------------------------------------------------

_FRAME_CURLY_RE = re.compile(
    r"\{\{([\d.]+),\s*([\d.]+)\},\s*\{([\d.]+),\s*([\d.]+)\}\}"
)

_FRAME_PAREN_RE = re.compile(
    r"\(([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\)"
)


def _parse_frame_string(raw: str) -> dict | None:
    """Try to extract {x, y, width, height} from various string formats."""
    if not raw:
        return None

    m = _FRAME_CURLY_RE.search(raw)
    if m:
        return {
            "x": float(m.group(1)),
            "y": float(m.group(2)),
            "width": float(m.group(3)),
            "height": float(m.group(4)),
        }

    m = _FRAME_PAREN_RE.search(raw)
    if m:
        return {
            "x": float(m.group(1)),
            "y": float(m.group(2)),
            "width": float(m.group(3)),
            "height": float(m.group(4)),
        }

    return None


def _parse_frame_dict(d: dict) -> dict | None:
    """Handle dict-style frames like {"X": n, "Y": n, "Width": n, "Height": n}."""
    if not isinstance(d, dict):
        return None

    # Try various key casings
    for keys in [
        ("X", "Y", "Width", "Height"),
        ("x", "y", "width", "height"),
        ("x", "y", "w", "h"),
    ]:
        if all(k in d for k in keys):
            return {
                "x": float(d[keys[0]]),
                "y": float(d[keys[1]]),
                "width": float(d[keys[2]]),
                "height": float(d[keys[3]]),
            }

    return None


def _extract_frame(node: dict) -> dict | None:
    """Pull a frame from a node, checking common key names."""
    for key in ("frame", "rect", "bounds", "Frame", "Rect", "Bounds"):
        val = node.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            result = _parse_frame_string(val)
            if result:
                return result
        elif isinstance(val, dict):
            result = _parse_frame_dict(val)
            if result:
                return result
            # Nested origin/size format: {"origin": {"x":..,"y":..}, "size": {"width":..,"height":..}}
            origin = val.get("origin") or val.get("Origin") or {}
            size = val.get("size") or val.get("Size") or {}
            if origin and size:
                try:
                    return {
                        "x": float(origin.get("x", origin.get("X", 0))),
                        "y": float(origin.get("y", origin.get("Y", 0))),
                        "width": float(size.get("width", size.get("Width", size.get("w", 0)))),
                        "height": float(size.get("height", size.get("Height", size.get("h", 0)))),
                    }
                except (TypeError, ValueError):
                    pass
    return None


# ---------------------------------------------------------------------------
# Indented-text tree parser
# ---------------------------------------------------------------------------

_INDENT_NODE_RE = re.compile(
    r"^(?P<indent>\s*)(?P<type>\w+)"
    r"(?:\s*[:\-]\s*(?P<rest>.*))?$"
)

_KV_RE = re.compile(r"(\w+)\s*[:=]\s*['\"]?([^'\",}]+)['\"]?")


def _parse_text_tree(raw_text: str) -> list[dict]:
    """Parse indented text accessibility output into a nested structure.

    Each line is expected to look roughly like:
        Button: label='OK' frame={{10, 20}, {80, 30}}
    or:
        StaticText 'Hello World' {{0, 0}, {100, 20}}
    """
    lines = raw_text.strip().splitlines()
    if not lines:
        return []

    root_children: list[dict] = []
    stack: list[tuple[int, dict]] = []  # (indent_level, node)

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            continue

        indent = len(stripped) - len(stripped.lstrip())
        m = _INDENT_NODE_RE.match(stripped)
        if not m:
            continue

        node_type = m.group("type")
        rest = m.group("rest") or ""

        node: dict = {"type": node_type, "children": []}

        # Extract key=value pairs from the rest of the line
        for kv_match in _KV_RE.finditer(rest):
            node[kv_match.group(1).lower()] = kv_match.group(2).strip()

        # Try to find a frame in the rest of the line
        frame = _parse_frame_string(rest)
        if frame:
            node["frame"] = frame

        # Pop stack until we find the parent
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            stack[-1][1]["children"].append(node)
        else:
            root_children.append(node)

        stack.append((indent, node))

    return root_children


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_tree(raw_text: str) -> list | dict:
    """Parse raw accessibility dump text into a structured tree.

    Handles both JSON and indented-text formats.
    Returns a list or dict representing the tree.
    """
    if not raw_text or not raw_text.strip():
        _log("empty input")
        return []

    text = raw_text.strip()

    # Try JSON first
    if text.startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            _log("parsed as JSON")
            return parsed
        except json.JSONDecodeError:
            _log("JSON decode failed, falling back to text parser")

    # Fall back to indented-text parsing
    result = _parse_text_tree(text)
    _log(f"parsed text tree, {len(result)} top-level nodes")
    return result


def _make_searchable_text(label, name, value, title) -> str:
    parts = [s for s in (label, name, value, title) if s]
    return " ".join(parts).lower()


def _normalize_element(node: dict) -> dict:
    """Turn a single tree node into a flat element dict."""
    label = node.get("label") or node.get("AXLabel") or None
    name = node.get("name") or node.get("AXName") or node.get("identifier") or None
    value = node.get("value") or node.get("AXValue") or None
    title = node.get("title") or node.get("AXTitle") or None
    etype = node.get("type") or node.get("AXRole") or node.get("role") or "Unknown"

    frame = _extract_frame(node)
    if frame is None:
        frame = {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}

    return {
        "label": label,
        "name": name,
        "value": value,
        "title": title,
        "type": etype,
        "frame": frame,
        "searchable_text": _make_searchable_text(label, name, value, title),
    }


def flatten_elements(tree) -> list[dict]:
    """Recursively walk a parsed tree and produce a flat list of element dicts.

    Accepts a dict (single root), a list of dicts, or already-flat structures.
    """
    results: list[dict] = []

    if isinstance(tree, dict):
        results.append(_normalize_element(tree))
        for child in tree.get("children", []):
            results.extend(flatten_elements(child))
    elif isinstance(tree, list):
        for item in tree:
            results.extend(flatten_elements(item))

    return results


def get_element_center(element: dict) -> tuple[int, int]:
    """Compute the center point of an element's frame as integer (x, y)."""
    frame = element.get("frame") or {}
    x = frame.get("x", 0.0)
    y = frame.get("y", 0.0)
    w = frame.get("width", 0.0)
    h = frame.get("height", 0.0)
    return (int(x + w / 2), int(y + h / 2))


def dump_json(elements: list[dict], path: str | None = None) -> str:
    """Serialize flattened elements to JSON.

    If path is given, also write to that file.
    Returns the JSON string either way.
    """
    text = json.dumps(elements, indent=2)
    if path:
        with open(path, "w") as f:
            f.write(text)
        _log(f"wrote {len(elements)} elements to {path}")
    return text


# ---------------------------------------------------------------------------
# CLI entry point for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <accessibility_dump_file> [output.json]")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        raw = f.read()

    tree = parse_tree(raw)
    elements = flatten_elements(tree)
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    result = dump_json(elements, out_path)

    if not out_path:
        print(result)
    else:
        _log(f"done - {len(elements)} elements")
