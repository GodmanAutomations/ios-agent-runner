"""agent_loop.py - Autonomous LLM agent loop for iOS simulator automation.

Give it a goal in plain English and it reads the screen, reasons, acts,
reads again, and loops until done (or gives up).
"""

import json
import os
import sys
import time

import anthropic

from scripts import idbwrap, screen_mapper, screenshot

MODEL = "claude-sonnet-4-5-20250929"

SYSTEM_PROMPT = """\
You are an iOS automation agent controlling a real iPhone simulator.

You see the screen via an accessibility tree (provided as JSON).
Your job: accomplish the user's goal by issuing one action per turn.

Available actions:
  tap     - Tap a UI element. Params: {"text": "<label to tap>"}
  type    - Type into the focused field. Params: {"text": "<text to type>"}
  scroll  - Swipe the screen. Params: {"direction": "up"|"down"|"left"|"right"}
  screenshot - Capture the screen for the user. No params.
  wait    - Pause before next action. Params: {"seconds": <1-5>}
  done    - Goal achieved. Params: {"summary": "<what you accomplished>"}
  fail    - Stuck / impossible. Params: {"reason": "<why>"}

Rules:
- Respond with EXACTLY ONE JSON object per turn. No markdown, no commentary.
- Always include a "reasoning" field explaining your thinking.
- Use "tap" with the visible label text — fuzzy matching is handled for you.
- After typing, the keyboard may cover the screen; scroll or tap elsewhere if needed.
- Call "done" as soon as the goal is achieved. Call "fail" if truly stuck.

Example responses:
{"action": "tap", "text": "Search", "reasoning": "Tapping the search bar to enter a URL"}
{"action": "type", "text": "openai.com\\n", "reasoning": "Typing the URL and pressing enter"}
{"action": "done", "summary": "Navigated to openai.com", "reasoning": "Page has loaded"}
"""


def _log(msg: str) -> None:
    print(f"[agent] {msg}", file=sys.stderr)


def _dump_tree(udid: str) -> tuple[list[dict], str]:
    """Dump accessibility tree and return (elements, json_string)."""
    raw = idbwrap.describe_all(udid)
    if not raw:
        return [], "[]"
    tree = screen_mapper.parse_tree(raw)
    elements = screen_mapper.flatten_elements(tree)
    # Build a compact representation for the LLM
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


def _parse_action(text: str) -> dict | None:
    """Parse the LLM's JSON response into an action dict."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        _log(f"Failed to parse action JSON: {text[:200]}")
        return None


def _execute_action(action: dict, udid: str, elements: list[dict], step: int) -> str:
    """Execute one action and return a result string for the conversation."""
    act = action.get("action", "").lower()

    if act == "tap":
        target_text = action.get("text", "")
        if not target_text:
            return "ERROR: tap action requires 'text' param"
        from scripts.navigator import find_element
        el, score = find_element(target_text, elements)
        if el is None:
            return f"TAP FAILED: Could not find element matching '{target_text}'. Available elements include: {_element_summary(elements)}"
        center = screen_mapper.get_element_center(el)
        x, y = center
        idbwrap.tap(udid, x, y)
        matched_label = el.get("searchable_text", target_text)
        return f"TAPPED '{matched_label}' at ({x}, {y}) [score={score}]"

    elif act == "type":
        text = action.get("text", "")
        if not text:
            return "ERROR: type action requires 'text' param"
        idbwrap.type_text(udid, text)
        return f"TYPED '{text}'"

    elif act == "scroll":
        direction = action.get("direction", "down")
        idbwrap.scroll(udid, direction)
        return f"SCROLLED {direction}"

    elif act == "screenshot":
        path = screenshot.capture_with_label(udid, f"step_{step:02d}")
        return f"SCREENSHOT saved: {path}" if path else "SCREENSHOT failed"

    elif act == "wait":
        seconds = min(max(action.get("seconds", 2), 1), 5)
        time.sleep(seconds)
        return f"WAITED {seconds}s"

    elif act == "done":
        summary = action.get("summary", "Goal achieved")
        return f"DONE: {summary}"

    elif act == "fail":
        reason = action.get("reason", "Unknown failure")
        return f"FAIL: {reason}"

    else:
        return f"ERROR: Unknown action '{act}'"


def _element_summary(elements: list[dict], limit: int = 15) -> str:
    """Build a short summary of visible elements for error messages."""
    labels = []
    for el in elements:
        text = el.get("label") or el.get("name") or el.get("title") or el.get("value")
        if text:
            labels.append(text)
    return ", ".join(labels[:limit])


def run(
    goal: str,
    udid: str,
    bundle_id: str = "com.apple.mobilesafari",
    max_steps: int = 20,
) -> dict:
    """Run the autonomous agent loop.

    Returns a dict with:
        success: bool
        steps: int
        summary: str
        history: list of step dicts
    """
    client = anthropic.Anthropic()

    _log(f"Goal: {goal}")
    _log(f"Bundle: {bundle_id} | Max steps: {max_steps}")

    # Launch the app
    idbwrap.launch_app(udid, bundle_id)
    time.sleep(3)

    # Initial tree dump
    elements, tree_json = _dump_tree(udid)
    _log(f"Initial tree: {len(elements)} elements")

    # Take initial screenshot for audit trail
    screenshot.capture_with_label(udid, "step_00_initial")

    messages = [
        {
            "role": "user",
            "content": (
                f"GOAL: {goal}\n\n"
                f"Current app: {bundle_id}\n\n"
                f"Current accessibility tree:\n{tree_json}"
            ),
        }
    ]

    step_history = []

    for step in range(1, max_steps + 1):
        _log(f"--- Step {step}/{max_steps} ---")

        # Call Claude
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        assistant_text = response.content[0].text
        _log(f"Claude: {assistant_text.strip()}")

        # Parse the action
        action = _parse_action(assistant_text)
        if action is None:
            _log("Could not parse action, asking Claude to retry")
            messages.append({"role": "assistant", "content": assistant_text})
            messages.append({
                "role": "user",
                "content": "ERROR: Your response was not valid JSON. Respond with exactly one JSON object.",
            })
            continue

        reasoning = action.get("reasoning", "")
        _log(f"Action: {action.get('action')} | Reasoning: {reasoning}")

        # Execute
        result = _execute_action(action, udid, elements, step)
        _log(f"Result: {result}")

        # Record step
        step_record = {
            "step": step,
            "action": action,
            "result": result,
        }
        step_history.append(step_record)

        # Capture audit screenshot after every action
        screenshot.capture_with_label(udid, f"step_{step:02d}_{action.get('action', 'unknown')}")

        # Check for terminal actions
        act = action.get("action", "").lower()
        if act == "done":
            _log(f"Agent finished: {result}")
            return {
                "success": True,
                "steps": step,
                "summary": action.get("summary", "Goal achieved"),
                "history": step_history,
            }

        if act == "fail":
            _log(f"Agent gave up: {result}")
            return {
                "success": False,
                "steps": step,
                "summary": action.get("reason", "Agent failed"),
                "history": step_history,
            }

        # Wait a moment for UI to settle, then refresh the tree
        time.sleep(1)
        elements, tree_json = _dump_tree(udid)
        _log(f"Refreshed tree: {len(elements)} elements")

        # Append to conversation
        messages.append({"role": "assistant", "content": assistant_text})
        messages.append({
            "role": "user",
            "content": f"Result: {result}\n\nUpdated accessibility tree:\n{tree_json}",
        })

    _log("Max steps reached")
    return {
        "success": False,
        "steps": max_steps,
        "summary": f"Reached max steps ({max_steps}) without completing goal",
        "history": step_history,
    }
