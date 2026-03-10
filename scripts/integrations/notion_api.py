"""Notion integration (minimal).

Env:
  NOTION_TOKEN (required)
  NOTION_PARENT_PAGE_ID (optional default for create_page)
"""

from __future__ import annotations

import os
import re

from scripts.integrations.http import request_json

_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

_MAX_BLOCKS_PER_REQUEST = 100
_MAX_TEXT_LEN = 1900
_MAX_RICH_TEXT_CHUNKS = 80


def _token() -> str:
    return os.getenv("NOTION_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
    }


def _rich_text(text: str) -> list[dict]:
    text = text or ""
    if not text:
        return []

    chunks = [text[i : i + _MAX_TEXT_LEN] for i in range(0, len(text), _MAX_TEXT_LEN)]
    if len(chunks) > _MAX_RICH_TEXT_CHUNKS:
        chunks = chunks[:_MAX_RICH_TEXT_CHUNKS]
        chunks[-1] = chunks[-1] + "\n... <clipped>"

    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks]


def _block(block_type: str, text: str = "", **kwargs) -> dict:
    if block_type == "divider":
        return {"object": "block", "type": "divider", "divider": {}}
    if block_type == "code":
        language = str(kwargs.get("language") or "plain text")
        return {
            "object": "block",
            "type": "code",
            "code": {"rich_text": _rich_text(text), "language": language},
        }
    if block_type in {"heading_1", "heading_2", "heading_3", "paragraph", "quote"}:
        return {"object": "block", "type": block_type, block_type: {"rich_text": _rich_text(text)}}
    if block_type in {"bulleted_list_item", "numbered_list_item"}:
        return {"object": "block", "type": block_type, block_type: {"rich_text": _rich_text(text)}}
    if block_type == "to_do":
        checked = bool(kwargs.get("checked", False))
        return {
            "object": "block",
            "type": "to_do",
            "to_do": {"rich_text": _rich_text(text), "checked": checked},
        }
    # Fallback to paragraph.
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def blocks_from_markdown(md: str) -> list[dict]:
    """Convert a small markdown subset into Notion blocks.

    Supported:
      - # / ## / ### headings
      - - / * bullets
      - 1. numbered list items
      - > quote
      - --- divider
      - ``` fenced code blocks (language optional)
    """
    md = md or ""
    lines = md.splitlines()
    out: list[dict] = []

    in_code = False
    code_lang = "plain text"
    code_lines: list[str] = []

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            fence = stripped
            if not in_code:
                in_code = True
                code_lang = (fence[3:].strip() or "plain text").lower()
                code_lines = []
                continue
            # close
            in_code = False
            out.append(_block("code", "\n".join(code_lines).rstrip(), language=code_lang))
            code_lang = "plain text"
            code_lines = []
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            continue

        if stripped == "---":
            out.append(_block("divider"))
            continue

        if stripped.startswith("# "):
            out.append(_block("heading_1", stripped[2:].strip()))
            continue
        if stripped.startswith("## "):
            out.append(_block("heading_2", stripped[3:].strip()))
            continue
        if stripped.startswith("### "):
            out.append(_block("heading_3", stripped[4:].strip()))
            continue

        if stripped.startswith("> "):
            out.append(_block("quote", stripped[2:].strip()))
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            out.append(_block("bulleted_list_item", stripped[2:].strip()))
            continue

        m = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if m:
            out.append(_block("numbered_list_item", m.group(2).strip()))
            continue

        out.append(_block("paragraph", stripped))

    if in_code and code_lines:
        out.append(_block("code", "\n".join(code_lines).rstrip(), language=code_lang))

    return out


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


def append_blocks(block_id: str, blocks: list[dict]) -> dict:
    """Append blocks to an existing page/block (chunked to API limits)."""
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}

    block_id = (block_id or "").strip()
    if not block_id:
        return {"ok": False, "error": "block_id is required"}

    blocks = list(blocks or [])
    if not blocks:
        return {"ok": True, "status": 200, "data": {"appended": 0}, "error": ""}

    appended = 0
    for i in range(0, len(blocks), _MAX_BLOCKS_PER_REQUEST):
        batch = blocks[i : i + _MAX_BLOCKS_PER_REQUEST]
        res = request_json(
            "PATCH",
            f"{_NOTION_API}/blocks/{block_id}/children",
            headers=_headers(),
            body={"children": batch},
        )
        if not res.get("ok"):
            return {"ok": False, "status": res.get("status", 0), "data": {"appended": appended}, "error": res.get("error", "")}
        appended += len(batch)

    return {"ok": True, "status": 200, "data": {"appended": appended}, "error": ""}


