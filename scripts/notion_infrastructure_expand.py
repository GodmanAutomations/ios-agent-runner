#!/usr/bin/env python3
"""Expand the Infrastructure + Artesian areas in the Notion Control Hub.

Adds:
  - Incidents (Auto) database (infra issue log)
  - Maintenance (Auto) database (recurring checklist)
  - Artesian Measurements (Template) database (measurement intake)
  - Small "Infrastructure Dashboard" block section with links (idempotent marker)

Safety:
  - No secrets are read or printed.
  - Seed data is safe placeholders only.
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


def _marker_present(page_id: str, marker: str) -> bool:
    for b in _list_block_children(page_id, page_size=100):
        if b.get("type") != "code":
            continue
        rt = ((b.get("code") or {}).get("rich_text") or [])
        text = "".join(((c.get("text") or {}).get("content") or "") for c in rt if c.get("type") == "text")
        if marker in text:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand Infrastructure + Artesian in Notion Control Hub.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    hub_id = (args.control_hub_id or "").strip()
    if not hub_id:
        print(json.dumps({"ok": False, "error": "missing control hub id"}, indent=2))
        return 2

    child = _child_pages(hub_id)
    infra_id = _pick_id(child.get("Infrastructure") or [])
    artesian_id = _pick_id(child.get("Artesian Pools") or [])
    if not infra_id:
        print(json.dumps({"ok": False, "error": "Infrastructure page not found (run notion_command_center.py first)."}, indent=2))
        return 2
    if not artesian_id:
        print(json.dumps({"ok": False, "error": "Artesian Pools page not found under hub."}, indent=2))
        return 2

    infra_dbs = _child_databases(infra_id)
    devices_db = _pick_id(infra_dbs.get("Devices (Auto)") or [])
    services_db = _pick_id(infra_dbs.get("Services (Auto)") or [])
    cameras_db = _pick_id(infra_dbs.get("Cameras (Auto)") or [])
    modes_db = _pick_id(infra_dbs.get("Modes (Auto)") or [])

    created_dbs: dict[str, str] = {}
    seeded: dict[str, dict] = {}
    errors: list[str] = []

    # ---- Incidents DB ----
    incident_schema = {
        "Incident": {"title": {}},
        "Severity": {"select": {"options": [
            {"name": "P0", "color": "red"},
            {"name": "P1", "color": "orange"},
            {"name": "P2", "color": "yellow"},
            {"name": "P3", "color": "gray"},
        ]}},
        "Status": {"select": {"options": [
            {"name": "Open", "color": "red"},
            {"name": "Monitoring", "color": "yellow"},
            {"name": "Closed", "color": "green"},
        ]}},
        "When": {"date": {}},
        "Symptoms": {"rich_text": {}},
        "Root Cause": {"rich_text": {}},
        "Fix / Notes": {"rich_text": {}},
    }
    if devices_db:
        incident_schema["Related Device"] = {"relation": {"database_id": devices_db, "single_property": {}}}
    if services_db:
        incident_schema["Related Service"] = {"relation": {"database_id": services_db, "single_property": {}}}

    created, incidents_db, err = _maybe_create_db(infra_id, "Incidents (Auto)", incident_schema)
    if err:
        errors.append(f"Incidents DB: {err}")
    else:
        if created:
            created_dbs["Incidents (Auto)"] = incidents_db
        incidents_rows = [
            {
                "Incident": build_title_prop("Tailscale peers show as 0 on Mac"),
                "Severity": build_select_prop("P1"),
                "Status": build_select_prop("Monitoring"),
                "Symptoms": build_rich_text_prop("Mac connected but no peers listed; breaks Pi/Quest tailnet actions."),
                "Root Cause": build_rich_text_prop("Often version mismatch / daemon state / account mismatch."),
                "Fix / Notes": build_rich_text_prop("Restart Tailscale app/daemon, confirm same account, confirm peers in dashboard."),
            },
            {
                "Incident": build_title_prop("Shield HDMI drops every ~4 seconds (hotplug loop)"),
                "Severity": build_select_prop("P1"),
                "Status": build_select_prop("Open"),
                "Symptoms": build_rich_text_prop("Signal drops; hotplug events in dumpsys; routing changes."),
                "Root Cause": build_rich_text_prop("CEC/HDMI chain instability (Shield -> Yamaha -> LG)."),
                "Fix / Notes": build_rich_text_prop("Use troubleshooting guide; try disabling CEC on one hop; replace cable; isolate ports."),
            },
            {
                "Incident": build_title_prop("Quest 3 wireless ADB missing / flaky"),
                "Severity": build_select_prop("P2"),
                "Status": build_select_prop("Open"),
                "Symptoms": build_rich_text_prop("Wireless debugging toggle missing; ADB connect fails."),
                "Root Cause": build_rich_text_prop("Developer options not fully enabled / settings moved / USB authorization state."),
                "Fix / Notes": build_rich_text_prop("Re-enable dev mode; authorize ADB; avoid kill-server if Shield depends on it."),
            },
        ]
        seeded["Incidents (Auto)"] = _seed_rows(incidents_db, "Incident", incidents_rows)

    # ---- Maintenance DB ----
    maintenance_schema = {
        "Task": {"title": {}},
        "Frequency": {"select": {"options": [
            {"name": "Daily", "color": "green"},
            {"name": "Weekly", "color": "blue"},
            {"name": "Monthly", "color": "purple"},
            {"name": "Quarterly", "color": "yellow"},
        ]}},
        "Risk": {"select": {"options": [
            {"name": "Safe", "color": "green"},
            {"name": "Network", "color": "orange"},
            {"name": "Destructive", "color": "red"},
        ]}},
        "Last Done": {"date": {}},
        "Due": {"date": {}},
        "Notes": {"rich_text": {}},
        "Done": {"checkbox": {}},
    }
    created, maint_db, err = _maybe_create_db(infra_id, "Maintenance (Auto)", maintenance_schema)
    if err:
        errors.append(f"Maintenance DB: {err}")
    else:
        if created:
            created_dbs["Maintenance (Auto)"] = maint_db
        maint_rows = [
            {
                "Task": build_title_prop("Ops Digest review (disk/git/services)"),
                "Frequency": build_select_prop("Daily"),
                "Risk": build_select_prop("Safe"),
                "Notes": build_rich_text_prop("Skim the digest and fix issues while small."),
                "Done": build_checkbox_prop(False),
            },
            {
                "Task": build_title_prop("Camera storage check (30-day loop)"),
                "Frequency": build_select_prop("Weekly"),
                "Risk": build_select_prop("Safe"),
                "Notes": build_rich_text_prop("Confirm retention rotation; ensure disk usage is stable."),
                "Done": build_checkbox_prop(False),
            },
            {
                "Task": build_title_prop("Tailscale peer health check"),
                "Frequency": build_select_prop("Weekly"),
                "Risk": build_select_prop("Network"),
                "Notes": build_rich_text_prop("Confirm peers visible from Mac; fix before you need it."),
                "Done": build_checkbox_prop(False),
            },
            {
                "Task": build_title_prop("Backup sanity check (important configs)"),
                "Frequency": build_select_prop("Monthly"),
                "Risk": build_select_prop("Safe"),
                "Notes": build_rich_text_prop("Confirm you have copies of configs, scripts, and key runbooks."),
                "Done": build_checkbox_prop(False),
            },
        ]
        seeded["Maintenance (Auto)"] = _seed_rows(maint_db, "Task", maint_rows)

    # ---- Artesian Measurements DB ----
    artesian_dbs = _child_databases(artesian_id)
    jobs_db = _pick_id(artesian_dbs.get("Artesian Jobs (Template)") or [])

    measure_schema = {
        "Measurement": {"title": {}},
        "Date": {"date": {}},
        "Length (ft)": {"number": {"format": "number"}},
        "Width (ft)": {"number": {"format": "number"}},
        "Shallow (ft)": {"number": {"format": "number"}},
        "Deep (ft)": {"number": {"format": "number"}},
        "Notes": {"rich_text": {}},
    }
    if jobs_db:
        measure_schema["Job"] = {"relation": {"database_id": jobs_db, "single_property": {}}}
    created, meas_db, err = _maybe_create_db(artesian_id, "Artesian Measurements (Template)", measure_schema)
    if err:
        errors.append(f"Measurements DB: {err}")
    else:
        if created:
            created_dbs["Artesian Measurements (Template)"] = meas_db
        meas_rows = [
            {
                "Measurement": build_title_prop("SAMPLE - 16x32 w/ 4-8 depth"),
                "Date": build_date_prop("2026-02-17"),
                "Length (ft)": build_number_prop(32),
                "Width (ft)": build_number_prop(16),
                "Shallow (ft)": build_number_prop(4),
                "Deep (ft)": build_number_prop(8),
                "Notes": build_rich_text_prop("Template measurement row. Duplicate for real jobs."),
            }
        ]
        seeded["Artesian Measurements (Template)"] = _seed_rows(meas_db, "Measurement", meas_rows)

    # ---- Add a small dashboard section to Infrastructure page (once) ----
    marker = "AUTOGEN: infra_expand_v1"
    if not _marker_present(infra_id, marker):
        links = {
            "Devices": _get_db_url(devices_db) if devices_db else "",
            "Services": _get_db_url(services_db) if services_db else "",
            "Cameras": _get_db_url(cameras_db) if cameras_db else "",
            "Modes": _get_db_url(modes_db) if modes_db else "",
            "Incidents": _get_db_url(incidents_db),
            "Maintenance": _get_db_url(maint_db),
        }
        blocks = [
            _block_heading(1, "Infrastructure Dashboard"),
            _block_callout("Devices", url=links["Devices"], icon="🧩", color="gray_background"),
            _block_callout("Services", url=links["Services"], icon="🧰", color="orange_background"),
            _block_callout("Cameras", url=links["Cameras"], icon="📷", color="pink_background"),
            _block_callout("Modes (Quiet Hours / Dry Run)", url=links["Modes"], icon="🛡️", color="green_background"),
            _block_callout("Incidents", url=links["Incidents"], icon="🚨", color="red_background"),
            _block_callout("Maintenance", url=links["Maintenance"], icon="🗓️", color="blue_background"),
            _block_divider(),
            {"object": "block", "type": "code", "code": {"language": "plain text", "rich_text": [_rt(marker)]}},
        ]
        res = append_blocks(infra_id, blocks)
        if not res.get("ok"):
            errors.append(f"append infra dashboard blocks: {(res.get('error') or '')[:200]}")

    out = {
        "ok": not errors and all(v.get("ok", True) for v in seeded.values()),
        "infrastructure_page": _get_page_url(infra_id),
        "artesian_page": _get_page_url(artesian_id),
        "created_databases": created_dbs,
        "seeded": seeded,
        "errors": errors,
    }
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

