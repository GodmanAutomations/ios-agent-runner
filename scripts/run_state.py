"""Run-state persistence for pause/resume/replay and telemetry artifacts."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RUNS_ROOT = _PROJECT_ROOT / "_artifacts" / "runs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dir(run_id: str) -> Path:
    return _RUNS_ROOT / run_id


def _state_path(run_id: str) -> Path:
    return _run_dir(run_id) / "state.json"


def _events_path(run_id: str) -> Path:
    return _run_dir(run_id) / "events.jsonl"


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"run_{stamp}_{suffix}"


def create_run(
    goal: str,
    bundle_id: str,
    udid: str,
    max_steps: int,
    safe_mode: bool,
    run_id: str | None = None,
) -> dict:
    """Create a new run-state document and persist it."""
    resolved_run_id = run_id or new_run_id()
    created_at = _now_iso()
    state = {
        "run_id": resolved_run_id,
        "goal": goal,
        "bundle_id": bundle_id,
        "udid": udid,
        "max_steps": max_steps,
        "safe_mode": safe_mode,
        "status": "running",
        "summary": "",
        "history": [],
        "created_at": created_at,
        "updated_at": created_at,
        "completed_at": "",
        "last_step": 0,
        "metrics": {
            "model_calls": 0,
            "model_retries": 0,
            "model_failures": 0,
            "policy_blocks": 0,
            "action_failures": 0,
            "recoveries": 0,
        },
    }
    save_state(state)
    append_event(resolved_run_id, {"type": "run_started", "timestamp": created_at})
    return state


def load_state(run_id: str) -> dict | None:
    """Load state.json for a run, returning None if absent/corrupt."""
    path = _state_path(run_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def save_state(state: dict) -> None:
    """Persist state.json atomically enough for local single-process writes."""
    run_id = state["run_id"]
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now_iso()
    _state_path(run_id).write_text(json.dumps(state, indent=2))


def append_event(run_id: str, event: dict) -> None:
    """Append a telemetry event to events.jsonl."""
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("timestamp", _now_iso())
    with _events_path(run_id).open("a") as f:
        f.write(json.dumps(payload) + "\n")


def append_history(state: dict, step_record: dict) -> None:
    """Append a step record to history and persist state."""
    history = state.setdefault("history", [])
    history.append(step_record)
    state["last_step"] = max(int(state.get("last_step", 0)), int(step_record.get("step", 0)))
    save_state(state)


def increment_metric(state: dict, metric: str, amount: int = 1) -> None:
    """Increment a run metric counter and persist state."""
    metrics = state.setdefault("metrics", {})
    metrics[metric] = int(metrics.get(metric, 0)) + amount
    save_state(state)


def finalize_run(state: dict, status: str, summary: str, steps: int) -> None:
    """Finalize run state at completion/failure/pause."""
    state["status"] = status
    state["summary"] = summary
    state["last_step"] = steps
    state["completed_at"] = _now_iso()
    save_state(state)
    append_event(
        state["run_id"],
        {
            "type": "run_finished",
            "status": status,
            "summary": summary,
            "steps": steps,
        },
    )


def list_runs(limit: int = 20) -> list[dict]:
    """Return recent run summaries sorted by created time descending."""
    if not _RUNS_ROOT.exists():
        return []

    items: list[dict] = []
    for entry in _RUNS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        state_path = entry / "state.json"
        if not state_path.exists():
            continue
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            continue
        items.append(
            {
                "run_id": state.get("run_id", entry.name),
                "goal": state.get("goal", ""),
                "status": state.get("status", "unknown"),
                "last_step": state.get("last_step", 0),
                "created_at": state.get("created_at", ""),
                "updated_at": state.get("updated_at", ""),
                "summary": state.get("summary", ""),
            }
        )

    items.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    return items[: max(1, limit)]


def replay_run(run_id: str) -> dict:
    """Load state + all events for deterministic replay/audit."""
    state = load_state(run_id)
    if state is None:
        return {"error": f"run '{run_id}' not found"}

    events: list[dict] = []
    events_path = _events_path(run_id)
    if events_path.exists():
        for line in events_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return {
        "run_id": run_id,
        "state": state,
        "events": events,
    }


def run_paths(run_id: str) -> dict:
    """Return canonical artifact paths for a run."""
    return {
        "run_dir": str(_run_dir(run_id)),
        "state_path": str(_state_path(run_id)),
        "events_path": str(_events_path(run_id)),
    }
