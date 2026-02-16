"""HTML report generator for persisted runs."""

import html
import json
import os
from pathlib import Path

from scripts import run_state


def _relpath(from_dir: Path, target: str) -> str:
    if not target:
        return ""
    try:
        return os.path.relpath(target, start=str(from_dir))
    except Exception:
        return target


def render_run_report(run_id: str) -> str | None:
    """Render an HTML dashboard for a run and return the output path."""
    replay = run_state.replay_run(run_id)
    if "error" in replay:
        return None

    state = replay["state"]
    events = replay.get("events", [])

    run_dir = Path(run_state.run_paths(run_id)["run_dir"])
    out_path = run_dir / "report.html"
    run_dir.mkdir(parents=True, exist_ok=True)

    title = f"iOS Agent Run Report: {run_id}"
    goal = html.escape(str(state.get("goal", "")))
    bundle = html.escape(str(state.get("bundle_id", "")))
    status = html.escape(str(state.get("status", "")))
    summary = html.escape(str(state.get("summary", "")))

    metrics = state.get("metrics", {}) if isinstance(state.get("metrics", {}), dict) else {}
    history = state.get("history", []) if isinstance(state.get("history", []), list) else []

    def row_kv(k: str, v: str) -> str:
        return f"<tr><td class='k'>{html.escape(k)}</td><td class='v'>{html.escape(v)}</td></tr>"

    meta_rows = "\n".join(
        [
            row_kv("run_id", str(run_id)),
            row_kv("status", str(state.get("status", ""))),
            row_kv("created_at", str(state.get("created_at", ""))),
            row_kv("updated_at", str(state.get("updated_at", ""))),
            row_kv("completed_at", str(state.get("completed_at", ""))),
            row_kv("bundle_id", str(state.get("bundle_id", ""))),
            row_kv("max_steps", str(state.get("max_steps", ""))),
            row_kv("safe_mode", str(state.get("safe_mode", ""))),
        ]
    )

    metrics_rows = "\n".join(row_kv(k, str(v)) for k, v in sorted(metrics.items()))

    steps_html: list[str] = []
    for step in history:
        if not isinstance(step, dict):
            continue
        n = step.get("step", "")
        tool = html.escape(str(step.get("tool", "")))
        result = html.escape(str(step.get("result", "")))
        params = step.get("params", {}) if isinstance(step.get("params", {}), dict) else {}
        params_json = html.escape(json.dumps(params, indent=2))

        screenshot_path = str(step.get("screenshot_path", "") or "")
        tree_path = str(step.get("tree_path", "") or "")

        ss_rel = _relpath(run_dir, screenshot_path) if screenshot_path else ""
        tree_rel = _relpath(run_dir, tree_path) if tree_path else ""

        links = []
        if screenshot_path and os.path.exists(screenshot_path):
            links.append(f"<a href='{html.escape(ss_rel)}' target='_blank'>screenshot</a>")
        if tree_path and os.path.exists(tree_path):
            links.append(f"<a href='{html.escape(tree_rel)}' target='_blank'>tree</a>")

        thumb = ""
        if screenshot_path and os.path.exists(screenshot_path):
            thumb = f"<img class='thumb' src='{html.escape(ss_rel)}' loading='lazy'/>"

        links_html = " | ".join(links) if links else ""

        steps_html.append(
            "\n".join(
                [
                    "<div class='step'>",
                    f"  <div class='step-h'>Step {html.escape(str(n))}: <span class='tool'>{tool}</span></div>",
                    f"  <div class='result'>{result}</div>",
                    f"  <div class='links'>{links_html}</div>",
                    f"  {thumb}",
                    "  <details><summary>params</summary>",
                    f"    <pre>{params_json}</pre>",
                    "  </details>",
                    "</div>",
                ]
            )
        )

    events_path = run_state.run_paths(run_id)["events_path"]
    events_rel = _relpath(run_dir, events_path) if events_path else ""

    events_preview = html.escape(json.dumps(events[-30:], indent=2)) if isinstance(events, list) else "[]"

    doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #0b0d10;
      --panel: #10151b;
      --border: #233041;
      --text: #e7eef7;
      --muted: #a7b6c7;
      --accent: #59c2ff;
      --bad: #ff6b6b;
      --ok: #4cd4a0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }}
    body {{ background: var(--bg); color: var(--text); margin: 0; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 20px; }}
    .sub {{ color: var(--muted); margin-bottom: 18px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td {{ padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); vertical-align: top; }}
    td.k {{ color: var(--muted); width: 160px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .status {{ font-weight: 700; }}
    .status.ok {{ color: var(--ok); }}
    .status.bad {{ color: var(--bad); }}
    .steps {{ margin-top: 16px; }}
    .step {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 12px; margin-bottom: 12px; }}
    .step-h {{ font-weight: 700; }}
    .tool {{ color: var(--accent); }}
    .result {{ margin-top: 8px; color: var(--text); }}
    .links {{ margin-top: 8px; color: var(--muted); }}
    pre {{ background: rgba(0,0,0,0.35); padding: 10px; border-radius: 10px; overflow: auto; }}
    .thumb {{ width: 260px; max-width: 100%; border-radius: 10px; margin-top: 10px; border: 1px solid rgba(255,255,255,0.08); }}
    details summary {{ cursor: pointer; color: var(--muted); margin-top: 8px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <div class="sub">
    <span class="status {'ok' if status == 'completed' else 'bad'}">{status}</span>
    &nbsp; | &nbsp; {bundle}
  </div>

  <div class="card" style="margin-bottom:16px;">
    <div><b>Goal</b></div>
    <div style="color:var(--muted); margin-top:6px;">{goal}</div>
    <div style="margin-top:10px;"><b>Summary</b></div>
    <div style="color:var(--muted); margin-top:6px;">{summary}</div>
  </div>

  <div class="grid">
    <div class="card">
      <div style="font-weight:700; margin-bottom:8px;">Metadata</div>
      <table>{meta_rows}</table>
    </div>
    <div class="card">
      <div style="font-weight:700; margin-bottom:8px;">Metrics</div>
      <table>{metrics_rows}</table>
      <div style="margin-top:10px; color:var(--muted);">
        <a href="{html.escape(events_rel)}" target="_blank">events.jsonl</a>
      </div>
    </div>
  </div>

  <div class="steps">
    <h2 style="font-size:16px; margin: 18px 0 10px;">Steps ({len(history)})</h2>
    {''.join(steps_html) if steps_html else '<div class=\"card\">No history recorded.</div>'}
  </div>

  <div class="card" style="margin-top: 16px;">
    <div style="font-weight:700; margin-bottom:8px;">Recent Events (last 30)</div>
    <pre>{events_preview}</pre>
  </div>
</body>
</html>
"""

    out_path.write_text(doc)
    return str(out_path)
