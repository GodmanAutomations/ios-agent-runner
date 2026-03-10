#!/usr/bin/env python3
"""Create a Reminders OS in the Notion Control Hub.

Creates (under Control Hub):
  - Reminders page (cover + icon)
  - Reminders Inbox (Auto) database with a calendar-friendly "Due" date field

This is meant to work with Notion Calendar (and can be fed by iPhone Shortcuts).

Safety:
  - No secrets are read or printed.
  - Seed rows are safe placeholders.
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
    append_blocks,
    build_checkbox_prop,
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


def _rt(text: str, url: str | None = None) -> dict:
    obj: dict = {"type": "text", "text": {"content": text or ""}}
    if url:
        obj["text"]["link"] = {"url": url}
    return obj


def _block_heading(level: int, text: str) -> dict:
    t = max(1, min(int(level), 3))
    key = f"heading_{t}"
    return {"object": "block", "type": key, key: {"rich_text": [_rt(text)]}}


def _block_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _block_callout(text: str, *, url: str | None = None, icon: str = "✨", color: str = "gray_background") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [_rt(text, url=url)] if url else [_rt(text)],
            "icon": {"type": "emoji", "emoji": icon},
            "color": color,
        },
    }


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


def _get_db_url(db_id: str) -> str:
    res = request_json("GET", f"https://api.notion.com/v1/databases/{db_id}", headers=_headers())
    if not res.get("ok"):
        return ""
    return ((res.get("data") or {}).get("url") or "").strip()


def _create_page(parent_page_id: str, title: str, *, icon: str, cover_url: str) -> tuple[bool, str, str]:
    body: dict = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        "icon": {"type": "emoji", "emoji": icon},
        "cover": {"type": "external", "external": {"url": cover_url}},
    }
    res = request_json("POST", "https://api.notion.com/v1/pages", headers=_headers(), body=body)
    if not res.get("ok"):
        return False, "", (res.get("error") or "")[:300]
    return True, ((res.get("data") or {}).get("id") or "").strip(), ""


def _update_page_meta(page_id: str, *, icon: str | None = None, cover_url: str | None = None) -> bool:
    body: dict = {}
    if icon:
        body["icon"] = {"type": "emoji", "emoji": icon}
    if cover_url:
        body["cover"] = {"type": "external", "external": {"url": cover_url}}
    if not body:
        return True
    res = request_json("PATCH", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers(), body=body)
    return bool(res.get("ok"))


def _marker_present(page_id: str, marker: str) -> bool:
    for b in _list_block_children(page_id, page_size=100):
        if b.get("type") != "code":
            continue
        rt = ((b.get("code") or {}).get("rich_text") or [])
        text = "".join(((c.get("text") or {}).get("content") or "") for c in rt if c.get("type") == "text")
        if marker in text:
            return True
    return False


def _title_set(database_id: str, title_prop: str, page_size: int = 200) -> set[str]:
    res = query_database(database_id, page_size=min(page_size, 100))
    if not res.get("ok"):
        return set()
    seen: set[str] = set()
    for page in (res.get("data") or {}).get("results") or []:
        props = page.get("properties") or {}
        prop = props.get(title_prop) or {}
        chunks = prop.get("title") or []
        if chunks:
            txt = (chunks[0].get("plain_text") or "").strip().lower()
            if txt:
                seen.add(txt)
    return seen


def _seed_rows(database_id: str, title_prop: str, rows: list[dict]) -> dict:
    existing = _title_set(database_id, title_prop)
    added = 0
    skipped = 0
    errors: list[str] = []
    for props in rows:
        title = ""
        chunks = (props.get(title_prop) or {}).get("title") if isinstance(props.get(title_prop), dict) else None
        if chunks:
            title = (chunks[0].get("text") or {}).get("content", "")
        if title and title.strip().lower() in existing:
            skipped += 1
            continue
        res = add_database_row(database_id, props)
        if res.get("ok"):
            added += 1
            if title:
                existing.add(title.strip().lower())
        else:
            errors.append((res.get("error") or "")[:160])
        time.sleep(0.15)
    return {"ok": not errors, "added": added, "skipped": skipped, "errors": errors[:10]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Reminders OS + database in Notion Control Hub.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ios-agent-runner/.env)"}, indent=2))
        return 2

    hub_id = (args.control_hub_id or "").strip()
    child = _child_pages(hub_id)

    reminders_id = _pick_id(child.get("Reminders") or [])
    created_page = False
    if not reminders_id:
        ok, pid, err = _create_page(
            hub_id,
            "Reminders",
            icon="⏰",
            cover_url="https://www.notion.so/images/page-cover/gradients_3.png",
        )
        if not ok:
            print(json.dumps({"ok": False, "error": f"create Reminders page: {err}"}, indent=2))
            return 1
        reminders_id = pid
        created_page = True
    else:
        _update_page_meta(reminders_id, icon="⏰", cover_url="https://www.notion.so/images/page-cover/gradients_3.png")

    # Ensure DB exists.
    dbs = _child_databases(reminders_id)
    inbox_db = _pick_id(dbs.get("Reminders Inbox (Auto)") or [])
    created_db = False
    if not inbox_db:
        schema = {
            "Task": {"title": {}},
            "Due": {"date": {}},
            "Priority": {"select": {"options": [
                {"name": "P0", "color": "red"},
                {"name": "P1", "color": "orange"},
                {"name": "P2", "color": "yellow"},
                {"name": "P3", "color": "gray"},
            ]}},
            "Context": {"select": {"options": [
                {"name": "Home", "color": "blue"},
                {"name": "Business", "color": "green"},
                {"name": "Family", "color": "pink"},
                {"name": "Tools", "color": "gray"},
            ]}},
            "Status": {"select": {"options": [
                {"name": "Inbox", "color": "gray"},
                {"name": "Next", "color": "blue"},
                {"name": "Waiting", "color": "yellow"},
                {"name": "Done", "color": "green"},
            ]}},
            "Source": {"select": {"options": [
                {"name": "Manual", "color": "gray"},
                {"name": "iPhone Shortcut", "color": "blue"},
                {"name": "Import", "color": "purple"},
            ]}},
            "Notes": {"rich_text": {}},
            "Done": {"checkbox": {}},
        }
        res = create_database(reminders_id, "Reminders Inbox (Auto)", schema, is_inline=True)
        if not res.get("ok"):
            print(json.dumps({"ok": False, "error": (res.get("error") or "")[:300]}, indent=2))
            return 1
        inbox_db = ((res.get("data") or {}).get("id") or "").strip()
        created_db = True

    # Seed example tasks.
    seed = [
        {
            "Task": build_title_prop("Set up iPhone Shortcut: Add reminder to Notion"),
            "Context": build_select_prop("Tools"),
            "Priority": build_select_prop("P2"),
            "Status": build_select_prop("Inbox"),
            "Source": build_select_prop("Manual"),
            "Done": build_checkbox_prop(False),
            "Notes": build_rich_text_prop("One button: dictation -> Notion API -> new row in this DB."),
        },
        {
            "Task": build_title_prop("Garage inventory sweep (starter pass)"),
            "Context": build_select_prop("Business"),
            "Priority": build_select_prop("P2"),
            "Status": build_select_prop("Next"),
            "Source": build_select_prop("Manual"),
            "Due": build_date_prop("2026-02-20"),
            "Done": build_checkbox_prop(False),
            "Notes": build_rich_text_prop("Add 20 key items; attach photos; set Min qty for reorder list."),
        },
    ]
    seed_res = _seed_rows(inbox_db, "Task", seed)

    # Add a header + calendar guidance (once).
    marker = "AUTOGEN: reminders_os_v1"
    if not _marker_present(reminders_id, marker):
        page_url = _get_page_url(reminders_id)
        db_url = _get_db_url(inbox_db)
        blocks = [
            _block_heading(1, "Reminders OS"),
            _block_callout("Reminders Inbox (Auto)", url=db_url, icon="✅", color="green_background"),
            _block_callout("Tip: add this DB to Notion Calendar (uses the Due field)", url=page_url, icon="📆", color="yellow_background"),
            _block_divider(),
            {"object": "block", "type": "code", "code": {"language": "plain text", "rich_text": [_rt(marker)]}},
        ]
        append_blocks(reminders_id, blocks)

    out = {
        "ok": True,
        "reminders_page": _get_page_url(reminders_id),
        "inbox_db": _get_db_url(inbox_db),
        "created": {"page": created_page, "db": created_db},
        "seed": seed_res,
        "note": "In Notion Calendar: add 'Reminders Inbox (Auto)' and select the 'Due' date field.",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

