"""Minimal HTTP JSON helper (stdlib-only).

Avoids new deps while keeping consistent error handling.
Never logs or returns auth headers.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict | list | None = None,
    timeout: int = 20,
) -> dict:
    """Perform an HTTP request and parse JSON response.

    Returns dict:
      ok: bool
      status: int
      data: any (parsed JSON) | None
      error: str
    """
    req_headers = dict(headers or {})
    data_bytes = None
    if body is not None:
        data_bytes = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            if not text.strip():
                return {"ok": True, "status": status, "data": None, "error": ""}
            try:
                return {"ok": True, "status": status, "data": json.loads(text), "error": ""}
            except json.JSONDecodeError:
                return {"ok": False, "status": status, "data": None, "error": "invalid json response"}
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        try:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
        except Exception:
            text = ""
        return {"ok": False, "status": status, "data": None, "error": text.strip() or str(exc)}
    except urllib.error.URLError as exc:
        return {"ok": False, "status": 0, "data": None, "error": str(exc.reason) if hasattr(exc, "reason") else str(exc)}
    except Exception as exc:
        return {"ok": False, "status": 0, "data": None, "error": str(exc)}

