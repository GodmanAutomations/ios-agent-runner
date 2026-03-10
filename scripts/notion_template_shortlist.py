#!/usr/bin/env python3
"""Create a Template Shortlist page in the Notion Control Hub.

This page is a curated list of templates that:
  - look good (dashboards, charts, organization)
  - are automation-friendly (date fields, databases, import hooks)

It also links to the internal OS pages we created (Inventory, Schedule, etc.).
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


def _p(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [_rt(text)]}}


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
    for b in _list_children(page_id, page_size=100):
        if b.get("type") != "code":
            continue
        rt = ((b.get("code") or {}).get("rich_text") or [])
        txt = "".join(((c.get("text") or {}).get("content") or "") for c in rt if c.get("type") == "text")
        if marker in txt:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Template Shortlist page in Control Hub.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ios-agent-runner/.env)"}, indent=2))
        return 2

    hub_id = (args.control_hub_id or "").strip()
    child = _child_pages(hub_id)

    page_id = _pick_id(child.get("Template Shortlist") or [])
    created = False
    if not page_id:
        ok, pid, err = _create_page(
            hub_id,
            "Template Shortlist",
            icon="🧩",
            cover_url="https://www.notion.so/images/page-cover/gradients_6.png",
        )
        if not ok:
            print(json.dumps({"ok": False, "error": f"create page: {err}"}, indent=2))
            return 1
        page_id = pid
        created = True
    else:
        _update_page_meta(page_id, icon="🧩", cover_url="https://www.notion.so/images/page-cover/gradients_6.png")

    marker = "AUTOGEN: template_shortlist_v1"
    if not _marker_present(page_id, marker):
        # External templates (curated from Notion Marketplace + a few good roundups).
        templates = {
            "Inventory": [
                ("Notion Home Inventory Templates (category)", "https://www.notion.com/templates/category/home-inventory", "🏠", "blue_background"),
                ("Home Safe Inventory (built-in charts)", "https://www.notion.com/templates/home-safe-inventory-w-built-in-charts", "📊", "yellow_background"),
                ("Household Inventory (offsite record + photos)", "https://www.notion.com/templates/household-inventory", "📸", "green_background"),
                ("Home Inventory + Shopping List", "https://www.notion.com/templates/home-inventory-shopping-list", "🛒", "pink_background"),
                ("Inventory Management Templates (category)", "https://www.notion.com/templates/category/inventory-management", "📦", "gray_background"),
                ("IT Inventory Templates (category)", "https://www.notion.com/templates/category/it-inventory", "🖥️", "purple_background"),
            ],
            "Finance": [
                ("Personal Finance Templates (category)", "https://www.notion.com/templates/category/personal-finance", "💵", "green_background"),
                ("Budgets Templates (category)", "https://www.notion.com/templates/category/budgets", "🧾", "yellow_background"),
                ("Finance & Budget Tracker (dashboard)", "https://www.notion.com/templates/finance-budget-tracker-income-expenses-dashboard", "📈", "blue_background"),
                ("Simple Finance Tracker + Analytics", "https://www.notion.com/templates/simple-finance-tracker-analytics", "📊", "gray_background"),
                ("Bank-connected Notion Budget Tracker (guide)", "https://matthiasfrank.de/en/notion-budget-tracker/", "🏦", "purple_background"),
            ],
            "Tasks / Reminders": [
                ("Reminders Template (Marketplace)", "https://www.notion.com/templates/reminder-679", "⏰", "yellow_background"),
                ("To-Do Lists Templates (category)", "https://www.notion.com/templates/category/to-do-lists", "✅", "green_background"),
                ("Notion Reminders Help", "https://www.notion.com/help/reminders", "📎", "gray_background"),
            ],
        }

        blocks: list[dict] = []
        blocks.append(_h(1, "Template Shortlist (Looks Good + Automation-Friendly)"))
        blocks.append(_p("Use this page as your 'template store'. Duplicate what you like, then we wire it to auto-populate via scripts/Shortcuts."))
        blocks.append(_div())

        blocks.append(_h(2, "Inventory Templates (Garage/Shed/Pool Stuff)"))
        for title, url, icon, color in templates["Inventory"]:
            blocks.append(_callout(title, url, icon=icon, color=color))
        blocks.append(_div())

        blocks.append(_h(2, "Finance Templates (Plaid-friendly)"))
        blocks.append(_p("Best pattern: transactions DB + categories + rules + dashboards. Plaid fills the transactions DB; Notion does the views/charts."))
        for title, url, icon, color in templates["Finance"]:
            blocks.append(_callout(title, url, icon=icon, color=color))
        blocks.append(_div())

        blocks.append(_h(2, "Tasks / Reminders Templates"))
        blocks.append(_p("Notion Calendar will show any database with a Date property. Your Reminders DB should always have a 'Due' field."))
        for title, url, icon, color in templates["Tasks / Reminders"]:
            blocks.append(_callout(title, url, icon=icon, color=color))
        blocks.append(_div())

        blocks.append(_h(2, "What Makes a Template Auto-Populate"))
        blocks.append(_p("Templates don't truly auto-fill unless you connect a data source. Your options:"))
        blocks.append(_p("1. Notion automations + formulas (good for internal logic)"))
        blocks.append(_p("2. iPhone Shortcuts (fastest: one button -> create DB row)"))
        blocks.append(_p("3. Notion API scripts (best: daily sync from Plaid, LAN, cameras, etc.)"))
        blocks.append(_div())

        blocks.append(
            {
                "object": "block",
                "type": "code",
                "code": {"language": "plain text", "rich_text": [_rt(marker)]},
            }
        )

        appended = append_blocks(page_id, blocks)
        if not appended.get("ok"):
            print(json.dumps({"ok": False, "error": (appended.get("error") or "")[:200]}, indent=2))
            return 1

    out = {"ok": True, "page_id": page_id, "page_url": _get_page_url(page_id), "created": created}
    print(json.dumps(out, indent=2))
    return 0


def _get_page_url(page_id: str) -> str:
    res = request_json("GET", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers())
    if not res.get("ok"):
        return ""
    return ((res.get("data") or {}).get("url") or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())

