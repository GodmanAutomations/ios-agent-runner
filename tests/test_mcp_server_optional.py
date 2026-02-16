import json

import mcp_server


def test_ios_runtime_health_reports_feature_status(monkeypatch):
    def fake_status(module_name: str):
        if module_name.endswith("vision_extract"):
            return True, "ok"
        return False, "missing dependency"

    monkeypatch.setattr(mcp_server, "_optional_feature_status", fake_status)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    payload = json.loads(mcp_server.ios_runtime_health())

    assert payload["openai_key_set"] is True
    assert payload["features"]["vision_extract"]["available"] is True
    assert payload["features"]["local_ocr"]["available"] is False
    assert payload["features"]["local_ocr"]["detail"] == "missing dependency"


def test_ios_extract_photos_returns_error_when_module_unavailable(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "_load_optional_module",
        lambda module_name: (None, "import failed"),
    )

    payload = json.loads(mcp_server.ios_extract_photos())

    assert payload["error"] == "Vision extraction unavailable"
    assert payload["detail"] == "import failed"


def test_ios_local_ocr_returns_error_when_module_unavailable(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "_load_optional_module",
        lambda module_name: (None, "import failed"),
    )

    payload = json.loads(mcp_server.ios_local_ocr())

    assert payload["error"] == "Local OCR unavailable"
    assert payload["detail"] == "import failed"


def test_ios_list_runs_uses_run_state(monkeypatch):
    monkeypatch.setattr(
        mcp_server.run_state,
        "list_runs",
        lambda limit=20: [{"run_id": "run_1", "status": "completed"}],
    )

    payload = json.loads(mcp_server.ios_list_runs(limit=5))

    assert payload[0]["run_id"] == "run_1"
    assert payload[0]["status"] == "completed"


def test_ios_replay_run_uses_run_state(monkeypatch):
    monkeypatch.setattr(
        mcp_server.run_state,
        "replay_run",
        lambda run_id: {"run_id": run_id, "state": {"status": "paused"}, "events": []},
    )

    payload = json.loads(mcp_server.ios_replay_run("run_abc"))

    assert payload["run_id"] == "run_abc"
    assert payload["state"]["status"] == "paused"
