"""Notion integration (minimal).

Env:
  NOTION_TOKEN (required)
  NOTION_PARENT_PAGE_ID (optional default for create_page)
"""

from __future__ import annotations

import os

from scripts.integrations.http import request_json

_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


def _token() -> str:
    return os.getenv("NOTION_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
    }


def is_available() -> tuple[bool, str]:
    if not _token():
        return False, "NOTION_TOKEN is not set"
    return True, "ok"


def me() -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    res = request_json("GET", f"{_NOTION_API}/users/me", headers=_headers())
    return res


def search(query: str, limit: int = 10) -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    body = {
        "query": query,
        "page_size": max(1, min(int(limit), 25)),
    }
    return request_json("POST", f"{_NOTION_API}/search", headers=_headers(), body=body)


def create_page(parent_page_id: str, title: str, content: str = "") -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}

    parent_page_id = (parent_page_id or os.getenv("NOTION_PARENT_PAGE_ID", "")).strip()
    if not parent_page_id:
        return {"ok": False, "error": "parent_page_id is required (or set NOTION_PARENT_PAGE_ID)"}

    blocks = []
    for line in (content or "").splitlines():
        line = line.strip()
        if not line:
            continue
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}],
                },
            }
        )

    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}],
            }
        },
    }
    if blocks:
        body["children"] = blocks[:100]

    return request_json("POST", f"{_NOTION_API}/pages", headers=_headers(), body=body)

