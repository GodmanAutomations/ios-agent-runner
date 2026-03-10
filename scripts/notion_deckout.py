#!/usr/bin/env python3
"""Deck out the Notion "Stephen Control Hub" with more structure + templates.

Goal: Give Stephen a richer, more interactive Control Hub by creating a few
databases (runbooks, buttons, scenes, artesian business templates, docs index)
and seeding them with safe, non-secret starter content.

Safety:
  - Never reads or prints secrets.
  - Skips paths that look credential/tax/bank related.
  - Writes only to Notion via NOTION_TOKEN from .env (do not modify .env).
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
    build_checkbox_prop,
    build_date_prop,
    build_number_prop,
    build_rich_text_prop,
    build_select_prop,
    build_title_prop,
    create_database,
    query_database,
    search,
)

_NOTION_VERSION = "2022-06-28"


def _headers() -> dict[str, str]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}", "Notion-Version": _NOTION_VERSION}


def _parent_id_for(obj_id: str, obj: str) -> str:
    """Return parent page_id if this object is directly nested under a page."""
    if not obj_id:
        return ""
    res = request_json("GET", f"https://api.notion.com/v1/{obj}s/{obj_id}", headers=_headers())
    if not res.get("ok"):
        return ""
    parent = (res.get("data") or {}).get("parent") or {}
    if parent.get("type") == "page_id":
        return (parent.get("page_id") or "").strip()
    return ""

def _list_block_children(block_id: str, page_size: int = 100) -> list[dict]:
    """List block children with pagination (safe, read-only)."""
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
    """Prefer the newer integration-created ids (30af...) when duplicates exist."""
    if not candidates:
        return ""
    for cid in candidates:
        if cid.startswith("30af"):
            return cid
    return candidates[0]


def _looks_sensitive_name(name: str) -> bool:
    s = (name or "").lower()
    bad = [
        "auth",
        "credential",
        "credentials",
        "token",
        "password",
        "secret",
        "tax",
        "bank",
        "routing",
        "ssn",
        "social",
    ]
    return any(b in s for b in bad)


def _read_text_excerpt(path: Path, max_bytes: int = 30_000, max_lines: int = 18) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    if len(data) > max_bytes:
        data = data[:max_bytes]
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return ""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[:max_lines]).strip()


def _find_page_id_under_parent(title: str, parent_page_id: str) -> str:
    # Prefer deterministic lookup from the parent's visible child pages.
    child = _child_pages(parent_page_id)
    if title in child:
        return _pick_id(child[title])

    # Fallback to global search (sometimes Notion search ranking is weird).
    res = search(title, limit=25)
    if not res.get("ok"):
        return ""
    for r in (res.get("data") or {}).get("results") or []:
        if r.get("object") != "page":
            continue
        # Only accept exact title matches to avoid grabbing unrelated pages.
        props = r.get("properties") or {}
        found_title = ""
        for v in props.values():
            if isinstance(v, dict) and v.get("type") == "title":
                chunks = v.get("title") or []
                if chunks:
                    found_title = (chunks[0].get("plain_text") or "").strip()
                break
        if found_title.strip().lower() != (title or "").strip().lower():
            continue
        pid = (r.get("id") or "").strip()
        if not pid:
            continue
        if not parent_page_id:
            return pid
        if _parent_id_for(pid, "page") == parent_page_id:
            return pid
    return ""


def _find_database_id_under_parent(title: str, parent_page_id: str) -> str:
    # Prefer deterministic lookup from inline DB blocks under the parent.
    child = _child_databases(parent_page_id)
    if title in child:
        return _pick_id(child[title])

    # Fallback to global search.
    res = search(title, limit=25)
    if not res.get("ok"):
        return ""
    for r in (res.get("data") or {}).get("results") or []:
        if r.get("object") != "database":
            continue
        # Only accept exact title matches to avoid grabbing the wrong inline DB.
        found_title = ""
        chunks = r.get("title") or []
        if chunks:
            found_title = (chunks[0].get("plain_text") or "").strip()
        if found_title.strip().lower() != (title or "").strip().lower():
            continue
        did = (r.get("id") or "").strip()
        if not did:
            continue
        if not parent_page_id:
            return did
        if _parent_id_for(did, "database") == parent_page_id:
            return did
    return ""


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


def _projects_title_to_page_id(projects_db_id: str) -> dict[str, str]:
    res = query_database(projects_db_id, page_size=200)
    if not res.get("ok"):
        return {}
    out: dict[str, str] = {}
    for page in (res.get("data") or {}).get("results") or []:
        pid = (page.get("id") or "").strip()
        props = page.get("properties") or {}
        title_chunks = ((props.get("Project") or {}).get("title") or [])
        if pid and title_chunks:
            name = (title_chunks[0].get("plain_text") or "").strip()
            if name:
                out[name] = pid
    return out


def _relation_schema(target_db_id: str) -> dict:
    return {"relation": {"database_id": target_db_id, "single_property": {}}}


def _maybe_create_db(parent_page_id: str, title: str, schema: dict) -> tuple[bool, str, str]:
    """Return (created, db_id, error)."""
    existing = _find_database_id_under_parent(title, parent_page_id)
    if existing:
        return False, existing, ""
    res = create_database(parent_page_id, title, schema, is_inline=True)
    if not res.get("ok"):
        return False, "", (res.get("error") or "")[:400]
    db_id = ((res.get("data") or {}).get("id") or "").strip()
    if not db_id:
        return False, "", "database created but id missing"
    return True, db_id, ""


def _seed_rows(database_id: str, title_prop: str, rows: list[dict]) -> dict:
    existing = _title_set(database_id, title_prop)
    added = 0
    skipped = 0
    errors: list[str] = []
    for props in rows:
        title = ""
        if title_prop in props:
            chunks = (props[title_prop].get("title") or []) if isinstance(props[title_prop], dict) else []
            if chunks:
                title = (chunks[0].get("text") or {}).get("content", "")
        if not title:
            # Try best-effort: fall back to first prop with title type.
            for v in props.values():
                if isinstance(v, dict) and "title" in v:
                    ch = v.get("title") or []
                    if ch:
                        title = (ch[0].get("text") or {}).get("content", "")
                        break
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
    parser = argparse.ArgumentParser(description="Deck out the Notion Control Hub with more structured content.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    parser.add_argument("--projects-db-id", default="30af7bec-843d-81c3-b2d2-c892b27b1a17")
    parser.add_argument("--ideas-db-id", default="30af7bec-843d-818d-8d6d-e0e02953e527")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    control_hub_id = (args.control_hub_id or "").strip()
    projects_db_id = (args.projects_db_id or "").strip()

    # Locate key hub pages.
    pages = {
        "Phone Buttons": _find_page_id_under_parent("Phone Buttons", control_hub_id),
        "ULAN Home Automation": _find_page_id_under_parent("ULAN Home Automation", control_hub_id),
        "System Health": _find_page_id_under_parent("System Health", control_hub_id),
        "Integrations": _find_page_id_under_parent("Integrations", control_hub_id),
        "Troubleshooting": _find_page_id_under_parent("Troubleshooting", control_hub_id),
        "Artesian Pools": _find_page_id_under_parent("Artesian Pools", control_hub_id),
    }

    missing_pages = [k for k, v in pages.items() if not v]
    if missing_pages:
        print(json.dumps({"ok": False, "error": f"Missing hub pages: {missing_pages}"}, indent=2))
        return 2

    projects_map = _projects_title_to_page_id(projects_db_id)

    created: dict[str, str] = {}
    seeded: dict[str, dict] = {}
    errors: list[str] = []

    # --- System Health: Runbooks ---
    runbooks_schema = {
        "Runbook": {"title": {}},
        "Domain": {"select": {"options": [
            {"name": "Home", "color": "blue"},
            {"name": "Business", "color": "green"},
            {"name": "Family", "color": "pink"},
            {"name": "Tools", "color": "gray"},
        ]}},
        "Risk": {"select": {"options": [
            {"name": "Safe", "color": "green"},
            {"name": "Noisy", "color": "yellow"},
            {"name": "Network", "color": "orange"},
            {"name": "Destructive", "color": "red"},
        ]}},
        "When": {"select": {"options": [
            {"name": "On demand", "color": "blue"},
            {"name": "Daily", "color": "green"},
            {"name": "Weekly", "color": "purple"},
            {"name": "When broken", "color": "red"},
        ]}},
        "Summary": {"rich_text": {}},
        "Commands": {"rich_text": {}},
        "Related Project": _relation_schema(projects_db_id),
        "Last Verified": {"date": {}},
    }
    created_db, runbooks_db_id, err = _maybe_create_db(pages["System Health"], "Runbooks (Auto)", runbooks_schema)
    if err:
        errors.append(f"Runbooks DB: {err}")
    else:
        if created_db:
            created["Runbooks (Auto)"] = runbooks_db_id

        def rel(name: str) -> dict:
            if name in projects_map:
                return {"relation": [{"id": projects_map[name]}]}
            return {"relation": []}

        runbook_rows = [
            {
                "Runbook": build_title_prop("Tailscale: peers show as 0 on Mac"),
                "Domain": build_select_prop("Tools"),
                "Risk": build_select_prop("Network"),
                "When": build_select_prop("When broken"),
                "Summary": build_rich_text_prop("Fix the 'connected but no peers' problem; confirm services and versions."),
                "Commands": build_rich_text_prop(
                    "tailscale status --peers\n"
                    "tailscale status --json | jq '.Peer | length'\n"
                    "tailscale ping <pi-host>\n"
                    "open -a Tailscale\n"
                    "# If still broken: restart Tailscale app/daemon; ensure same account on all devices."
                ),
                "Related Project": rel("MAX AI (Pi5)"),
            },
            {
                "Runbook": build_title_prop("Integrations: smoke test Notion/Linear/Sentry/Figma"),
                "Domain": build_select_prop("Tools"),
                "Risk": build_select_prop("Safe"),
                "When": build_select_prop("On demand"),
                "Summary": build_rich_text_prop("Quick check to confirm your API tokens still work."),
                "Commands": build_rich_text_prop(
                    "cd ~/ios-agent-runner && source .venv/bin/activate\n"
                    "python -c \"from scripts.integrations import notion_api; print(notion_api.me())\"\n"
                    "python -c \"from scripts.integrations import linear_api; print(linear_api.viewer())\"\n"
                    "python -c \"from scripts.integrations import sentry_api; print(sentry_api.me())\"\n"
                    "python -c \"from scripts.integrations import figma_api; print(figma_api.me())\""
                ),
                "Related Project": rel("ios-agent-runner"),
            },
            {
                "Runbook": build_title_prop("Ops Digest: generate daily status (silent)"),
                "Domain": build_select_prop("Tools"),
                "Risk": build_select_prop("Safe"),
                "When": build_select_prop("Daily"),
                "Summary": build_rich_text_prop("Disk, git, docker, integrations: a daily summary in one place."),
                "Commands": build_rich_text_prop(
                    "cd ~/ios-agent-runner && source .venv/bin/activate\n"
                    "python scripts/ops_digest.py --no-network\n"
                    "# optional: publish digest to Notion"
                ),
                "Related Project": rel("ios-agent-runner"),
            },
            {
                "Runbook": build_title_prop("ULAN: start bridge + test a command"),
                "Domain": build_select_prop("Home"),
                "Risk": build_select_prop("Noisy"),
                "When": build_select_prop("On demand"),
                "Summary": build_rich_text_prop("Start the local bridge and verify one command path works."),
                "Commands": build_rich_text_prop(
                    "cd ~/ulan-agent && source .venv/bin/activate\n"
                    "bash scripts/start-alexa-bridge.sh\n"
                    "# then hit your endpoint from Shortcuts or curl"
                ),
                "Related Project": rel("ulan-agent"),
            },
            {
                "Runbook": build_title_prop("Hey Claude: interactive test (no microphone)"),
                "Domain": build_select_prop("Home"),
                "Risk": build_select_prop("Safe"),
                "When": build_select_prop("On demand"),
                "Summary": build_rich_text_prop("Test intent routing without triggering devices or speaking aloud."),
                "Commands": build_rich_text_prop(
                    "cd ~/hey-claude\n"
                    "python3 -m venv venv && source venv/bin/activate\n"
                    "pip install -r requirements.txt\n"
                    "python -m hey_claude.cli interactive"
                ),
                "Related Project": rel("Hey Claude"),
            },
            {
                "Runbook": build_title_prop("LaunchAgents: audit com.godman / com.stephen"),
                "Domain": build_select_prop("Tools"),
                "Risk": build_select_prop("Safe"),
                "When": build_select_prop("Weekly"),
                "Summary": build_rich_text_prop("Inventory what's installed, what's loaded, and what it does."),
                "Commands": build_rich_text_prop(
                    "ls -l ~/Library/LaunchAgents/*.plist | wc -l\n"
                    "launchctl list | rg 'com\\.godman|com\\.stephen'\n"
                    "plutil -p ~/Library/LaunchAgents/<name>.plist"
                ),
                "Related Project": rel("MAX AI (Pi5)"),
            },
            {
                "Runbook": build_title_prop("Kroger Pantry app: run locally for Ashley"),
                "Domain": build_select_prop("Family"),
                "Risk": build_select_prop("Safe"),
                "When": build_select_prop("On demand"),
                "Summary": build_rich_text_prop("Start the Streamlit UI on your LAN."),
                "Commands": build_rich_text_prop("cd ~/kroger-playground\n./run_app.sh\n# then open the printed LAN URL"),
                "Related Project": rel("kroger-playground"),
            },
        ]
        seeded["Runbooks (Auto)"] = _seed_rows(runbooks_db_id, "Runbook", runbook_rows)

    # --- Phone Buttons: Buttons DB ---
    buttons_schema = {
        "Button": {"title": {}},
        "Type": {"select": {"options": [
            {"name": "iPhone Shortcut", "color": "blue"},
            {"name": "Alexa Routine", "color": "yellow"},
            {"name": "Hey Claude", "color": "purple"},
        ]}},
        "Command": {"rich_text": {}},
        "Output": {"rich_text": {}},
        "Risk": {"select": {"options": [
            {"name": "Safe", "color": "green"},
            {"name": "Noisy", "color": "yellow"},
        ]}},
        "Related Project": _relation_schema(projects_db_id),
        "Notes": {"rich_text": {}},
    }
    created_db, buttons_db_id, err = _maybe_create_db(pages["Phone Buttons"], "Buttons (Auto)", buttons_schema)
    if err:
        errors.append(f"Buttons DB: {err}")
    else:
        if created_db:
            created["Buttons (Auto)"] = buttons_db_id
        buttons_rows = [
            {
                "Button": build_title_prop("Movie Mode"),
                "Type": build_select_prop("iPhone Shortcut"),
                "Command": build_rich_text_prop("tell my house play Netflix on the LG"),
                "Output": build_rich_text_prop("TV on + receiver input + launch app + volume preset"),
                "Risk": build_select_prop("Noisy"),
                "Related Project": {"relation": [{"id": projects_map.get("ulan-agent", "")}]} if "ulan-agent" in projects_map else {"relation": []},
                "Notes": build_rich_text_prop("Pin as a widget. Add a 'quiet hours' guard to prevent night surprises."),
            },
            {
                "Button": build_title_prop("Goodnight"),
                "Type": build_select_prop("Alexa Routine"),
                "Command": build_rich_text_prop("tell my house goodnight"),
                "Output": build_rich_text_prop("Turns off TVs + safe receiver state"),
                "Risk": build_select_prop("Noisy"),
                "Related Project": {"relation": [{"id": projects_map.get("ulan-agent", "")}]} if "ulan-agent" in projects_map else {"relation": []},
                "Notes": build_rich_text_prop("Add 'quiet hours on' inside this scene."),
            },
            {
                "Button": build_title_prop("Quiet Hours ON"),
                "Type": build_select_prop("iPhone Shortcut"),
                "Command": build_rich_text_prop("quiet hours on"),
                "Output": build_rich_text_prop("Blocks noisy actions (lights/TV volume/speaking)"),
                "Risk": build_select_prop("Safe"),
                "Related Project": {"relation": [{"id": projects_map.get("Hey Claude", "")}]} if "Hey Claude" in projects_map else {"relation": []},
                "Notes": build_rich_text_prop("Use this at night. Also switch Hey Claude to text-only responses."),
            },
            {
                "Button": build_title_prop("Ops Digest Now"),
                "Type": build_select_prop("iPhone Shortcut"),
                "Command": build_rich_text_prop("Run ops digest (silent)"),
                "Output": build_rich_text_prop("Generates a status summary and pushes it into Notion"),
                "Risk": build_select_prop("Safe"),
                "Related Project": {"relation": [{"id": projects_map.get("ios-agent-runner", "")}]} if "ios-agent-runner" in projects_map else {"relation": []},
                "Notes": build_rich_text_prop("Perfect 1-tap sanity check before debugging anything."),
            },
            {
                "Button": build_title_prop("Field Capture (voice memo -> tasks)"),
                "Type": build_select_prop("Hey Claude"),
                "Command": build_rich_text_prop("Hey Claude, add job notes: ..."),
                "Output": build_rich_text_prop("Extracts action items and appends to the job in Notion"),
                "Risk": build_select_prop("Safe"),
                "Related Project": {"relation": [{"id": projects_map.get("Artesian Pools Automation", "")}]} if "Artesian Pools Automation" in projects_map else {"relation": []},
                "Notes": build_rich_text_prop("Turns messy field notes into structured next actions."),
            },
        ]
        seeded["Buttons (Auto)"] = _seed_rows(buttons_db_id, "Button", buttons_rows)

    # --- ULAN Home Automation: Scenes DB ---
    scenes_schema = {
        "Scene": {"title": {}},
        "Intent Phrase": {"rich_text": {}},
        "Devices": {"rich_text": {}},
        "Risk": {"select": {"options": [
            {"name": "Safe", "color": "green"},
            {"name": "Noisy", "color": "yellow"},
        ]}},
        "Notes": {"rich_text": {}},
        "Related Project": _relation_schema(projects_db_id),
    }
    created_db, scenes_db_id, err = _maybe_create_db(pages["ULAN Home Automation"], "Scenes (Auto)", scenes_schema)
    if err:
        errors.append(f"Scenes DB: {err}")
    else:
        if created_db:
            created["Scenes (Auto)"] = scenes_db_id
        scenes_rows = [
            {
                "Scene": build_title_prop("House Reset"),
                "Intent Phrase": build_rich_text_prop("house reset"),
                "Devices": build_rich_text_prop("LG TV, Yamaha receiver, Shield/Sony (as needed)"),
                "Risk": build_select_prop("Noisy"),
                "Notes": build_rich_text_prop("Emergency reset to a safe state. Include Quiet Hours ON."),
                "Related Project": {"relation": [{"id": projects_map.get("ulan-agent", "")}]} if "ulan-agent" in projects_map else {"relation": []},
            },
            {
                "Scene": build_title_prop("Movie Mode"),
                "Intent Phrase": build_rich_text_prop("movie mode"),
                "Devices": build_rich_text_prop("LG TV + Yamaha input + app launch"),
                "Risk": build_select_prop("Noisy"),
                "Notes": build_rich_text_prop("Your flagship scene. Make this rock-solid."),
                "Related Project": {"relation": [{"id": projects_map.get("ulan-agent", "")}]} if "ulan-agent" in projects_map else {"relation": []},
            },
            {
                "Scene": build_title_prop("Quiet Hours"),
                "Intent Phrase": build_rich_text_prop("quiet hours on/off"),
                "Devices": build_rich_text_prop("All automations"),
                "Risk": build_select_prop("Safe"),
                "Notes": build_rich_text_prop("Blocks noisy actions. Required safety layer for voice systems."),
                "Related Project": {"relation": [{"id": projects_map.get("Hey Claude", "")}]} if "Hey Claude" in projects_map else {"relation": []},
            },
        ]
        seeded["Scenes (Auto)"] = _seed_rows(scenes_db_id, "Scene", scenes_rows)

    # --- Integrations: Integration Status DB ---
    integrations_schema = {
        "Integration": {"title": {}},
        "Status": {"select": {"options": [
            {"name": "OK", "color": "green"},
            {"name": "Failing", "color": "red"},
            {"name": "Unknown", "color": "gray"},
        ]}},
        "Last Success": {"date": {}},
        "Notes": {"rich_text": {}},
        "Related Project": _relation_schema(projects_db_id),
    }
    created_db, integrations_db_id, err = _maybe_create_db(pages["Integrations"], "Integration Status (Auto)", integrations_schema)
    if err:
        errors.append(f"Integration Status DB: {err}")
    else:
        if created_db:
            created["Integration Status (Auto)"] = integrations_db_id
        integrations_rows = [
            {
                "Integration": build_title_prop("Notion"),
                "Status": build_select_prop("OK"),
                "Notes": build_rich_text_prop("Control Hub pages/databases created via ios-agent-runner integration."),
                "Related Project": {"relation": [{"id": projects_map.get("ios-agent-runner", "")}]} if "ios-agent-runner" in projects_map else {"relation": []},
            },
            {
                "Integration": build_title_prop("Linear"),
                "Status": build_select_prop("Unknown"),
                "Notes": build_rich_text_prop("Run the integration smoke test runbook to confirm."),
                "Related Project": {"relation": [{"id": projects_map.get("ios-agent-runner", "")}]} if "ios-agent-runner" in projects_map else {"relation": []},
            },
            {
                "Integration": build_title_prop("Sentry"),
                "Status": build_select_prop("Unknown"),
                "Notes": build_rich_text_prop("Run the integration smoke test runbook to confirm."),
                "Related Project": {"relation": [{"id": projects_map.get("ios-agent-runner", "")}]} if "ios-agent-runner" in projects_map else {"relation": []},
            },
            {
                "Integration": build_title_prop("Figma"),
                "Status": build_select_prop("Unknown"),
                "Notes": build_rich_text_prop("Run the integration smoke test runbook to confirm."),
                "Related Project": {"relation": [{"id": projects_map.get("ios-agent-runner", "")}]} if "ios-agent-runner" in projects_map else {"relation": []},
            },
        ]
        seeded["Integration Status (Auto)"] = _seed_rows(integrations_db_id, "Integration", integrations_rows)

    # --- Artesian Pools: Customers/Quotes/Vendors/Materials/Checklists (templates) ---
    artesian_parent = pages["Artesian Pools"]

    # Find the existing Jobs DB created earlier (by exact title under the Artesian page).
    jobs_db_id = _find_database_id_under_parent("Artesian Jobs (Template)", artesian_parent)
    if not jobs_db_id:
        # If missing, do not fail hard; user can run notion_possibilities_expand.py --only-artesian-jobs.
        errors.append("Artesian Jobs (Template) DB not found; skipping customer/quote relations.")

    customers_schema = {
        "Customer": {"title": {}},
        "Status": {"select": {"options": [
            {"name": "Lead", "color": "gray"},
            {"name": "Active", "color": "blue"},
            {"name": "Past", "color": "green"},
            {"name": "Do Not Contact", "color": "red"},
        ]}},
        "Phone": {"rich_text": {}},
        "Email": {"rich_text": {}},
        "Address": {"rich_text": {}},
        "Source": {"select": {"options": [
            {"name": "Referral", "color": "green"},
            {"name": "Google", "color": "blue"},
            {"name": "Facebook", "color": "purple"},
            {"name": "Yard Sign", "color": "yellow"},
            {"name": "Other", "color": "gray"},
        ]}},
        "Notes": {"rich_text": {}},
    }
    if jobs_db_id:
        customers_schema["Related Jobs"] = _relation_schema(jobs_db_id)

    created_db, customers_db_id, err = _maybe_create_db(artesian_parent, "Artesian Customers (Template)", customers_schema)
    if err:
        errors.append(f"Customers DB: {err}")
    else:
        if created_db:
            created["Artesian Customers (Template)"] = customers_db_id
        customers_rows = [
            {
                "Customer": build_title_prop("SAMPLE - Customer A"),
                "Status": build_select_prop("Lead"),
                "Source": build_select_prop("Google"),
                "Notes": build_rich_text_prop("Template row. Replace with a real customer."),
            },
            {
                "Customer": build_title_prop("SAMPLE - Customer B"),
                "Status": build_select_prop("Active"),
                "Source": build_select_prop("Referral"),
                "Notes": build_rich_text_prop("Template row. Add phone/email/address if desired."),
            },
        ]
        seeded["Artesian Customers (Template)"] = _seed_rows(customers_db_id, "Customer", customers_rows)

    quotes_schema = {
        "Quote": {"title": {}},
        "Status": {"select": {"options": [
            {"name": "Draft", "color": "gray"},
            {"name": "Sent", "color": "blue"},
            {"name": "Accepted", "color": "green"},
            {"name": "Declined", "color": "red"},
        ]}},
        "Amount": {"number": {"format": "dollar"}},
        "Date Sent": {"date": {}},
        "Deposit %": {"number": {"format": "percent"}},
        "Notes": {"rich_text": {}},
    }
    if jobs_db_id:
        quotes_schema["Job"] = _relation_schema(jobs_db_id)

    created_db, quotes_db_id, err = _maybe_create_db(artesian_parent, "Artesian Quotes (Template)", quotes_schema)
    if err:
        errors.append(f"Quotes DB: {err}")
    else:
        if created_db:
            created["Artesian Quotes (Template)"] = quotes_db_id
        quotes_rows = [
            {
                "Quote": build_title_prop("SAMPLE - Liner Replace Quote"),
                "Status": build_select_prop("Draft"),
                "Amount": build_number_prop(0),
                "Deposit %": build_number_prop(0.5),
                "Notes": build_rich_text_prop("Template. Link to a job once jobs are real."),
            },
            {
                "Quote": build_title_prop("SAMPLE - Repair Quote"),
                "Status": build_select_prop("Sent"),
                "Amount": build_number_prop(0),
                "Date Sent": build_date_prop("2026-03-01"),
                "Deposit %": build_number_prop(0.5),
                "Notes": build_rich_text_prop("Template. Replace with your actual quote workflow."),
            },
        ]
        seeded["Artesian Quotes (Template)"] = _seed_rows(quotes_db_id, "Quote", quotes_rows)

    vendors_schema = {
        "Vendor": {"title": {}},
        "Category": {"select": {"options": [
            {"name": "Liner", "color": "blue"},
            {"name": "Hardware", "color": "yellow"},
            {"name": "Chemicals", "color": "green"},
            {"name": "Disposal", "color": "gray"},
            {"name": "Other", "color": "purple"},
        ]}},
        "Contact": {"rich_text": {}},
        "Phone": {"rich_text": {}},
        "Website": {"url": {}},
        "Notes": {"rich_text": {}},
    }
    created_db, vendors_db_id, err = _maybe_create_db(artesian_parent, "Artesian Vendors (Template)", vendors_schema)
    if err:
        errors.append(f"Vendors DB: {err}")
    else:
        if created_db:
            created["Artesian Vendors (Template)"] = vendors_db_id
        vendors_rows = [
            {"Vendor": build_title_prop("SCP Distributors"), "Category": build_select_prop("Hardware"), "Notes": build_rich_text_prop("Common pool supply vendor.")},
            {"Vendor": build_title_prop("Home Depot"), "Category": build_select_prop("Hardware"), "Notes": build_rich_text_prop("Materials + tools.")},
            {"Vendor": build_title_prop("Local Disposal / Dump"), "Category": build_select_prop("Disposal"), "Notes": build_rich_text_prop("Trash/debris for demo day.")},
        ]
        seeded["Artesian Vendors (Template)"] = _seed_rows(vendors_db_id, "Vendor", vendors_rows)

    materials_schema = {
        "Item": {"title": {}},
        "Unit Cost": {"number": {"format": "dollar"}},
        "SKU": {"rich_text": {}},
        "Notes": {"rich_text": {}},
        "Last Updated": {"date": {}},
    }
    if "vendors_db_id" in locals() and vendors_db_id:
        materials_schema["Vendor"] = _relation_schema(vendors_db_id)
    created_db, materials_db_id, err = _maybe_create_db(artesian_parent, "Artesian Materials (Template)", materials_schema)
    if err:
        errors.append(f"Materials DB: {err}")
    else:
        if created_db:
            created["Artesian Materials (Template)"] = materials_db_id
        materials_rows = [
            {"Item": build_title_prop("Liner (pattern TBD)"), "Unit Cost": build_number_prop(0), "Notes": build_rich_text_prop("Track liner pattern + cost here."), "Last Updated": build_date_prop("2026-02-17")},
            {"Item": build_title_prop("Skimmer gasket set"), "Unit Cost": build_number_prop(0), "Notes": build_rich_text_prop("Common replacement part."), "Last Updated": build_date_prop("2026-02-17")},
            {"Item": build_title_prop("Return fittings set"), "Unit Cost": build_number_prop(0), "Notes": build_rich_text_prop("Common replacement part."), "Last Updated": build_date_prop("2026-02-17")},
        ]
        seeded["Artesian Materials (Template)"] = _seed_rows(materials_db_id, "Item", materials_rows)

    checklists_schema = {
        "Checklist": {"title": {}},
        "Phase": {"select": {"options": [
            {"name": "Pre-Job", "color": "blue"},
            {"name": "Demo Day", "color": "yellow"},
            {"name": "Install Day", "color": "green"},
            {"name": "Punch List", "color": "orange"},
            {"name": "Closeout", "color": "purple"},
        ]}},
        "Steps (short)": {"rich_text": {}},
        "Notes": {"rich_text": {}},
    }
    created_db, checklists_db_id, err = _maybe_create_db(artesian_parent, "Artesian Checklists (Template)", checklists_schema)
    if err:
        errors.append(f"Checklists DB: {err}")
    else:
        if created_db:
            created["Artesian Checklists (Template)"] = checklists_db_id
        checklists_rows = [
            {
                "Checklist": build_title_prop("Pre-Job Checklist"),
                "Phase": build_select_prop("Pre-Job"),
                "Steps (short)": build_rich_text_prop("Confirm schedule; confirm liner pattern; confirm water source; confirm access; prep materials."),
                "Notes": build_rich_text_prop("Expand inside the row page with more detailed steps."),
            },
            {
                "Checklist": build_title_prop("Demo Day Checklist"),
                "Phase": build_select_prop("Demo Day"),
                "Steps (short)": build_rich_text_prop("Protect deck; remove old liner; inspect walls; note repairs; dispose debris."),
                "Notes": build_rich_text_prop("Add photo checklist here."),
            },
            {
                "Checklist": build_title_prop("Install Day Checklist"),
                "Phase": build_select_prop("Install Day"),
                "Steps (short)": build_rich_text_prop("Prep base; set liner; vac lines; fill; set fittings; verify leaks."),
                "Notes": build_rich_text_prop("Add a final walkaround checklist here."),
            },
            {
                "Checklist": build_title_prop("Punch List / Closeout"),
                "Phase": build_select_prop("Closeout"),
                "Steps (short)": build_rich_text_prop("Clean up; educate customer; collect final payment; archive photos; request review."),
                "Notes": build_rich_text_prop("Standardize your end-of-job ritual."),
            },
        ]
        seeded["Artesian Checklists (Template)"] = _seed_rows(checklists_db_id, "Checklist", checklists_rows)

    # --- Troubleshooting: Local Knowledge Index (safe subset) ---
    mem_dir = Path.home() / ".claude" / "projects" / "-Users-stephengodman" / "memory"
    docs_schema = {
        "Doc": {"title": {}},
        "Category": {"select": {"options": [
            {"name": "Media", "color": "blue"},
            {"name": "Digital Twin", "color": "purple"},
            {"name": "LLM Docs", "color": "gray"},
            {"name": "Ops", "color": "green"},
            {"name": "Other", "color": "yellow"},
        ]}},
        "Local Path": {"rich_text": {}},
        "Excerpt": {"rich_text": {}},
        "Notes": {"rich_text": {}},
    }
    created_db, docs_db_id, err = _maybe_create_db(pages["Troubleshooting"], "Local Knowledge Index (Auto)", docs_schema)
    if err:
        errors.append(f"Docs Index DB: {err}")
    else:
        if created_db:
            created["Local Knowledge Index (Auto)"] = docs_db_id

        docs_rows: list[dict] = []
        if mem_dir.exists():
            md_files = sorted([p for p in mem_dir.iterdir() if p.is_file() and p.suffix.lower() == ".md"], key=lambda p: p.name.lower())
            for p in md_files[:200]:
                if _looks_sensitive_name(p.name):
                    continue
                cat = "Other"
                n = p.name
                if n.startswith("MEDIA-"):
                    cat = "Media"
                elif n.startswith("DIGITAL-TWIN-"):
                    cat = "Digital Twin"
                elif n.startswith("anthropic-"):
                    cat = "LLM Docs"
                elif n.startswith("ops-") or "ops" in n.lower():
                    cat = "Ops"

                excerpt = _read_text_excerpt(p)
                if not excerpt:
                    continue
                excerpt = excerpt[:1700]
                docs_rows.append(
                    {
                        "Doc": build_title_prop(n),
                        "Category": build_select_prop(cat),
                        "Local Path": build_rich_text_prop(str(p)),
                        "Excerpt": build_rich_text_prop(excerpt),
                        "Notes": build_rich_text_prop("Safe index entry (content excerpted)."),
                    }
                )
                if len(docs_rows) >= 30:
                    break
        seeded["Local Knowledge Index (Auto)"] = _seed_rows(docs_db_id, "Doc", docs_rows)

    out = {
        "ok": not errors and all(v.get("ok", True) for v in seeded.values()),
        "created_databases": created,
        "seeded": seeded,
        "errors": errors,
        "pages": pages,
    }
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
