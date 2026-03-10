#!/usr/bin/env python3
"""Auto-populate Notion Infrastructure databases from real discovery (daily-friendly).

This script is intended to be run on a schedule (LaunchAgent). It:
  - Collects local discovery info (LAN ARP table, Tailscale peer list)
  - Optionally checks Pi health via SSH (non-interactive)
  - Upserts rows into Notion:
      * LAN Inventory (Auto)       (new/ensured)
      * Tailscale Peers (Auto)     (new/ensured)
      * Devices (Auto)             (existing; updates key devices)
      * Services (Auto)            (existing; updates a few service checks)

Safety:
  - Never reads or prints secrets.
  - Does not run ADB or control devices.
  - SSH uses BatchMode to avoid password prompts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
)

_NOTION_VERSION = "2022-06-28"


def _headers() -> dict[str, str]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}", "Notion-Version": _NOTION_VERSION}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], timeout_s: int = 6) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return int(proc.returncode), (proc.stdout or ""), (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "not found"
    except Exception as exc:
        return 1, "", str(exc)


def _tailscale_status_json() -> dict | None:
    code, out, _ = _run(["tailscale", "status", "--json"], timeout_s=8)
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


@dataclass(frozen=True)
class TailPeer:
    dns_name: str
    host_name: str
    os: str
    ipv4: str
    online: bool
    last_seen: str


def _parse_tail_peers(ts: dict) -> list[TailPeer]:
    peer_obj = (ts or {}).get("Peer") or {}
    peers: list[TailPeer] = []
    for _k, v in peer_obj.items():
        if not isinstance(v, dict):
            continue
        dns = str(v.get("DNSName") or "").strip().rstrip(".")
        host = str(v.get("HostName") or "").strip()
        os_name = str(v.get("OS") or "").strip()
        ips = v.get("TailscaleIPs") or []
        ipv4 = ""
        for ip in ips:
            ip = str(ip)
            if "." in ip:
                ipv4 = ip
                break
        online = bool(v.get("Online", False))
        last_seen = str(v.get("LastSeen") or "").strip()
        if not dns and not host:
            continue
        peers.append(TailPeer(dns_name=dns, host_name=host, os=os_name, ipv4=ipv4, online=online, last_seen=last_seen))

    peers.sort(key=lambda p: (p.dns_name or p.host_name).lower())
    return peers


@dataclass(frozen=True)
class ArpEntry:
    ip: str
    mac: str
    iface: str
    name: str


_ARP_RE = re.compile(
    r"^(?P<name>.+?)\s+\((?P<ip>\d+\.\d+\.\d+\.\d+)\)\s+at\s+(?P<mac>[0-9a-f:]{11,17}|<incomplete>)\s+on\s+(?P<iface>\S+)",
    re.IGNORECASE,
)


def _arp_table() -> list[ArpEntry]:
    code, out, _ = _run(["arp", "-a"], timeout_s=6)
    if code != 0 or not out.strip():
        return []
    entries: list[ArpEntry] = []
    for raw in out.splitlines():
        m = _ARP_RE.match(raw.strip())
        if not m:
            continue
        ip = m.group("ip")
        mac = m.group("mac").lower()
        iface = m.group("iface")
        name = m.group("name").strip()
        if mac == "<incomplete>":
            continue
        entries.append(ArpEntry(ip=ip, mac=mac, iface=iface, name=name))
    # Prefer the current LAN segment only (Stephen uses 192.168.4.x).
    entries.sort(key=lambda e: e.ip)
    return entries


def _ping(ip: str, timeout_s: int = 2) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False
    # macOS ping: -c count, -W timeout(ms)
    code, _, _ = _run(["ping", "-c", "1", "-W", str(int(timeout_s * 1000)), ip], timeout_s=timeout_s + 1)
    return code == 0


def _ssh_pi(cmd: str, *, host: str = "pi@100.100.32.58", timeout_s: int = 8) -> tuple[bool, str]:
    # BatchMode avoids password prompts (non-interactive).
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(1, int(timeout_s))}",
        host,
        cmd,
    ]
    code, out, err = _run(args, timeout_s=timeout_s + 2)
    if code != 0:
        msg = (err or out or "").strip()
        return False, msg[:400]
    return True, (out or "").strip()[:4000]


def _database_properties(database_id: str) -> dict[str, dict]:
    res = request_json("GET", f"https://api.notion.com/v1/databases/{database_id}", headers=_headers())
    if not res.get("ok"):
        return {}
    return (res.get("data") or {}).get("properties") or {}


def _patch_database_properties(database_id: str, properties: dict) -> bool:
    body = {"properties": properties}
    res = request_json("PATCH", f"https://api.notion.com/v1/databases/{database_id}", headers=_headers(), body=body)
    return bool(res.get("ok"))


def _update_page_properties(page_id: str, properties: dict) -> bool:
    body = {"properties": properties}
    res = request_json("PATCH", f"https://api.notion.com/v1/pages/{page_id}", headers=_headers(), body=body)
    return bool(res.get("ok"))


def _query_all(database_id: str, page_size: int = 200) -> list[dict]:
    res = query_database(database_id, page_size=min(page_size, 100))
    if not res.get("ok"):
        return []
    data = res.get("data") or {}
    results = data.get("results") or []
    # If there are more than 100 rows, we keep it simple: we only handle first page.
    return list(results)


def _title_of(page: dict, prop: str) -> str:
    props = page.get("properties") or {}
    p = props.get(prop) or {}
    chunks = p.get("title") or []
    if chunks:
        return (chunks[0].get("plain_text") or "").strip()
    return ""


def _index_by_title(database_id: str, title_prop: str) -> dict[str, str]:
    idx: dict[str, str] = {}
    for page in _query_all(database_id, page_size=200):
        pid = (page.get("id") or "").strip()
        title = _title_of(page, title_prop)
        if pid and title:
            idx[title.lower()] = pid
    return idx


def _ensure_db(parent_page_id: str, title: str, schema: dict) -> tuple[bool, str, str]:
    # Check inline child DB blocks under the parent for exact title match.
    res = request_json("GET", f"https://api.notion.com/v1/blocks/{parent_page_id}/children?page_size=100", headers=_headers())
    if res.get("ok"):
        for b in (res.get("data") or {}).get("results") or []:
            if b.get("type") == "child_database" and ((b.get("child_database") or {}).get("title") or "").strip() == title:
                return False, (b.get("id") or "").strip(), ""

    created = create_database(parent_page_id, title, schema, is_inline=True)
    if not created.get("ok"):
        return False, "", (created.get("error") or "")[:400]
    db_id = ((created.get("data") or {}).get("id") or "").strip()
    if not db_id:
        return False, "", "database created but id missing"
    return True, db_id, ""


def _upsert_row(database_id: str, title_prop: str, title: str, properties: dict, index: dict[str, str]) -> tuple[str, bool]:
    """Return (page_id, created)."""
    key = (title or "").strip().lower()
    if not key:
        return "", False
    if key in index:
        pid = index[key]
        _update_page_properties(pid, properties)
        return pid, False

    # Create new
    props = dict(properties)
    props[title_prop] = build_title_prop(title)
    created = add_database_row(database_id, props)
    if created.get("ok"):
        pid = ((created.get("data") or {}).get("id") or "").strip()
        if pid:
            index[key] = pid
        return pid, True
    return "", False


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync infra discovery into Notion databases.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    parser.add_argument("--infrastructure-page-id", default="")  # optional override
    parser.add_argument("--devices-db-id", default="30af7bec-843d-8155-9ee3-e3f2b59888ad")
    parser.add_argument("--services-db-id", default="30af7bec-843d-8148-8d54-ef55d72d8b83")
    parser.add_argument("--pi-host", default="pi@100.100.32.58")
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".godman_keys.env")

    if not os.getenv("NOTION_TOKEN", "").strip():
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN not set (check ~/.godman_keys.env)"}, indent=2))
        return 2

    hub_id = (args.control_hub_id or "").strip()
    infra_page_id = (args.infrastructure_page_id or "").strip()

    # Resolve Infrastructure page id via Control Hub children if not provided.
    if not infra_page_id and hub_id:
        res = request_json("GET", f"https://api.notion.com/v1/blocks/{hub_id}/children?page_size=100", headers=_headers())
        if res.get("ok"):
            for b in (res.get("data") or {}).get("results") or []:
                if b.get("type") != "child_page":
                    continue
                title = ((b.get("child_page") or {}).get("title") or "").strip()
                if title == "Infrastructure":
                    infra_page_id = (b.get("id") or "").strip()
                    break

    if not infra_page_id:
        print(json.dumps({"ok": False, "error": "Infrastructure page id not found."}, indent=2))
        return 2

    # Ensure the two inventory DBs exist under Infrastructure.
    lan_schema = {
        "IP": {"title": {}},
        "MAC": {"rich_text": {}},
        "Interface": {"rich_text": {}},
        "Name": {"rich_text": {}},
        "Last Seen": {"date": {}},
        "Notes": {"rich_text": {}},
    }
    created, lan_db, err = _ensure_db(infra_page_id, "LAN Inventory (Auto)", lan_schema)
    if err:
        print(json.dumps({"ok": False, "error": f"LAN Inventory DB: {err}"}, indent=2))
        return 1

    tail_schema = {
        "Peer": {"title": {}},
        "DNS": {"rich_text": {}},
        "Tailscale IP": {"rich_text": {}},
        "OS": {"select": {"options": [
            {"name": "macOS", "color": "blue"},
            {"name": "linux", "color": "green"},
            {"name": "android", "color": "purple"},
            {"name": "windows", "color": "yellow"},
            {"name": "ios", "color": "pink"},
            {"name": "other", "color": "gray"},
        ]}},
        "Online": {"select": {"options": [
            {"name": "Online", "color": "green"},
            {"name": "Offline", "color": "red"},
            {"name": "Unknown", "color": "gray"},
        ]}},
        "Last Seen": {"date": {}},
        "Notes": {"rich_text": {}},
    }
    created2, tail_db, err = _ensure_db(infra_page_id, "Tailscale Peers (Auto)", tail_schema)
    if err:
        print(json.dumps({"ok": False, "error": f"Tailscale Peers DB: {err}"}, indent=2))
        return 1

    # Patch Devices/Services DB schemas with last-seen/last-checked fields if missing.
    devices_db_id = (args.devices_db_id or "").strip()
    services_db_id = (args.services_db_id or "").strip()

    schema_changes: dict[str, dict[str, dict]] = {}

    dev_props = _database_properties(devices_db_id)
    dev_patch: dict[str, dict] = {}
    if dev_props and "Last Seen" not in dev_props:
        dev_patch["Last Seen"] = {"date": {}}
    if dev_props and "Online" not in dev_props:
        dev_patch["Online"] = {"select": {"options": [
            {"name": "Online", "color": "green"},
            {"name": "Offline", "color": "red"},
            {"name": "Unknown", "color": "gray"},
        ]}}
    if dev_patch:
        ok = _patch_database_properties(devices_db_id, dev_patch)
        schema_changes["Devices (Auto)"] = {"ok": ok, "patched": list(dev_patch.keys())}

    svc_props = _database_properties(services_db_id)
    svc_patch: dict[str, dict] = {}
    if svc_props and "Last Checked" not in svc_props:
        svc_patch["Last Checked"] = {"date": {}}
    if svc_props and "Status Detail" not in svc_props:
        svc_patch["Status Detail"] = {"rich_text": {}}
    if svc_patch:
        ok = _patch_database_properties(services_db_id, svc_patch)
        schema_changes["Services (Auto)"] = {"ok": ok, "patched": list(svc_patch.keys())}

    # Discovery
    ts = _tailscale_status_json()
    peers = _parse_tail_peers(ts or {}) if ts else []
    arp = _arp_table()

    pi_ok, pi_info = _ssh_pi("echo ok", host=args.pi_host, timeout_s=6)
    pi_health: dict = {"ok": pi_ok, "detail": pi_info[:300] if pi_info else ""}
    docker_summary = ""
    if pi_ok:
        ok, out = _ssh_pi(
            "docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}' 2>/dev/null | head -40",
            host=args.pi_host,
            timeout_s=8,
        )
        if ok and out.strip():
            docker_summary = out.strip()

    # Upserts: LAN inventory
    lan_index = _index_by_title(lan_db, "IP")
    lan_added = 0
    lan_updated = 0
    now = _now_iso()
    for e in arp:
        props = {
            "MAC": build_rich_text_prop(e.mac),
            "Interface": build_rich_text_prop(e.iface),
            "Name": build_rich_text_prop(e.name),
            "Last Seen": build_date_prop(now),
        }
        _, created_row = _upsert_row(lan_db, "IP", e.ip, props, lan_index)
        if created_row:
            lan_added += 1
        else:
            lan_updated += 1
        time.sleep(0.05)

    # Upserts: Tail peers
    tail_index = _index_by_title(tail_db, "Peer")
    tail_added = 0
    tail_updated = 0
    for p in peers:
        os_name = p.os or "other"
        os_choice = os_name if os_name in {"macOS", "linux", "android", "windows", "ios"} else "other"
        online_choice = "Online" if p.online else "Offline"
        props = {
            "DNS": build_rich_text_prop(p.dns_name),
            "Tailscale IP": build_rich_text_prop(p.ipv4),
            "OS": build_select_prop(os_choice),
            "Online": build_select_prop(online_choice),
        }
        # LastSeen from tailscale is already ISO-ish; store as date if parseable.
        if p.last_seen and p.last_seen.startswith("20"):
            props["Last Seen"] = build_date_prop(p.last_seen)
        else:
            props["Last Seen"] = build_date_prop(now)
        _, created_row = _upsert_row(tail_db, "Peer", p.dns_name or p.host_name or p.ipv4, props, tail_index)
        if created_row:
            tail_added += 1
        else:
            tail_updated += 1
        time.sleep(0.05)

    # Update Devices (Auto) for key devices only.
    devices_index = _index_by_title(devices_db_id, "Device")

    def upsert_device(title: str, props: dict) -> None:
        _upsert_row(devices_db_id, "Device", title, props, devices_index)
        time.sleep(0.05)

    upsert_device(
        "MacBook Pro (Control Hub host)",
        {
            "Online": build_select_prop("Online"),
            "Last Seen": build_date_prop(now),
            "Notes": build_rich_text_prop("Synced by notion_infra_sync.py"),
        },
    )

    # Pi
    upsert_device(
        "Pi5 (tailnet + services)",
        {
            "Online": build_select_prop("Online" if pi_ok else "Offline"),
            "Last Seen": build_date_prop(now),
            "Notes": build_rich_text_prop(f"SSH: {'ok' if pi_ok else 'fail'}; docker:\n{docker_summary[:1400]}".strip()),
        },
    )

    # Quest via LAN ping (best-effort)
    quest_ip = "192.168.4.98"
    quest_online = _ping(quest_ip, timeout_s=2)
    upsert_device(
        "Quest 3 (VR headset)",
        {
            "IP": build_rich_text_prop(quest_ip),
            "Online": build_select_prop("Online" if quest_online else "Unknown"),
            "Last Seen": build_date_prop(now),
            "Notes": build_rich_text_prop("Ping-based check only (no ADB)."),
        },
    )

    # Services checks
    services_index = _index_by_title(services_db_id, "Service")

    def port_listening(port: int) -> bool:
        code, out, _ = _run(["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN"], timeout_s=3)
        return code == 0 and "LISTEN" in (out or "")

    svc_now_props = {"Last Checked": build_date_prop(now)}

    def upsert_service(name: str, status: str, detail: str) -> None:
        props = {
            "Status": build_select_prop(status),
            "Status Detail": build_rich_text_prop(detail[:1800]),
            **svc_now_props,
        }
        _upsert_row(services_db_id, "Service", name, props, services_index)
        time.sleep(0.05)

    ulan_ok = port_listening(3001)
    upsert_service("ULAN Alexa bridge", "OK" if ulan_ok else "Unknown", "Check: lsof TCP:3001 LISTEN")

    pantry_ok = port_listening(8410)
    upsert_service("Ash-Leigh's Pantry (Streamlit UI)", "OK" if pantry_ok else "Unknown", "Check: lsof TCP:8410 LISTEN")

    # iOS MCP server: process check (best effort)
    code, out, _ = _run(["pgrep", "-fl", "mcp_server.py"], timeout_s=3)
    mcp_ok = bool(out.strip())
    upsert_service("iOS Agent Runner MCP server", "OK" if mcp_ok else "Unknown", f"Check: pgrep mcp_server.py -> {'found' if mcp_ok else 'not found'}")

    # Camera loop + Hey Claude: only if Pi reachable
    if pi_ok and docker_summary:
        upsert_service("Camera loop (3 cams, 30-day retention)", "OK", "docker ps summary captured (see device notes).")
    else:
        upsert_service("Camera loop (3 cams, 30-day retention)", "Unknown", "Pi unreachable or docker ps unavailable.")

    upsert_service("Hey Claude (wake word assistant)", "Unknown", "Not auto-checked here (safe default).")

    out = {
        "ok": True,
        "when": now,
        "infrastructure_page_id": infra_page_id,
        "databases": {
            "lan_inventory_id": lan_db,
            "tailscale_peers_id": tail_db,
            "devices_id": devices_db_id,
            "services_id": services_db_id,
        },
        "schema_changes": schema_changes,
        "lan": {"count": len(arp), "added": lan_added, "updated": lan_updated},
        "tailscale": {
            "peer_count": len(peers),
            "added": tail_added,
            "updated": tail_updated,
            "backend_state": (ts or {}).get("BackendState") if ts else None,
            "self_ip": ((ts or {}).get("TailscaleIPs") or [None])[0] if ts else None,
        },
        "pi": pi_health,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
