"""vision_extract.py - Batch OCR sweep screenshots through OpenAI vision, feed results into intel pipeline.

Takes a directory of sweep PNGs, sends each to gpt-4o-mini for text extraction,
then runs the extracted text through the intel pipeline for classification + persistence.

Uses OpenAI (free on Stephen's plan) instead of Anthropic to save API costs.
No simulator needed. Just reads PNGs and calls the API.
"""

import base64
import glob
import json
import os
import sys
import time
from typing import Any

from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
# Also load home .env for OPENAI_API_KEY
load_dotenv(os.path.expanduser("~/.env"))

from scripts import intel

VISION_MODEL = "gpt-4o-mini"

EXTRACT_PROMPT = """\
You are an OCR and data extraction tool. Look at this screenshot from an iPhone and extract ALL visible text and data.

Output a JSON object with these fields:
- "all_text": array of every readable text string on screen, in reading order
- "app_name": the app shown (if identifiable from UI)
- "device_name": if this shows a device config, the device name
- "ips": any IP addresses visible
- "macs": any MAC addresses visible
- "model": any model numbers or hardware identifiers
- "firmware": any firmware/software versions
- "network": any network info (SSID, connection type, band, wired/wireless)
- "settings": key settings visible (on/off toggles, values, modes)
- "description": one-sentence description of what this screenshot shows

Be thorough. Extract EVERYTHING. If a field has no data, use an empty array or empty string.
Return ONLY valid JSON, no markdown fences."""


def _log(msg: str) -> None:
    print(f"[vision] {msg}", file=sys.stderr)


def is_available() -> tuple[bool, str]:
    """Return whether OpenAI vision dependencies are configured."""
    try:
        import openai  # noqa: F401
    except Exception as exc:
        return False, f"OpenAI SDK unavailable: {exc}"

    if not os.getenv("OPENAI_API_KEY"):
        return False, "OPENAI_API_KEY is not set"

    return True, "ok"


def _build_openai_client() -> tuple[Any | None, str | None]:
    """Create an OpenAI client for vision requests."""
    try:
        from openai import OpenAI
    except Exception as exc:
        return None, f"OpenAI SDK unavailable: {exc}"

    if not os.getenv("OPENAI_API_KEY"):
        return None, "OPENAI_API_KEY is not set"

    try:
        return OpenAI(), None
    except Exception as exc:
        return None, f"OpenAI client init failed: {exc}"


