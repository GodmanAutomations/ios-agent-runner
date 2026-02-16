from scripts import doctor


def test_doctor_collect_checks_contains_expected_keys(monkeypatch):
    # Avoid actually running subprocesses in unit test.
    monkeypatch.setattr(doctor, "_check_osascript_permissions", lambda: {"ok": True})
    monkeypatch.setattr(doctor, "_check_git_origin", lambda: {"origin_url": "git@github.com:x/y.git", "is_ssh": True})
    monkeypatch.setattr(doctor, "_check_gh_auth", lambda: {"ok": True, "scopes": "repo, workflow"})
    monkeypatch.setattr(doctor, "_check_idb", lambda: {"ok": True})
    monkeypatch.setattr(doctor, "_check_mcp_importable_in_venv", lambda: {"ok": True})
    monkeypatch.setattr(doctor, "_check_adb_devices", lambda: {"ok": True})

    payload = doctor.collect_checks()

    assert "ok" in payload
    assert "macos_automation" in payload
    assert "git" in payload
    assert "tools" in payload
