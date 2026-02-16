from scripts import local_ocr, vision_extract


def test_local_ocr_reports_unavailable_when_frameworks_missing(monkeypatch):
    monkeypatch.setattr(local_ocr, "Cocoa", None)
    monkeypatch.setattr(local_ocr, "Vision", None)
    monkeypatch.setattr(local_ocr, "_IMPORT_ERROR", "missing framework")

    available, detail = local_ocr.is_available()

    assert available is False
    assert "missing framework" in detail


def test_local_ocr_process_batch_returns_failed_when_unavailable(monkeypatch):
    monkeypatch.setattr(local_ocr, "Cocoa", None)
    monkeypatch.setattr(local_ocr, "Vision", None)
    monkeypatch.setattr(local_ocr, "_IMPORT_ERROR", "missing framework")

    results = local_ocr.process_batch(["a.png", "b.png"])

    assert [item["status"] for item in results] == ["failed", "failed"]
    assert "missing framework" in results[0]["error"]


def test_vision_extract_process_batch_returns_failed_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(
        vision_extract,
        "_build_openai_client",
        lambda: (None, "OPENAI_API_KEY is not set"),
    )

    results = vision_extract.process_batch(["one.png", "two.png"], delay=0)

    assert [item["status"] for item in results] == ["failed", "failed"]
    assert results[0]["error"] == "OPENAI_API_KEY is not set"


def test_vision_extract_is_available_false_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    available, detail = vision_extract.is_available()

    assert available is False
    assert "OPENAI_API_KEY" in detail or "OpenAI SDK unavailable" in detail
