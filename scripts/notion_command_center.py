#!/usr/bin/env python3
"""Create a customized-looking Notion dashboard + infra databases for Stephen.

What it builds (under the existing Control Hub page):
  - Command Center page (dashboard tiles + links) with icon + cover
  - Infrastructure page with icon + cover
  - Databases under Infrastructure:
      * Devices (Auto)
      * Services (Auto)
      * Cameras (Auto)
      * Modes (Auto)

Design goal:
  Make the Control Hub feel like a "Command Center" instead of a bland Notion page,
  using covers, icons, callout tiles, and columns.

Safety:
  - Never reads or prints secrets.
  - Seeds only safe starter content (no tokens/passwords).
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


def _rt_list(lines: list[tuple[str, str | None]]) -> list[dict]:
    return [_rt(t, u) for t, u in lines if t is not None]


def _block_heading(level: int, text: str) -> dict:
    t = max(1, min(int(level), 3))
    key = f"heading_{t}"
    return {"object": "block", "type": key, key: {"rich_text": [_rt(text)]}}


def _block_paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [_rt(text)]}}


def _block_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _block_callout(text: str, *, url: str | None = None, icon: str = "✨", color: str = "gray_background") -> dict:
    # Make the whole callout clickable by applying a link to the rich text.
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [_rt(text, url=url)] if url else [_rt(text)],
            "icon": {"type": "emoji", "emoji": icon},
            "color": color,
        },
    }


def _block_column(children: list[dict]) -> dict:
    return {"object": "block", "type": "column", "column": {"children": children}}


def _block_column_list(columns: list[list[dict]]) -> dict:
    return {
        "object": "block",
        "type": "column_list",
        "column_list": {"children": [_block_column(col) for col in columns]},
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
    # Prefer the integration-created ids (30af...) when duplicates exist.
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


def _update_page_meta(page_id: str, *, icon: str | None = None, cover_url: str | None = None) -> bool:
    page_id = (page_id or "").strip()
    if not page_id:
        return False
    body: dict = {}
    if icon:
        body["icon"] = {"type": "emoji", "emoji": icon}
    if cover_url:
        body["cover"] = {"type": "external", "external": {"url": cover_url}}
    if not body:
        return True
    res = request_json("PATCH", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers(), body=body)
    return bool(res.get("ok"))


def _maybe_create_db(parent_page_id: str, title: str, schema: dict) -> tuple[bool, str, str]:
    existing = _child_databases(parent_page_id).get(title) or []
    if existing:
        return False, _pick_id(existing), ""
    res = create_database(parent_page_id, title, schema, is_inline=True)
    if not res.get("ok"):
        return False, "", (res.get("error") or "")[:400]
    db_id = ((res.get("data") or {}).get("id") or "").strip()
    if not db_id:
        return False, "", "database created but id missing"
    return True, db_id, ""


def _title_set(database_id: str, title_prop: str, page_size: int = 200) -> set[str]:
    res = query_database(database_id, page_size=page_size)
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


def _dashboard_marker_present(page_id: str) -> bool:
    marker = "AUTOGEN: command_center_v1"
    for b in _list_block_children(page_id, page_size=100):
        if b.get("type") != "code":
            continue
        rt = ((b.get("code") or {}).get("rich_text") or [])
        text = "".join(((c.get("text") or {}).get("content") or "") for c in rt if c.get("type") == "text")
        if marker in text:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Notion Command Center + infra databases.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    parser.add_argument("--projects-db-id", default="30af7bec-843d-81c3-b2d2-c892b27b1a17")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    hub_id = (args.control_hub_id or "").strip()
    if not hub_id:
        print(json.dumps({"ok": False, "error": "missing control hub id"}, indent=2))
        return 2

    child = _child_pages(hub_id)

    def pick(title: str) -> str:
        ids = child.get(title) or []
        return _pick_id(ids)

    # Prefer the integration-created versions of the core pages (30af...).
    page_ids = {
        "Start Here": pick("Start Here"),
        "Artesian Pools": pick("Artesian Pools"),
        "ULAN Home Automation": pick("ULAN Home Automation"),
        "System Health": pick("System Health"),
        "Integrations": pick("Integrations"),
        "Troubleshooting": pick("Troubleshooting"),
        "iOS Agent Runner": pick("iOS Agent Runner"),
        "Hey Claude": pick("Hey Claude"),
        "Phone Buttons": pick("Phone Buttons"),
        "Ideas Backlog": pick("Ideas Backlog"),
        "Projects": pick("Projects"),
        "Possibilities / Use Cases": pick("Possibilities / Use Cases"),
        "Ash-Leigh's Pantry": pick("Ash-Leigh's Pantry"),
        "Now / Next / Later": pick("Now / Next / Later"),
    }

    # Ensure Infrastructure + Command Center pages exist.
    infra_title = "Infrastructure"
    cc_title = "Command Center"

    infra_id = pick(infra_title)
    if not infra_id:
        ok, pid, err = _create_page(hub_id, infra_title, icon="🛠️", cover_url="https://www.notion.so/images/page-cover/gradients_2.png")
        if not ok:
            print(json.dumps({"ok": False, "error": f"create Infrastructure page: {err}"}, indent=2))
            return 1
        infra_id = pid

    cc_id = pick(cc_title)
    if not cc_id:
        ok, pid, err = _create_page(hub_id, cc_title, icon="🧭", cover_url="https://www.notion.so/images/page-cover/gradients_5.png")
        if not ok:
            print(json.dumps({"ok": False, "error": f"create Command Center page: {err}"}, indent=2))
            return 1
        cc_id = pid

    # Update icons/covers on key pages to reduce "bland Notion" feel.
    _update_page_meta(cc_id, icon="🧭", cover_url="https://www.notion.so/images/page-cover/gradients_5.png")
    _update_page_meta(infra_id, icon="🛠️", cover_url="https://www.notion.so/images/page-cover/gradients_2.png")
    if page_ids.get("Artesian Pools"):
        _update_page_meta(page_ids["Artesian Pools"], icon="🏊", cover_url="https://www.notion.so/images/page-cover/gradients_7.png")
    if page_ids.get("ULAN Home Automation"):
        _update_page_meta(page_ids["ULAN Home Automation"], icon="📡", cover_url="https://www.notion.so/images/page-cover/gradients_4.png")
    if page_ids.get("System Health"):
        _update_page_meta(page_ids["System Health"], icon="🩺", cover_url="https://www.notion.so/images/page-cover/gradients_3.png")
    if page_ids.get("Troubleshooting"):
        _update_page_meta(page_ids["Troubleshooting"], icon="🧯", cover_url="https://www.notion.so/images/page-cover/gradients_6.png")
    if page_ids.get("Integrations"):
        _update_page_meta(page_ids["Integrations"], icon="🔌", cover_url="https://www.notion.so/images/page-cover/gradients_8.png")
    if page_ids.get("iOS Agent Runner"):
        _update_page_meta(page_ids["iOS Agent Runner"], icon="📱", cover_url="https://www.notion.so/images/page-cover/gradients_1.png")
    if page_ids.get("Hey Claude"):
        _update_page_meta(page_ids["Hey Claude"], icon="🎙️", cover_url="https://www.notion.so/images/page-cover/gradients_9.png")
    if page_ids.get("Possibilities / Use Cases"):
        _update_page_meta(page_ids["Possibilities / Use Cases"], icon="🧠", cover_url="https://www.notion.so/images/page-cover/gradients_5.png")
    if page_ids.get("Ash-Leigh's Pantry"):
        _update_page_meta(page_ids["Ash-Leigh's Pantry"], icon="🥫", cover_url="https://www.notion.so/images/page-cover/gradients_2.png")
    if page_ids.get("Now / Next / Later"):
        _update_page_meta(page_ids["Now / Next / Later"], icon="🗺️", cover_url="https://www.notion.so/images/page-cover/gradients_4.png")

    # Create infra databases under Infrastructure.
    created_dbs: dict[str, str] = {}
    seeded: dict[str, dict] = {}
    errors: list[str] = []

    devices_schema = {
        "Device": {"title": {}},
        "Category": {"select": {"options": [
            {"name": "VR", "color": "purple"},
            {"name": "Server", "color": "green"},
            {"name": "Laptop", "color": "blue"},
            {"name": "TV", "color": "yellow"},
            {"name": "Receiver", "color": "orange"},
            {"name": "Camera", "color": "pink"},
            {"name": "Other", "color": "gray"},
        ]}},
        "Location": {"select": {"options": [
            {"name": "Home", "color": "blue"},
            {"name": "Living Room", "color": "green"},
            {"name": "Office", "color": "purple"},
            {"name": "Garage", "color": "yellow"},
            {"name": "Unknown", "color": "gray"},
        ]}},
        "IP": {"rich_text": {}},
        "MAC": {"rich_text": {}},
        "Hostname": {"rich_text": {}},
        "Connection": {"select": {"options": [
            {"name": "LAN", "color": "green"},
            {"name": "WiFi", "color": "blue"},
            {"name": "Tailscale", "color": "purple"},
            {"name": "USB", "color": "yellow"},
            {"name": "Bluetooth", "color": "orange"},
        ]}},
        "Critical": {"checkbox": {}},
        "Notes": {"rich_text": {}},
    }

    created, devices_db, err = _maybe_create_db(infra_id, "Devices (Auto)", devices_schema)
    if err:
        errors.append(f"Devices DB: {err}")
    else:
        if created:
            created_dbs["Devices (Auto)"] = devices_db
        devices_rows = [
            {
                "Device": build_title_prop("MacBook Pro (Control Hub host)"),
                "Category": build_select_prop("Laptop"),
                "Location": build_select_prop("Office"),
                "Connection": build_select_prop("LAN"),
                "Critical": build_checkbox_prop(True),
                "Notes": build_rich_text_prop("Runs ULAN bridge + iOS Agent Runner + Notion automation scripts."),
            },
            {
                "Device": build_title_prop("Pi5 (tailnet + services)"),
                "Category": build_select_prop("Server"),
                "Location": build_select_prop("Home"),
                "IP": build_rich_text_prop("100.100.32.58 (Tailscale)"),
                "Connection": build_select_prop("Tailscale"),
                "Critical": build_checkbox_prop(True),
                "Notes": build_rich_text_prop("Primary offload/automation box. SSH user: pi."),
            },
            {
                "Device": build_title_prop("Quest 3 (VR headset)"),
                "Category": build_select_prop("VR"),
                "Location": build_select_prop("Home"),
                "IP": build_rich_text_prop("192.168.4.98 (WiFi ADB)"),
                "Connection": build_select_prop("WiFi"),
                "Critical": build_checkbox_prop(False),
                "Notes": build_rich_text_prop("USB serial: 2G0YC5ZG8F07NT. Use for field measurement assist + showroom."),
            },
            {
                "Device": build_title_prop("Shield TV (DO NOT TOUCH)"),
                "Category": build_select_prop("TV"),
                "Location": build_select_prop("Living Room"),
                "IP": build_rich_text_prop("192.168.4.64:5555 (per Stephen); 192.168.4.79:5555 (ticket)"),
                "Connection": build_select_prop("LAN"),
                "Critical": build_checkbox_prop(True),
                "Notes": build_rich_text_prop("Mark as critical. Avoid disconnecting/kill-server operations that could drop it."),
            },
            {
                "Device": build_title_prop("LG C9 (TV)"),
                "Category": build_select_prop("TV"),
                "Location": build_select_prop("Living Room"),
                "Connection": build_select_prop("LAN"),
                "Critical": build_checkbox_prop(False),
                "Notes": build_rich_text_prop("Add IP/adapter details as you confirm them."),
            },
            {
                "Device": build_title_prop("Yamaha RX-V6A (Receiver)"),
                "Category": build_select_prop("Receiver"),
                "Location": build_select_prop("Living Room"),
                "Connection": build_select_prop("LAN"),
                "Critical": build_checkbox_prop(False),
                "Notes": build_rich_text_prop("Good candidate for a robust ULAN adapter + scenes."),
            },
            {
                "Device": build_title_prop("Wyze Cam v2 (Camera)"),
                "Category": build_select_prop("Camera"),
                "Location": build_select_prop("Unknown"),
                "MAC": build_rich_text_prop("2C:AA:8E:AB:D0:BA"),
                "Connection": build_select_prop("WiFi"),
                "Critical": build_checkbox_prop(False),
                "Notes": build_rich_text_prop("Model: WYZEC2. Add stream URL/retention workflow once confirmed."),
            },
        ]
        seeded["Devices (Auto)"] = _seed_rows(devices_db, "Device", devices_rows)

    services_schema = {
        "Service": {"title": {}},
        "Host": {"select": {"options": [
            {"name": "Mac", "color": "blue"},
            {"name": "Pi5", "color": "green"},
            {"name": "Other", "color": "gray"},
        ]}},
        "Kind": {"select": {"options": [
            {"name": "Python", "color": "purple"},
            {"name": "Node", "color": "yellow"},
            {"name": "Docker", "color": "orange"},
            {"name": "LaunchAgent", "color": "gray"},
            {"name": "Other", "color": "blue"},
        ]}},
        "URL": {"url": {}},
        "Status": {"select": {"options": [
            {"name": "OK", "color": "green"},
            {"name": "Unknown", "color": "gray"},
            {"name": "Failing", "color": "red"},
        ]}},
        "Health Check": {"rich_text": {}},
        "Restart (manual)": {"rich_text": {}},
        "Notes": {"rich_text": {}},
    }
    created, services_db, err = _maybe_create_db(infra_id, "Services (Auto)", services_schema)
    if err:
        errors.append(f"Services DB: {err}")
    else:
        if created:
            created_dbs["Services (Auto)"] = services_db
        services_rows = [
            {
                "Service": build_title_prop("ULAN Alexa bridge"),
                "Host": build_select_prop("Mac"),
                "Kind": build_select_prop("Python"),
                "Status": build_select_prop("Unknown"),
                "Health Check": build_rich_text_prop("Hit the /claude endpoint from Shortcuts or curl; expect a JSON response."),
                "Restart (manual)": build_rich_text_prop("cd ~/ulan-agent && source .venv/bin/activate && bash scripts/start-alexa-bridge.sh"),
                "Notes": build_rich_text_prop("Core home-control entrypoint."),
            },
            {
                "Service": build_title_prop("iOS Agent Runner MCP server"),
                "Host": build_select_prop("Mac"),
                "Kind": build_select_prop("Python"),
                "Status": build_select_prop("Unknown"),
                "Health Check": build_rich_text_prop("Start mcp_server.py and confirm MCP tools are reachable."),
                "Restart (manual)": build_rich_text_prop("cd ~/ios-agent-runner && source .venv/bin/activate && python mcp_server.py"),
                "Notes": build_rich_text_prop("Enables automation + intel pipeline."),
            },
            {
                "Service": build_title_prop("Ash-Leigh's Pantry (Streamlit UI)"),
                "Host": build_select_prop("Mac"),
                "Kind": build_select_prop("Python"),
                "Status": build_select_prop("Unknown"),
                "Health Check": build_rich_text_prop("Run app and open the LAN URL from your phone."),
                "Restart (manual)": build_rich_text_prop("cd ~/kroger-playground && ./run_app.sh"),
                "Notes": build_rich_text_prop("Family-friendly UI for pantry + shopping list workflows."),
            },
            {
                "Service": build_title_prop("Hey Claude (wake word assistant)"),
                "Host": build_select_prop("Pi5"),
                "Kind": build_select_prop("Python"),
                "Status": build_select_prop("Unknown"),
                "Health Check": build_rich_text_prop("Use interactive mode (no mic) to validate intents safely."),
                "Restart (manual)": build_rich_text_prop("cd ~/hey-claude && ./install.sh (or systemd service if installed)"),
                "Notes": build_rich_text_prop("Add Quiet Hours + Dry Run guards first."),
            },
            {
                "Service": build_title_prop("Camera loop (3 cams, 30-day retention)"),
                "Host": build_select_prop("Pi5"),
                "Kind": build_select_prop("Docker"),
                "Status": build_select_prop("Unknown"),
                "Health Check": build_rich_text_prop("Confirm recording + storage usage; verify oldest footage rotates out at ~30 days."),
                "Restart (manual)": build_rich_text_prop("docker ps; docker logs <container>; docker restart <container>"),
                "Notes": build_rich_text_prop("Placeholder row for the ongoing camera build."),
            },
        ]
        seeded["Services (Auto)"] = _seed_rows(services_db, "Service", services_rows)

    cameras_schema = {
        "Camera": {"title": {}},
        "Model": {"rich_text": {}},
        "Location": {"select": {"options": [
            {"name": "Front", "color": "blue"},
            {"name": "Back", "color": "green"},
            {"name": "Garage", "color": "yellow"},
            {"name": "Office", "color": "purple"},
            {"name": "Unknown", "color": "gray"},
        ]}},
        "MAC": {"rich_text": {}},
        "Stream URL": {"url": {}},
        "Retention (days)": {"number": {"format": "number"}},
        "Recording": {"select": {"options": [
            {"name": "Continuous", "color": "green"},
            {"name": "Motion", "color": "yellow"},
            {"name": "Off", "color": "gray"},
        ]}},
        "Storage Target": {"select": {"options": [
            {"name": "Pi5", "color": "green"},
            {"name": "Cloud", "color": "blue"},
            {"name": "NAS", "color": "purple"},
        ]}},
        "Notes": {"rich_text": {}},
    }
    created, cameras_db, err = _maybe_create_db(infra_id, "Cameras (Auto)", cameras_schema)
    if err:
        errors.append(f"Cameras DB: {err}")
    else:
        if created:
            created_dbs["Cameras (Auto)"] = cameras_db
        cameras_rows = [
            {
                "Camera": build_title_prop("Wyze Cam v2 (template)"),
                "Model": build_rich_text_prop("WYZEC2"),
                "Location": build_select_prop("Unknown"),
                "MAC": build_rich_text_prop("2C:AA:8E:AB:D0:BA"),
                "Retention (days)": build_number_prop(30),
                "Recording": build_select_prop("Continuous"),
                "Storage Target": build_select_prop("Pi5"),
                "Notes": build_rich_text_prop("Fill in the stream URL once you confirm RTSP / NVR pipeline."),
            },
            {
                "Camera": build_title_prop("Camera #2 (template)"),
                "Retention (days)": build_number_prop(30),
                "Recording": build_select_prop("Continuous"),
                "Storage Target": build_select_prop("Pi5"),
                "Notes": build_rich_text_prop("Placeholder for the 3-camera loop build."),
            },
            {
                "Camera": build_title_prop("Camera #3 (template)"),
                "Retention (days)": build_number_prop(30),
                "Recording": build_select_prop("Continuous"),
                "Storage Target": build_select_prop("Pi5"),
                "Notes": build_rich_text_prop("Placeholder for the 3-camera loop build."),
            },
        ]
        seeded["Cameras (Auto)"] = _seed_rows(cameras_db, "Camera", cameras_rows)

    modes_schema = {
        "Mode": {"title": {}},
        "Quiet Hours": {"checkbox": {}},
        "Dry Run": {"checkbox": {}},
        "Notes": {"rich_text": {}},
    }
    created, modes_db, err = _maybe_create_db(infra_id, "Modes (Auto)", modes_schema)
    if err:
        errors.append(f"Modes DB: {err}")
    else:
        if created:
            created_dbs["Modes (Auto)"] = modes_db
        modes_rows = [
            {
                "Mode": build_title_prop("Global"),
                "Quiet Hours": build_checkbox_prop(False),
                "Dry Run": build_checkbox_prop(False),
                "Notes": build_rich_text_prop("Flip these when testing new automations. Quiet Hours blocks noisy actions."),
            }
        ]
        seeded["Modes (Auto)"] = _seed_rows(modes_db, "Mode", modes_rows)

    # Append a dashboard layout to the Command Center page once.
    if not _dashboard_marker_present(cc_id):
        urls = {
            "Infrastructure": _get_page_url(infra_id),
            "Start Here": _get_page_url(page_ids.get("Start Here") or ""),
            "Artesian Pools": _get_page_url(page_ids.get("Artesian Pools") or ""),
            "ULAN Home Automation": _get_page_url(page_ids.get("ULAN Home Automation") or ""),
            "System Health": _get_page_url(page_ids.get("System Health") or ""),
            "Integrations": _get_page_url(page_ids.get("Integrations") or ""),
            "Troubleshooting": _get_page_url(page_ids.get("Troubleshooting") or ""),
            "Possibilities / Use Cases": _get_page_url(page_ids.get("Possibilities / Use Cases") or ""),
            "Pantry": _get_page_url(page_ids.get("Ash-Leigh's Pantry") or ""),
            "Roadmap": _get_page_url(page_ids.get("Now / Next / Later") or ""),
        }
        db_urls = {
            "Devices": _get_db_url(devices_db) if "devices_db" in locals() else "",
            "Services": _get_db_url(services_db) if "services_db" in locals() else "",
            "Cameras": _get_db_url(cameras_db) if "cameras_db" in locals() else "",
            "Modes": _get_db_url(modes_db) if "modes_db" in locals() else "",
            "Ideas": _get_db_url("30af7bec-843d-818d-8d6d-e0e02953e527"),
            "Projects": _get_db_url("30af7bec-843d-81c3-b2d2-c892b27b1a17"),
        }

        tiles_home = [
            _block_callout("Scenes (Auto)", url=(_get_db_url("30af7bec-843d-814c-9f39-d517ea09a246")), icon="🎬", color="yellow_background"),
            _block_callout("Buttons (Auto)", url=(_get_db_url("30af7bec-843d-8160-bd9e-e2370f588ede")), icon="📲", color="blue_background"),
            _block_callout("Devices (Auto)", url=db_urls["Devices"], icon="🧩", color="gray_background"),
            _block_callout("Quiet Hours / Dry Run (Modes)", url=db_urls["Modes"], icon="🛡️", color="green_background"),
        ]

        tiles_business = [
            _block_callout("Artesian Pools", url=urls["Artesian Pools"], icon="🏊", color="green_background"),
            _block_callout("Jobs (Template)", url=_get_db_url("30af7bec-843d-8144-af68-f056b4602582"), icon="🧾", color="yellow_background"),
            _block_callout("Customers", url=_get_db_url("30af7bec-843d-8176-be9e-d54570d5cc38"), icon="🧑‍🤝‍🧑", color="blue_background"),
            _block_callout("Quotes", url=_get_db_url("30af7bec-843d-81ad-860d-fe61c33ba4bd"), icon="💰", color="pink_background"),
        ]

        tiles_ops = [
            _block_callout("Runbooks (Auto)", url=_get_db_url("30af7bec-843d-8196-8ef3-f8a920a86685"), icon="📟", color="gray_background"),
            _block_callout("Services (Auto)", url=db_urls["Services"], icon="🧰", color="orange_background"),
            _block_callout("Integration Status", url=_get_db_url("30af7bec-843d-8144-a4b2-c55e56cca7aa"), icon="🔌", color="purple_background"),
            _block_callout("Local Knowledge Index", url=_get_db_url("30af7bec-843d-81fb-9dee-db018ec0e975"), icon="📚", color="blue_background"),
        ]

        tiles_misc = [
            _block_callout("Possibilities / Use Cases", url=urls["Possibilities / Use Cases"], icon="🧠", color="purple_background"),
            _block_callout("Now / Next / Later", url=urls["Roadmap"], icon="🗺️", color="yellow_background"),
            _block_callout("Pantry", url=urls["Pantry"], icon="🥫", color="green_background"),
            _block_callout("Ideas DB", url=db_urls["Ideas"], icon="💡", color="gray_background"),
        ]

        blocks: list[dict] = []
        blocks.append(_block_heading(1, "Stephen Command Center"))
        blocks.append(_block_paragraph("A dashboard for home, business, and ops. Built to look like a command center, not a plain Notion doc."))
        blocks.append(_block_divider())
        blocks.append(_block_heading(2, "Quick Tiles"))
        blocks.append(_block_column_list([tiles_home, tiles_business, tiles_ops]))
        blocks.append(_block_divider())
        blocks.append(_block_heading(2, "More"))
        blocks.append(_block_column_list([tiles_misc, [
            _block_callout("Infrastructure", url=urls["Infrastructure"], icon="🛠️", color="orange_background"),
            _block_callout("ULAN Home Automation", url=urls["ULAN Home Automation"], icon="📡", color="blue_background"),
            _block_callout("System Health", url=urls["System Health"], icon="🩺", color="green_background"),
            _block_callout("Troubleshooting", url=urls["Troubleshooting"], icon="🧯", color="red_background"),
        ], [
            _block_callout("Projects DB", url=db_urls["Projects"], icon="🗂️", color="gray_background"),
            _block_callout("Integrations", url=urls["Integrations"], icon="🔌", color="purple_background"),
            _block_callout("Cameras (Auto)", url=db_urls["Cameras"], icon="📷", color="pink_background"),
            _block_callout("Start Here", url=urls["Start Here"], icon="🏠", color="gray_background"),
        ]]))
        blocks.append(_block_divider())
        blocks.append(
            {
                "object": "block",
                "type": "code",
                "code": {"language": "plain text", "rich_text": [_rt("AUTOGEN: command_center_v1")]},
            }
        )

        appended = append_blocks(cc_id, blocks)
        if not appended.get("ok"):
            errors.append(f"append dashboard blocks: {(appended.get('error') or '')[:200]}")

    # Add link to Command Center from Start Here (small, safe, one-way append).
    start_here_id = page_ids.get("Start Here") or ""
    if start_here_id:
        cc_url = _get_page_url(cc_id)
        infra_url = _get_page_url(infra_id)
        add = append_blocks(
            start_here_id,
            [
                _block_divider(),
                _block_heading(2, "Command Center"),
                _block_callout("Open Command Center", url=cc_url, icon="🧭", color="blue_background"),
                _block_callout("Open Infrastructure", url=infra_url, icon="🛠️", color="orange_background"),
            ],
        )
        if not add.get("ok"):
            errors.append(f"update Start Here links: {(add.get('error') or '')[:200]}")

    out = {
        "ok": not errors and all(v.get("ok", True) for v in seeded.values()),
        "control_hub_id": hub_id,
        "pages": {
            "command_center_id": cc_id,
            "infrastructure_id": infra_id,
        },
        "created_databases": created_dbs,
        "seeded": seeded,
        "errors": errors,
    }
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

