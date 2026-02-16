#!/usr/bin/env python3
"""Environment enablement checks for ios-agent-runner.

This is a *read-only* diagnostic that helps unlock the "power switches":
1) macOS UI automation permissions (Accessibility/Automation)
2) GitHub auth/scopes for pushing workflows
3) integration tokens (Notion/Linear/Sentry/Figma/OpenAI/Anthropic)
4) device connectivity tooling (idb/adb/ssh)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Mirror the project's usual env loading behavior without ever printing secrets.
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(Path.home() / ".env")


def _run(cmd: list[str], timeout: int = 10) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_PROJECT_ROOT),
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
    except Exception as exc:
        return {"ok": False, "error": str(exc), "returncode": -1, "stdout": "", "stderr": ""}


def _check_env(keys: list[str]) -> dict[str, bool]:
    return {k: bool(os.getenv(k)) for k in keys}


def _venv_python() -> Path:
    return _PROJECT_ROOT / ".venv" / "bin" / "python"


def _venv_pip() -> Path:
    return _PROJECT_ROOT / ".venv" / "bin" / "pip"


def _check_osascript_permissions() -> dict:
    # Non-destructive: asks System Events for a boolean setting.
    return _run(["osascript", "-e", 'tell application "System Events" to get UI elements enabled'])


def _check_git_origin() -> dict:
    if not shutil.which("git"):
        return {"ok": False, "error": "git not found on PATH"}
    res = _run(["git", "remote", "get-url", "origin"])
    url = res.get("stdout", "") if isinstance(res, dict) else ""
    return {
        "ok": bool(url),
        "origin_url": url,
        "is_ssh": url.startswith("git@github.com:"),
        "raw": res,
    }


def _check_gh_auth() -> dict:
    gh = shutil.which("gh")
    if not gh:
        return {"ok": False, "error": "gh not found on PATH"}

    # Use `gh api -i` to retrieve token scopes from response headers without printing the token.
    res = _run([gh, "api", "-i", "user"], timeout=10)
    scopes = ""
    accepted_scopes = ""
    out = (res.get("stdout", "") or "").strip()
    for line in out.splitlines():
        lower = line.lower()
        if lower.startswith("x-oauth-scopes:"):
            scopes = line.split(":", 1)[1].strip()
        if lower.startswith("x-accepted-oauth-scopes:"):
            accepted_scopes = line.split(":", 1)[1].strip()

    return {
        "ok": bool(res.get("ok")),
        "scopes": scopes,
        "accepted_scopes": accepted_scopes,
        "has_workflow_scope": ("workflow" in scopes.split(",") if scopes else False),
        "error": res.get("stderr", "") if not res.get("ok") else "",
    }


def _check_idb() -> dict:
    project_idb = _PROJECT_ROOT / ".venv" / "bin" / "idb"
    system_idb = shutil.which("idb") or ""
    return {
        "ok": project_idb.exists() or bool(system_idb),
        "project_venv_idb": str(project_idb) if project_idb.exists() else "",
        "system_idb": system_idb,
    }


def _check_mcp_importable_in_venv() -> dict:
    vpy = _venv_python()
    if not vpy.exists():
        return {"ok": False, "error": "no .venv python found"}
    res = _run([str(vpy), "-c", "import mcp; print('mcp ok')"], timeout=10)
    return {"ok": bool(res.get("ok")), "raw": res}


def _check_adb_devices() -> dict:
    adb = shutil.which("adb")
    if not adb:
        return {"ok": False, "error": "adb not found on PATH"}
    # Read-only.
    res = _run([adb, "devices", "-l"], timeout=10)
    return {"ok": bool(res.get("ok")), "raw": res}


def collect_checks() -> dict:
    checks: dict = {
        "project_root": str(_PROJECT_ROOT),
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        "venv": {
            "python": str(_venv_python()),
            "pip": str(_venv_pip()),
            "exists": _venv_python().exists(),
        },
        "keys": _check_env(
            [
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "NOTION_TOKEN",
                "LINEAR_API_KEY",
                "SENTRY_AUTH_TOKEN",
                "FIGMA_TOKEN",
            ]
        ),
        "macos_automation": {
            "osascript_system_events": _check_osascript_permissions(),
            "note": "If this fails, enable Accessibility + Automation permissions for the app running this.",
        },
        "git": {"origin": _check_git_origin(), "gh_auth": _check_gh_auth()},
        "tools": {
            "idb": _check_idb(),
            "mcp_importable_in_venv": _check_mcp_importable_in_venv(),
            "adb_devices": _check_adb_devices(),
        },
        "hints": {
            "enable_accessibility": "System Settings -> Privacy & Security -> Accessibility: enable for Terminal/Codex host app",
            "enable_automation": "System Settings -> Privacy & Security -> Automation: allow controlling System Events/Simulator",
            "github_workflow_scope": "If pushing workflows over HTTPS, ensure token has workflow scope (SSH bypasses this).",
        },
    }

    # Basic overall status:
    checks["ok"] = True
    problems: list[str] = []

    if not checks["venv"]["exists"]:
        checks["ok"] = False
        problems.append("missing .venv")

    if not checks["tools"]["idb"]["ok"]:
        checks["ok"] = False
        problems.append("idb not found (install fb-idb in venv or via brew)")

    if not checks["macos_automation"]["osascript_system_events"].get("ok"):
        problems.append("macOS UI scripting permissions likely missing (Accessibility/Automation)")

    if not checks["git"]["origin"].get("is_ssh"):
        problems.append("origin remote is not SSH (workflow pushes may be blocked over HTTPS)")

    missing_keys = [k for k, present in checks["keys"].items() if not present]
    checks["missing_keys"] = missing_keys
    if missing_keys:
        problems.append("missing integration keys: " + ", ".join(missing_keys))

    checks["problems"] = problems
    return checks


def main() -> int:
    payload = collect_checks()
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
