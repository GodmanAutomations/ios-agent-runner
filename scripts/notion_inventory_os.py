#!/usr/bin/env python3
"""Create an Inventory OS in the Notion Control Hub (garage/shed/pool supplies).

Creates (under Control Hub):
  - Inventory page (cover + icon)
  - Databases under Inventory page:
      * Garage & Shed Inventory (Auto)
      * Supply Purchases (Import)

Design:
  - Add a small dashboard header + link tiles so it feels less like plain Notion.

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
    build_number_prop,
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


def _patch_database_properties(database_id: str, properties: dict) -> bool:
    res = request_json("PATCH", f"https://api.notion.com/v1/databases/{database_id}", headers=_headers(), body={"properties": properties})
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
    parser = argparse.ArgumentParser(description="Create Inventory OS + databases in Notion Control Hub.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ios-agent-runner/.env)"}, indent=2))
        return 2

    hub_id = (args.control_hub_id or "").strip()
    child = _child_pages(hub_id)

    inventory_id = _pick_id(child.get("Inventory") or [])
    created_page = False
    if not inventory_id:
        ok, pid, err = _create_page(
            hub_id,
            "Inventory",
            icon="📦",
            cover_url="https://www.notion.so/images/page-cover/gradients_7.png",
        )
        if not ok:
            print(json.dumps({"ok": False, "error": f"create Inventory page: {err}"}, indent=2))
            return 1
        inventory_id = pid
        created_page = True
    else:
        _update_page_meta(inventory_id, icon="📦", cover_url="https://www.notion.so/images/page-cover/gradients_7.png")

    # Create Inventory items DB.
    dbs = _child_databases(inventory_id)
    items_db = _pick_id(dbs.get("Garage & Shed Inventory (Auto)") or [])
    created_items_db = False
    if not items_db:
        items_schema = {
            "Item": {"title": {}},
            "Location": {"select": {"options": [
                {"name": "Garage", "color": "yellow"},
                {"name": "Shed", "color": "green"},
                {"name": "Truck", "color": "blue"},
                {"name": "Office", "color": "purple"},
                {"name": "Job Site", "color": "gray"},
            ]}},
            "Category": {"select": {"options": [
                {"name": "Pool Parts", "color": "blue"},
                {"name": "Tools", "color": "yellow"},
                {"name": "Hardware", "color": "orange"},
                {"name": "Plumbing", "color": "green"},
                {"name": "Electrical", "color": "purple"},
                {"name": "Safety", "color": "red"},
                {"name": "Chemicals", "color": "pink"},
                {"name": "Misc", "color": "gray"},
            ]}},
            "Qty": {"number": {"format": "number"}},
            "Unit": {"select": {"options": [
                {"name": "each", "color": "gray"},
                {"name": "box", "color": "yellow"},
                {"name": "bag", "color": "green"},
                {"name": "ft", "color": "blue"},
                {"name": "lb", "color": "orange"},
                {"name": "gal", "color": "purple"},
            ]}},
            "Min": {"number": {"format": "number"}},
            "Reorder": {"checkbox": {}},
            "Vendor": {"select": {"options": [
                {"name": "SupplyHouse", "color": "blue"},
                {"name": "SCP", "color": "green"},
                {"name": "Home Depot", "color": "orange"},
                {"name": "Lowe's", "color": "yellow"},
                {"name": "Amazon", "color": "purple"},
                {"name": "Other", "color": "gray"},
            ]}},
            "SKU": {"rich_text": {}},
            "Last Price": {"number": {"format": "dollar"}},
            "Barcode": {"rich_text": {}},
            "Photo URL": {"url": {}},
            "Notes": {"rich_text": {}},
            "Last Updated": {"date": {}},
        }
        res = create_database(inventory_id, "Garage & Shed Inventory (Auto)", items_schema, is_inline=True)
        if not res.get("ok"):
            print(json.dumps({"ok": False, "error": (res.get("error") or "")[:300]}, indent=2))
            return 1
        items_db = ((res.get("data") or {}).get("id") or "").strip()
        created_items_db = True

    # Create Purchases DB (with relation to Items).
    dbs = _child_databases(inventory_id)
    purchases_db = _pick_id(dbs.get("Supply Purchases (Import)") or [])
    created_purchases_db = False
    if not purchases_db:
        purchases_schema = {
            "Purchase": {"title": {}},
            "Date": {"date": {}},
            "Vendor": {"select": {"options": [
                {"name": "SupplyHouse", "color": "blue"},
                {"name": "SCP", "color": "green"},
                {"name": "Home Depot", "color": "orange"},
                {"name": "Lowe's", "color": "yellow"},
                {"name": "Amazon", "color": "purple"},
                {"name": "Other", "color": "gray"},
            ]}},
            "Order ID": {"rich_text": {}},
            "SKU": {"rich_text": {}},
            "Description": {"rich_text": {}},
            "Qty": {"number": {"format": "number"}},
            "Unit Price": {"number": {"format": "dollar"}},
            "Total": {"number": {"format": "dollar"}},
            "URL": {"url": {}},
            "Item": {"relation": {"database_id": items_db, "single_property": {}}},
            "Notes": {"rich_text": {}},
        }
        res = create_database(inventory_id, "Supply Purchases (Import)", purchases_schema, is_inline=True)
        if not res.get("ok"):
            print(json.dumps({"ok": False, "error": (res.get("error") or "")[:300]}, indent=2))
            return 1
        purchases_db = ((res.get("data") or {}).get("id") or "").strip()
        created_purchases_db = True

    # Add reverse relation on Items DB (idempotent best-effort).
    _patch_database_properties(items_db, {"Purchases": {"relation": {"database_id": purchases_db, "single_property": {}}}})

    # Seed items (placeholders).
    seed_items = [
        {
            "Item": build_title_prop("Skimmer gasket set"),
            "Location": build_select_prop("Garage"),
            "Category": build_select_prop("Pool Parts"),
            "Qty": build_number_prop(2),
            "Unit": build_select_prop("each"),
            "Min": build_number_prop(2),
            "Vendor": build_select_prop("SupplyHouse"),
            "Reorder": build_checkbox_prop(False),
            "Notes": build_rich_text_prop("Template item. Add SKU + photo."),
        },
        {
            "Item": build_title_prop("Return fitting kit"),
            "Location": build_select_prop("Garage"),
            "Category": build_select_prop("Pool Parts"),
            "Qty": build_number_prop(1),
            "Unit": build_select_prop("each"),
            "Min": build_number_prop(2),
            "Vendor": build_select_prop("SupplyHouse"),
            "Reorder": build_checkbox_prop(True),
            "Notes": build_rich_text_prop("Example of a reorder-needed item (Qty < Min)."),
        },
        {
            "Item": build_title_prop("PVC primer + cement"),
            "Location": build_select_prop("Shed"),
            "Category": build_select_prop("Plumbing"),
            "Qty": build_number_prop(1),
            "Unit": build_select_prop("each"),
            "Min": build_number_prop(1),
            "Vendor": build_select_prop("Home Depot"),
            "Reorder": build_checkbox_prop(False),
            "Notes": build_rich_text_prop("Common plumbing supplies."),
        },
        {
            "Item": build_title_prop("Contractor trash bags"),
            "Location": build_select_prop("Garage"),
            "Category": build_select_prop("Misc"),
            "Qty": build_number_prop(1),
            "Unit": build_select_prop("box"),
            "Min": build_number_prop(2),
            "Vendor": build_select_prop("Home Depot"),
            "Reorder": build_checkbox_prop(True),
            "Notes": build_rich_text_prop("Demo day essential."),
        },
    ]
    items_seed_res = _seed_rows(items_db, "Item", seed_items)

    # Build a title -> page id map for seeded items (so we can seed a sample purchase).
    title_to_id: dict[str, str] = {}
    res = query_database(items_db, page_size=100)
    if res.get("ok"):
        for page in (res.get("data") or {}).get("results") or []:
            pid = (page.get("id") or "").strip()
            props = page.get("properties") or {}
            chunks = ((props.get("Item") or {}).get("title") or [])
            if pid and chunks:
                title = (chunks[0].get("plain_text") or "").strip()
                if title:
                    title_to_id[title] = pid

    seed_purchases = [
        {
            "Purchase": build_title_prop("SAMPLE - SupplyHouse order (template)"),
            "Date": build_date_prop("2026-02-17"),
            "Vendor": build_select_prop("SupplyHouse"),
            "Order ID": build_rich_text_prop("SAMPLE-ORDER-123"),
            "SKU": build_rich_text_prop("SAMPLE-SKU"),
            "Description": build_rich_text_prop("Skimmer gasket set"),
            "Qty": build_number_prop(2),
            "Unit Price": build_number_prop(0),
            "Total": build_number_prop(0),
            "Item": {"relation": [{"id": title_to_id.get("Skimmer gasket set", "")}]} if title_to_id.get("Skimmer gasket set") else {"relation": []},
            "Notes": build_rich_text_prop("When you paste/import SupplyHouse history, these rows will become real."),
        }
    ]
    purchases_seed_res = _seed_rows(purchases_db, "Purchase", seed_purchases)

    # Add a dashboard header (once).
    marker = "AUTOGEN: inventory_os_v1"
    if not _marker_present(inventory_id, marker):
        inv_url = _get_page_url(inventory_id)
        items_url = _get_db_url(items_db)
        purchases_url = _get_db_url(purchases_db)

        blocks = [
            _block_heading(1, "Inventory OS"),
            _block_callout("Garage & Shed Inventory (Auto)", url=items_url, icon="📦", color="blue_background"),
            _block_callout("Supply Purchases (Import)", url=purchases_url, icon="🧾", color="yellow_background"),
            _block_callout("Tip: paste SupplyHouse history -> import -> link SKUs to items", url=inv_url, icon="⚡", color="gray_background"),
            _block_divider(),
            {"object": "block", "type": "code", "code": {"language": "plain text", "rich_text": [_rt(marker)]}},
        ]
        append_blocks(inventory_id, blocks)

    out = {
        "ok": True,
        "inventory_page": _get_page_url(inventory_id),
        "items_db": _get_db_url(items_db),
        "purchases_db": _get_db_url(purchases_db),
        "created": {
            "page": created_page,
            "items_db": created_items_db,
            "purchases_db": created_purchases_db,
        },
        "seed": {
            "items": items_seed_res,
            "purchases": purchases_seed_res,
        },
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
