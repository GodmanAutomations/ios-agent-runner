import json

from scripts import run_state


def test_run_state_create_append_finalize_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(run_state, "_RUNS_ROOT", tmp_path)

    state = run_state.create_run(
        goal="test goal",
        bundle_id="com.apple.Preferences",
        udid="SIM-1",
        max_steps=10,
        safe_mode=True,
        run_id="run_test",
    )
    assert state["run_id"] == "run_test"
    assert state["status"] == "running"

    run_state.append_event("run_test", {"type": "custom_event", "step": 1})
    run_state.append_history(state, {"step": 1, "tool": "tap", "result": "ok", "params": {}})
    run_state.increment_metric(state, "model_calls")
    run_state.finalize_run(state, "completed", "done", 1)

    loaded = run_state.load_state("run_test")
    assert loaded is not None
    assert loaded["status"] == "completed"
    assert loaded["summary"] == "done"
    assert loaded["last_step"] == 1
    assert loaded["metrics"]["model_calls"] == 1
    assert len(loaded["history"]) == 1


def test_run_state_list_and_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(run_state, "_RUNS_ROOT", tmp_path)

    state = run_state.create_run(
        goal="replay goal",
        bundle_id="com.apple.mobilesafari",
        udid="SIM-2",
        max_steps=5,
        safe_mode=False,
        run_id="run_replay",
    )
    run_state.append_event("run_replay", {"type": "step", "step": 1, "tool": "scroll"})
    run_state.append_history(state, {"step": 1, "tool": "scroll", "result": "SCROLLED", "params": {}})
    run_state.finalize_run(state, "paused", "pause here", 1)

    listed = run_state.list_runs(limit=5)
    assert listed
    assert listed[0]["run_id"] == "run_replay"
    assert listed[0]["status"] == "paused"

    replay = run_state.replay_run("run_replay")
    assert replay["run_id"] == "run_replay"
    assert replay["state"]["summary"] == "pause here"
    event_types = [row["type"] for row in replay["events"]]
    assert "run_started" in event_types
    assert "run_finished" in event_types

    paths = run_state.run_paths("run_replay")
    assert paths["run_dir"].endswith("run_replay")
    assert paths["state_path"].endswith("state.json")
