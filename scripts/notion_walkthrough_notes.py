#!/usr/bin/env python3
"""Notion Walkthrough Notes OS (Quest-friendly field notes).

Goal
- When you record a bunch of Quest clips (attic walkthrough, garage tour, etc.),
  create a Notion database + session rows that link to the captured media paths
  and give you a structured place to write follow-up notes.

Notes
- Notion API cannot upload local MP4 files directly; this stores file paths.
- Never reads or prints secrets. Uses NOTION_TOKEN from ios-agent-runner/.env.

Usage
  cd ~/ios-agent-runner && source .venv/bin/activate

  # One-time setup (idempotent)
  python scripts/notion_walkthrough_notes.py setup

  # Create a session from recent media
  python scripts/notion_walkthrough_notes.py capture --location Attic --since-minutes 30
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.integrations.http import request_json
from scripts.integrations.notion_api import (
    add_database_row,
    append_blocks,
    blocks_from_markdown,
    build_date_prop,
    build_multi_select_prop,
    build_number_prop,
    build_rich_text_prop,
    build_select_prop,
    build_title_prop,
    create_database,
)

_NOTION_VERSION = "2022-06-28"

DEFAULT_CONTROL_HUB_ID = "309f7bec-843d-804a-9d21-c7e980580069"
DEFAULT_COMMAND_CENTER_ID = "30af7bec-843d-81e6-a29b-e78d4254b72e"
DEFAULT_MEDIA_DIR = Path.home() / "ulan-agent" / "_artifacts" / "quest3" / "screenshots"

STATE_FILE = Path.home() / ".ulan" / "notion_walkthrough_ids.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _headers() -> dict[str, str]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}", "Notion-Version": _NOTION_VERSION}


def _normalize_notion_id(raw: str) -> str:
    raw = (raw or "").strip().strip("/")
    if not raw:
        return ""

    m_uuid = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        raw,
    )
    if m_uuid:
        return m_uuid.group(0).lower()

    m_32 = re.search(r"([0-9a-fA-F]{32})", raw)
    if not m_32:
        return ""

    s = m_32.group(1).lower()
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"


def _ensure_state_dir() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    try:
        obj = json.loads(STATE_FILE.read_text("utf-8"))
        return obj if isinstance(obj, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    _ensure_state_dir()
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", "utf-8")


def _list_block_children(block_id: str, page_size: int = 100) -> list[dict[str, Any]]:
    block_id = (block_id or "").strip()
    if not block_id:
        return []

    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size={min(int(page_size), 100)}"
        if cursor:
            url += f"&start_cursor={cursor}"
        res = request_json("GET", url, headers=_headers())
        if not res.get("ok"):
            return out
        data = res.get("data") or {}
        out.extend((data.get("results") or []))
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return out


def _child_pages(parent_page_id: str) -> dict[str, list[str]]:
    pages: dict[str, list[str]] = {}
    for b in _list_block_children(parent_page_id, page_size=100):
        if b.get("type") != "child_page":
            continue
        title = ((b.get("child_page") or {}).get("title") or "").strip()
        bid = (b.get("id") or "").strip()
        if title and bid:
            pages.setdefault(title, []).append(bid)
    return pages


def _child_databases(parent_page_id: str) -> dict[str, list[str]]:
    dbs: dict[str, list[str]] = {}
    for b in _list_block_children(parent_page_id, page_size=100):
        if b.get("type") != "child_database":
            continue
        title = ((b.get("child_database") or {}).get("title") or "").strip()
        bid = (b.get("id") or "").strip()
        if title and bid:
            dbs.setdefault(title, []).append(bid)
    return dbs


def _pick_id(candidates: list[str]) -> str:
    for cid in candidates:
        if cid.startswith("30af"):
            return cid
    return candidates[0] if candidates else ""


def _get_page_url(page_id: str) -> str:
    res = request_json("GET", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers())
    if not res.get("ok"):
        return ""
    return ((res.get("data") or {}).get("url") or "").strip()


def _get_db_url(db_id: str) -> str:
    res = request_json("GET", f"https://api.notion.com/v1/databases/{db_id}", headers=_headers())
    if not res.get("ok"):
        return ""
    return ((res.get("data") or {}).get("url") or "").strip()


def _create_page(parent_page_id: str, title: str, *, icon: str, cover_url: str) -> tuple[bool, str, str]:
    body: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        "icon": {"type": "emoji", "emoji": icon},
        "cover": {"type": "external", "external": {"url": cover_url}},
    }
    res = request_json("POST", "https://api.notion.com/v1/pages", headers=_headers(), body=body)
    if not res.get("ok"):
        return False, "", (res.get("error") or "")[:400]
    pid = ((res.get("data") or {}).get("id") or "").strip()
    return True, pid, ""


def _append_markdown(page_id: str, md: str) -> dict[str, Any]:
    blocks = blocks_from_markdown(md)
    if not blocks:
        return {"ok": True, "appended": 0}
    return append_blocks(page_id, blocks)


def _walkthrough_schema() -> dict[str, Any]:
    return {
        "Session": {"title": {}},
        "When": {"date": {}},
        "Location": {
            "select": {
                "options": [
                    {"name": "Attic", "color": "gray"},
                    {"name": "Garage", "color": "blue"},
                    {"name": "Shed", "color": "green"},
                    {"name": "House", "color": "purple"},
                    {"name": "Truck", "color": "orange"},
                    {"name": "Other", "color": "yellow"},
                ]
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "to_review", "color": "yellow"},
                    {"name": "reviewed", "color": "green"},
                    {"name": "actioned", "color": "blue"},
                ]
            }
        },
        "Clips": {"number": {"format": "number"}},
        "Media Path": {"rich_text": {}},
        "Voice Memo": {"url": {}},
        "Tags": {
            "multi_select": {
                "options": [
                    {"name": "quest3", "color": "gray"},
                    {"name": "walkthrough", "color": "gray"},
                ]
            }
        },
        "Summary": {"rich_text": {}},
    }


def setup(*, control_hub_id: str, command_center_id: str) -> dict[str, Any]:
    hub_id = _normalize_notion_id(control_hub_id) or DEFAULT_CONTROL_HUB_ID
    cc_id = _normalize_notion_id(command_center_id) or DEFAULT_COMMAND_CENTER_ID

    pages = _child_pages(hub_id)
    title = "Walkthrough Notes"
    if pages.get(title):
        walkthrough_page_id = _pick_id(pages[title])
        created_page = False
    else:
        ok, pid, err = _create_page(
            hub_id,
            title,
            icon="🗂️",
            cover_url="https://www.notion.so/images/page-cover/gradients_9.png",
        )
        if not ok:
            return {"ok": False, "error": f"failed_to_create_page: {err}"}
        walkthrough_page_id = pid
        created_page = True

        _append_markdown(
            walkthrough_page_id,
            "\n".join(
                [
                    "# Walkthrough Notes",
                    "Quest field notes: record short clips per area, then review and write notes.",
                    "",
                    "Suggested workflow:",
                    "- Record clips: `cd ~/ulan-agent && python scripts/quest3_scan.py --video 60`",
                    "- Create a Notion session: `python scripts/notion_walkthrough_notes.py capture --location Attic --since-minutes 30`",
                    "- Paste your iPhone Voice Memo link into the session row (optional).",
                    "---",
                ]
            ),
        )

    dbs = _child_databases(walkthrough_page_id)
    db_title = "Walkthrough Sessions (Auto)"
    if dbs.get(db_title):
        db_id = _pick_id(dbs[db_title])
        created_db = False
    else:
        res = create_database(walkthrough_page_id, db_title, _walkthrough_schema(), is_inline=True)
        if not res.get("ok"):
            return {"ok": False, "error": f"failed_to_create_db: {(res.get('error') or '')[:400]}"}
        db_id = ((res.get("data") or {}).get("id") or "").strip()
        created_db = True

    state = _load_state()
    state.update(
        {
            "control_hub_id": hub_id,
            "command_center_id": cc_id,
            "walkthrough_page_id": walkthrough_page_id,
            "walkthrough_db_id": db_id,
            "updated_at": _now_iso(),
        }
    )
    _save_state(state)

    # Best-effort: add a tile link to Command Center.
    try:
        cc_children = _list_block_children(cc_id, page_size=100)
        already = False
        for b in cc_children:
            if b.get("type") != "callout":
                continue
            rich = (((b.get("callout") or {}).get("rich_text")) or [])
            text = " ".join((t.get("plain_text") or "") for t in rich).lower()
            if "walkthrough" in text and "notes" in text:
                already = True
                break
        if not already:
            url = _get_page_url(walkthrough_page_id)
            callout = {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Walkthrough Notes", "link": {"url": url}}}
                    ]
                    if url
                    else [{"type": "text", "text": {"content": "Walkthrough Notes"}}],
                    "icon": {"type": "emoji", "emoji": "🗂️"},
                    "color": "gray_background",
                },
            }
            append_blocks(cc_id, [callout])
    except Exception:
        pass

    return {
        "ok": True,
        "created_page": created_page,
        "created_db": created_db,
        "walkthrough_page_id": walkthrough_page_id,
        "walkthrough_page_url": _get_page_url(walkthrough_page_id),
        "walkthrough_db_id": db_id,
        "walkthrough_db_url": _get_db_url(db_id),
        "state_file": str(STATE_FILE),
    }


def _coerce_location(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "Other"
    canonical = value.strip().title()
    known = {"Attic", "Garage", "Shed", "House", "Truck", "Other"}
    return canonical if canonical in known else canonical[:40]


def _scan_media(media_dir: Path, *, cutoff_ts: float) -> list[Path]:
    if not media_dir.exists():
        return []
    exts = {".mp4", ".png", ".jpg", ".jpeg"}
    found: list[Path] = []
    for p in media_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue
        try:
            if p.stat().st_mtime < cutoff_ts:
                continue
        except FileNotFoundError:
            continue
        found.append(p)
    found.sort(key=lambda x: x.stat().st_mtime)
    return found


def capture(
    *,
    location: str,
    since_minutes: int,
    media_dir: Path,
    voice_memo_url: str,
    summary: str,
    max_files: int,
) -> dict[str, Any]:
    state = _load_state()
    db_id = _normalize_notion_id(state.get("walkthrough_db_id", ""))
    if not db_id:
        setup_res = setup(control_hub_id=DEFAULT_CONTROL_HUB_ID, command_center_id=DEFAULT_COMMAND_CENTER_ID)
        if not setup_res.get("ok"):
            return {"ok": False, "error": "setup_required_and_failed", "detail": setup_res}
        state = _load_state()
        db_id = _normalize_notion_id(state.get("walkthrough_db_id", ""))

    now = time.time()
    cutoff = now - (max(1, int(since_minutes)) * 60)
    media_dir = media_dir.expanduser()
    media_files = _scan_media(media_dir, cutoff_ts=cutoff)
    if max_files > 0:
        media_files = media_files[-int(max_files) :]

    clip_count = len([p for p in media_files if p.suffix.lower() == ".mp4"])

    loc = _coerce_location(location)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    title = f"{loc} Walkthrough {stamp}"

    props: dict[str, Any] = {
        "Session": build_title_prop(title),
        "When": build_date_prop(_now_iso()),
        "Location": build_select_prop(loc),
        "Status": build_select_prop("to_review"),
        "Clips": build_number_prop(int(clip_count)),
        "Media Path": build_rich_text_prop(str(media_dir)),
        "Tags": build_multi_select_prop(["quest3", "walkthrough"]),
    }
    if voice_memo_url.strip():
        props["Voice Memo"] = {"url": voice_memo_url.strip()}
    if summary.strip():
        props["Summary"] = build_rich_text_prop(summary.strip())

    created = add_database_row(db_id, props)
    if not created.get("ok"):
        return {"ok": False, "error": "failed_to_create_row", "detail": created}

    page_id = ((created.get("data") or {}).get("id") or "").strip()
    if page_id:
        lines: list[str] = []
        lines.append("## Media")
        if not media_files:
            lines.append("- (No files found; increase `--since-minutes`.)")
        else:
            for p in media_files:
                try:
                    st = p.stat()
                except FileNotFoundError:
                    continue
                size_mb = st.st_size / (1024 * 1024)
                ts_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
                lines.append(f"- {p.name} ({size_mb:.1f} MB) [{ts_s}]")
                lines.append(f"  {p}")

        lines.append("---")
        lines.append("## Voice Memo")
        lines.append("- Record on iPhone and paste link in the `Voice Memo` column.")
        lines.append("")
        lines.append("## Notes")
        lines.append("- Big items:")
        lines.append("- Keep / Sell / Trash:")
        lines.append("- Follow-ups:")

        _append_markdown(page_id, "\n".join(lines))

    state["last_capture_at"] = _now_iso()
    state["last_media_dir"] = str(media_dir)
    state["last_location"] = loc
    _save_state(state)

    return {
        "ok": True,
        "database_id": db_id,
        "database_url": _get_db_url(db_id),
        "page_id": page_id,
        "page_url": _get_page_url(page_id) if page_id else "",
        "location": loc,
        "media_dir": str(media_dir),
        "since_minutes": int(since_minutes),
        "files_found": len(media_files),
        "clips_found": int(clip_count),
        "state_file": str(STATE_FILE),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Notion Walkthrough Notes OS")
    sub = parser.add_subparsers(dest="cmd", required=True)

    setup_p = sub.add_parser("setup", help="Create Walkthrough Notes page + database")
    setup_p.add_argument("--control-hub-id", default=DEFAULT_CONTROL_HUB_ID, help="Notion Control Hub page id/url")
    setup_p.add_argument("--command-center-id", default=DEFAULT_COMMAND_CENTER_ID, help="Notion Command Center page id/url")

    cap = sub.add_parser("capture", help="Create a session row from recent Quest media")
    cap.add_argument("--location", default="Attic", help="Location label (Attic/Garage/Shed/etc)")
    cap.add_argument("--since-minutes", type=int, default=30, help="Lookback window for media files")
    cap.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR, help="Directory containing MP4/PNG captures")
    cap.add_argument("--voice-memo-url", default="", help="Optional iPhone Voice Memo share URL")
    cap.add_argument("--summary", default="", help="Optional one-line summary")
    cap.add_argument("--max-files", type=int, default=50, help="Limit number of files listed on the Notion page")

    args = parser.parse_args(argv)

    load_dotenv(_PROJECT_ROOT / ".env")
    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ios-agent-runner/.env)"}, indent=2))
        return 2

    if args.cmd == "setup":
        out = setup(control_hub_id=str(args.control_hub_id), command_center_id=str(args.command_center_id))
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1

    if args.cmd == "capture":
        out = capture(
            location=str(args.location),
            since_minutes=int(args.since_minutes),
            media_dir=Path(args.media_dir),
            voice_memo_url=str(args.voice_memo_url),
            summary=str(args.summary),
            max_files=int(args.max_files),
        )
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
