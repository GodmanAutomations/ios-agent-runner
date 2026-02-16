import pytest

from scripts import agent_loop, idbwrap


class _Config:
    center_x = 100
    center_y = 200
    swipe_delta = 50


def test_idbwrap_scroll_fallback_uses_drag_script(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]):
        calls.append(cmd)
        return "", "", 0

    monkeypatch.setattr(idbwrap, "_has_idb", lambda: False)
    monkeypatch.setattr(idbwrap, "_run", fake_run)

    ok = idbwrap.scroll("SIM-UDID", direction="down", config=_Config())

    assert ok is True
    assert calls
    assert calls[0][0] == "osascript"
    assert "drag from {100, 150} to {100, 250}" in calls[0][2]


def test_idbwrap_scroll_fallback_failure_returns_false(monkeypatch):
    def fake_run(cmd: list[str]):
        return "", "boom", 1

    monkeypatch.setattr(idbwrap, "_has_idb", lambda: False)
    monkeypatch.setattr(idbwrap, "_run", fake_run)

    assert idbwrap.scroll("SIM-UDID", direction="up", config=_Config()) is False


def test_agent_loop_call_model_retries_then_succeeds(monkeypatch):
    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("transient")
            return {"status": "ok"}

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    sleeps: list[int] = []
    monkeypatch.setattr(agent_loop.time, "sleep", lambda seconds: sleeps.append(seconds))

    response, retries = agent_loop._call_model(FakeClient(), tools=[], messages=[], retries=3)

    assert response == {"status": "ok"}
    assert retries == 2
    assert sleeps == [1, 2]


def test_agent_loop_call_model_raises_after_retry_limit(monkeypatch):
    class FakeMessages:
        def create(self, **kwargs):
            raise RuntimeError("always down")

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    monkeypatch.setattr(agent_loop.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="Model call failed after 2 attempts"):
        agent_loop._call_model(FakeClient(), tools=[], messages=[], retries=2)


def test_execute_tool_reports_scroll_failure(monkeypatch):
    monkeypatch.setattr(agent_loop.idbwrap, "scroll", lambda udid, direction, config=None: False)
    result = agent_loop._execute_tool(
        "scroll",
        {"direction": "down", "reasoning": "test"},
        "SIM-UDID",
        [],
        step=1,
        config=_Config(),
    )

    assert result == "SCROLL FAILED: down"
