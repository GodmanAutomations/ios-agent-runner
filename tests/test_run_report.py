from pathlib import Path

from scripts import run_report, run_state


def test_render_run_report_writes_html(tmp_path, monkeypatch):
    monkeypatch.setattr(run_state, "_RUNS_ROOT", tmp_path / "runs")

    state = run_state.create_run(
        goal="hello",
        bundle_id="com.apple.Preferences",
        udid="SIM",
        max_steps=3,
        safe_mode=True,
        run_id="run_report",
    )

    # Create fake artifacts and include in history for linking.
    shot = tmp_path / "shot.png"
    tree = tmp_path / "tree.json"
    shot.write_bytes(b"png")
    tree.write_text("{}")

    run_state.append_history(
        state,
        {
            "step": 1,
            "tool": "tap",
            "params": {"text": "Wi-Fi"},
            "result": "TAPPED 'Wi-Fi'",
            "screenshot_path": str(shot),
            "tree_path": str(tree),
        },
    )
    run_state.finalize_run(state, "completed", "ok", 1)

    out = run_report.render_run_report("run_report")
    assert out is not None
    out_path = Path(out)
    assert out_path.exists()
    html = out_path.read_text()
    assert "run_report" in html
    assert "Steps" in html
