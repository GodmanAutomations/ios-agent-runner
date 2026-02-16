"""Safe-mode policy enforcement for autonomous iOS agent actions."""

from dataclasses import dataclass, field

ALLOWED_TOOLS = {
    "tap",
    "type_text",
    "scroll",
    "take_screenshot",
    "wait",
    "open_app",
    "press_home",
    "press_key",
    "tap_xy",
    "done",
    "fail",
    "extract_info",
}


@dataclass
class SafeModePolicy:
    """Guardrails for unattended automation runs."""

    enabled: bool = True
    max_steps: int = 25
    allow_tap_xy: bool = False
    allow_open_app: bool = True
    allowed_bundle_prefixes: tuple[str, ...] = (
        "com.apple.",
        "com.google.",
        "com.microsoft.",
        "com.openai.",
        "com.anthropic.",
    )
    blocked_tools: set[str] = field(default_factory=set)

    @classmethod
    def disabled(cls) -> "SafeModePolicy":
        """Create an unrestricted policy."""
        return cls(
            enabled=False,
            max_steps=200,
            allow_tap_xy=True,
            allow_open_app=True,
            allowed_bundle_prefixes=(),
            blocked_tools=set(),
        )

    def effective_max_steps(self, requested: int) -> int:
        """Clamp requested max steps when safe mode is enabled."""
        if not self.enabled:
            return requested
        return max(1, min(requested, self.max_steps))

    def validate_bundle(self, bundle_id: str) -> tuple[bool, str]:
        """Validate target bundle before launch."""
        if not self.enabled:
            return True, "safe mode disabled"
        if not bundle_id:
            return False, "bundle_id is required in safe mode"
        if any(bundle_id.startswith(prefix) for prefix in self.allowed_bundle_prefixes):
            return True, "allowed by prefix"
        return False, f"bundle '{bundle_id}' does not match allowed safe-mode prefixes"

    def validate_action(self, tool_name: str, params: dict | None = None) -> tuple[bool, str]:
        """Validate a planned action before execution."""
        if not self.enabled:
            return True, "safe mode disabled"

        if tool_name in self.blocked_tools:
            return False, f"tool '{tool_name}' is blocked by policy"

        if tool_name not in ALLOWED_TOOLS:
            return False, f"tool '{tool_name}' is not in allowed safe-mode tool set"

        params = params or {}

        if tool_name == "tap_xy" and not self.allow_tap_xy:
            return False, "tap_xy disabled in safe mode"

        if tool_name == "open_app":
            if not self.allow_open_app:
                return False, "open_app disabled in safe mode"
            bundle_id = str(params.get("bundle_id", "")).strip()
            return self.validate_bundle(bundle_id)

        if tool_name == "wait":
            seconds = int(params.get("seconds", 1) or 1)
            if seconds > 5:
                return False, "wait longer than 5 seconds is blocked in safe mode"

        return True, "allowed"
