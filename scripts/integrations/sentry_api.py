"""Sentry integration (minimal REST).

Env:
  SENTRY_AUTH_TOKEN (required)
"""

from __future__ import annotations

import os
import urllib.parse

from scripts.integrations.http import request_json

_SENTRY_API = "https://sentry.io/api/0"


def _token() -> str:
    return os.getenv("SENTRY_AUTH_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    return {"Authorization": f"Bearer {token}"}


def is_available() -> tuple[bool, str]:
    if not _token():
        return False, "SENTRY_AUTH_TOKEN is not set"
    return True, "ok"


def me() -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    return request_json("GET", f"{_SENTRY_API}/", headers=_headers())


def list_orgs() -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    return request_json("GET", f"{_SENTRY_API}/organizations/", headers=_headers())


def list_projects(org_slug: str) -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    org_slug = org_slug.strip()
    if not org_slug:
        return {"ok": False, "error": "org_slug is required"}
    return request_json("GET", f"{_SENTRY_API}/organizations/{org_slug}/projects/", headers=_headers())


def list_issues(org_slug: str, project_slug: str = "", query: str = "", limit: int = 20) -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    org_slug = org_slug.strip()
    if not org_slug:
        return {"ok": False, "error": "org_slug is required"}

    limit = max(1, min(int(limit), 50))
    params = {"limit": str(limit)}
    if query:
        params["query"] = query

    if project_slug:
        path = f"{_SENTRY_API}/projects/{org_slug}/{project_slug.strip()}/issues/"
    else:
        path = f"{_SENTRY_API}/organizations/{org_slug}/issues/"

    url = path + "?" + urllib.parse.urlencode(params)
    return request_json("GET", url, headers=_headers())

