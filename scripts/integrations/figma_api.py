"""Figma integration (minimal REST).

Env:
  FIGMA_TOKEN (required)
"""

from __future__ import annotations

import os
import urllib.parse

from scripts.integrations.http import request_json

_FIGMA_API = "https://api.figma.com/v1"


def _token() -> str:
    return os.getenv("FIGMA_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    return {"X-Figma-Token": token}


def is_available() -> tuple[bool, str]:
    if not _token():
        return False, "FIGMA_TOKEN is not set"
    return True, "ok"


def me() -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    return request_json("GET", f"{_FIGMA_API}/me", headers=_headers())


def file_meta(file_key: str) -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    file_key = file_key.strip()
    if not file_key:
        return {"ok": False, "error": "file_key is required"}

    res = request_json("GET", f"{_FIGMA_API}/files/{file_key}", headers=_headers())
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        return res

    data = res["data"]
    # Drop the giant document by default; keep only metadata-ish fields.
    slim = {
        "name": data.get("name", ""),
        "lastModified": data.get("lastModified", ""),
        "version": data.get("version", ""),
        "role": data.get("role", ""),
        "editorType": data.get("editorType", ""),
        "thumbnailUrl": data.get("thumbnailUrl", ""),
        "linkAccess": data.get("linkAccess", ""),
    }
    return {"ok": True, "status": res.get("status", 200), "data": slim, "error": ""}


def nodes(file_key: str, node_ids: list[str]) -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    file_key = file_key.strip()
    if not file_key:
        return {"ok": False, "error": "file_key is required"}
    ids = [s.strip() for s in (node_ids or []) if str(s).strip()]
    if not ids:
        return {"ok": False, "error": "node_ids is required"}
    params = urllib.parse.urlencode({"ids": ",".join(ids)})
    return request_json("GET", f"{_FIGMA_API}/files/{file_key}/nodes?{params}", headers=_headers())

