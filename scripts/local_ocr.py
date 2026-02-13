"""local_ocr.py - Bulk OCR using macOS Vision framework. Zero API calls, runs on-device.

Uses Apple's VNRecognizeTextRequest for text recognition. Feeds extracted text
through the intel pipeline for classification + persistence.

Speed: ~0.3s per image on M5. 200 photos in ~60 seconds.
"""

import glob
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import Cocoa
import Vision

from scripts import intel


def _log(msg: str) -> None:
    print(f"[local_ocr] {msg}", file=sys.stderr)


def ocr_one(image_path: str) -> list[str]:
    """Run local OCR on a single image. Returns list of recognized text strings."""
    try:
        img = Cocoa.NSImage.alloc().initWithContentsOfFile_(image_path)
        if img is None:
            _log(f"Failed to load image: {image_path}")
            return []

        ci_image = Cocoa.CIImage.imageWithData_(img.TIFFRepresentation())
        if ci_image is None:
            return []

        handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(ci_image, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(1)  # accurate mode

        success, error = handler.performRequests_error_([request], None)
        if not success:
            _log(f"OCR failed for {image_path}: {error}")
            return []

        texts = []
        for obs in request.results():
            candidates = obs.topCandidates_(1)
            if candidates:
                text = candidates[0].string()
                if text and text.strip():
                    texts.append(text.strip())

        return texts

    except Exception as e:
        _log(f"Error processing {image_path}: {e}")
        return []


def process_batch(image_paths: list[str]) -> list[dict]:
    """Process a batch of images through local OCR + intel pipeline.

    Returns list of result dicts with status and finding IDs.
    """
    results = []

    for i, path in enumerate(image_paths):
        _log(f"[{i + 1}/{len(image_paths)}] {os.path.basename(path)}")

        texts = ocr_one(path)
        if not texts:
            results.append({"path": path, "status": "empty"})
            continue

        # Build fake accessibility elements for the intel pipeline
        elements = [{"type": "StaticText", "label": t, "value": t} for t in texts]

        # Run through intel pipeline
        finding = intel.build_finding(
            elements=elements,
            bundle_id="local_ocr",
            screenshot_path=os.path.abspath(path),
            tree_path="",
            step=0,
            goal="local_ocr_batch",
        )

        finding.tags.append("local_ocr")
        finding.tags.append("macos_vision")

        if finding.text_content:
            fid = intel.save_finding(finding)
            results.append({
                "path": path,
                "status": "ok",
                "finding_id": fid,
                "category": finding.category,
                "texts": len(texts),
                "extracted": finding.extracted_data,
            })
        else:
            results.append({"path": path, "status": "empty"})

    ok = sum(1 for r in results if r.get("status") == "ok")
    empty = sum(1 for r in results if r.get("status") == "empty")
    _log(f"Batch complete: {ok} extracted, {empty} empty")
    return results


def run_unprocessed():
    """Find and process all unprocessed sweep photos."""
    artifacts_dir = os.path.join(_PROJECT_ROOT, "_artifacts")
    all_photos = sorted(glob.glob(os.path.join(artifacts_dir, "screenshot_sweep_*_photo_*.png")))
    print(f"Total sweep photos on disk: {len(all_photos)}")

    # Skip already-processed
    existing = intel.load_all_findings()
    processed_paths = set()
    for f in existing:
        p = f.get("screenshot_path", "")
        if p:
            processed_paths.add(os.path.abspath(p))

    to_process = [p for p in all_photos if os.path.abspath(p) not in processed_paths]
    print(f"Already processed: {len(all_photos) - len(to_process)}")
    print(f"To process: {len(to_process)}")

    if not to_process:
        print("Nothing to process!")
        return

    start = time.time()
    results = process_batch(to_process)
    elapsed = time.time() - start

    ok = sum(1 for r in results if r.get("status") == "ok")
    empty = sum(1 for r in results if r.get("status") == "empty")

    print(f"\n{'='*60}")
    print(f"LOCAL OCR COMPLETE in {elapsed:.1f}s ({elapsed/len(to_process):.2f}s/image)")
    print(f"Extracted: {ok} | Empty: {empty}")
    print(f"Total findings in store: {len(intel.load_all_findings())}")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_unprocessed()
