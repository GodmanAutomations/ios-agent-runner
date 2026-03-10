#!/usr/bin/env python3
"""Refresh the Command Center page with links to newly created OS pages.

Appends a "New Additions" section (idempotent marker) that links to:
  - Inventory
  - Reminders
  - Template Shortlist
  - Schedule
  - Financial Command Center (if present)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.integrations.http import request_json
from scripts.integrations.notion_api import append_blocks

_NOTION_VERSION = "2022-06-28"


def _headers() -> dict[str, str]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}", "Notion-Version": _NOTION_VERSION}


def _rt(text: str, url: str | None = None) -> dict:
    obj: dict = {"type": "text", "text": {"content": text or ""}}
    if url:
        obj["text"]["link"] = {"url": url}
    return obj


def _h(level: int, text: str) -> dict:
    t = max(1, min(int(level), 3))
    key = f"heading_{t}"
    return {"object": "block", "type": key, key: {"rich_text": [_rt(text)]}}


def _div() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _callout(text: str, url: str, *, icon: str, color: str) -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": icon},
            "color": color,
            "rich_text": [_rt(text, url=url)],
        },
    }


def _list_children(block_id: str, page_size: int = 100) -> list[dict]:
    out: list[dict] = []
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


def _pick_id(candidates: list[str]) -> str:
    for cid in candidates:
        if cid.startswith("30af"):
            return cid
    return candidates[0] if candidates else ""


def _child_pages(parent_page_id: str) -> dict[str, list[str]]:
    pages: dict[str, list[str]] = {}
    for b in _list_children(parent_page_id, page_size=100):
        if b.get("type") != "child_page":
            continue
        title = ((b.get("child_page") or {}).get("title") or "").strip()
        bid = (b.get("id") or "").strip()
        if title and bid:
            pages.setdefault(title, []).append(bid)
    return pages


def _get_page_url(page_id: str) -> str:
    res = request_json("GET", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers())
    if not res.get("ok"):
        return ""
    return ((res.get("data") or {}).get("url") or "").strip()


def _marker_present(page_id: str, marker: str) -> bool:
    for b in _list_children(page_id, page_size=100):
        if b.get("type") != "code":
            continue
        rt = ((b.get("code") or {}).get("rich_text") or [])
        txt = "".join(((c.get("text") or {}).get("content") or "") for c in rt if c.get("type") == "text")
        if marker in txt:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Append new tiles to Command Center page.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    parser.add_argument("--command-center-id", default="30af7bec-843d-81e6-a29b-e78d4254b72e")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ios-agent-runner/.env)"}, indent=2))
        return 2

    hub_id = (args.control_hub_id or "").strip()
    cc_id = (args.command_center_id or "").strip()
    if not cc_id:
        print(json.dumps({"ok": False, "error": "missing command center id"}, indent=2))
        return 2

    marker = "AUTOGEN: command_center_new_additions_v1"
    if _marker_present(cc_id, marker):
        print(json.dumps({"ok": True, "skipped": True}, indent=2))
        return 0

    pages = _child_pages(hub_id)
    def url(title: str) -> str:
        pid = _pick_id(pages.get(title) or [])
        return _get_page_url(pid) if pid else ""

    blocks: list[dict] = []
    blocks.append(_div())
    blocks.append(_h(2, "New Additions"))

    inv = url("Inventory")
    rem = url("Reminders")
    tmpl = url("Template Shortlist")
    sched = url("Schedule")
    finance = url("Financial Command Center")
    infra = url("Infrastructure")

    if inv:
        blocks.append(_callout("Inventory OS", inv, icon="📦", color="blue_background"))
    if rem:
        blocks.append(_callout("Reminders OS", rem, icon="⏰", color="yellow_background"))
    if sched:
        blocks.append(_callout("Schedule (Calendar)", sched, icon="📆", color="green_background"))
    if infra:
        blocks.append(_callout("Infrastructure", infra, icon="🛠️", color="orange_background"))
    if tmpl:
        blocks.append(_callout("Template Shortlist (cool templates)", tmpl, icon="🧩", color="purple_background"))
    if finance:
        blocks.append(_callout("Financial Command Center", finance, icon="💵", color="green_background"))

    blocks.append(
        {
            "object": "block",
            "type": "code",
            "code": {"language": "plain text", "rich_text": [_rt(marker)]},
        }
    )

    res = append_blocks(cc_id, blocks)
    if not res.get("ok"):
        print(json.dumps({"ok": False, "error": (res.get("error") or "")[:200]}, indent=2))
        return 1

    print(json.dumps({"ok": True, "appended": (res.get("data") or {}).get("appended", 0)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

