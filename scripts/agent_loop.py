"""agent_loop.py - Autonomous LLM agent loop for iOS simulator automation.

Give it a goal in plain English and it reads the screen, reasons, acts,
reads again, and loops until done (or gives up).

Uses Anthropic's native tool_use API for structured actions (no JSON parsing).
Falls back to vision (screenshot) when the accessibility tree is empty.
"""

import base64
import hashlib
import json
import os
import sys
import time

import anthropic

from dataclasses import asdict, dataclass

from scripts import idbwrap, intel, run_report, run_state, screen_mapper, screenshot
from scripts.safe_mode import SafeModePolicy

MODEL = "claude-sonnet-4-5-20250929"

SYSTEM_PROMPT = """\
You are an iOS automation agent controlling a real iPhone simulator.

You see the screen via an accessibility tree (provided as JSON).
Your job: accomplish the user's goal by calling exactly one tool per turn.

Guidelines:
- Use "tap" with the visible label text — fuzzy matching is handled for you.
- After typing a URL or search query, use press_key with RETURN to submit it.
- After typing, the keyboard may cover the screen; scroll or tap elsewhere if needed.
- Call "done" as soon as the goal is achieved. Call "fail" if truly stuck after multiple attempts.
- If the accessibility tree is empty, you may receive a screenshot instead — use visual cues to act.
- If you can see a button in the screenshot but it has no accessibility label, use tap_xy with coordinates.
- Always explain your reasoning in the tool call parameters.
- You can switch between apps using open_app with a bundle ID.
- Use press_home to return to the home screen.
- CRITICAL: When you read text from the screen and need to reproduce it (e.g. copying a message into another app), you MUST type the EXACT text, character for character. Never paraphrase, summarize, or invent different words. If unsure, take a screenshot first and read carefully.
- In Messages, the text input field ("iMessage") is at the very bottom of the screen. If tapping by label fails, use tap_xy at coordinates near the bottom center.

Common bundle IDs (simulator):
- com.apple.mobilesafari — Safari
- com.apple.Preferences — Settings
- com.apple.MobileSMS — Messages
- com.apple.Maps — Maps
- com.apple.mobilecal — Calendar
- com.apple.reminders — Reminders
- com.apple.MobileAddressBook — Contacts
- com.apple.mobileslideshow — Photos
- com.apple.DocumentsApp — Files
- com.apple.Health — Health
Note: Not all apps are available on every simulator. If open_app fails, the app is not installed.
"""


@dataclass
class PlannedAction:
    """Planner output for one tool execution step."""

    name: str
    params: dict
    tool_use_id: str
    reasoning: str

