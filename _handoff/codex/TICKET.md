# TICKET

## Title
Build comprehensive test suite for scripts/intel.py

## Scope
Write unit tests for ALL public functions in `scripts/intel.py`:
- `extract_all_text(elements)` — text extraction from accessibility elements
- `classify_screen(elements, bundle_id)` — screen category classification
- `extract_structured(texts)` — regex extraction of IPs, MACs, models, firmware, URLs, etc.
- `build_finding(elements, bundle_id, screenshot_path, tree_path, step, goal)` — full pipeline
- `save_finding(finding)` and `load_all_findings()` — JSONL persistence
- `search_findings(query, category, since)` — search/filter

Create: `tests/__init__.py` and `tests/test_intel.py`

Test cases needed:
1. extract_all_text: empty input, all field types (label/name/value/title), dedup, whitespace skip
2. classify_screen: each ScreenCategory has at least one test, bundle_id shortcut for Photos, fallback to APP_UI
3. extract_structured: IPv4, MAC (colon+dash), model numbers (RX-V6A, OLED65C9PUA, LCA003), firmware versions, URLs, ports, resolutions, SSIDs, temperatures, empty input, deduplication
4. build_finding: correct fields, category set, tags populated, finding_id is 12-char hex
5. save/load round-trip: use tmp_path, monkeypatch _INTEL_STORE and _MEMORY_FILE paths, verify append-only behavior
6. search_findings: keyword, category, since, combined filters, case-insensitive

## Forbidden Areas
- Do NOT modify any existing source files
- Do NOT touch .env or any secrets
- Do NOT run the agent loop or make API calls
- Do NOT write to ~/.ulan/ or ~/.claude/ (use tmp_path)

## Verification Commands
- [ ] `source .venv/bin/activate && pip install pytest`
- [ ] `source .venv/bin/activate && python -m pytest tests/test_intel.py -v`

## Notes
- Pure Python tests, no simulator, no network, no API calls
- Use pytest tmp_path fixture + monkeypatch for file I/O isolation
- Target: all tests pass, thorough edge case coverage
