#!/usr/bin/env python3
"""Generate a detailed Notion "Control Hub" for Stephen.

This script scans local (non-secret) project docs and creates a set of Notion
sub-pages under a parent page you share with the "Ios Agent Runner" integration.

Why a parent page is required:
  Notion API cannot create workspace-root pages for internal integrations.

Security:
  - Never reads `.env` files for content.
  - Skips credential-related paths by default.
  - Does not print or persist secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.integrations import notion_api

_HOME = Path.home()
_MEMORY_DIR = _HOME / ".claude" / "projects" / "-Users-stephengodman" / "memory"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_read_text(path: Path, *, max_bytes: int = 80_000) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    if len(data) > max_bytes:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _looks_sensitive_path(path: Path) -> bool:
    lowered = str(path).lower()
    if "/.env" in lowered or lowered.endswith(".env") or lowered.endswith(".env.local"):
        return True
    if "credential" in lowered or "recovery" in lowered or "token" in lowered or "password" in lowered:
        return True
    return False


def _normalize_notion_id(raw: str) -> str:
    raw = (raw or "").strip().strip("/")
    if not raw:
        return ""

    # UUID format already.
    m_uuid = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", raw)
    if m_uuid:
        return m_uuid.group(0).lower()

    # 32-hex format often present in Notion URLs.
    m_32 = re.search(r"([0-9a-fA-F]{32})", raw)
    if not m_32:
        return ""

    s = m_32.group(1).lower()
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"


def _repo_summary(repo_dir: Path) -> dict:
    readme = repo_dir / "README.md"
    excerpt = ""
    if readme.exists() and not _looks_sensitive_path(readme):
        txt = _safe_read_text(readme, max_bytes=20_000)
        # First ~25 non-empty lines.
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        excerpt = "\n".join(lines[:25]).strip()

    return {
        "path": str(repo_dir),
        "name": repo_dir.name,
        "readme_excerpt": excerpt,
    }


def _discover_repos() -> list[Path]:
    candidates = [
        _HOME / "ulan-agent",
        _HOME / "ios-agent-runner",
        _HOME / "ulan-wakeword-client",
        _HOME / "quest-claude-assistant",
        _HOME / "plaid-control-center",
        _HOME / "godmanautomations-website",
    ]

    # Any other git repos directly under ~/
    try:
        for entry in _HOME.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            if (entry / ".git").exists():
                candidates.append(entry)
    except Exception:
        pass

    repos: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        p = p.expanduser().resolve()
        if str(p) in seen:
            continue
        seen.add(str(p))
        if p.is_dir() and (p / ".git").exists():
            repos.append(p)

    repos.sort(key=lambda x: x.name.lower())
    return repos


def _render_start_here() -> str:
    lines: list[str] = []
    lines.append("# Stephen Control Hub")
    lines.append("")
    lines.append("This hub is your home base for everything you've built: projects, automations, devices, and ideas.")
    lines.append("")
    lines.append("## What you have working right now")
    lines.append("- ULAN: local-first home control (TVs, Shield, Yamaha, Hue, etc.)")
    lines.append("- Wake-word client: 'Hey house' voice -> ULAN webhook")
    lines.append("- iOS Agent Runner: iOS simulator automation + intel pipeline")
    lines.append("- Integrations: Notion / Linear / Sentry / Figma API access (already verified)")
    lines.append("")
    lines.append("## Immediate next fixes (known blockers)")
    lines.append("- Tailscale: this Mac currently sees 0 peers, so Pi/Quest tailnet actions won't work until peers appear.")
    lines.append("- Quest ADB: USB serial not currently visible; WiFi ADB ports refused.")
    lines.append("")
    lines.append("## Quick actions")
    lines.append("```bash")
    lines.append("# System + integrations health")
    lines.append("cd ~/ios-agent-runner && source .venv/bin/activate")
    lines.append("python scripts/doctor.py | jq .")
    lines.append("python scripts/ops_digest.py --no-network")
    lines.append("")
    lines.append("# Home control (ULAN)")
    lines.append("cd ~/ulan-agent && source .venv/bin/activate")
    lines.append("python -m ulan.cli --help")
    lines.append("```")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_projects_section() -> str:
    repos = _discover_repos()
    lines: list[str] = []
    lines.append("# Projects (Local)")
    lines.append("")
    lines.append("This is what you have on disk right now, plus a quick sketch of each repo.")
    lines.append("")

    for repo in repos:
        info = _repo_summary(repo)
        lines.append(f"## {info['name']}")
        lines.append(f"- path: `{info['path']}`")
        if info["readme_excerpt"]:
            lines.append("")
            lines.append("### README excerpt")
            lines.append("```")
            lines.append(info["readme_excerpt"])
            lines.append("```")
        lines.append("")

    # Desktop projects (non-git)
    claude_project = _HOME / "Desktop" / "The Claude Project"
    if claude_project.exists():
        lines.append("# Desktop: The Claude Project")
        lines.append(f"- path: `{claude_project}`")
        try:
            subs = sorted([p for p in claude_project.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
        except Exception:
            subs = []
        for sub in subs:
            lines.append(f"- {sub.name}: `{sub}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_ideas_section() -> str:
    lines: list[str] = []
    lines.append("# Ideas / Backlog")
    lines.append("")
    lines.append("Pulled from local docs and current capabilities (no secrets).")
    lines.append("")

    cool = _HOME / "Desktop" / "COOL-SHIT-MENU.md"
    if cool.exists() and not _looks_sensitive_path(cool):
        lines.append("## COOL SHIT MENU (from Desktop)")
        lines.append("```")
        lines.append(_safe_read_text(cool, max_bytes=80_000).strip())
        lines.append("```")
        lines.append("")

    lines.append("## ULAN + iOS agent runner combo ideas")
    lines.append("- Use iOS intel pipeline to scrape settings/screens for device configs and auto-update ULAN notes")
    lines.append("- Daily Ops Digest (local markdown + Notion publish): repo health, device health, integrations health")
    lines.append("- Field checklist page: pre-job steps + measurement checklist + liner order checklist")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_phone_buttons_section() -> str:
    lines: list[str] = []
    lines.append("# Phone Buttons (iPhone Shortcuts + Widgets)")
    lines.append("")
    lines.append("Fastest way to get \"hit a button and stuff happens\".")
    lines.append("")
    lines.append("You already have ULAN running on your Mac on port 3001. It exposes:")
    lines.append("- `POST /claude` (alias of `/alexa`) which accepts an Alexa-style JSON payload")
    lines.append("")
    lines.append("## Shortcut: Hey House (voice -> action)")
    lines.append("Create a Shortcut with these actions:")
    lines.append("- Dictate Text (variable: `Command`)")
    lines.append("- Get Contents of URL")
    lines.append("")
    lines.append("### Get Contents of URL settings")
    lines.append("- URL (LAN): `http://192.168.4.153:3001/claude`")
    lines.append("- URL (Tailscale): `http://100.114.106.68:3001/claude` (after tailnet is fixed)")
    lines.append("- Method: POST")
    lines.append("- Headers: `Content-Type: application/json`")
    lines.append("- Body: JSON:")
    lines.append("```json")
    lines.append("{")
    lines.append('  "version": "1.0",')
    lines.append('  "session": { "user": { "userId": "iphone-shortcuts" } },')
    lines.append('  "request": {')
    lines.append('    "type": "IntentRequest",')
    lines.append('    "intent": {')
    lines.append('      "name": "HomeControlIntent",')
    lines.append('      "slots": {')
    lines.append('        "command": { "name": "command", "value": "<REPLACE WITH SHORTCUT VARIABLE>" }')
    lines.append("      }")
    lines.append("    }")
    lines.append("  }")
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("Then add:")
    lines.append("- Show Result (or Speak Text) using `response.outputSpeech.text` from the returned JSON.")
    lines.append("")
    lines.append("## Shortcut: Movie Mode (one tap)")
    lines.append("Skip Dictate Text and hardcode the command:")
    lines.append("- `play Netflix on the LG`")
    lines.append("")
    lines.append("Pin it to your Home Screen as a widget.")
    lines.append("")
    lines.append("## Shortcut: Pushover Quick Note (capture in the field)")
    lines.append("If you want a \"brain dump\" button that pings your phone:")
    lines.append("- Dictate Text -> POST to `https://api.pushover.net/1/messages.json` with token+user+message")
    lines.append("- (Keep the tokens in the Shortcut, not in git.)")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_alexa_routines_section() -> str:
    lines: list[str] = []
    lines.append("# Alexa Buttons (Routines)")
    lines.append("")
    lines.append("This is the other 1-tap path: Alexa app -> Routines -> \"When you tap\" -> Custom phrase.")
    lines.append("")
    lines.append("Your current local skill model (checked in `~/ulan-agent/alexa-skill`) uses invocation name:")
    lines.append("- `my house`")
    lines.append("")
    lines.append("So your routine Custom action should look like:")
    lines.append("- `tell my house <command>`")
    lines.append("")
    lines.append("## Routine Button Pack (10)")
    lines.append("- Movie Mode: `tell my house play Netflix on the LG`")
    lines.append("- YouTube: `tell my house play YouTube on the LG`")
    lines.append("- Volume Up: `tell my house volume up on the LG`")
    lines.append("- Volume Down: `tell my house volume down on the LG`")
    lines.append("- Mute: `tell my house mute the LG`")
    lines.append("- Unmute: `tell my house unmute the LG`")
    lines.append("- Switch to Yamaha: `tell my house switch to Yamaha`")
    lines.append("- Turn Off Sony: `tell my house turn off the Sony`")
    lines.append("- Turn Off LG: `tell my house turn off the LG`")
    lines.append("- Goodnight: `tell my house goodnight`")
    lines.append("")
    lines.append("If you're using a different invocation name (like `hey claude`), swap the words accordingly.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_hey_claude_section() -> str:
    lines: list[str] = []
    lines.append("# Hey Claude (Wake Word Voice Assistant)")
    lines.append("")
    lines.append("Local repo:")
    lines.append("- `~/hey-claude/`")
    lines.append("")
    lines.append("What it is:")
    lines.append("- Wake word: Porcupine (Picovoice)")
    lines.append("- STT: faster-whisper (local)")
    lines.append("- Intent routing: GPT-4o-mini (and/or local heuristics)")
    lines.append("- Actions: ULAN bridge + Artesian + profile lookups + system checks")
    lines.append("")
    readme = _HOME / "hey-claude" / "README.md"
    if readme.exists() and not _looks_sensitive_path(readme):
        lines.append("## README excerpt")
        lines.append("```")
        lines.append(_safe_read_text(readme, max_bytes=40_000).strip())
        lines.append("```")
        lines.append("")
    lines.append("## Fast local test (no microphone)")
    lines.append("```bash")
    lines.append("cd ~/hey-claude")
    lines.append("python3 -m venv venv")
    lines.append("source venv/bin/activate")
    lines.append("pip install -r requirements.txt")
    lines.append("python -m hey_claude.cli interactive")
    lines.append("```")
    lines.append("")
    lines.append("## Wake word key (Porcupine)")
    lines.append("- Create a Picovoice account and generate an AccessKey.")
    lines.append("- Add it to `~/hey-claude/.env` (do not commit it).")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_troubleshooting_section() -> str:
    lines: list[str] = []
    lines.append("# Troubleshooting / Known Blockers")
    lines.append("")
    lines.append("## Tailscale (Mac shows 0 peers)")
    lines.append("- If peers are 0, your iPhone and Pi won't be reachable by Tailscale IP.")
    lines.append("- Fix checklist:")
    lines.append("  - Confirm iPhone is signed into the same Tailscale account")
    lines.append("  - Turn on Tailscale on iPhone")
    lines.append("  - On Mac: `tailscale status --json` and confirm `peer_count > 0`")
    lines.append("")
    lines.append("## Quest ADB missing")
    lines.append("- USB serial not visible; WiFi ADB ports refused.")
    lines.append("- Likely cause: Wireless Debugging toggle missing/disabled or dev mode not fully enabled.")
    lines.append("- Important: avoid `adb kill-server` because it could drop Shield ADB.")
    lines.append("")
    lines.append("## Pi SSH timeout")
    lines.append("- Expected until Tailscale peers are visible or LAN routing is confirmed.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def _render_artesian_section() -> str:
    lines: list[str] = []
    lines.append("# Artesian Pools (Inground Vinyl Liner Remodels)")
    lines.append("")
    lines.append("You said: you remodel inground vinyl liner pools. Here's how the current stack can help.")
    lines.append("")

    ap_dir = _HOME / "Desktop" / "The Claude Project" / "artesian_pools_automation"
    lines.append("## Existing automation project")
    lines.append(f"- path: `{ap_dir}`")
    lines.append("- purpose: Trello job sync + smart pricing + work order enrichment")
    lines.append("")

    readme = ap_dir / "README.md"
    if readme.exists() and not _looks_sensitive_path(readme):
        lines.append("### README excerpt")
        lines.append("```")
        lines.append(_safe_read_text(readme, max_bytes=30_000).strip())
        lines.append("```")
        lines.append("")

    lines.append("## High-leverage next automations (recommended)")
    lines.append("- Measurement intake: one form -> schema -> quote template -> Trello card enrich")
    lines.append("- Job photo pipeline: drop photos -> OCR -> tag (liner, steps, fittings, damage, brands) -> attach to job")
    lines.append("- Customer comms templates: before/after, schedule changes, approvals, payment reminders")
    lines.append("- Pricing sanity guardrails: detect outliers vs historical jobs; require confirm before sending")
    lines.append("- Field mode: iPhone shortcut -> voice memo -> structured action items")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_ulan_section() -> str:
    lines: list[str] = []
    lines.append("# ULAN (Home Control)")
    lines.append("")
    lines.append("Core projects:")
    lines.append(f"- Agent: `{_HOME / 'ulan-agent'}`")
    lines.append(f"- Wake-word client: `{_HOME / 'ulan-wakeword-client'}`")
    lines.append("")
    lines.append("Quick commands:")
    lines.append("```bash")
    lines.append("cd ~/ulan-agent && source .venv/bin/activate")
    lines.append("python -m ulan.cli --help")
    lines.append("bash scripts/start-alexa-bridge.sh")
    lines.append("```")
    lines.append("")

    devices_md = _MEMORY_DIR / "ulan-devices.md"
    if devices_md.exists():
        lines.append("## Current device inventory (from memory)")
        lines.append("```")
        lines.append(_safe_read_text(devices_md, max_bytes=40_000).strip())
        lines.append("```")
        lines.append("")

    quest_md = _MEMORY_DIR / "quest3-status.md"
    if quest_md.exists():
        lines.append("## Quest 3 status (known blocker)")
        lines.append("```")
        lines.append(_safe_read_text(quest_md, max_bytes=30_000).strip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_ios_agent_section() -> str:
    lines: list[str] = []
    lines.append("# iOS Agent Runner (Simulator Automation + Intel)")
    lines.append("")
    lines.append(f"- repo: `{_HOME / 'ios-agent-runner'}`")
    lines.append(f"- findings store: `{_HOME / '.ulan' / 'ios_intel.json'}`")
    lines.append("")
    lines.append("Quick commands:")
    lines.append("```bash")
    lines.append("cd ~/ios-agent-runner && source .venv/bin/activate")
    lines.append("python main.py --dump-tree")
    lines.append("python main.py --bundle-id com.apple.Preferences --dump-tree")
    lines.append("python mcp_server.py")
    lines.append("python scripts/doctor.py | jq .")
    lines.append("```")
    lines.append("")

    doc = _MEMORY_DIR / "ios-agent-runner.md"
    if doc.exists():
        lines.append("## Project summary (from memory)")
        lines.append("```")
        lines.append(_safe_read_text(doc, max_bytes=60_000).strip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_integrations_section() -> str:
    lines: list[str] = []
    lines.append("# Integrations (Notion / Linear / Sentry / Figma)")
    lines.append("")
    lines.append("These are already wired up in `~/ios-agent-runner/.env` (tokens not shown here).")
    lines.append("")
    lines.append("Smoke test:")
    lines.append("```bash")
    lines.append("cd ~/ios-agent-runner && source .venv/bin/activate")
    lines.append("python -c \"from scripts.integrations import notion_api; print(notion_api.me())\"")
    lines.append("python -c \"from scripts.integrations import linear_api; print(linear_api.viewer())\"")
    lines.append("python -c \"from scripts.integrations import sentry_api; print(sentry_api.me())\"")
    lines.append("python -c \"from scripts.integrations import figma_api; print(figma_api.me())\"")
    lines.append("```")
    lines.append("")

    quick = _MEMORY_DIR / "integration-quick-start.md"
    if quick.exists():
        lines.append("## Quick reference (from memory)")
        lines.append("```")
        lines.append(_safe_read_text(quick, max_bytes=60_000).strip())
        lines.append("```")
        lines.append("")

    lines.append("## Notion setup requirement")
    lines.append("> Create a page in Notion, Share -> invite 'Ios Agent Runner', give edit access, then pass that page URL into this script.")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_system_section() -> str:
    lines: list[str] = []
    lines.append("# System Health")
    lines.append("")
    lines.append("Run the local digest:")
    lines.append("```bash")
    lines.append("cd ~/ios-agent-runner && source .venv/bin/activate")
    lines.append("python scripts/ops_digest.py --no-network")
    lines.append("```")
    lines.append("")

    latest = _MEMORY_DIR / "ops-digest_latest.md"
    if latest.exists():
        lines.append("## Latest digest snapshot")
        lines.append("```")
        lines.append(_safe_read_text(latest, max_bytes=80_000).strip())
        lines.append("```")
        lines.append("")
    else:
        lines.append("> No digest snapshot found yet. Run it once and re-run this Notion bootstrap.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_hub_pages() -> list[dict]:
    return [
        {"title": "Start Here", "content_md": _render_start_here()},
        {"title": "Phone Buttons", "content_md": _render_phone_buttons_section()},
        {"title": "Alexa Routines", "content_md": _render_alexa_routines_section()},
        {"title": "Hey Claude", "content_md": _render_hey_claude_section()},
        {"title": "Projects", "content_md": _render_projects_section()},
        {"title": "Ideas Backlog", "content_md": _render_ideas_section()},
        {"title": "Artesian Pools", "content_md": _render_artesian_section()},
        {"title": "ULAN Home Automation", "content_md": _render_ulan_section()},
        {"title": "iOS Agent Runner", "content_md": _render_ios_agent_section()},
        {"title": "Integrations", "content_md": _render_integrations_section()},
        {"title": "System Health", "content_md": _render_system_section()},
        {"title": "Troubleshooting", "content_md": _render_troubleshooting_section()},
    ]


def _write_local_json(out_dir: Path, name: str, payload: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{_now_stamp()}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def publish(parent_page_id: str, pages: list[dict]) -> dict:
    results: list[dict] = []
    for p in pages:
        title = str(p.get("title") or "").strip()
        content_md = str(p.get("content_md") or "")
        if not title:
            continue

        created = notion_api.create_page(parent_page_id=parent_page_id, title=title, content=content_md)
        row = {
            "title": title,
            "ok": bool(created.get("ok")),
            "status": created.get("status"),
            "error": "",
        }
        if not created.get("ok"):
            row["error"] = str(created.get("error") or "")[:800]
        else:
            data = created.get("data") or {}
            row["id"] = data.get("id")
            row["url"] = data.get("url")
        results.append(row)

    ok = all(r.get("ok") for r in results) if results else True
    return {"ok": ok, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a detailed Notion Control Hub.")
    parser.add_argument(
        "--parent-url",
        default="",
        help="Notion parent page URL (preferred).",
    )
    parser.add_argument(
        "--parent-page-id",
        default=os.getenv("NOTION_PARENT_PAGE_ID", ""),
        help="Notion parent page id (fallback).",
    )
    parser.add_argument("--publish", action="store_true", help="Actually create pages in Notion.")
    parser.add_argument("--out-dir", default=str(_MEMORY_DIR), help="Where to write local draft + results.")
    args = parser.parse_args()

    # Mirror project env loading (never print secrets).
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(_HOME / ".env")

    parent = _normalize_notion_id(args.parent_url) or _normalize_notion_id(args.parent_page_id)
    pages = build_hub_pages()
    out_dir = Path(args.out_dir).expanduser()

    draft_path = _write_local_json(out_dir, "notion_control_hub_draft", {"pages": pages})

    if not args.publish:
        payload = {
            "ok": True,
            "draft": str(draft_path),
            "note": "dry-run (add --publish to create pages)",
        }
        if not parent:
            payload["publish_requires"] = "Share a Notion page with 'Ios Agent Runner' and pass its URL via --parent-url"
        print(json.dumps(payload, indent=2))
        return 0

    if not parent:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "missing parent page id",
                    "how": "In Notion: create a page -> Share -> invite 'Ios Agent Runner' -> copy URL -> rerun with --parent-url",
                    "draft": str(draft_path),
                },
                indent=2,
            )
        )
        return 2

    res = publish(parent, pages)
    results_path = _write_local_json(out_dir, "notion_control_hub_results", res)

    print(json.dumps({"ok": res.get("ok"), "draft": str(draft_path), "results": str(results_path)}, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
