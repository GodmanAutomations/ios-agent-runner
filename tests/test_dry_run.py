from scripts import dry_run, run_state


def test_dry_run_validate_ok_with_existing_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(run_state, "_RUNS_ROOT", tmp_path / "runs")

    state = run_state.create_run(
        goal="g",
        bundle_id="com.apple.Preferences",
        udid="SIM",
        max_steps=5,
        safe_mode=True,
        run_id="run_dry",
    )
    # Persist policy metadata for validator.
    state["policy"] = {
        "allow_tap_xy": False,
        "allowed_bundle_prefixes": ["com.apple."],
    }
    run_state.save_state(state)

    shot = tmp_path / "shot.png"
    tree = tmp_path / "tree.json"
    shot.write_bytes(b"png")
    tree.write_text("{}")

    run_state.append_history(
        state,
        {
            "step": 1,
            "tool": "open_app",
            "params": {"bundle_id": "com.apple.Preferences"},
            "result": "OPENED com.apple.Preferences",
            "screenshot_path": str(shot),
            "tree_path": str(tree),
        },
    )

    report = dry_run.validate_run("run_dry", strict=True)
    assert report["ok"] is True
    assert report["counts"]["steps"] == 1


def test_dry_run_policy_violation_is_warning_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(run_state, "_RUNS_ROOT", tmp_path / "runs")

    state = run_state.create_run(
        goal="g",
        bundle_id="com.apple.Preferences",
        udid="SIM",
        max_steps=5,
        safe_mode=True,
        run_id="run_violation",
    )
    state["policy"] = {"allow_tap_xy": False, "allowed_bundle_prefixes": ["com.apple."]}
    run_state.save_state(state)

    run_state.append_history(
        state,
        {
            "step": 1,
            "tool": "tap_xy",
            "params": {"x": 1, "y": 2},
            "result": "TAPPED coordinates (1, 2)",
        },
    )

    report = dry_run.validate_run("run_violation", strict=False)
    assert report["ok"] is True  # warnings only
    assert report["warnings"]
