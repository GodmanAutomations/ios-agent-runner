import json
import re
from datetime import datetime

import pytest

from scripts import intel


@pytest.fixture()
def isolated_paths(tmp_path, monkeypatch):
    store = tmp_path / "ios_intel.jsonl"
    memory = tmp_path / "memory" / "ios-discoveries.md"
    monkeypatch.setattr(intel, "_INTEL_STORE", str(store))
    monkeypatch.setattr(intel, "_MEMORY_FILE", str(memory))
    return store, memory


def test_extract_all_text_empty_input():
    assert intel.extract_all_text([]) == []


def test_extract_all_text_uses_all_fields_dedups_and_skips_whitespace():
    elements = [
        {"label": "  Wi-Fi  ", "name": " Settings ", "value": "", "title": None},
        {"label": "Wi-Fi", "name": "   ", "value": " Router ", "title": "Router"},
        {"label": "   ", "name": "Device", "value": 123, "title": "  "},
    ]

    assert intel.extract_all_text(elements) == ["Wi-Fi", "Settings", "Router", "Device"]


@pytest.mark.parametrize(
    ("elements", "bundle_id", "expected"),
    [
        (
            [{"label": "IP Address 192.168.1.10"}, {"label": "DNS Settings"}],
            "",
            intel.ScreenCategory.NETWORK_CONFIG,
        ),
        (
            [{"label": "Model RX-V6A"}, {"label": "Firmware 1.2.3"}],
            "",
            intel.ScreenCategory.DEVICE_SETTINGS,
        ),
        (
            [{"label": "Password"}, {"label": "API key"}],
            "",
            intel.ScreenCategory.CREDENTIALS,
        ),
        (
            [{"label": "HDMI output"}, {"label": "120Hz"}],
            "",
            intel.ScreenCategory.AV_CONFIG,
        ),
        (
            [{"label": "Photos"}, {"label": "Albums"}],
            "",
            intel.ScreenCategory.PHOTO_GALLERY,
        ),
    ],
)
def test_classify_screen_pattern_categories(elements, bundle_id, expected):
    assert intel.classify_screen(elements, bundle_id) == expected


def test_classify_screen_photo_bundle_shortcut_wins():
    elements = [{"label": "Nothing matching patterns"}]
    assert intel.classify_screen(elements, "com.apple.mobileslideshow") == intel.ScreenCategory.PHOTO_GALLERY


def test_classify_screen_text_content_heuristic():
    long_text = "lorem ipsum dolor sit amet consectetur adipiscing elit " * 5
    elements = [
        {"type": "StaticText", "label": long_text},
        {"type": "StaticText", "label": long_text + "more words"},
        {"type": "StaticText", "label": long_text + "final words"},
        {"type": "Button", "label": "Continue"},
    ]

    assert intel.classify_screen(elements, "") == intel.ScreenCategory.TEXT_CONTENT


def test_classify_screen_falls_back_to_app_ui():
    elements = [{"label": "Tap here"}, {"name": "Continue"}]
    assert intel.classify_screen(elements, "") == intel.ScreenCategory.APP_UI


def test_classify_screen_unknown_category_when_unknown_pattern_scores(monkeypatch):
    monkeypatch.setitem(intel._CATEGORY_PATTERNS, intel.ScreenCategory.UNKNOWN, [r"mysterytoken"])
    elements = [{"label": "mysterytoken"}]
    assert intel.classify_screen(elements, "") == intel.ScreenCategory.UNKNOWN


def test_extract_structured_empty_input():
    assert intel.extract_structured([]) == {}


def test_extract_structured_all_patterns_and_deduplication():
    texts = [
        "IP Address: 192.168.0.10",
        "Backup IP 192.168.0.10",
        "MAC: AA:BB:CC:DD:EE:FF",
        "Secondary MAC AA-BB-CC-DD-EE-FF",
        "Model RX-V6A",
        "Model OLED65C9PUA",
        "Model LCA003",
        "Firmware: 1.2.3",
        "ver 1.2.3",
        "Version 2.0.1",
        "Visit https://example.com/setup",
        "Mirror https://example.com/setup",
        "Port: 8080",
        "Resolution 3840x2160",
        "SSID: HomeNet",
        "Network Guest-WiFi",
        "Current temp 72\u00b0C and ambient 23\u00b0F",
    ]

    extracted = intel.extract_structured(texts)

    assert extracted["ips"] == ["192.168.0.10"]
    assert extracted["macs"] == ["AA:BB:CC:DD:EE:FF", "AA-BB-CC-DD-EE-FF"]
    assert extracted["model_numbers"] == ["RX-V6A", "OLED65C9PUA", "LCA003"]
    assert extracted["firmware"] == ["1.2.3", "2.0.1"]
    assert extracted["urls"] == ["https://example.com/setup"]
    assert extracted["ports"] == ["8080"]
    assert extracted["resolutions"] == ["3840x2160"]
    assert extracted["ssids"] == ["HomeNet", "Guest-WiFi"]
    assert extracted["temperatures"] == ["72\u00b0C", "23\u00b0F"]


