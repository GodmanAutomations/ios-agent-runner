import os

from scripts import idbwrap


def test_find_idb_prefers_project_venv(monkeypatch, tmp_path):
    fake_root = tmp_path / "proj"
    fake_idb = fake_root / ".venv" / "bin" / "idb"
    fake_idb.parent.mkdir(parents=True)
    fake_idb.write_text("#!/bin/sh\necho idb\n")

    monkeypatch.setattr(idbwrap, "_PROJECT_ROOT", str(fake_root))
    monkeypatch.setattr(idbwrap, "_idb_path", None)

    def isfile(path: str) -> bool:
        return os.path.abspath(path) == os.path.abspath(str(fake_idb))

    def access(path: str, mode: int) -> bool:
        return os.path.abspath(path) == os.path.abspath(str(fake_idb))

    monkeypatch.setattr(os.path, "isfile", isfile)
    monkeypatch.setattr(os, "access", access)

    found = idbwrap._find_idb()
    assert found == str(fake_idb)
