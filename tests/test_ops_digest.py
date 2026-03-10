from scripts.ops_digest import parse_adb_devices, parse_git_porcelain


def test_parse_git_porcelain_clean_branch():
    out = "## main...origin/main\n"
    res = parse_git_porcelain(out)
    assert res["ok"] is True
    assert res["branch"] == "main"
    assert res["dirty"] is False
    assert res["dirty_count"] == 0


def test_parse_git_porcelain_ahead_behind_dirty():
    out = "\n".join(
        [
            "## feature...origin/feature [ahead 2, behind 1]",
            " M file1.py",
            "?? new.txt",
        ]
    )
    res = parse_git_porcelain(out)
    assert res["ok"] is True
    assert res["branch"] == "feature"
    assert res["ahead"] == 2
    assert res["behind"] == 1
    assert res["dirty"] is True
    assert res["dirty_count"] == 2


def test_parse_adb_devices_parses_rows():
    sample = "\n".join(
        [
            "List of devices attached",
            "192.168.4.79:5555      device product:mdarcy model:SHIELD_Android_TV device:mdarcy transport_id:1",
            "2G0YC5ZG8F07NT         device transport_id:2",
            "",
        ]
    )
    rows = parse_adb_devices(sample)
    assert len(rows) == 2
    assert rows[0]["serial"] == "192.168.4.79:5555"
    assert rows[0]["state"] == "device"
    assert rows[0]["meta"]["model"] == "SHIELD_Android_TV"
    assert rows[1]["serial"] == "2G0YC5ZG8F07NT"

