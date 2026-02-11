"""Semantic element finding and interaction via fuzzy text matching."""

import sys

try:
    from thefuzz import fuzz as _fuzz

    def _score(query: str, candidate: str) -> int:
        return _fuzz.partial_ratio(query.lower(), candidate.lower())

except ImportError:
    from difflib import SequenceMatcher

    def _score(query: str, candidate: str) -> int:
        ratio = SequenceMatcher(None, query.lower(), candidate.lower()).ratio()
        return int(ratio * 100)

from scripts.screen_mapper import get_element_center, parse_tree, flatten_elements


def _log(msg: str) -> None:
    print(f"[nav] {msg}", file=sys.stderr)


def find_element(text: str, elements: list, threshold: int = 60):
    """Find best matching element from flattened elements list.

    Returns (element, score) for best match above threshold,
    or (None, 0) if no match.
    """
    best_el = None
    best_score = 0

    for el in elements:
        searchable = el.get("searchable_text", "")
        if not searchable:
            continue
        score = _score(text, searchable)
        if score > best_score:
            best_score = score
            best_el = el

    if best_score >= threshold:
        _log(f"find_element: '{text}' -> '{best_el.get('searchable_text', '')}' (score={best_score})")
        return (best_el, best_score)

    _log(f"find_element: '{text}' -> no match above threshold {threshold} (best={best_score})")
    return (None, 0)


def find_candidates(text: str, elements: list, threshold: int = 50, limit: int = 5):
    """Return top N candidates sorted by score descending.

    Returns list of (element, score) tuples.
    """
    scored = []
    for el in elements:
        searchable = el.get("searchable_text", "")
        if not searchable:
            continue
        score = _score(text, searchable)
        if score >= threshold:
            scored.append((el, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    results = scored[:limit]
    _log(f"find_candidates: '{text}' -> {len(results)} candidates (threshold={threshold})")
    return results


def tap_element(text: str, elements: list, idb_module, udid: str) -> bool:
    """Find element by text, compute center, tap via idb_module.

    Returns True on success, False on failure.
    """
    el, score = find_element(text, elements)
    if el is None:
        _log(f"tap_element: could not find '{text}'")
        return False

    center = get_element_center(el)
    if center is None:
        _log(f"tap_element: no center for element '{el.get('searchable_text', '')}'")
        return False

    x, y = center
    _log(f"tap_element: tapping '{text}' at ({x}, {y})")
    idb_module.tap(udid, x, y)
    return True


def retry_with_alternatives(
    text: str,
    alternatives: list,
    elements: list,
    idb_module,
    udid: str,
    screen_mapper_module,
):
    """Self-correction loop: try primary text, then alternatives with re-dump.

    Returns (success: bool, matched_text: str or None, reasoning: str).
    """
    # Try primary text first
    el, score = find_element(text, elements)
    if el is not None:
        center = get_element_center(el)
        if center is not None:
            x, y = center
            idb_module.tap(udid, x, y)
            reasoning = f"Matched primary text '{text}' (score={score})"
            _log(f"retry_with_alternatives: {reasoning}")
            return (True, text, reasoning)

    reasoning_parts = [f"Primary text '{text}' failed (score={score})"]

    # Re-dump accessibility tree and re-flatten
    _log("retry_with_alternatives: re-dumping accessibility tree")
    raw_tree = idb_module.describe_all(udid)
    parsed = screen_mapper_module.parse_tree(raw_tree)
    fresh_elements = screen_mapper_module.flatten_elements(parsed)

    for alt in alternatives:
        el, score = find_element(alt, fresh_elements)
        if el is not None:
            center = get_element_center(el)
            if center is not None:
                x, y = center
                idb_module.tap(udid, x, y)
                reasoning = f"Alternative '{alt}' matched (score={score}) after re-dump"
                reasoning_parts.append(reasoning)
                full_reasoning = "; ".join(reasoning_parts)
                _log(f"retry_with_alternatives: {full_reasoning}")
                return (True, alt, full_reasoning)
            else:
                reasoning_parts.append(f"Alternative '{alt}' found but no center coords")
        else:
            reasoning_parts.append(f"Alternative '{alt}' no match (score={score})")

    full_reasoning = "; ".join(reasoning_parts)
    _log(f"retry_with_alternatives: all alternatives exhausted. {full_reasoning}")
    return (False, None, full_reasoning)


def type_after_tap(text: str, type_text: str, elements: list, idb_module, udid: str) -> bool:
    """Tap element then type text. Convenience wrapper.

    Returns True on success, False if tap failed.
    """
    if not tap_element(text, elements, idb_module, udid):
        return False

    _log(f"type_after_tap: typing '{type_text}'")
    idb_module.type_text(udid, type_text)
    return True
