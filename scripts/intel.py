"""Intel Pipeline — classify, extract, persist, and search iOS screen captures.

Every screen the agent sees gets text-extracted, classified, structured-data-mined,
and saved to a JSONL store + a markdown memory file. No caps, no trimming.
"""

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class ScreenCategory(str, Enum):
    NETWORK_CONFIG = "network_config"
    DEVICE_SETTINGS = "device_settings"
    CREDENTIALS = "credentials"
    AV_CONFIG = "av_config"
    APP_UI = "app_ui"
    PHOTO_GALLERY = "photo_gallery"
    TEXT_CONTENT = "text_content"
    UNKNOWN = "unknown"


@dataclass
class Finding:
    timestamp: str
    category: str
    source_app: str
    screenshot_path: str
    tree_path: str
    text_content: list[str]
    extracted_data: dict
    tags: list[str]
    step: int
    goal: str
    finding_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_INTEL_STORE = os.path.expanduser("~/.ulan/ios_intel.json")
_MEMORY_FILE = os.path.expanduser(
    "~/.claude/projects/-Users-stephengodman/memory/ios-discoveries.md"
)


def _log(msg: str) -> None:
    print(f"[intel] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_all_text(elements: list[dict]) -> list[str]:
    """Pull every text field from every element. No filtering. Get it all."""
    texts: list[str] = []
    for el in elements:
        for key in ("label", "name", "value", "title"):
            val = el.get(key)
            if val and isinstance(val, str) and val.strip():
                cleaned = val.strip()
                if cleaned not in texts:
                    texts.append(cleaned)
    return texts


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_CATEGORY_PATTERNS: dict[ScreenCategory, list[str]] = {
    ScreenCategory.NETWORK_CONFIG: [
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        r"(?i)\b(subnet|gateway|dns|dhcp|wifi|wi-fi|ssid|signal|router|ip\s*address)\b",
    ],
    ScreenCategory.DEVICE_SETTINGS: [
        r"(?i)\b(model|firmware|serial|version|hardware|manufacturer)\b",
        r"(?i)\b(software\s*update|about|general|device\s*name)\b",
    ],
    ScreenCategory.CREDENTIALS: [
        r"(?i)\b(password|token|key|secret|auth|login|api\s*key|credential)\b",
    ],
    ScreenCategory.AV_CONFIG: [
        r"(?i)\b(hdmi|audio|display|resolution|surround|dolby|cec|arc|earc)\b",
        r"\b\d{2,3}\s*[Hh][Zz]\b",
    ],
    ScreenCategory.PHOTO_GALLERY: [
        r"(?i)\b(photos|albums|library|camera\s*roll|recents|favorites)\b",
    ],
    ScreenCategory.TEXT_CONTENT: [],  # scored by ratio of StaticText elements
}


def classify_screen(elements: list[dict], bundle_id: str = "") -> ScreenCategory:
    """Score patterns against visible text, return highest-scoring category."""
    # Photo gallery shortcut
    if "mobileslideshow" in bundle_id:
        return ScreenCategory.PHOTO_GALLERY

    all_text = " ".join(extract_all_text(elements))

    scores: dict[ScreenCategory, int] = {cat: 0 for cat in ScreenCategory}

    for cat, patterns in _CATEGORY_PATTERNS.items():
        for pat in patterns:
            matches = re.findall(pat, all_text)
            scores[cat] += len(matches)

    # Text content heuristic: mostly StaticText with long strings
    static_count = sum(1 for el in elements if el.get("type") == "StaticText")
    total = max(len(elements), 1)
    if static_count / total > 0.5 and len(all_text) > 200:
        scores[ScreenCategory.TEXT_CONTENT] += 3

    # Photo gallery bundle check (already handled above, but also keyword)
    if "mobileslideshow" in bundle_id:
        scores[ScreenCategory.PHOTO_GALLERY] += 10

    best = max(scores, key=lambda c: scores[c])
    if scores[best] == 0:
        return ScreenCategory.APP_UI  # default fallback

    return best


# ---------------------------------------------------------------------------
# Structured extraction (regex)
# ---------------------------------------------------------------------------

_EXTRACTORS: dict[str, str] = {
    "ips": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    "macs": r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}",
    "model_numbers": r"\b[A-Z]{2,5}[-]?[A-Z0-9]{1,3}\d[A-Z0-9]{0,5}\b",
    "firmware": r"(?i)(?:firmware|fw|version|ver)[:\s]*([\d.]+)",
    "urls": r"https?://[^\s<>\"]+",
    "ports": r"(?i)(?:port)[:\s]*(\d{1,5})",
    "resolutions": r"\d{3,4}\s*[xX]\s*\d{3,4}",
    "ssids": r"(?i)(?:ssid|network)[:\s]*(\S+)",
    "temperatures": r"\b\d+°[CF]\b",
}