def _build_tools(config=None) -> list[dict]:
    """Build the tool definitions, interpolating actual screen dimensions."""
    if config is not None:
        w, h = config.width, config.height
        br_x, br_y = w - 30, h - 34
    else:
        w, h = 390, 844
        br_x, br_y = 360, 810

    return [
        {
            "name": "tap",
            "description": "Tap a UI element by its visible label text. Fuzzy matching is applied.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The label/name of the element to tap"},
                    "reasoning": {"type": "string", "description": "Why you're tapping this element"},
                },
                "required": ["text", "reasoning"],
            },
        },
        {
            "name": "type_text",
            "description": "Type text into the currently focused input field. Use \\n for enter/return.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to type"},
                    "reasoning": {"type": "string", "description": "Why you're typing this"},
                },
                "required": ["text", "reasoning"],
            },
        },
        {
            "name": "scroll",
            "description": "Swipe/scroll the screen in a direction.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                        "description": "Direction to scroll",
                    },
                    "reasoning": {"type": "string", "description": "Why you're scrolling"},
                },
                "required": ["direction", "reasoning"],
            },
        },
        {
            "name": "take_screenshot",
            "description": "Capture the current screen for the user's audit trail.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string", "description": "Why you're capturing this"},
                },
                "required": ["reasoning"],
            },
        },
        {
            "name": "wait",
            "description": "Pause to let the UI settle (e.g. after navigation or loading).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "How long to wait",
                    },
                    "reasoning": {"type": "string", "description": "Why you're waiting"},
                },
                "required": ["seconds", "reasoning"],
            },
        },
        {
            "name": "open_app",
            "description": (
                "Switch to a different app by bundle ID. If the app is not installed, "
                "the result will say OPEN FAILED. Common IDs: "
                "com.apple.mobilesafari (Safari), com.apple.Preferences (Settings), "
                "com.apple.Maps (Maps), com.apple.reminders (Reminders), "
                "com.apple.mobilecal (Calendar), com.apple.DocumentsApp (Files)"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "bundle_id": {"type": "string", "description": "The bundle ID of the app to open"},
                    "reasoning": {"type": "string", "description": "Why you're switching apps"},
                },
                "required": ["bundle_id", "reasoning"],
            },
        },
        {
            "name": "press_home",
            "description": "Press the home button to return to the home screen / springboard.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string", "description": "Why you're pressing home"},
                },
                "required": ["reasoning"],
            },
        },
        {
            "name": "press_key",
            "description": (
                "Press a special key. Use RETURN to submit search/text, DELETE to backspace, "
                "TAB to move between fields, ESCAPE to dismiss."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "enum": ["RETURN", "DELETE", "TAB", "ESCAPE"],
                        "description": "The key to press",
                    },
                    "reasoning": {"type": "string", "description": "Why you're pressing this key"},
                },
                "required": ["key", "reasoning"],
            },
        },
        {
            "name": "tap_xy",
            "description": (
                f"Tap at exact screen coordinates in POINTS (not pixels). "
                f"WARNING: The screenshot image is scaled — do NOT use pixel coordinates from the image. "
                f"The actual screen is {w}x{h} points. x must be 0-{w}, y must be 0-{h}. "
                f"Top-left=(0,0), bottom-right=~({br_x},{br_y}). "
                f"If using the accessibility tree, read the 'frame' values directly — those are already in points."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": f"X in points (0-{w}). NOT image pixels."},
                    "y": {"type": "integer", "description": f"Y in points (0-{h}). NOT image pixels."},
                    "reasoning": {"type": "string", "description": "What you see at these coordinates"},
                },
                "required": ["x", "y", "reasoning"],
            },
        },
        {
            "name": "done",
            "description": "Signal that the goal has been achieved. Call this when finished.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "What was accomplished"},
                    "reasoning": {"type": "string", "description": "How you know the goal is met"},
                },
                "required": ["summary", "reasoning"],
            },
        },
        {
            "name": "fail",
            "description": "Signal that the goal cannot be achieved. Only call after multiple attempts.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why the goal cannot be achieved"},
                },
                "required": ["reason"],
            },
        },
        {
            "name": "extract_info",
            "description": "Extract and save all visible information from the current screen. Use when you see useful data (IPs, configs, settings, etc.).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "notes": {"type": "string", "description": "What you see that's worth capturing"},
                    "reasoning": {"type": "string", "description": "Why this is valuable"},
                },
                "required": ["notes", "reasoning"],
            },
        },
    ]


def _log(msg: str) -> None:
    print(f"[agent] {msg}", file=sys.stderr)


def _dump_tree(udid: str) -> tuple[list[dict], str]:
    """Dump accessibility tree and return (elements, json_string)."""
    raw = idbwrap.describe_all(udid)
    if not raw:
        return [], "[]"
    tree = screen_mapper.parse_tree(raw)
    elements = screen_mapper.flatten_elements(tree)
    compact = []
    for el in elements:
        entry = {"type": el.get("type", "Unknown")}
        for key in ("label", "name", "value", "title"):
            if el.get(key):
                entry[key] = el[key]
        if el.get("frame"):
            f = el["frame"]
            if f.get("width", 0) > 0 or f.get("height", 0) > 0:
                entry["frame"] = f
        compact.append(entry)
    return elements, json.dumps(compact, indent=1)


