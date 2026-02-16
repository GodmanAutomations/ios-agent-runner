from scripts.safe_mode import SafeModePolicy


def test_safe_mode_blocks_disallowed_bundle():
    policy = SafeModePolicy(enabled=True)
    allowed, reason = policy.validate_bundle("io.random.app")
    assert allowed is False
    assert "does not match allowed safe-mode prefixes" in reason


def test_safe_mode_allows_open_app_for_apple_bundle():
    policy = SafeModePolicy(enabled=True)
    allowed, reason = policy.validate_action("open_app", {"bundle_id": "com.apple.Preferences"})
    assert allowed is True
    assert reason == "allowed by prefix"


def test_safe_mode_blocks_tap_xy_by_default():
    policy = SafeModePolicy(enabled=True)
    allowed, reason = policy.validate_action("tap_xy", {"x": 10, "y": 20})
    assert allowed is False
    assert reason == "tap_xy disabled in safe mode"


def test_safe_mode_disabled_allows_any_tool():
    policy = SafeModePolicy.disabled()
    allowed, reason = policy.validate_action("custom_tool", {"x": 1})
    assert allowed is True
    assert reason == "safe mode disabled"
