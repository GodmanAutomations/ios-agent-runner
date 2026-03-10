#!/usr/bin/env python3
"""Expand Stephen's Notion Control Hub with a deeper use-case library + idea seeds.

Safe by design:
  - Does not read or print secrets.
  - Only writes to Notion via the existing integration token in `./.env`.

What it does:
  1. Appends additional content to the "Possibilities / Use Cases" page.
  2. Adds more rows into "Ideas / Backlog (Auto)" (skips duplicates by title).
  3. Ensures a few key non-git projects exist in "Projects (Auto)" for relations.
  4. Creates an "Artesian Jobs (Template)" database under the Control Hub's
     "Artesian Pools" page (idempotent by title+parent), with a couple samples.
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
    blocks_from_markdown,
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


def _extract_title(page: dict, prop_name: str) -> str:
    props = page.get("properties") or {}
    prop = props.get(prop_name) or {}
    chunks = prop.get("title") or []
    if not chunks:
        return ""
    return (chunks[0].get("plain_text") or "").strip()


def _get_parent_page_id(page_or_db_id: str, obj: str) -> str:
    if not page_or_db_id:
        return ""
    url = f"https://api.notion.com/v1/{obj}s/{page_or_db_id}"
    res = request_json("GET", url, headers=_headers())
    if not res.get("ok"):
        return ""
    parent = (res.get("data") or {}).get("parent") or {}
    if parent.get("type") == "page_id":
        return (parent.get("page_id") or "").strip()
    return ""


def _find_page_id_by_title_under_parent(title: str, parent_page_id: str) -> str:
    # Notion search relevance can return many database rows/pages first; use the max
    # page size so we can still find the actual hub page under the parent.
    res = search(title, limit=25)
    if not res.get("ok"):
        return ""
    for r in (res.get("data") or {}).get("results") or []:
        if r.get("object") != "page":
            continue
        pid = (r.get("id") or "").strip()
        if not pid:
            continue
        if not parent_page_id:
            return pid
        if _get_parent_page_id(pid, "page") == parent_page_id:
            return pid
    return ""


def _find_database_id_by_title_under_parent(title: str, parent_page_id: str) -> str:
    res = search(title, limit=25)
    if not res.get("ok"):
        return ""
    for r in (res.get("data") or {}).get("results") or []:
        if r.get("object") != "database":
            continue
        did = (r.get("id") or "").strip()
        if not did:
            continue
        if not parent_page_id:
            return did
        if _get_parent_page_id(did, "database") == parent_page_id:
            return did
    return ""


def _build_projects_title_to_id(projects_db_id: str) -> dict[str, str]:
    res = query_database(projects_db_id, page_size=100)
    if not res.get("ok"):
        return {}
    out: dict[str, str] = {}
    for page in (res.get("data") or {}).get("results") or []:
        pid = (page.get("id") or "").strip()
        name = _extract_title(page, "Project")
        if pid and name:
            out[name] = pid
    return out


def _build_idea_titles(ideas_db_id: str) -> set[str]:
    res = query_database(ideas_db_id, page_size=100)
    if not res.get("ok"):
        return set()
    titles: set[str] = set()
    for page in (res.get("data") or {}).get("results") or []:
        name = _extract_title(page, "Idea")
        if name:
            titles.add(name.lower())
    return titles


def _ensure_project(
    projects_db_id: str,
    title_to_id: dict[str, str],
    *,
    project: str,
    local_path: str,
    stack: str,
    recommendation: str,
    potential: int = 8,
    status: str = "prototype",
) -> tuple[bool, str]:
    if project in title_to_id:
        return False, title_to_id[project]

    props: dict = {
        "Project": build_title_prop(project),
        "Status": build_select_prop(status),
        "Local Path": build_rich_text_prop(local_path),
        "Stack": build_rich_text_prop(stack),
        "Potential": build_number_prop(potential),
        "Recommendation": build_rich_text_prop(recommendation),
    }
    created = add_database_row(projects_db_id, props)
    if not created.get("ok"):
        return False, ""

    pid = ((created.get("data") or {}).get("id") or "").strip()
    if pid:
        title_to_id[project] = pid
    return True, pid


def _append_usecase_content(usecases_page_id: str) -> dict:
    md = """