def create_database(
    parent_page_id: str,
    title: str,
    properties: dict,
    is_inline: bool = True,
) -> dict:
    """Create a database under a parent page.

    Args:
        parent_page_id: The page to nest the database under.
        title: Database title shown in Notion.
        properties: Column definitions (Notion property schema format).
        is_inline: If True, database appears inline on the page.
    """
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}

    parent_page_id = (parent_page_id or "").strip()
    if not parent_page_id:
        return {"ok": False, "error": "parent_page_id is required"}

    body: dict = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "is_inline": is_inline,
        "properties": properties,
    }
    return request_json("POST", f"{_NOTION_API}/databases", headers=_headers(), body=body)


def add_database_row(database_id: str, properties: dict) -> dict:
    """Add a row (page) to a database.

    Args:
        database_id: The database to add the row to.
        properties: Row values matching the database schema.
    """
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}

    database_id = (database_id or "").strip()
    if not database_id:
        return {"ok": False, "error": "database_id is required"}

    body = {
        "parent": {"type": "database_id", "database_id": database_id},
        "properties": properties,
    }
    return request_json("POST", f"{_NOTION_API}/pages", headers=_headers(), body=body)


def query_database(database_id: str, filter_obj: dict | None = None, page_size: int = 100) -> dict:
    """Query a database with optional filter."""
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}

    database_id = (database_id or "").strip()
    if not database_id:
        return {"ok": False, "error": "database_id is required"}

    body: dict = {"page_size": min(page_size, 100)}
    if filter_obj:
        body["filter"] = filter_obj
    return request_json(
        "POST", f"{_NOTION_API}/databases/{database_id}/query",
        headers=_headers(), body=body,
    )


# --- Property builder helpers for database rows ---

def build_title_prop(text: str) -> dict:
    """Build a title property value."""
    return {"title": [{"type": "text", "text": {"content": text or ""}}]}


def build_rich_text_prop(text: str) -> dict:
    """Build a rich_text property value."""
    return {"rich_text": [{"type": "text", "text": {"content": text or ""}}]}


def build_select_prop(name: str) -> dict:
    """Build a select property value."""
    return {"select": {"name": name}}


def build_multi_select_prop(names: list[str]) -> dict:
    """Build a multi_select property value."""
    return {"multi_select": [{"name": n} for n in names]}


def build_number_prop(value: float | int | None) -> dict:
    """Build a number property value."""
    return {"number": value}


def build_date_prop(start: str, end: str | None = None) -> dict:
    """Build a date property value (ISO 8601 strings)."""
    d: dict = {"start": start}
    if end:
        d["end"] = end
    return {"date": d}


def build_checkbox_prop(checked: bool) -> dict:
    """Build a checkbox property value."""
    return {"checkbox": checked}


def build_url_prop(url: str) -> dict:
    """Build a url property value."""
    return {"url": url}


def create_page(parent_page_id: str, title: str, content: str = "") -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}

    parent_page_id = (parent_page_id or os.getenv("NOTION_PARENT_PAGE_ID", "")).strip()
    if not parent_page_id:
        return {"ok": False, "error": "parent_page_id is required (or set NOTION_PARENT_PAGE_ID)"}

    blocks = blocks_from_markdown(content or "")

    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}],
            }
        },
    }
    if blocks:
        body["children"] = blocks[:_MAX_BLOCKS_PER_REQUEST]

    created = request_json("POST", f"{_NOTION_API}/pages", headers=_headers(), body=body)
    if not created.get("ok") or not blocks:
        return created

    remaining = blocks[_MAX_BLOCKS_PER_REQUEST :]
    if not remaining:
        return created

    page = created.get("data") or {}
    page_id = (page.get("id") or "").strip()
    if not page_id:
        return created

    appended = append_blocks(page_id, remaining)
    if appended.get("ok"):
        return created

    return {
        "ok": True,
        "status": created.get("status", 200),
        "data": created.get("data"),
        "error": "",
        "append": appended,
    }
