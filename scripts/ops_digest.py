#!/usr/bin/env python3
"""Ops digest for Stephen's local automation stack.

This script is intentionally "boring": it is a single command that validates the
current state of the automation ecosystem and produces a report you can share
or publish to Notion.

It does NOT print or persist secrets.
It does NOT run the iOS agent loop (no Anthropic credit burn).
It does NOT disrupt existing ADB sessions (no adb kill-server).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.integrations import figma_api, linear_api, notion_api, sentry_api

_DEFAULT_OUT_DIR = Path.home() / ".claude" / "projects" / "-Users-stephengodman" / "memory"
_DEFAULT_MCP_CONFIG = Path.home() / ".claude" / "mcp_servers.json"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _run(cmd: list[str], timeout: int = 10, cwd: Path | None = None) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or _PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "timeout"}
    except Exception as exc:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}


def _clip(s: str, max_len: int = 4000) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 20] + "\n... <clipped> ..."


def parse_git_porcelain(porcelain: str) -> dict:
    """Parse `git status --porcelain=v1 -b` output into a small summary."""
    lines = [ln.rstrip("\n") for ln in (porcelain or "").splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("##"):
        return {
            "ok": False,
            "branch": "",
            "upstream": "",
            "ahead": 0,
            "behind": 0,
            "dirty": False,
            "dirty_count": 0,
            "error": "unexpected status output",
        }

    header = lines[0][2:].strip()
    branch = header.split("...", 1)[0].strip()
    upstream = ""
    ahead = 0
    behind = 0
    if "..." in header:
        rest = header.split("...", 1)[1]
        upstream = rest.split("[", 1)[0].strip()
        if "[" in rest and "]" in rest:
            bracket = rest.split("[", 1)[1].split("]", 1)[0]
            # Examples: "ahead 1", "behind 2", "ahead 1, behind 2"
            parts = [p.strip() for p in bracket.split(",") if p.strip()]
            for p in parts:
                bits = p.split()
                if len(bits) == 2 and bits[1].isdigit():
                    if bits[0] == "ahead":
                        ahead = int(bits[1])
                    if bits[0] == "behind":
                        behind = int(bits[1])

    dirty_count = max(0, len(lines) - 1)
    return {
        "ok": True,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty_count > 0,
        "dirty_count": dirty_count,
        "error": "",
    }


def parse_adb_devices(output: str) -> list[dict]:
    devices: list[dict] = []
    for ln in (output or "").splitlines():
        ln = ln.strip()
        if not ln or ln.lower().startswith("list of devices"):
            continue
        parts = ln.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        meta: dict[str, str] = {}
        for tok in parts[2:]:
            if ":" in tok:
                k, v = tok.split(":", 1)
                meta[k] = v
        devices.append({"serial": serial, "state": state, "meta": meta})
    return devices


def _discover_repos(extra_repos: list[str] | None = None) -> list[Path]:
    candidates = [
        Path.home() / "ios-agent-runner",
        Path.home() / "ulan-agent",
        Path.home() / "ulan-wakeword-client",
        Path.home() / "quest-claude-assistant",
    ]
    for raw in extra_repos or []:
        p = Path(raw).expanduser().resolve()
        candidates.append(p)

    repos: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        if str(p) in seen:
            continue
        seen.add(str(p))
        if p.is_dir() and (p / ".git").exists():
            repos.append(p)
    return repos


def _check_git(repos: list[Path]) -> dict:
    if not shutil.which("git"):
        return {"ok": False, "error": "git not found on PATH", "repos": []}

    rows: list[dict] = []
    for repo in repos:
        status = _run(["git", "-C", str(repo), "status", "--porcelain=v1", "-b"], timeout=8, cwd=repo)
        summary = parse_git_porcelain(status.get("stdout", ""))
        head = _run(["git", "-C", str(repo), "log", "--oneline", "-n", "1"], timeout=8, cwd=repo)
        rows.append(
            {
                "path": str(repo),
                "status_ok": bool(status.get("ok")),
                "branch": summary.get("branch", ""),
                "ahead": int(summary.get("ahead", 0) or 0),
                "behind": int(summary.get("behind", 0) or 0),
                "dirty": bool(summary.get("dirty")),
                "dirty_count": int(summary.get("dirty_count", 0) or 0),
                "head": head.get("stdout", "") if head.get("ok") else "",
                "error": status.get("stderr", "") if not status.get("ok") else "",
            }
        )

    ok = all(r.get("status_ok") for r in rows) if rows else True
    return {"ok": ok, "error": "" if ok else "git status failed for one or more repos", "repos": rows}


def _check_integrations(network: bool) -> dict:
    payload: dict[str, dict] = {}

    def run_call(name: str, fn) -> dict:
        try:
            return fn()
        except Exception as exc:
            return {"ok": False, "status": 0, "data": None, "error": f"{name}: {exc}"}

    # Availability is checked without network.
    notion_ok, notion_detail = notion_api.is_available()
    linear_ok, linear_detail = linear_api.is_available()
    sentry_ok, sentry_detail = sentry_api.is_available()
    figma_ok, figma_detail = figma_api.is_available()

    payload["notion"] = {"available": notion_ok, "detail": notion_detail}
    payload["linear"] = {"available": linear_ok, "detail": linear_detail}
    payload["sentry"] = {"available": sentry_ok, "detail": sentry_detail}
    payload["figma"] = {"available": figma_ok, "detail": figma_detail}

    if not network:
        return {"ok": True, "calls": payload, "note": "network calls disabled"}

    # Live smoke calls. These do not include token values.
    if notion_ok:
        payload["notion"]["me"] = run_call("notion.me", notion_api.me)
    if linear_ok:
        payload["linear"]["viewer"] = run_call("linear.viewer", linear_api.viewer)
    if sentry_ok:
        payload["sentry"]["me"] = run_call("sentry.me", sentry_api.me)
    if figma_ok:
        payload["figma"]["me"] = run_call("figma.me", figma_api.me)

    ok = all(v.get("available") for v in payload.values())
    # "ok" here means credentials exist; live API may still fail (network).
    return {"ok": ok, "calls": payload, "note": ""}


def _check_tailscale() -> dict:
    if not shutil.which("tailscale"):
        return {"ok": False, "error": "tailscale not found on PATH"}
    res = _run(["tailscale", "status", "--json"], timeout=8)
    if not res.get("ok"):
        return {"ok": False, "error": _clip(res.get("stderr", "") or res.get("stdout", ""))}
    try:
        data = json.loads(res.get("stdout", "") or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid json from tailscale status --json"}

    peers = data.get("Peer") or {}
    self_node = data.get("Self") or {}
    return {
        "ok": True,
        "self_host": self_node.get("HostName", ""),
        "self_ips": self_node.get("TailscaleIPs", []),
        "peer_count": len(peers) if isinstance(peers, dict) else 0,
        "warning": _clip(res.get("stderr", ""), 200),
    }


def _check_adb() -> dict:
    adb = shutil.which("adb")
    if not adb:
        return {"ok": False, "error": "adb not found on PATH", "devices": []}
    res = _run([adb, "devices", "-l"], timeout=8)
    if not res.get("ok"):
        return {"ok": False, "error": _clip(res.get("stderr", "") or res.get("stdout", "")), "devices": []}
    devices = parse_adb_devices(res.get("stdout", ""))
    return {"ok": True, "error": "", "devices": devices}


def _check_pi_ssh(host: str, enabled: bool) -> dict:
    if not enabled:
        return {"ok": True, "skipped": True, "error": ""}
    if not shutil.which("ssh"):
        return {"ok": False, "skipped": False, "error": "ssh not found on PATH"}
    # Never prompt; never write to known_hosts.
    res = _run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            host,
            "echo ok",
        ],
        timeout=8,
        cwd=Path.home(),
    )
    if not res.get("ok"):
        return {"ok": False, "skipped": False, "error": _clip(res.get("stderr", "") or res.get("stdout", ""))}
    return {"ok": True, "skipped": False, "error": "", "stdout": _clip(res.get("stdout", ""), 200)}


def _check_disk() -> dict:
    df = _run(["df", "-h"], timeout=8, cwd=Path.home())
    du = _run(["bash", "-lc", "du -sh ~/* 2>/dev/null | sort -h | tail -n 20"], timeout=25, cwd=Path.home())
    return {
        "ok": bool(df.get("ok")),
        "df": _clip(df.get("stdout", ""), 2000),
        "du_top20": _clip(du.get("stdout", ""), 2000) if du.get("ok") else "",
        "du_error": "" if du.get("ok") else _clip(du.get("stderr", "") or du.get("stdout", ""), 200),
    }


def _check_launchagents() -> dict:
    la_dir = Path.home() / "Library" / "LaunchAgents"
    plists = []
    if la_dir.exists():
        plists = sorted([p.name for p in la_dir.glob("*.plist") if p.is_file()])

    loaded = _run(["launchctl", "list"], timeout=10, cwd=Path.home())
    loaded_lines = []
    if loaded.get("ok"):
        for ln in loaded.get("stdout", "").splitlines():
            if "com.godman" in ln or "com.stephen" in ln or "quest-watcher" in ln:
                loaded_lines.append(ln.strip())

    return {
        "ok": True,
        "plist_count": len(plists),
        "plists_sample": plists[:40],
        "loaded_matches": loaded_lines[:80],
        "error": "" if loaded.get("ok") else _clip(loaded.get("stderr", ""), 200),
    }


def _check_mcp_servers(config_path: Path) -> dict:
    if not config_path.exists():
        return {"ok": False, "error": f"missing {config_path}", "servers": []}
    try:
        data = json.loads(config_path.read_text())
    except Exception as exc:
        return {"ok": False, "error": f"failed to parse {config_path}: {exc}", "servers": []}

    servers = (data.get("mcpServers") or {}) if isinstance(data, dict) else {}
    if not isinstance(servers, dict):
        return {"ok": False, "error": "invalid mcp_servers.json format", "servers": []}

    rows: list[dict] = []
    for name, cfg in sorted(servers.items()):
        if not isinstance(cfg, dict):
            continue
        command = str(cfg.get("command", "") or "")
        args = cfg.get("args", []) if isinstance(cfg.get("args", []), list) else []
        cwd = str(cfg.get("cwd", "") or "")
        env = cfg.get("env", {}) if isinstance(cfg.get("env", {}), dict) else {}

        cmd_ok = False
        cmd_path = ""
        if command:
            if command.startswith("/"):
                cmd_path = command
                cmd_ok = Path(command).exists()
            else:
                resolved = shutil.which(command) or ""
                cmd_path = resolved or command
                cmd_ok = bool(resolved)

        arg_paths_missing: list[str] = []
        for a in args:
            s = str(a)
            if s.startswith("/") and not Path(s).exists():
                arg_paths_missing.append(s)

        rows.append(
            {
                "name": name,
                "command": command,
                "command_resolved": cmd_path,
                "command_exists": cmd_ok,
                "cwd": cwd,
                "cwd_exists": bool(cwd and Path(cwd).exists()),
                "args_count": len(args),
                "arg_paths_missing": arg_paths_missing[:10],
                # Never include env values; only key names.
                "env_keys": sorted([str(k) for k in env.keys()])[:50],
            }
        )

    ok = all(r.get("command_exists") and r.get("cwd_exists") for r in rows) if rows else True
    return {"ok": ok, "error": "" if ok else "one or more mcp servers look misconfigured", "servers": rows}


def collect_digest(
    *,
    network: bool,
    repos: list[Path],
    pi_host: str,
    check_pi: bool,
    mcp_config: Path,
) -> dict:
    integrations = _check_integrations(network=network)
    git = _check_git(repos)
    tailscale = _check_tailscale()
    adb = _check_adb()
    pi = _check_pi_ssh(pi_host, enabled=(network and check_pi))
    disk = _check_disk()
    launchagents = _check_launchagents()
    mcp = _check_mcp_servers(mcp_config)

    problems: list[str] = []
    if tailscale.get("ok") and int(tailscale.get("peer_count", 0) or 0) == 0:
        problems.append("tailscale: no peers visible (likely wrong tailnet/account or other nodes offline)")
    if not adb.get("ok"):
        problems.append("adb: not available (Quest/Shield checks limited)")
    if network and check_pi and not pi.get("ok"):
        problems.append(f"pi ssh: {pi_host} unreachable")
    if not mcp.get("ok"):
        problems.append("mcp servers: at least one misconfigured")
    if not git.get("ok"):
        problems.append("git: status failed for one or more repos")

    # Integrations being "unavailable" means missing keys; that's actionable.
    calls = integrations.get("calls", {}) if isinstance(integrations.get("calls", {}), dict) else {}
    missing = [k for k, v in calls.items() if isinstance(v, dict) and not v.get("available")]
    if missing:
        problems.append("missing integration creds: " + ", ".join(sorted(missing)))

    return {
        "ok": len(problems) == 0,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "integrations": integrations,
        "git": git,
        "tailscale": tailscale,
        "adb": adb,
        "pi": pi,
        "disk": disk,
        "launchagents": launchagents,
        "mcp": mcp,
        "problems": problems,
    }


def render_markdown(digest: dict) -> str:
    ts = str(digest.get("timestamp_utc", "") or "")
    ok = bool(digest.get("ok"))
    problems = digest.get("problems", []) if isinstance(digest.get("problems", []), list) else []

    lines: list[str] = []
    lines.append(f"# Ops Digest ({ts})")
    lines.append("")
    lines.append(f"- overall_ok: {ok}")
    lines.append(f"- problems: {len(problems)}")
    for p in problems[:50]:
        lines.append(f"  - {p}")
    lines.append("")

    tailscale = digest.get("tailscale", {}) if isinstance(digest.get("tailscale", {}), dict) else {}
    lines.append("## Tailscale")
    lines.append(f"- ok: {tailscale.get('ok')}")
    lines.append(f"- self: {tailscale.get('self_host')} ({', '.join(tailscale.get('self_ips', []) or [])})")
    lines.append(f"- peers: {tailscale.get('peer_count')}")
    warn = str(tailscale.get("warning", "") or "").strip()
    if warn:
        lines.append(f"- warning: {warn}")
    lines.append("")

    adb = digest.get("adb", {}) if isinstance(digest.get("adb", {}), dict) else {}
    lines.append("## ADB")
    lines.append(f"- ok: {adb.get('ok')}")
    if adb.get("ok"):
        devices = adb.get("devices", []) if isinstance(adb.get("devices", []), list) else []
        lines.append(f"- devices: {len(devices)}")
        for d in devices[:20]:
            lines.append(f"  - {d.get('serial')} {d.get('state')} {d.get('meta', {})}")
    else:
        lines.append(f"- error: {adb.get('error')}")
    lines.append("")

    pi = digest.get("pi", {}) if isinstance(digest.get("pi", {}), dict) else {}
    lines.append("## Pi SSH")
    lines.append(f"- ok: {pi.get('ok')}")
    if pi.get("skipped"):
        lines.append("- skipped: true")
    if pi.get("error"):
        lines.append(f"- error: {pi.get('error')}")
    if pi.get("stdout"):
        lines.append(f"- stdout: {pi.get('stdout')}")
    lines.append("")

    integrations = digest.get("integrations", {}) if isinstance(digest.get("integrations", {}), dict) else {}
    calls = integrations.get("calls", {}) if isinstance(integrations.get("calls", {}), dict) else {}
    lines.append("## Integrations")
    for name in ["notion", "linear", "sentry", "figma"]:
        item = calls.get(name, {}) if isinstance(calls.get(name, {}), dict) else {}
        lines.append(f"- {name}: available={item.get('available')} detail={item.get('detail')}")
        # If live call exists, include status only (not full data payload).
        for k in ["me", "viewer"]:
            if k in item and isinstance(item.get(k), dict):
                r = item.get(k) or {}
                lines.append(f"  - {k}: ok={r.get('ok')} status={r.get('status')} error={_clip(str(r.get('error','') or ''), 200)}")
    lines.append("")

    git = digest.get("git", {}) if isinstance(digest.get("git", {}), dict) else {}
    repos = git.get("repos", []) if isinstance(git.get("repos", []), list) else []
    lines.append("## Git")
    lines.append(f"- ok: {git.get('ok')}")
    for r in repos[:50]:
        lines.append(
            f"- {r.get('path')}: branch={r.get('branch')} dirty={r.get('dirty')} ahead={r.get('ahead')} behind={r.get('behind')}"
        )
        head = str(r.get("head", "") or "").strip()
        if head:
            lines.append(f"  - head: {head}")
        if r.get("error"):
            lines.append(f"  - error: {r.get('error')}")
    lines.append("")

    disk = digest.get("disk", {}) if isinstance(digest.get("disk", {}), dict) else {}
    lines.append("## Disk")
    lines.append(f"- ok: {disk.get('ok')}")
    df = str(disk.get("df", "") or "").strip()
    if df:
        lines.append("```")
        lines.append(df)
        lines.append("```")
    du = str(disk.get("du_top20", "") or "").strip()
    if du:
        lines.append("```")
        lines.append(du)
        lines.append("```")
    if disk.get("du_error"):
        lines.append(f"- du_error: {disk.get('du_error')}")
    lines.append("")

    la = digest.get("launchagents", {}) if isinstance(digest.get("launchagents", {}), dict) else {}
    lines.append("## LaunchAgents")
    lines.append(f"- plist_count: {la.get('plist_count')}")
    for p in (la.get("plists_sample", []) or [])[:40]:
        lines.append(f"  - {p}")
    if la.get("loaded_matches"):
        lines.append("- loaded_matches:")
        for ln in (la.get("loaded_matches", []) or [])[:80]:
            lines.append(f"  - {ln}")
    if la.get("error"):
        lines.append(f"- error: {la.get('error')}")
    lines.append("")

    mcp = digest.get("mcp", {}) if isinstance(digest.get("mcp", {}), dict) else {}
    lines.append("## MCP Servers")
    lines.append(f"- ok: {mcp.get('ok')}")
    if mcp.get("error"):
        lines.append(f"- error: {mcp.get('error')}")
    for s in (mcp.get("servers", []) or [])[:60]:
        lines.append(
            f"- {s.get('name')}: cmd_exists={s.get('command_exists')} cwd_exists={s.get('cwd_exists')} args={s.get('args_count')}"
        )
        missing = s.get("arg_paths_missing", []) or []
        if missing:
            lines.append(f"  - arg_paths_missing: {', '.join(missing)}")
        env_keys = s.get("env_keys", []) or []
        if env_keys:
            lines.append(f"  - env_keys: {', '.join(env_keys[:25])}")

    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_outputs(out_dir: Path, digest: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    md_path = out_dir / f"ops-digest_{stamp}.md"
    json_path = out_dir / f"ops-digest_{stamp}.json"
    md_latest = out_dir / "ops-digest_latest.md"
    json_latest = out_dir / "ops-digest_latest.json"

    md = render_markdown(digest)
    md_path.write_text(md)
    json_path.write_text(json.dumps(digest, indent=2))
    md_latest.write_text(md)
    json_latest.write_text(json.dumps(digest, indent=2))

    return {
        "md": str(md_path),
        "json": str(json_path),
        "md_latest": str(md_latest),
        "json_latest": str(json_latest),
    }


def _maybe_publish_notion(digest_md: str, title: str, enabled: bool, parent_page_id: str) -> dict:
    if not enabled:
        return {"ok": True, "skipped": True}
    res = notion_api.create_page(parent_page_id=parent_page_id, title=title, content=digest_md)
    return {"ok": bool(res.get("ok")), "skipped": False, "raw": {"ok": res.get("ok"), "status": res.get("status"), "error": res.get("error", "")}}


def _maybe_create_linear_issue(digest_md: str, title: str, enabled: bool, only_if_problems: bool, digest: dict) -> dict:
    if not enabled:
        return {"ok": True, "skipped": True}
    problems = digest.get("problems", []) if isinstance(digest.get("problems", []), list) else []
    if only_if_problems and not problems:
        return {"ok": True, "skipped": True, "reason": "no problems detected"}

    # Keep description reasonably sized.
    desc_lines = []
    if problems:
        desc_lines.append("Problems:")
        for p in problems[:80]:
            desc_lines.append(f"- {p}")
        desc_lines.append("")
    desc_lines.append("Full digest:")
    desc_lines.append("")
    desc_lines.append(_clip(digest_md, 9000))

    res = linear_api.create_issue(title=title, description="\n".join(desc_lines))
    return {"ok": bool(res.get("ok")), "skipped": False, "raw": {"ok": res.get("ok"), "status": res.get("status"), "error": res.get("error", "")}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an ops digest for the automation stack.")
    parser.add_argument("--out-dir", default=str(_DEFAULT_OUT_DIR), help="Output directory for reports.")
    parser.add_argument("--no-network", action="store_true", help="Disable network calls (integrations + ssh).")
    parser.add_argument("--repo", action="append", default=[], help="Additional repo path to include (repeatable).")
    parser.add_argument("--publish-notion", action="store_true", help="Publish digest to Notion (creates a page).")
    parser.add_argument("--notion-parent-page-id", default=os.getenv("NOTION_PARENT_PAGE_ID", ""), help="Notion parent page id.")
    parser.add_argument("--linear-issue", action="store_true", help="Create a Linear issue when problems are detected.")
    parser.add_argument("--linear-issue-always", action="store_true", help="Create a Linear issue even if no problems.")
    parser.add_argument("--pi-host", default="pi@100.100.32.58", help="Pi SSH target (user@host).")
    parser.add_argument("--check-pi", action="store_true", help="Attempt Pi SSH check (requires network).")
    parser.add_argument("--mcp-config", default=str(_DEFAULT_MCP_CONFIG), help="Path to mcp_servers.json.")
    args = parser.parse_args()

    # Mirror project behavior: load repo .env + shared ~/.env (but never print secrets).
    load_dotenv(_PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env")

    repos = _discover_repos(extra_repos=list(args.repo or []))
    digest = collect_digest(
        network=(not args.no_network),
        repos=repos,
        pi_host=str(args.pi_host),
        check_pi=bool(args.check_pi),
        mcp_config=Path(args.mcp_config).expanduser(),
    )

    out_dir = Path(args.out_dir).expanduser()
    written = _write_outputs(out_dir, digest)

    title = f"Ops Digest {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    md = (Path(written["md"]).read_text() if written.get("md") else render_markdown(digest))

    notion_publish = _maybe_publish_notion(md, title, enabled=bool(args.publish_notion), parent_page_id=str(args.notion_parent_page_id))
    linear_issue = _maybe_create_linear_issue(
        md,
        title=f"{title} (Problems)",
        enabled=bool(args.linear_issue),
        only_if_problems=not bool(args.linear_issue_always),
        digest=digest,
    )

    # Print only paths + non-sensitive status.
    print(json.dumps({"ok": digest.get("ok"), "written": written, "notion": notion_publish, "linear": linear_issue}, indent=2))
    return 0 if digest.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
