#!/usr/bin/env python3
"""Set up a Notion Calendar-friendly schedule database under the Control Hub.

Creates:
  - A "Schedule" page under the Control Hub (cover + icon)
  - An inline "Schedule (Auto)" database with a single date property "When"

Notes:
  - Notion Calendar can display any Notion database that has a Date property.
  - Your Jobs DB and Maintenance DB already have date fields; this database is a
    single, unified place for events you want to see on the calendar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.integrations.http import request_json
from scripts.integrations.notion_api import (
    add_database_row,
    build_date_prop,
    build_rich_text_prop,
    build_select_prop,
    build_title_prop,
    create_database,
    query_database,
)

_NOTION_VERSION = "2022-06-28"


def _headers() -> dict[str, str]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}", "Notion-Version": _NOTION_VERSION}


def _list_block_children(block_id: str, page_size: int = 100) -> list[dict]:
    block_id = (block_id or "").strip()
    if not block_id:
        return []
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


def _get_page_url(page_id: str) -> str:
    res = request_json("GET", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers())
    if not res.get("ok"):
        return ""
    return ((res.get("data") or {}).get("url") or "").strip()


def _create_page(parent_page_id: str, title: str, *, icon: str, cover_url: str) -> tuple[bool, str, str]:
    body: dict = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]},
        },
        "icon": {"type": "emoji", "emoji": icon},
        "cover": {"type": "external", "external": {"url": cover_url}},
    }
    res = request_json("POST", "https://api.notion.com/v1/pages", headers=_headers(), body=body)
    if not res.get("ok"):
        return False, "", (res.get("error") or "")[:300]
    pid = ((res.get("data") or {}).get("id") or "").strip()
    return True, pid, ""


def _seed_if_empty(database_id: str) -> dict:
    res = query_database(database_id, page_size=5)
    if not res.get("ok"):
        return {"ok": False, "error": (res.get("error") or "")[:200]}
    rows = (res.get("data") or {}).get("results") or []
    if rows:
        return {"ok": True, "seeded": False}

    # Seed a couple safe examples.
    samples = [
        {
            "Event": build_title_prop("Daily Ops Digest (review)"),
            "When": build_date_prop("2026-02-18"),
            "Type": build_select_prop("Tools"),
            "Notes": build_rich_text_prop("Review disk/git/services status. Keep it silent."),
        },
        {
            "Event": build_title_prop("Camera retention check (30-day loop)"),
            "When": build_date_prop("2026-02-23"),
            "Type": build_select_prop("Home"),
            "Notes": build_rich_text_prop("Confirm storage + rotation. Add the real day/time you prefer."),
        },
    ]
    added = 0
    for row in samples:
        r = add_database_row(database_id, row)
        if r.get("ok"):
            added += 1
        time.sleep(0.15)
    return {"ok": True, "seeded": True, "added": added}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Notion Schedule page + calendar-friendly database.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    parser.add_argument("--command-center-id", default="30af7bec-843d-81e6-a29b-e78d4254b72e")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ios-agent-runner/.env)"}, indent=2))
        return 2

    hub_id = (args.control_hub_id or "").strip()
    child = _child_pages(hub_id)
    schedule_id = _pick_id(child.get("Schedule") or [])
    if not schedule_id:
        ok, pid, err = _create_page(
            hub_id,
            "Schedule",
            icon="📆",
            cover_url="https://www.notion.so/images/page-cover/gradients_1.png",
        )
        if not ok:
            print(json.dumps({"ok": False, "error": f"create Schedule page: {err}"}, indent=2))
            return 1
        schedule_id = pid

    # Ensure the Schedule DB exists under the Schedule page.
    dbs = _child_databases(schedule_id)
    schedule_db_id = _pick_id(dbs.get("Schedule (Auto)") or [])
    created_db = False
    if not schedule_db_id:
        schema = {
            "Event": {"title": {}},
            "When": {"date": {}},
            "Type": {"select": {"options": [
                {"name": "Home", "color": "blue"},
                {"name": "Business", "color": "green"},
                {"name": "Family", "color": "pink"},
                {"name": "Tools", "color": "gray"},
            ]}},
            "Source": {"select": {"options": [
                {"name": "Manual", "color": "gray"},
                {"name": "Auto", "color": "purple"},
            ]}},
            "Notes": {"rich_text": {}},
        }
        res = create_database(schedule_id, "Schedule (Auto)", schema, is_inline=True)
        if not res.get("ok"):
            print(json.dumps({"ok": False, "error": (res.get("error") or "")[:300]}, indent=2))
            return 1
        schedule_db_id = ((res.get("data") or {}).get("id") or "").strip()
        created_db = True

    seed_res = _seed_if_empty(schedule_db_id)

    out = {
        "ok": True,
        "schedule_page": _get_page_url(schedule_id),
        "schedule_db_id": schedule_db_id,
        "created_schedule_db": created_db,
        "seed": seed_res,
        "note": "In Notion Calendar: add the 'Schedule (Auto)' database and choose the 'When' date field.",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