def _screenshot_b64(udid: str, label: str, max_dim: int = 1600) -> str | None:
    """Capture screenshot, resize to fit max_dim, return base64 PNG.

    Anthropic's API limits images to 2000px per side in many-image requests.
    We resize to max_dim (default 1600) to stay safely under that limit.
    """
    path = screenshot.capture_with_label(udid, label)
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import Image
        import io
        img = Image.open(path)
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            _log(f"Resized screenshot {w}x{h} → {new_w}x{new_h}")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.standard_b64encode(buf.getvalue()).decode("ascii")
    except ImportError:
        # Pillow not available, send raw (may fail on many-image requests)
        with open(path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("ascii")


def _build_user_content(
    text: str, udid: str, label: str, elements: list[dict]
) -> list[dict]:
    """Build a user message content array — text + optional screenshot if tree is sparse."""
    parts: list[dict] = [{"type": "text", "text": text}]

    # If tree has fewer than 8 meaningful elements, add a screenshot for vision.
    # Messages conversations typically have 6-7 elements with sparse labels,
    # so we need a generous threshold to ensure vision is used.
    meaningful = [e for e in elements if e.get("label") or e.get("name") or e.get("title")]
    if len(meaningful) < 8:
        _log(f"Sparse tree ({len(meaningful)} labeled elements) — adding screenshot for vision")
        b64 = _screenshot_b64(udid, label)
        if b64:
            parts.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })
    return parts


def _element_summary(elements: list[dict], limit: int = 15) -> str:
    """Build a short summary of visible elements for error messages."""
    labels = []
    for el in elements:
        text = el.get("label") or el.get("name") or el.get("title") or el.get("value")
        if text:
            labels.append(text)
    return ", ".join(labels[:limit])


def _tree_signature(elements: list[dict]) -> str:
    """Hash element labels/types into a compact signature for change detection."""
    parts = []
    for el in elements:
        etype = el.get("type", "")
        label = el.get("label") or el.get("name") or el.get("title") or ""
        parts.append(f"{etype}:{label}")
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()


def _recover(udid: str, elements: list[dict], attempt: int, config=None) -> str:
    """Attempt recovery from a stuck state. Returns a description of the action taken."""
    if attempt == 1:
        _log("STUCK DETECTED — attempting recovery (scroll down)")
        idbwrap.scroll(udid, "down", config=config)
        return "RECOVERY: scrolled down"
    elif attempt == 2:
        _log("STUCK DETECTED — attempting recovery (scroll up)")
        idbwrap.scroll(udid, "up", config=config)
        return "RECOVERY: scrolled up"
    elif attempt == 3:
        _log("STUCK DETECTED — attempting recovery (tap Back button)")
        from scripts.navigator import find_element
        el, score = find_element("Back", elements)
        if el is not None:
            x, y = screen_mapper.get_element_center(el)
            idbwrap.tap(udid, x, y)
            return f"RECOVERY: tapped Back button at ({x}, {y})"
        # No Back button found — try common nav labels
        for label in ("Close", "Cancel", "Done", "Home"):
            el, score = find_element(label, elements)
            if el is not None and score > 60:
                x, y = screen_mapper.get_element_center(el)
                idbwrap.tap(udid, x, y)
                return f"RECOVERY: tapped '{label}' at ({x}, {y})"
        return "RECOVERY: no navigation button found"
    else:
        return "RECOVERY: all attempts exhausted"