---
## Safety Layer: Quiet Hours + Dry-Run (4am-proof)

You want the power, without the "lights just fired at 4:00am" risk.

### Quiet Hours (global guard)
- A state flag (on/off) that blocks "loud" actions:
- Lights
- TV power / volume changes
- Alexa / speakers speaking out loud
- Anything that could wake someone up

### Dry-Run Mode (simulate everything)
- Same inputs (voice/button), but output is: "Here is what I *would* do."
- Use it for testing new intents and new device actions safely.

### Confirmations (for dangerous actions)
- If an action is destructive/expensive/noisy: require "confirm" within 15 seconds.

### Implementation (where it lives)
- Hey Claude: gate the intent router with `quiet_hours` + `dry_run`.
- ULAN: expose a `quiet_hours` state + refuse actions unless override.
- Notion: store current mode in a single page/database row so it's visible.

---
## Ops / Reliability: Autopilots That Pay You Back

### Daily Ops Digest (silent)
- Trigger: schedule (7:00am)
- Inputs: disk space, git status across repos, tailscale peer count, Pi health, docker health
- Outputs: Notion update + Pushover summary
- Safety: no device control, no audio

### "Is Anything Broken?" button
- Trigger: iPhone shortcut widget
- Output: one JSON response (green/yellow/red) + links to the failing logs

### Integration Smoke Tests
- Trigger: schedule hourly
- Output: Notion row per integration with status and last success
- Scope: Notion / Linear / Sentry / Figma

---
## Home: Scenes That Feel Like Magic (But Are Simple)

### Scene: Movie Mode (one tap)
- Trigger: iPhone button / Alexa routine / Hey Claude
- Output: TV on, Yamaha input set, launch app, volume preset

### Scene: "House Reset" (panic button)
- Trigger: one tap
- Output: turn off TVs, stop playback, set receiver to a safe input, quiet hours on

### Scene: "No Noise" (kid asleep)
- Trigger: iPhone button
- Output: quiet hours on + disable voice responses + block loud automations

---
## Business: Artesian Pools (Inground Vinyl Liner Remodels)

### Measurement -> Quote (the money printer)
- Trigger: voice memo or form
- Inputs: pool dims, steps, slope, liner pattern, add-ons
- Output: quote draft + materials list + job checklist created automatically

### Job Photos -> Tagged Archive
- Trigger: drop photos in a folder
- Output: auto-tags (skimmer, returns, steps, liner damage, fittings) + attach to job

### Customer Comms Pack
- Trigger: status change in your jobs DB
- Output: pre-written texts/emails for: schedule confirm, delay, approvals, payment reminder

---
## iOS Agent Runner: Make Non-Generic Apps Faster

### Design Loop (Figma -> Simulator -> iterate)
- Start with a real visual direction: typography + color + spacing rules
- Export assets from Figma (via API)
- Drive the simulator to validate flows and capture a demo reel

### QA / Regression
- Script the "critical path" screens
- Fail fast when UI changes break the flow

---
## Quest 3: VR as a Productivity Tool (Not a Toy)

### Field measurement assist (silent)
- Use Quest as "visual checklist + measurement calculator"
- Output: a structured measurement payload stored into Notion

### VR showroom
- Keep a gallery of liner patterns / before-after photos
- Use it to help customers decide faster

---
## What To Build Next (Top 10)