def _image_to_b64(path: str) -> str:
    """Read a PNG and return base64-encoded string."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")


def extract_one(client: Any, image_path: str, max_retries: int = 3) -> dict | None:
    """Send one image to OpenAI vision, return parsed extraction dict.

    Retries on 429 rate limit errors with exponential backoff.
    """
    try:
        b64 = _image_to_b64(image_path)
    except (OSError, IOError) as e:
        _log(f"Failed to read {image_path}: {e}")
        return None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=VISION_MODEL,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"},
                        },
                        {"type": "text", "text": EXTRACT_PROMPT},
                    ],
                }],
            )

            text = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()
            if text.startswith("json"):
                text = text[4:].strip()

            return json.loads(text)

        except json.JSONDecodeError as e:
            _log(f"JSON parse error for {image_path}: {e}")
            _log(f"Raw response: {text[:200]}")
            return None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < max_retries:
                wait = 30 * (attempt + 1)  # 30s, 60s, 90s
                _log(f"Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait)
                continue
            _log(f"API error for {image_path}: {e}")
            return None

    return None


def _build_elements_from_extraction(data: dict) -> list[dict]:
    """Convert vision extraction data into fake accessibility elements for the intel pipeline."""
    elements = []
    for text in data.get("all_text", []):
        elements.append({"type": "StaticText", "label": text, "value": text})

    # Add structured fields as elements too
    for ip in data.get("ips", []):
        elements.append({"type": "StaticText", "label": "IP Address", "value": ip})
    for mac in data.get("macs", []):
        elements.append({"type": "StaticText", "label": "MAC Address", "value": mac})
    if data.get("model"):
        if isinstance(data["model"], list):
            for m in data["model"]:
                elements.append({"type": "StaticText", "label": "Model", "value": m})
        else:
            elements.append({"type": "StaticText", "label": "Model", "value": data["model"]})
    if data.get("firmware"):
        if isinstance(data["firmware"], list):
            for fw in data["firmware"]:
                elements.append({"type": "StaticText", "label": "Firmware", "value": fw})
        else:
            elements.append({"type": "StaticText", "label": "Firmware", "value": data["firmware"]})

    return elements


def process_batch(
    image_paths: list[str],
    delay: float = 0.5,
) -> list[dict]:
    """Process a batch of images through vision + intel pipeline.

    Returns list of extraction results with finding IDs.
    """
    client, error = _build_openai_client()
    if client is None:
        _log(error or "OpenAI client unavailable")
        return [
            {"path": path, "status": "failed", "error": error or "OpenAI client unavailable"}
            for path in image_paths
        ]

    results = []

    for i, path in enumerate(image_paths):
        _log(f"--- Image {i + 1}/{len(image_paths)}: {os.path.basename(path)} ---")

        data = extract_one(client, path)
        if not data:
            _log("Skipped (extraction failed)")
            results.append({"path": path, "status": "failed"})
            continue

        n_texts = len(data.get("all_text", []))
        desc = data.get("description", "")
        _log(f"Extracted {n_texts} texts: {desc}")

        # Build fake elements for intel pipeline
        elements = _build_elements_from_extraction(data)

        # Determine bundle ID from app name
        app = (data.get("app_name") or "unknown").lower()
        bundle_map = {
            "eero": "com.eero.eero",
            "hue": "com.philips.hue",
            "settings": "com.apple.Preferences",
            "photos": "com.apple.mobileslideshow",
            "safari": "com.apple.mobilesafari",
            "kasa": "com.tplink.kasa",
            "alexa": "com.amazon.echo",
            "google home": "com.google.chromecast",
            "nest": "com.google.nest",
        }
        bundle_id = "unknown"
        for key, bid in bundle_map.items():
            if key in app:
                bundle_id = bid
                break

        # Run through intel pipeline
        finding = intel.build_finding(
            elements=elements,
            bundle_id=bundle_id,
            screenshot_path=os.path.abspath(path),
            tree_path="",
            step=0,
            goal="photo_sweep_vision_extract",
        )

        # Add vision-specific tags
        finding.tags.append("vision_ocr")
        finding.tags.append("openai_gpt4o_mini")
        if data.get("device_name"):
            finding.tags.append(f"device:{data['device_name']}")
        if data.get("app_name"):
            finding.tags.append(f"app_detected:{data['app_name']}")

        # Store raw extraction as extracted_data supplement
        for key in ("ips", "macs", "model", "firmware", "network", "settings", "device_name"):
            val = data.get(key)
            if val:
                if isinstance(val, list) and val:
                    finding.extracted_data[key] = val
                elif isinstance(val, str) and val:
                    finding.extracted_data[key] = [val]
                elif isinstance(val, dict) and val:
                    finding.extracted_data[key] = val

        if finding.text_content:
            fid = intel.save_finding(finding)
            _log(f"Saved finding {fid}: {finding.category}")
            results.append({
                "path": path,
                "status": "ok",
                "finding_id": fid,
                "category": finding.category,
                "texts": n_texts,
                "description": desc,
                "extracted": finding.extracted_data,
            })
        else:
            _log("Skipped (no text content)")
            results.append({"path": path, "status": "empty"})

        # Rate limit courtesy
        if delay > 0:
            time.sleep(delay)

    # Summary
    ok = sum(1 for r in results if r.get("status") == "ok")
    failed = sum(1 for r in results if r.get("status") == "failed")
    empty = sum(1 for r in results if r.get("status") == "empty")
    _log(f"\nBatch complete: {ok} extracted, {failed} failed, {empty} empty")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Vision OCR extraction for sweep screenshots")
    parser.add_argument("path", nargs="?", default="_artifacts/",
                        help="Directory or glob pattern for sweep PNGs")
    parser.add_argument("--pattern", default="screenshot_sweep_*_photo_*.png",
                        help="Glob pattern within directory")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Delay between API calls (seconds)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max images to process (0 = all)")

    args = parser.parse_args()

    # Find images
    if os.path.isdir(args.path):
        pattern = os.path.join(args.path, args.pattern)
    else:
        pattern = args.path

    images = sorted(glob.glob(pattern))
    if not images:
        print(f"No images found matching: {pattern}")
        sys.exit(1)

    if args.limit > 0:
        images = images[:args.limit]

    print(f"Found {len(images)} images to process")

    results = process_batch(images, delay=args.delay)

    # Print summary
    print(f"\n{'='*60}")
    print(f"VISION EXTRACTION COMPLETE")
    print(f"{'='*60}")
    for r in results:
        status = r.get("status", "?")
        name = os.path.basename(r.get("path", ""))
        if status == "ok":
            desc = r.get("description", "")[:80]
            cat = r.get("category", "")
            print(f"  OK  {name}: [{cat}] {desc}")
        elif status == "failed":
            print(f"  FAIL {name}")
        else:
            print(f"  SKIP {name}")
