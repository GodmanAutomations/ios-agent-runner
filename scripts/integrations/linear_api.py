"""Linear integration (minimal GraphQL).

Env:
  LINEAR_API_KEY (required)
  LINEAR_TEAM_ID (optional default for create_issue)
"""

from __future__ import annotations

import os

from scripts.integrations.http import request_json

_LINEAR_API = "https://api.linear.app/graphql"


def _token() -> str:
    return os.getenv("LINEAR_API_KEY", "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    return {
        "Authorization": token,
        "Content-Type": "application/json",
    }


def is_available() -> tuple[bool, str]:
    if not _token():
        return False, "LINEAR_API_KEY is not set"
    return True, "ok"


def _graphql(query: str, variables: dict | None = None) -> dict:
    ok, detail = is_available()
    if not ok:
        return {"ok": False, "error": detail}
    body = {"query": query, "variables": variables or {}}
    return request_json("POST", _LINEAR_API, headers=_headers(), body=body)


def viewer() -> dict:
    return _graphql("query { viewer { id name email } }")


def list_teams(limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 50))
    q = "query($n:Int!){ teams(first:$n){ nodes { id name key } } }"
    return _graphql(q, {"n": limit})


def create_issue(title: str, description: str = "", team_id: str = "") -> dict:
    team_id = (team_id or os.getenv("LINEAR_TEAM_ID", "")).strip()
    if not team_id:
        teams = list_teams(limit=20)
        if teams.get("ok") and isinstance(teams.get("data"), dict):
            nodes = (((teams.get("data") or {}).get("data") or {}).get("teams") or {}).get("nodes") or []
            if isinstance(nodes, list) and len(nodes) == 1:
                team_id = nodes[0].get("id", "")
        if not team_id:
            return {"ok": False, "error": "team_id is required (or set LINEAR_TEAM_ID) and multiple teams exist"}

    q = (
        "mutation($input: IssueCreateInput!){ issueCreate(input:$input) { "
        "success issue { id title url } } }"
    )
    return _graphql(
        q,
        {
            "input": {
                "title": title,
                "description": description or "",
                "teamId": team_id,
            }
        },
    )

