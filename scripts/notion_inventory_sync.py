#!/usr/bin/env python3
"""Auto-maintain Inventory DB logic (reorder flag) in Notion.

This is the "auto-populate" part for inventory:
  - Reads Qty + Min for each item
  - Sets Reorder checkbox when Qty < Min
  - Updates Last Updated date

Intended to run on a schedule (LaunchAgent).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.integrations.http import request_json
from scripts.integrations.notion_api import query_database

_NOTION_VERSION = "2022-06-28"


def _headers() -> dict[str, str]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}", "Notion-Version": _NOTION_VERSION}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


def _child_databases(parent_page_id: str) -> dict[str, list[str]]:
    dbs: dict[str, list[str]] = {}
    for b in _list_children(parent_page_id, page_size=100):
        if b.get("type") != "child_database":
            continue
        title = ((b.get("child_database") or {}).get("title") or "").strip()
        bid = (b.get("id") or "").strip()
        if title and bid:
            dbs.setdefault(title, []).append(bid)
    return dbs


def _num(props: dict, name: str) -> float | None:
    p = (props.get(name) or {})
    if (p.get("type") or "") != "number":
        return None
    return p.get("number")


def _checkbox(props: dict, name: str) -> bool | None:
    p = (props.get(name) or {})
    if (p.get("type") or "") != "checkbox":
        return None
    return bool(p.get("checkbox"))


def _update_page(page_id: str, properties: dict) -> bool:
    res = request_json("PATCH", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers(), body={"properties": properties})
    return bool(res.get("ok"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync reorder flags in Inventory database.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    parser.add_argument("--inventory-page-id", default="")
    parser.add_argument("--items-db-id", default="")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".godman_keys.env")

    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ~/.godman_keys.env)"}, indent=2))
        return 2

    hub_id = (args.control_hub_id or "").strip()
    inventory_page_id = (args.inventory_page_id or "").strip()
    items_db_id = (args.items_db_id or "").strip()

    if not inventory_page_id and hub_id:
        pages = _child_pages(hub_id)
        inventory_page_id = _pick_id(pages.get("Inventory") or [])

    if not items_db_id and inventory_page_id:
        dbs = _child_databases(inventory_page_id)
        items_db_id = _pick_id(dbs.get("Garage & Shed Inventory (Auto)") or [])

    if not items_db_id:
        print(json.dumps({"ok": False, "error": "Items DB id not found (Inventory page missing?)"}, indent=2))
        return 2

    res = query_database(items_db_id, page_size=100)
    if not res.get("ok"):
        print(json.dumps({"ok": False, "error": (res.get("error") or "")[:300]}, indent=2))
        return 1

    rows = (res.get("data") or {}).get("results") or []
    today = _today()

    changed = 0
    checked = 0
    for page in rows:
        pid = (page.get("id") or "").strip()
        props = page.get("properties") or {}
        qty = _num(props, "Qty")
        min_qty = _num(props, "Min")
        current = _checkbox(props, "Reorder")

        if qty is None or min_qty is None:
            # If no min/qty, don't force anything.
            checked += 1
            continue

        should = bool(qty < min_qty)
        if current is not None and current == should:
            checked += 1
            continue

        ok = _update_page(
            pid,
            {
                "Reorder": {"checkbox": should},
                "Last Updated": {"date": {"start": today}},
            },
        )
        if ok:
            changed += 1
        checked += 1

    print(json.dumps({"ok": True, "items_db_id": items_db_id, "checked": checked, "changed": changed, "date": today}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