def test_build_finding_sets_expected_fields_category_tags_and_id():
    elements = [
        {"label": "IP Address 10.0.0.5", "name": "Router", "value": "Port: 8080", "title": "Router"},
        {"label": "Visit https://example.com/setup"},
    ]

    finding = intel.build_finding(
        elements=elements,
        bundle_id="com.example.settings",
        screenshot_path="shots/screen-01.png",
        tree_path="trees/screen-01.json",
        step=7,
        goal="Collect network settings",
    )

    assert finding.category == intel.ScreenCategory.NETWORK_CONFIG.value
    assert finding.source_app == "com.example.settings"
    assert finding.screenshot_path == "shots/screen-01.png"
    assert finding.tree_path == "trees/screen-01.json"
    assert finding.step == 7
    assert finding.goal == "Collect network settings"
    assert finding.text_content == ["IP Address 10.0.0.5", "Router", "Port: 8080", "Visit https://example.com/setup"]
    assert finding.extracted_data["ips"] == ["10.0.0.5"]
    assert finding.extracted_data["ports"] == ["8080"]
    assert finding.extracted_data["urls"] == ["https://example.com/setup"]
    assert re.fullmatch(r"[0-9a-f]{12}", finding.finding_id)
    datetime.fromisoformat(finding.timestamp)

    tags = set(finding.tags)
    assert intel.ScreenCategory.NETWORK_CONFIG.value in tags
    assert "app:com.example.settings" in tags
    assert "ips:10.0.0.5" in tags
    assert "ports:8080" in tags
    assert "urls:https://example.com/setup" in tags


def test_save_and_load_findings_round_trip_with_append_only_behavior(isolated_paths):
    store, memory = isolated_paths

    assert intel.load_all_findings() == []

    finding_one = intel.build_finding(
        elements=[{"label": "IP Address 10.0.0.1"}],
        bundle_id="com.example.router",
        screenshot_path="screen-1.png",
        tree_path="tree-1.json",
        step=1,
        goal="First capture",
    )
    finding_two = intel.build_finding(
        elements=[{"label": "Password token"}, {"label": "Port: 443"}],
        bundle_id="com.example.auth",
        screenshot_path="screen-2.png",
        tree_path="tree-2.json",
        step=2,
        goal="Second capture",
    )

    id_one = intel.save_finding(finding_one)
    first_write = store.read_text().splitlines()
    assert len(first_write) == 1

    id_two = intel.save_finding(finding_two)
    second_write = store.read_text().splitlines()
    assert len(second_write) == 2
    assert second_write[0] == first_write[0]

    loaded = intel.load_all_findings()
    assert len(loaded) == 2
    assert [entry["finding_id"] for entry in loaded] == [id_one, id_two]
    assert memory.exists()
    assert "Total findings: 2" in memory.read_text()


def test_search_findings_filters_keyword_category_since_and_case_insensitive(isolated_paths):
    store, _ = isolated_paths

    seeded = [
        {
            "timestamp": "2025-01-01T10:00:00",
            "category": intel.ScreenCategory.NETWORK_CONFIG.value,
            "source_app": "com.router.app",
            "screenshot_path": "screen-1.png",
            "tree_path": "tree-1.json",
            "text_content": ["Router Token ABC123"],
            "extracted_data": {"ips": ["10.0.0.1"]},
            "tags": ["network_config", "env:lab"],
            "step": 1,
            "goal": "Network audit",
            "finding_id": "111111111111",
        },
        {
            "timestamp": "2025-01-02T10:00:00",
            "category": intel.ScreenCategory.CREDENTIALS.value,
            "source_app": "com.auth.app",
            "screenshot_path": "screen-2.png",
            "tree_path": "tree-2.json",
            "text_content": ["Password reset page"],
            "extracted_data": {"urls": ["https://auth.example.com"]},
            "tags": ["credentials", "auth"],
            "step": 2,
            "goal": "Credential capture",
            "finding_id": "222222222222",
        },
        {
            "timestamp": "2025-01-03T10:00:00",
            "category": intel.ScreenCategory.NETWORK_CONFIG.value,
            "source_app": "com.router.app",
            "screenshot_path": "screen-3.png",
            "tree_path": "tree-3.json",
            "text_content": ["Status panel"],
            "extracted_data": {"urls": ["https://status.example.com"]},
            "tags": ["network_config"],
            "step": 3,
            "goal": "Health check",
            "finding_id": "333333333333",
        },
    ]
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("\n".join(json.dumps(item) for item in seeded) + "\n")

    keyword = intel.search_findings(query="TOKEN")
    category = intel.search_findings(category=intel.ScreenCategory.NETWORK_CONFIG.value)
    since = intel.search_findings(since="2025-01-02T00:00:00")
    combined = intel.search_findings(
        query="status.example.com",
        category=intel.ScreenCategory.NETWORK_CONFIG.value,
        since="2025-01-03T00:00:00",
    )
    case_insensitive = intel.search_findings(query="password")

    assert [item["finding_id"] for item in keyword] == ["111111111111"]
    assert [item["finding_id"] for item in category] == ["111111111111", "333333333333"]
    assert [item["finding_id"] for item in since] == ["222222222222", "333333333333"]
    assert [item["finding_id"] for item in combined] == ["333333333333"]
    assert [item["finding_id"] for item in case_insensitive] == ["222222222222"]
