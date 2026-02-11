"""agent_loop.py - Autonomous LLM agent loop for iOS simulator automation.

Give it a goal in plain English and it reads the screen, reasons, acts,
reads again, and loops until done (or gives up).

Uses Anthropic's native tool_use API for structured actions (no JSON parsing).
Falls back to vision (screenshot) when the accessibility tree is empty.
"""

import base64
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
Your job: accomplish the user's goal by calling exactly one tool per turn.

Guidelines:
- Use "tap" with the visible label text — fuzzy matching is handled for you.
- After typing, the keyboard may cover the screen; scroll or tap elsewhere if needed.
- Call "done" as soon as the goal is achieved. Call "fail" if truly stuck after multiple attempts.
- If the accessibility tree is empty, you may receive a screenshot instead — use visual cues to act.
- Always explain your reasoning in the tool call parameters.
"""

TOOLS = [
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


def _screenshot_b64(udid: str, label: str) -> str | None:
    """Capture screenshot and return base64-encoded PNG, or None."""
    path = screenshot.capture_with_label(udid, label)
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")


def _build_user_content(
    text: str, udid: str, label: str, elements: list[dict]
) -> list[dict]:
    """Build a user message content array — text + optional screenshot if tree is sparse."""
    parts: list[dict] = [{"type": "text", "text": text}]

    # If tree has fewer than 3 meaningful elements, add a screenshot for vision
    meaningful = [e for e in elements if e.get("label") or e.get("name") or e.get("title")]
    if len(meaningful) < 3:
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


def _execute_tool(name: str, params: dict, udid: str, elements: list[dict], step: int) -> str:
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
        idbwrap.tap(udid, x, y)
        return f"TAPPED '{el.get('searchable_text', target_text)}' at ({x}, {y}) [score={score}]"

    elif name == "type_text":
        text = params.get("text", "")
        if not text:
            return "ERROR: type_text requires 'text' param"
        idbwrap.type_text(udid, text)
        return f"TYPED '{text}'"

    elif name == "scroll":
        direction = params.get("direction", "down")
        idbwrap.scroll(udid, direction)
        return f"SCROLLED {direction}"

    elif name == "take_screenshot":
        path = screenshot.capture_with_label(udid, f"step_{step:02d}_requested")
        return f"SCREENSHOT saved: {path}" if path else "SCREENSHOT failed"

    elif name == "wait":
        seconds = min(max(params.get("seconds", 2), 1), 5)
        time.sleep(seconds)
        return f"WAITED {seconds}s"

    elif name == "done":
        return f"DONE: {params.get('summary', 'Goal achieved')}"

    elif name == "fail":
        return f"FAIL: {params.get('reason', 'Unknown failure')}"

    else:
        return f"ERROR: Unknown tool '{name}'"


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

    # Initial screenshot for audit trail
    screenshot.capture_with_label(udid, "step_00_initial")

    # Build first user message (with vision fallback if tree is sparse)
    first_text = (
        f"GOAL: {goal}\n\n"
        f"Current app: {bundle_id}\n\n"
        f"Current accessibility tree:\n{tree_json}"
    )
    messages = [
        {
            "role": "user",
            "content": _build_user_content(first_text, udid, "step_00_tree", elements),
        }
    ]

    step_history = []

    for step in range(1, max_steps + 1):
        _log(f"--- Step {step}/{max_steps} ---")

        # Call Claude with tool_use
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Extract the tool_use block from the response
        tool_block = None
        text_parts = []
        for block in response.content:
            if block.type == "tool_use":
                tool_block = block
            elif block.type == "text":
                text_parts.append(block.text)

        if text_parts:
            _log(f"Claude says: {' '.join(text_parts)}")

        if tool_block is None:
            # Claude didn't call a tool — nudge it
            _log("No tool call in response, nudging")
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": "You must call exactly one tool per turn. Please call a tool now.",
            })
            continue

        tool_name = tool_block.name
        tool_params = tool_block.input
        reasoning = tool_params.get("reasoning", "")
        _log(f"Tool: {tool_name} | Reasoning: {reasoning}")

        # Execute the tool
        result = _execute_tool(tool_name, tool_params, udid, elements, step)
        _log(f"Result: {result}")

        # Record step
        step_history.append({
            "step": step,
            "tool": tool_name,
            "params": tool_params,
            "result": result,
        })

        # Audit screenshot after every action
        screenshot.capture_with_label(
            udid, f"step_{step:02d}_{tool_name}"
        )

        # Check for terminal tools
        if tool_name == "done":
            _log(f"Agent finished: {result}")
            return {
                "success": True,
                "steps": step,
                "summary": tool_params.get("summary", "Goal achieved"),
                "history": step_history,
            }

        if tool_name == "fail":
            _log(f"Agent gave up: {result}")
            return {
                "success": False,
                "steps": step,
                "summary": tool_params.get("reason", "Agent failed"),
                "history": step_history,
            }

        # Wait for UI to settle, then refresh
        time.sleep(1)
        elements, tree_json = _dump_tree(udid)
        _log(f"Refreshed tree: {len(elements)} elements")

        # Build tool_result and next observation
        observation_text = f"Result: {result}\n\nUpdated accessibility tree:\n{tree_json}"

        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": _build_user_content(
                        observation_text, udid, f"step_{step:02d}_tree", elements
                    ),
                }
            ],
        })

    _log("Max steps reached")
    return {
        "success": False,
        "steps": max_steps,
        "summary": f"Reached max steps ({max_steps}) without completing goal",
        "history": step_history,
    }