1. Quiet Hours + Dry-Run guardrails (safety first)
2. One-tap Ops Digest (daily + widget)
3. Artesian Jobs database + templates (single source of truth)
4. Measurement intake -> quote draft generator
5. Photo pipeline: tag + attach to job
6. Pantry: shared below-min shopping list
7. Hey Claude: "what's next today?" (reads Now/Next/Later)
8. ULAN: reliable Yamaha/TV control with scenes
9. Pushover: field capture button (voice memo -> action items)
10. Weekly business review: revenue, jobs, costs, pending decisions
"""

    blocks = blocks_from_markdown(md)
    res = append_blocks(usecases_page_id, blocks)
    return {
        "ok": bool(res.get("ok")),
        "appended_blocks": int(((res.get("data") or {}).get("appended") or 0)),
        "status": res.get("status", 0),
        "error": (res.get("error") or "")[:400],
    }


def _seed_ideas(
    ideas_db_id: str,
    projects_title_to_id: dict[str, str],
    existing_titles: set[str],
) -> dict:
    ideas: list[dict] = [
        # Home
        {
            "Idea": "ULAN: House Reset panic button",
            "Domain": "Home",
            "Impact": "High",
            "Effort": "S",
            "Notes": "One tap: stop playback, turn off TVs, safe receiver input, quiet hours on.",
            "Project": "ulan-agent",
        },
        {
            "Idea": "ULAN: scene runner (Movie/Sports/Goodnight/Quiet Hours)",
            "Domain": "Home",
            "Impact": "High",
            "Effort": "M",
            "Notes": "Make scenes first-class actions with a single config file and a safety layer.",
            "Project": "ulan-agent",
        },
        {
            "Idea": "Home: Wyze Cam -> event digest to Notion (template)",
            "Domain": "Home",
            "Impact": "Med",
            "Effort": "M",
            "Notes": "Start with a placeholder pipeline: store camera inventory + checks; later integrate RTSP/Frigate.",
            "Project": "MAX AI (Pi5)",
        },
        {
            "Idea": "Home: WiFi/Tailscale health watchdog with 1-tap fix steps",
            "Domain": "Home",
            "Impact": "High",
            "Effort": "S",
            "Notes": "If peer count is 0, write a Notion incident log + checklist of fixes.",
            "Project": "MAX AI (Pi5)",
        },
        # Family
        {
            "Idea": "Family: shared quiet-hours toggle (everyone can see state)",
            "Domain": "Family",
            "Impact": "High",
            "Effort": "S",
            "Notes": "A single Notion row + iPhone widget to toggle 'no-noise' mode.",
            "Project": "ulan-agent",
        },
        {
            "Idea": "Family: shared shopping list widget (below-min pantry items)",
            "Domain": "Family",
            "Impact": "High",
            "Effort": "M",
            "Notes": "Expose read-only shopping list to iPhone via Shortcuts + a simple endpoint.",
            "Project": "kroger-playground",
        },
        {
            "Idea": "Family: one-tap 'Where is everyone?' (phone pings + location link)",
            "Domain": "Family",
            "Impact": "Med",
            "Effort": "M",
            "Notes": "Pushover buttons for quick family coordination without spam.",
            "Project": "MAX AI (Pi5)",
        },
        # Tools
        {
            "Idea": "Tools: repo health audit -> Notion (dirty, unpushed, stale branches)",
            "Domain": "Tools",
            "Impact": "High",
            "Effort": "S",
            "Notes": "Automate what you keep doing manually. Outputs a weekly checklist.",
            "Project": "ios-agent-runner",
        },
        {
            "Idea": "Tools: MCP servers inventory + smoke tests -> Notion",
            "Domain": "Tools",
            "Impact": "Med",
            "Effort": "M",
            "Notes": "List all MCP servers, test start/import, and track failures over time.",
            "Project": "ios-agent-runner",
        },
        {
            "Idea": "Tools: secrets audit report (local) + remediation checklist",
            "Domain": "Tools",
            "Impact": "High",
            "Effort": "M",
            "Notes": "Scan for accidental tokens in repos; output a safe report without printing secrets.",
            "Project": "ios-agent-runner",
        },
        # Business
        {
            "Idea": "Artesian: Job CRM in Notion (jobs/customers/quotes)",
            "Domain": "Business",
            "Impact": "High",
            "Effort": "M",
            "Notes": "Single source of truth for job status, measurements, photos, and next actions.",
            "Project": "Artesian Pools Automation",
        },
        {
            "Idea": "Artesian: quote template pack + customer comms pack",
            "Domain": "Business",
            "Impact": "High",
            "Effort": "M",
            "Notes": "Generate quotes and standardized comms from job status changes.",
            "Project": "Artesian Pools Automation",
        },
        {
            "Idea": "Artesian: measurement calculator (liner order helper)",
            "Domain": "Business",
            "Impact": "High",
            "Effort": "S",
            "Notes": "Compute liner order inputs + sanity checks + printable summary.",
            "Project": "Artesian Pools Automation",
        },
        {
            "Idea": "Artesian: job photo intake (tagging + attach to job record)",
            "Domain": "Business",
            "Impact": "High",
            "Effort": "L",
            "Notes": "Drop photos -> auto-tag -> file naming -> attach to job in Notion.",
            "Project": "Artesian Pools Automation",
        },
        {
            "Idea": "Artesian: 'field capture' shortcut (voice memo -> action items)",
            "Domain": "Business",
            "Impact": "High",
            "Effort": "S",
            "Notes": "One button: dictate notes; system extracts tasks and appends to the job.",
            "Project": "Artesian Pools Automation",
        },
        {
            "Idea": "iOS Agent Runner: Figma -> assets exporter for app prototypes",
            "Domain": "Tools",
            "Impact": "Med",
            "Effort": "M",
            "Notes": "Pull images/icons/colors from Figma automatically for a consistent look.",
            "Project": "ios-agent-runner",
        },
        {
            "Idea": "Hey Claude: dry-run mode for new intents",
            "Domain": "Tools",
            "Impact": "High",
            "Effort": "S",
            "Notes": "Simulate actions, output plan only. Prevents surprises at night.",
            "Project": "Hey Claude",
        },
        {
            "Idea": "Hey Claude: 'what should I do next' (Now/Next/Later reader)",
            "Domain": "Tools",
            "Impact": "Med",
            "Effort": "S",
            "Notes": "Read your Notion roadmap page and give the next 3 actions.",
            "Project": "Hey Claude",
        },
        # Pantry
        {
            "Idea": "Pantry: barcode scan -> add item (phone-first)",
            "Domain": "Family",
            "Impact": "High",
            "Effort": "M",
            "Notes": "Make it effortless for Ashley: scan, set minimum, done.",
            "Project": "kroger-playground",
        },
        {
            "Idea": "Pantry: weekly 'what to buy' push on Sunday",
            "Domain": "Family",
            "Impact": "Med",
            "Effort": "S",
            "Notes": "Auto-push below-min items weekly so groceries are easy.",
            "Project": "kroger-playground",
        },
        # Quest
        {
            "Idea": "Quest 3: VR showroom of liner patterns + before/after portfolio",
            "Domain": "Business",
            "Impact": "Med",
            "Effort": "L",
            "Notes": "A customer-friendly VR gallery to speed up decisions.",
            "Project": "ulan-agent",
        },
        # Lock UI
        {
            "Idea": "YR01 Smart Lock: premium UI theme + onboarding flow (non-generic)",
            "Domain": "Tools",
            "Impact": "Med",
            "Effort": "M",
            "Notes": "Typography, color, motion, and a clean 'setup wizard' UX.",
            "Project": "YR01SmartLock",
        },
    ]

    added = 0
    skipped = 0
    errors: list[str] = []

    for idea in ideas:
        title = (idea.get("Idea") or "").strip()
        if not title:
            continue
        if title.lower() in existing_titles:
            skipped += 1
            continue

        props: dict = {
            "Idea": build_title_prop(title),
            "Domain": build_select_prop(idea.get("Domain") or "Tools"),
            "Impact": build_select_prop(idea.get("Impact") or "Med"),
            "Effort": build_select_prop(idea.get("Effort") or "M"),
            "Notes": build_rich_text_prop(idea.get("Notes") or ""),
        }

        proj = (idea.get("Project") or "").strip()
        if proj and proj in projects_title_to_id:
            props["Related Project"] = {"relation": [{"id": projects_title_to_id[proj]}]}

        res = add_database_row(ideas_db_id, props)
        if res.get("ok"):
            existing_titles.add(title.lower())
            added += 1
        else:
            errors.append(f"{title}: {str(res.get('error') or '')[:160]}")
        time.sleep(0.15)

    return {"ok": not errors, "added": added, "skipped": skipped, "errors": errors[:10]}


def _ensure_artesian_jobs_db(control_hub_id: str, artesian_page_id: str) -> dict:
    db_title = "Artesian Jobs (Template)"
    existing = _find_database_id_by_title_under_parent(db_title, artesian_page_id)
    if existing:
        return {"ok": True, "created": False, "database_id": existing}

    schema = {
        "Job": {"title": {}},
        "Status": {"select": {"options": [
            {"name": "Lead", "color": "gray"},
            {"name": "Scheduled", "color": "blue"},
            {"name": "In Progress", "color": "yellow"},
            {"name": "Waiting", "color": "orange"},
            {"name": "Done", "color": "green"},
        ]}},
        "Customer": {"rich_text": {}},
        "Address": {"rich_text": {}},
        "Start Date": {"date": {}},
        "Target Finish": {"date": {}},
        "Pool Length (ft)": {"number": {"format": "number"}},
        "Pool Width (ft)": {"number": {"format": "number"}},
        "Shallow Depth (ft)": {"number": {"format": "number"}},
        "Deep Depth (ft)": {"number": {"format": "number"}},
        "Liner Pattern": {"rich_text": {}},
        "Quote Amount": {"number": {"format": "dollar"}},
        "Deposit Received": {"checkbox": {}},
        "Next Action": {"rich_text": {}},
        "Notes": {"rich_text": {}},
    }

    created = create_database(artesian_page_id, db_title, schema, is_inline=True)
    if not created.get("ok"):
        return {"ok": False, "created": False, "error": (created.get("error") or "")[:400]}

    db_id = ((created.get("data") or {}).get("id") or "").strip()
    if not db_id:
        return {"ok": False, "created": False, "error": "database created but id missing"}

    # Seed with a couple sample rows (fake data).
    samples = [
        {
            "Job": build_title_prop("SAMPLE - Liner Replace (16x32)"),
            "Status": build_select_prop("Lead"),
            "Customer": build_rich_text_prop("SAMPLE CUSTOMER"),
            "Address": build_rich_text_prop("SAMPLE ADDRESS"),
            "Pool Length (ft)": build_number_prop(32),
            "Pool Width (ft)": build_number_prop(16),
            "Shallow Depth (ft)": build_number_prop(4),
            "Deep Depth (ft)": build_number_prop(8),
            "Quote Amount": build_number_prop(0),
            "Deposit Received": build_checkbox_prop(False),
            "Next Action": build_rich_text_prop("Collect measurements + photos; choose liner pattern."),
            "Notes": build_rich_text_prop("Template row. Duplicate this for real jobs."),
        },
        {
            "Job": build_title_prop("SAMPLE - Repair + Refresh"),
            "Status": build_select_prop("Scheduled"),
            "Customer": build_rich_text_prop("SAMPLE CUSTOMER"),
            "Address": build_rich_text_prop("SAMPLE ADDRESS"),
            "Start Date": build_date_prop("2026-03-01"),
            "Target Finish": build_date_prop("2026-03-07"),
            "Quote Amount": build_number_prop(0),
            "Deposit Received": build_checkbox_prop(False),
            "Next Action": build_rich_text_prop("Confirm schedule + send prep checklist."),
            "Notes": build_rich_text_prop("Template row. Replace with real job details."),
        },
    ]
    for row in samples:
        add_database_row(db_id, row)
        time.sleep(0.15)

    return {"ok": True, "created": True, "database_id": db_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand Notion Control Hub with more use cases + ideas.")
    parser.add_argument("--control-hub-id", default="309f7bec-843d-804a-9d21-c7e980580069")
    parser.add_argument("--usecases-page-id", default="")
    parser.add_argument("--ideas-db-id", default="30af7bec-843d-818d-8d6d-e0e02953e527")
    parser.add_argument("--projects-db-id", default="30af7bec-843d-81c3-b2d2-c892b27b1a17")
    parser.add_argument(
        "--only-artesian-jobs",
        action="store_true",
        help="Only create/ensure the Artesian Jobs template DB (no page append, no idea seeds).",
    )
    args = parser.parse_args()

    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    control_hub_id = (args.control_hub_id or "").strip()
    usecases_page_id = (args.usecases_page_id or "").strip()
    if not usecases_page_id:
        usecases_page_id = _find_page_id_by_title_under_parent("Possibilities / Use Cases", control_hub_id)
    if not usecases_page_id and not args.only_artesian_jobs:
        print(json.dumps({"ok": False, "error": "Could not find use-cases page under control hub."}, indent=2))
        return 2

    projects_db_id = (args.projects_db_id or "").strip()
    ideas_db_id = (args.ideas_db_id or "").strip()

    # If requested, only ensure the Artesian Jobs DB exists and return.
    if args.only_artesian_jobs:
        artesian_page_id = _find_page_id_by_title_under_parent("Artesian Pools", control_hub_id)
        if not artesian_page_id:
            print(json.dumps({"ok": False, "error": "Artesian Pools page not found under control hub."}, indent=2))
            return 2
        jobs_res = _ensure_artesian_jobs_db(control_hub_id, artesian_page_id)
        print(json.dumps({"ok": bool(jobs_res.get("ok")), "artesian_jobs_db": jobs_res}, indent=2))
        return 0 if jobs_res.get("ok") else 1

    # Ensure a few key projects exist so Ideas can relate cleanly.
    title_to_id = _build_projects_title_to_id(projects_db_id)
    created_projects: list[str] = []

    created, _ = _ensure_project(
        projects_db_id,
        title_to_id,
        project="Hey Claude",
        local_path=str(Path.home() / "hey-claude"),
        stack="Porcupine (wake), faster-whisper (STT), ULAN bridge, OpenAI TTS",
        recommendation="Make Quiet Hours + Dry-Run the default guardrails; add a 'status' command.",
        potential=9,
    )
    if created:
        created_projects.append("Hey Claude")

    created, _ = _ensure_project(
        projects_db_id,
        title_to_id,
        project="YR01SmartLock",
        local_path=str(Path.home() / "YR01SmartLock"),
        stack="iOS prototype + BLE/lock workflow (UI/UX focused)",
        recommendation="Build a premium, non-generic UI theme pack + onboarding flow; validate in simulator.",
        potential=8,
    )
    if created:
        created_projects.append("YR01SmartLock")

    created, _ = _ensure_project(
        projects_db_id,
        title_to_id,
        project="Artesian Pools Automation",
        local_path=str(Path.home() / "Desktop" / "The Claude Project" / "artesian_pools_automation"),
        stack="Job workflow automation (checklists, quotes, photo pipeline)",
        recommendation="Create the Notion jobs DB + measurement schema; then automate quote drafts.",
        potential=10,
        status="mvp",
    )
    if created:
        created_projects.append("Artesian Pools Automation")

    # Expand the use-case library page.
    append_res = _append_usecase_content(usecases_page_id)

    # Seed more ideas (skip duplicates).
    existing_idea_titles = _build_idea_titles(ideas_db_id)
    seed_res = _seed_ideas(ideas_db_id, title_to_id, existing_idea_titles)

    # Create the Artesian Jobs template database under the Artesian page.
    artesian_page_id = _find_page_id_by_title_under_parent("Artesian Pools", control_hub_id)
    jobs_res = {"ok": False, "error": "Artesian Pools page not found under control hub."}
    if artesian_page_id:
        jobs_res = _ensure_artesian_jobs_db(control_hub_id, artesian_page_id)

    out = {
        "ok": bool(append_res.get("ok") and seed_res.get("ok") and jobs_res.get("ok")),
        "control_hub_id": control_hub_id,
        "usecases_page_id": usecases_page_id,
        "appended": append_res,
        "ideas_seed": seed_res,
        "projects_added": created_projects,
        "artesian_jobs_db": jobs_res,
    }
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