def _call_model(
    client: anthropic.Anthropic,
    tools: list[dict],
    messages: list[dict],
    retries: int = 3,
) -> tuple[object, int]:
    """Call Anthropic with bounded retries for transient API failures."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )
            return response, attempt - 1
        except Exception as exc:
            last_error = exc
            wait_seconds = min(2 ** (attempt - 1), 8)
            _log(f"Model call failed ({attempt}/{retries}): {exc}")
            if attempt < retries:
                _log(f"Retrying model call in {wait_seconds}s")
                time.sleep(wait_seconds)
    raise RuntimeError(f"Model call failed after {retries} attempts: {last_error}")


def _plan_next_action(response: object) -> tuple[PlannedAction | None, list[str]]:
    """Extract planner output from model response blocks."""
    tool_block = None
    text_parts: list[str] = []
    for block in response.content:
        if block.type == "tool_use":
            tool_block = block
        elif block.type == "text":
            text_parts.append(block.text)

    if tool_block is None:
        return None, text_parts

    params = tool_block.input if isinstance(tool_block.input, dict) else {}
    return PlannedAction(
        name=tool_block.name,
        params=params,
        tool_use_id=tool_block.id,
        reasoning=str(params.get("reasoning", "")),
    ), text_parts


def _execute_tool(name: str, params: dict, udid: str, elements: list[dict], step: int, config=None, bundle_id: str = "", goal: str = "") -> str:
    """Execute a tool call and return a result string."""
    if name == "tap":
        target_text = params.get("text", "")
        if not target_text:
            return "ERROR: tap requires 'text' param"
        from scripts.navigator import find_element
        el, score = find_element(target_text, elements)
        if el is None:
            return (
                f"TAP FAILED: No element matching '{target_text}'. "
                f"Available: {_element_summary(elements)}"
            )
        x, y = screen_mapper.get_element_center(el)
        if not idbwrap.tap(udid, x, y):
            return f"TAP FAILED: Could not tap '{target_text}' at ({x}, {y})"
        return f"TAPPED '{el.get('searchable_text', target_text)}' at ({x}, {y}) [score={score}]"

    elif name == "type_text":
        text = params.get("text", "")
        if not text:
            return "ERROR: type_text requires 'text' param"
        if not idbwrap.type_text(udid, text):
            return "TYPE FAILED: Could not type text"
        return f"TYPED '{text}'"

    elif name == "scroll":
        direction = params.get("direction", "down")
        if not idbwrap.scroll(udid, direction, config=config):
            return f"SCROLL FAILED: {direction}"
        return f"SCROLLED {direction}"

    elif name == "take_screenshot":
        path = screenshot.capture_with_label(udid, f"step_{step:02d}_requested")
        return f"SCREENSHOT saved: {path}" if path else "SCREENSHOT failed"

    elif name == "wait":
        seconds = min(max(params.get("seconds", 2), 1), 5)
        time.sleep(seconds)
        return f"WAITED {seconds}s"

    elif name == "press_key":
        key = params.get("key", "RETURN")
        success = idbwrap.key_press(udid, key)
        return f"PRESSED {key}" if success else f"KEY PRESS FAILED: {key}"

    elif name == "tap_xy":
        x = params.get("x", 0)
        y = params.get("y", 0)
        # Catch out-of-bounds coordinates (likely using pixel coords instead of points)
        if config and (x > config.width or y > config.height):
            return (
                f"ERROR: coordinates ({x}, {y}) are outside the screen "
                f"({config.width}x{config.height} points). "
                f"You are likely using image pixel coordinates instead of screen points. "
                f"The screen is only {config.width}x{config.height}."
            )
        if not idbwrap.tap(udid, x, y):
            return f"TAP FAILED: Could not tap coordinates ({x}, {y})"
        return f"TAPPED coordinates ({x}, {y})"

    elif name == "open_app":
        bid = params.get("bundle_id", "")
        if not bid:
            return "ERROR: open_app requires 'bundle_id' param"
        success = idbwrap.launch_app(udid, bid)
        if not success:
            return f"OPEN FAILED: Could not launch '{bid}' — app may not be installed"
        time.sleep(2)
        return f"OPENED {bid}"

    elif name == "press_home":
        if not idbwrap.press_home(udid):
            return "HOME FAILED: Could not press home"
        time.sleep(1)
        return "PRESSED HOME — now on springboard"

    elif name == "extract_info":
        # Force a fresh capture + full extraction
        path = screenshot.capture_with_label(udid, f"step_{step:02d}_extract")
        tree_path = screenshot.save_tree_json(elements, f"step_{step:02d}_extract")
        finding = intel.build_finding(elements, bundle_id, path or "", tree_path or "", step, goal)
        finding.tags.append("agent_flagged")
        if params.get("notes"):
            finding.tags.append(f"note:{params['notes'][:100]}")
        fid = intel.save_finding(finding)
        return f"EXTRACTED: {len(finding.text_content)} texts, {len(finding.extracted_data)} structured items. ID: {fid}"

    elif name == "done":
        return f"DONE: {params.get('summary', 'Goal achieved')}"

    elif name == "fail":
        return f"FAIL: {params.get('reason', 'Unknown failure')}"

    else:
        return f"ERROR: Unknown tool '{name}'"


def _execute_planned_action(
    action: PlannedAction,
    udid: str,
    elements: list[dict],
    step: int,
    config=None,
    bundle_id: str = "",
    goal: str = "",
) -> str:
    """Execute planner output through the executor."""
    return _execute_tool(
        action.name,
        action.params,
        udid,
        elements,
        step,
        config=config,
        bundle_id=bundle_id,
        goal=goal,
    )


def run(
    goal: str,
    udid: str,
    bundle_id: str = "com.apple.mobilesafari",
    max_steps: int = 20,
    config=None,
    safe_mode: bool = True,
    run_id: str | None = None,
    resume_run_id: str | None = None,
    stop_after_step: int | None = None,
    allow_tap_xy: bool = False,
    allowed_bundle_prefixes: list[str] | None = None,
) -> dict:
    """Run the autonomous agent loop.

    Returns a dict with:
        success: bool
        steps: int
        summary: str
        history: list of step dicts
    """
    if config is None:
        from scripts.device_config import detect
        config = detect(udid)

    policy = SafeModePolicy() if safe_mode else SafeModePolicy.disabled()
    if allow_tap_xy:
        policy.allow_tap_xy = True
    if allowed_bundle_prefixes:
        merged = tuple(dict.fromkeys(policy.allowed_bundle_prefixes + tuple(allowed_bundle_prefixes)))
        policy.allowed_bundle_prefixes = merged

    max_steps = policy.effective_max_steps(max_steps)

    state: dict
    start_step = 1
    if resume_run_id:
        loaded = run_state.load_state(resume_run_id)
        if loaded is None:
            return {
                "success": False,
                "steps": 0,
                "summary": f"Resume failed: run '{resume_run_id}' not found",
                "history": [],
                "findings": [],
                "findings_count": 0,
                "run_id": resume_run_id,
                "status": "failed",
            }
        state = loaded
        run_id = state.get("run_id", resume_run_id)
        goal = state.get("goal", goal)
        bundle_id = state.get("bundle_id", bundle_id)
        max_steps = int(state.get("max_steps", max_steps))
        start_step = int(state.get("last_step", 0)) + 1
        state["status"] = "running"
        run_state.save_state(state)
    else:
        bundle_allowed, bundle_reason = policy.validate_bundle(bundle_id)
        if not bundle_allowed:
            return {
                "success": False,
                "steps": 0,
                "summary": f"Safe-mode blocked start bundle: {bundle_reason}",
                "history": [],
                "findings": [],
                "findings_count": 0,
                "status": "failed",
            }
        state = run_state.create_run(
            goal=goal,
            bundle_id=bundle_id,
            udid=udid,
            max_steps=max_steps,
            safe_mode=safe_mode,
            run_id=run_id,
        )
        state["policy"] = {
            "allow_tap_xy": bool(policy.allow_tap_xy),
            "allow_open_app": bool(policy.allow_open_app),
            "allowed_bundle_prefixes": list(policy.allowed_bundle_prefixes),
            "blocked_tools": sorted(list(policy.blocked_tools)),
        }
        run_state.save_state(state)

    client = anthropic.Anthropic()

    run_id = state["run_id"]
    _log(f"Run ID: {run_id}")
    _log(f"Goal: {goal}")
    _log(f"Bundle: {bundle_id} | Max steps: {max_steps}")
    _log(f"Screen: {config.width}x{config.height} @{config.scale}x")

    # Launch the app
    idbwrap.launch_app(udid, bundle_id)
    time.sleep(3)

    # Initial tree dump
    elements, tree_json = _dump_tree(udid)
    _log(f"Initial tree: {len(elements)} elements")

    # Initial screenshot for audit trail
    initial_label = "step_00_initial" if start_step == 1 else f"step_{start_step - 1:02d}_resume"
    initial_ss = screenshot.capture_with_label(udid, initial_label)

    # --- Intel: capture initial screen ---
    all_findings: list[intel.Finding] = []
    initial_tree_json_path = screenshot.save_tree_json(elements, initial_label)
    initial_finding = intel.build_finding(
        elements=elements,
        bundle_id=bundle_id,
        screenshot_path=initial_ss or "",
        tree_path=initial_tree_json_path or "",
        step=max(start_step - 1, 0),
        goal=goal,
    )
    if initial_finding.text_content:
        intel.save_finding(initial_finding)
        all_findings.append(initial_finding)

    # Build first user message (with vision fallback if tree is sparse)
    step_history = list(state.get("history", []))
    prior_context = ""
    if step_history:
        recent_steps = step_history[-5:]
        lines = [
            f"- step {row.get('step')}: {row.get('tool')} => {str(row.get('result', ''))[:160]}"
            for row in recent_steps
        ]
        prior_context = "Previous run context:\n" + "\n".join(lines) + "\n\n"

    first_text = (
        f"GOAL: {goal}\n\n"
        f"{prior_context}"
        f"Current app: {bundle_id}\n\n"
        f"Current accessibility tree:\n{tree_json}"
    )
    messages = [
        {
            "role": "user",
            "content": _build_user_content(first_text, udid, "step_00_tree", elements),
        }
    ]

    tools = _build_tools(config)

    recent_trees: list[str] = []
    consecutive_failures: int = 0
    recovery_attempt: int = 0

    for step in range(start_step, max_steps + 1):
        _log(f"--- Step {step}/{max_steps} ---")

        if stop_after_step is not None and step > stop_after_step:
            pause_summary = f"Paused after step {step - 1} (stop_after_step={stop_after_step})"
            run_state.finalize_run(state, "paused", pause_summary, step - 1)
            run_report.render_run_report(run_id)
            return {
                "success": False,
                "paused": True,
                "steps": step - 1,
                "summary": pause_summary,
                "history": step_history,
                "findings": [asdict(f) for f in all_findings],
                "findings_count": len(all_findings),
                "run_id": run_id,
                "run_paths": run_state.run_paths(run_id),
                "status": "paused",
            }

        # Call Claude with tool_use
        model_start = time.monotonic()
        try:
            response, retries = _call_model(client, tools, messages)
            latency_ms = int((time.monotonic() - model_start) * 1000)
            run_state.increment_metric(state, "model_calls", 1)
            if retries:
                run_state.increment_metric(state, "model_retries", retries)
            run_state.append_event(
                run_id,
                {
                    "type": "model_response",
                    "step": step,
                    "latency_ms": latency_ms,
                    "retries": retries,
                },
            )
        except Exception as exc:
            failure_message = f"Model API failure: {exc}"
            _log(failure_message)
            run_state.increment_metric(state, "model_failures", 1)
            failure_record = {
                "step": step,
                "tool": "_model_call",
                "params": {},
                "result": f"FAIL: {failure_message}",
            }
            step_history.append(failure_record)
            run_state.append_history(state, failure_record)
            run_state.finalize_run(state, "failed", failure_message, step)
            run_report.render_run_report(run_id)
            return {
                "success": False,
                "steps": step,
                "summary": failure_message,
                "history": step_history,
                "findings": [asdict(f) for f in all_findings],
                "findings_count": len(all_findings),
                "run_id": run_id,
                "run_paths": run_state.run_paths(run_id),
                "status": "failed",
            }

        action, text_parts = _plan_next_action(response)

        if text_parts:
            _log(f"Claude says: {' '.join(text_parts)}")

        if action is None:
            # Claude didn't call a tool — nudge it
            _log("No tool call in response, nudging")
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": "You must call exactly one tool per turn. Please call a tool now.",
            })
            run_state.append_event(
                run_id,
                {
                    "type": "planner_no_action",
                    "step": step,
                },
            )
            continue

        tool_name = action.name
        tool_params = action.params
        _log(f"Tool: {tool_name} | Reasoning: {action.reasoning}")

        # Safe-mode policy gate (planner/executor split)
        allowed, policy_reason = policy.validate_action(tool_name, tool_params)
        if not allowed:
            result = f"POLICY BLOCKED: {policy_reason}"
            run_state.increment_metric(state, "policy_blocks", 1)
            run_state.append_event(
                run_id,
                {
                    "type": "policy_block",
                    "step": step,
                    "tool": tool_name,
                    "reason": policy_reason,
                },
            )
        else:
            action_start = time.monotonic()
            result = _execute_planned_action(
                action,
                udid,
                elements,
                step,
                config=config,
                bundle_id=bundle_id,
                goal=goal,
            )
            action_ms = int((time.monotonic() - action_start) * 1000)
            run_state.append_event(
                run_id,
                {
                    "type": "tool_executed",
                    "step": step,
                    "tool": tool_name,
                    "latency_ms": action_ms,
                    "result": result[:300],
                },
            )
        _log(f"Result: {result}")

        # Audit screenshot after every action
        last_screenshot_path = screenshot.capture_with_label(
            udid, f"step_{step:02d}_{tool_name}"
        )
        if last_screenshot_path:
            run_state.append_event(
                run_id,
                {
                    "type": "screenshot_captured",
                    "step": step,
                    "tool": tool_name,
                    "path": last_screenshot_path,
                },
            )

        # Track failures for stuck detection
        if "FAILED" in result or "POLICY BLOCKED" in result:
            consecutive_failures += 1
            run_state.increment_metric(state, "action_failures", 1)
        else:
            consecutive_failures = 0

        # Record step (include artifact paths when available)
        step_record = {
            "step": step,
            "tool": tool_name,
            "params": tool_params,
            "result": result,
            "screenshot_path": last_screenshot_path or "",
        }
        step_history.append(step_record)
        run_state.append_history(state, step_record)

        # Check for terminal tools
        if tool_name == "done":
            _log(f"Agent finished: {result}")
            summary = tool_params.get("summary", "Goal achieved")
            run_state.finalize_run(state, "completed", summary, step)
            run_report.render_run_report(run_id)
            return {
                "success": True,
                "steps": step,
                "summary": summary,
                "history": step_history,
                "findings": [asdict(f) for f in all_findings],
                "findings_count": len(all_findings),
                "run_id": run_id,
                "run_paths": run_state.run_paths(run_id),
                "status": "completed",
            }

        if tool_name == "fail":
            _log(f"Agent gave up: {result}")
            summary = tool_params.get("reason", "Agent failed")
            run_state.finalize_run(state, "failed", summary, step)
            run_report.render_run_report(run_id)
            return {
                "success": False,
                "steps": step,
                "summary": summary,
                "history": step_history,
                "findings": [asdict(f) for f in all_findings],
                "findings_count": len(all_findings),
                "run_id": run_id,
                "run_paths": run_state.run_paths(run_id),
                "status": "failed",
            }

        # Wait for UI to settle, then refresh
        time.sleep(1)
        elements, tree_json = _dump_tree(udid)
        _log(f"Refreshed tree: {len(elements)} elements")

        # --- Intel: capture everything ---
        tree_json_path = screenshot.save_tree_json(elements, f"step_{step:02d}_{tool_name}")
        if tree_json_path:
            run_state.append_event(
                run_id,
                {
                    "type": "tree_saved",
                    "step": step,
                    "tool": tool_name,
                    "path": tree_json_path,
                },
            )
            # Back-fill the history record with tree path for reporting.
            step_record["tree_path"] = tree_json_path
            run_state.save_state(state)
        finding = intel.build_finding(
            elements=elements,
            bundle_id=bundle_id,
            screenshot_path=last_screenshot_path or "",
            tree_path=tree_json_path or "",
            step=step,
            goal=goal,
        )
        if finding.text_content:
            intel.save_finding(finding)
            all_findings.append(finding)

        # --- Stuck detection ---
        sig = _tree_signature(elements)
        recent_trees.append(sig)
        if len(recent_trees) > 3:
            recent_trees.pop(0)

        tree_stuck = (
            len(recent_trees) == 3
            and recent_trees[0] == recent_trees[1] == recent_trees[2]
        )
        failure_stuck = consecutive_failures >= 3

        if tree_stuck or failure_stuck:
            reason = "identical tree 3 turns" if tree_stuck else f"{consecutive_failures} consecutive tap failures"
            recovery_attempt += 1

            if recovery_attempt <= 3:
                recovery_result = _recover(udid, elements, recovery_attempt, config=config)
                _log(f"Recovery ({reason}): {recovery_result}")
                run_state.increment_metric(state, "recoveries", 1)
                step_history.append({
                    "step": step,
                    "tool": "_recover",
                    "params": {"attempt": recovery_attempt, "reason": reason},
                    "result": recovery_result,
                })
                run_state.append_history(state, step_history[-1])
                # Re-refresh the tree after recovery action
                time.sleep(1)
                elements, tree_json = _dump_tree(udid)
                recent_trees.clear()
                consecutive_failures = 0
            else:
                _log(f"All recovery attempts exhausted ({reason}) — auto-failing")
                step_history.append({
                    "step": step,
                    "tool": "fail",
                    "params": {"reason": f"Stuck: {reason}, recovery exhausted"},
                    "result": "FAIL: agent stuck, all recovery attempts exhausted",
                })
                run_state.append_history(state, step_history[-1])
                run_state.finalize_run(
                    state,
                    "failed",
                    f"Stuck: {reason}, all recovery attempts exhausted",
                    step,
                )
                run_report.render_run_report(run_id)
                return {
                    "success": False,
                    "steps": step,
                    "summary": f"Stuck: {reason}, all recovery attempts exhausted",
                    "history": step_history,
                    "findings": [asdict(f) for f in all_findings],
                    "findings_count": len(all_findings),
                    "run_id": run_id,
                    "run_paths": run_state.run_paths(run_id),
                    "status": "failed",
                }
        else:
            # Reset recovery counter when the agent makes progress
            recovery_attempt = 0

        # Build tool_result and next observation
        observation_text = f"Result: {result}\n\nUpdated accessibility tree:\n{tree_json}"

        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": action.tool_use_id,
                    "content": _build_user_content(
                        observation_text, udid, f"step_{step:02d}_tree", elements
                    ),
                }
            ],
        })

        if stop_after_step is not None and step >= stop_after_step:
            pause_summary = f"Paused after step {step} (stop_after_step={stop_after_step})"
            run_state.finalize_run(state, "paused", pause_summary, step)
            run_report.render_run_report(run_id)
            return {
                "success": False,
                "paused": True,
                "steps": step,
                "summary": pause_summary,
                "history": step_history,
                "findings": [asdict(f) for f in all_findings],
                "findings_count": len(all_findings),
                "run_id": run_id,
                "run_paths": run_state.run_paths(run_id),
                "status": "paused",
            }

    _log("Max steps reached")
    max_step_summary = f"Reached max steps ({max_steps}) without completing goal"
    run_state.finalize_run(state, "failed", max_step_summary, max_steps)
    run_report.render_run_report(run_id)
    return {
        "success": False,
        "steps": max_steps,
        "summary": max_step_summary,
        "history": step_history,
        "findings": [asdict(f) for f in all_findings],
        "findings_count": len(all_findings),
        "run_id": run_id,
        "run_paths": run_state.run_paths(run_id),
        "status": "failed",
    }
