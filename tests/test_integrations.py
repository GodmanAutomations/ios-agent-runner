from scripts.integrations import figma_api, linear_api, notion_api, sentry_api


def test_notion_is_available_false_without_token(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    ok, detail = notion_api.is_available()
    assert ok is False
    assert "NOTION_TOKEN" in detail


def test_linear_is_available_false_without_token(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    ok, detail = linear_api.is_available()
    assert ok is False
    assert "LINEAR_API_KEY" in detail


def test_sentry_is_available_false_without_token(monkeypatch):
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    ok, detail = sentry_api.is_available()
    assert ok is False
    assert "SENTRY_AUTH_TOKEN" in detail


def test_figma_is_available_false_without_token(monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    ok, detail = figma_api.is_available()
    assert ok is False
    assert "FIGMA_TOKEN" in detail


def test_figma_file_meta_slims_large_document(monkeypatch):
    monkeypatch.setenv("FIGMA_TOKEN", "x")

    def fake_request_json(method, url, headers=None, body=None, timeout=20):
        assert method == "GET"
        assert url.startswith("https://api.figma.com/v1/files/")
        assert headers and "X-Figma-Token" in headers
        return {
            "ok": True,
            "status": 200,
            "data": {
                "name": "File Name",
                "lastModified": "2026-01-01T00:00:00Z",
                "version": "1",
                "role": "owner",
                "editorType": "figma",
                "thumbnailUrl": "https://thumb",
                "linkAccess": "view",
                "document": {"massive": True},
            },
            "error": "",
        }

    monkeypatch.setattr(figma_api, "request_json", fake_request_json)

    res = figma_api.file_meta("abc")
    assert res["ok"] is True
    assert "document" not in res["data"]
    assert res["data"]["name"] == "File Name"