def extract_structured(texts: list[str]) -> dict:
    """Regex extraction of IPs, MACs, model numbers, firmware, etc."""
    blob = "\n".join(texts)
    result: dict[str, list[str]] = {}

    for key, pattern in _EXTRACTORS.items():
        matches = re.findall(pattern, blob)
        if matches:
            # findall returns tuples for patterns with groups — flatten
            flat = []
            for m in matches:
                if isinstance(m, tuple):
                    flat.append(m[0] if m[0] else "".join(m))
                else:
                    flat.append(m)
            # Deduplicate while preserving order
            seen: set[str] = set()
            deduped = []
            for v in flat:
                if v and v not in seen:
                    seen.add(v)
                    deduped.append(v)
            if deduped:
                result[key] = deduped

    return result


# ---------------------------------------------------------------------------
# Build finding
# ---------------------------------------------------------------------------

def build_finding(
    elements: list[dict],
    bundle_id: str,
    screenshot_path: str,
    tree_path: str,
    step: int,
    goal: str,
) -> Finding:
    """Full pipeline: extract text, classify, extract structured, build Finding."""
    texts = extract_all_text(elements)
    category = classify_screen(elements, bundle_id)
    structured = extract_structured(texts)

    # Auto-generate tags
    tags: list[str] = [category.value]
    if bundle_id:
        tags.append(f"app:{bundle_id}")
    for key, vals in structured.items():
        for v in vals:
            tags.append(f"{key}:{v}")

    return Finding(
        timestamp=datetime.now().isoformat(),
        category=category.value,
        source_app=bundle_id,
        screenshot_path=screenshot_path,
        tree_path=tree_path,
        text_content=texts,
        extracted_data=structured,
        tags=tags,
        step=step,
        goal=goal,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_finding(finding: Finding) -> str:
    """Append to JSONL store, update memory file. Returns finding ID."""
    os.makedirs(os.path.dirname(_INTEL_STORE), exist_ok=True)

    data = asdict(finding)
    with open(_INTEL_STORE, "a") as f:
        f.write(json.dumps(data) + "\n")

    _log(f"Saved finding {finding.finding_id}: {finding.category} ({len(finding.text_content)} texts)")

    _update_memory_file()
    return finding.finding_id


def load_all_findings() -> list[dict]:
    """Read full JSONL store."""
    if not os.path.exists(_INTEL_STORE):
        return []
    findings = []
    with open(_INTEL_STORE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    findings.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return findings


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_findings(
    query: str | None = None,
    category: str | None = None,
    since: str | None = None,
) -> list[dict]:
    """Search by keyword, category, or date. Returns all matches."""
    all_findings = load_all_findings()
    results = []
    since_epoch = _timestamp_epoch(since) if since else None

    for f in all_findings:
        # Category filter
        if category and f.get("category") != category:
            continue

        # Date filter
        if since:
            ts = f.get("timestamp", "")
            if since_epoch is not None:
                ts_epoch = _timestamp_epoch(ts)
                if ts_epoch is None or ts_epoch < since_epoch:
                    continue
            elif ts < since:
                continue

        # Keyword filter — search across all text content, tags, extracted data
        if query:
            q = query.lower()
            searchable = " ".join([
                " ".join(f.get("text_content", [])),
                " ".join(f.get("tags", [])),
                json.dumps(f.get("extracted_data", {})),
                f.get("source_app", ""),
                f.get("goal", ""),
            ]).lower()
            if q not in searchable:
                continue

        results.append(f)

    return results


def _timestamp_epoch(value: str | None) -> float | None:
    """Parse an ISO-ish timestamp into epoch seconds for reliable comparisons."""
    if not value:
        return None

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.timestamp()


# ---------------------------------------------------------------------------
# Memory file generation
# ---------------------------------------------------------------------------

def _update_memory_file() -> None:
    """Regenerate the markdown memory file from all findings."""
    all_findings = load_all_findings()
    if not all_findings:
        return

    os.makedirs(os.path.dirname(_MEMORY_FILE), exist_ok=True)

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for f in all_findings:
        cat = f.get("category", "unknown")
        by_category.setdefault(cat, []).append(f)

    lines: list[str] = [
        "# iOS Runner Discoveries",
        "",
        f"Last updated: {datetime.now().isoformat()}",
        f"Total findings: {len(all_findings)}",
        "",
    ]

    # Category order (most interesting first)
    order = [
        "network_config", "device_settings", "credentials", "av_config",
        "photo_gallery", "text_content", "app_ui", "unknown",
    ]

    for cat in order:
        findings = by_category.get(cat, [])
        if not findings:
            continue

        cat_label = cat.replace("_", " ").title()
        lines.append(f"## {cat_label} ({len(findings)} findings)")
        lines.append("")

        for f in findings:
            ts = f.get("timestamp", "")[:19].replace("T", " ")
            app = f.get("source_app", "unknown").split(".")[-1]
            ss = f.get("screenshot_path", "")

            # Build detail string
            details: list[str] = []
            ext = f.get("extracted_data", {})
            if ext.get("ips"):
                details.append(f"IPs: {', '.join(ext['ips'])}")
            if ext.get("macs"):
                details.append(f"MACs: {', '.join(ext['macs'])}")
            if ext.get("model_numbers"):
                details.append(f"Models: {', '.join(ext['model_numbers'])}")
            if ext.get("firmware"):
                details.append(f"FW: {', '.join(ext['firmware'])}")
            if ext.get("urls"):
                details.append(f"URLs: {', '.join(ext['urls'][:3])}")
            if ext.get("resolutions"):
                details.append(f"Res: {', '.join(ext['resolutions'])}")
            if ext.get("ssids"):
                details.append(f"SSIDs: {', '.join(ext['ssids'])}")

            detail_str = " | ".join(details) if details else f"{len(f.get('text_content', []))} texts"
            link = f" | [screenshot]({ss})" if ss else ""
            tree = f.get("tree_path", "")
            tree_link = f" | [tree]({tree})" if tree else ""

            lines.append(f"- [{ts}] {app} — {detail_str}{link}{tree_link}")

        lines.append("")

    # All text captures log
    lines.append("## All Text Captures (full log)")
    lines.append("")
    for f in all_findings:
        ts = f.get("timestamp", "")[:19].replace("T", " ")
        app = f.get("source_app", "unknown").split(".")[-1]
        n_texts = len(f.get("text_content", []))
        tree = f.get("tree_path", "")
        tree_link = f" | [tree]({tree})" if tree else ""
        lines.append(f"- [{ts}] {n_texts} text elements captured from {app}{tree_link}")

    lines.append("")

    Path(_MEMORY_FILE).write_text("\n".join(lines))
    _log(f"Updated memory file: {len(all_findings)} findings")
