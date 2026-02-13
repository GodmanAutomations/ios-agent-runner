#!/usr/bin/env python3
"""Run vision extraction on all unprocessed sweep photos.

Checks the intel store for already-processed files and skips them.
Uses a longer delay to respect OpenAI free-tier rate limits (200k TPM).
"""

import glob
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
load_dotenv(os.path.expanduser("~/.env"))

from scripts import intel, vision_extract


def main():
    # Find all sweep photos
    artifacts_dir = os.path.join(_PROJECT_ROOT, "_artifacts")
    all_photos = sorted(glob.glob(os.path.join(artifacts_dir, "screenshot_sweep_*_photo_*.png")))
    print(f"Total sweep photos on disk: {len(all_photos)}")

    # Load existing findings to skip already-processed
    existing = intel.load_all_findings()
    processed_paths = set()
    for f in existing:
        p = f.get("screenshot_path", "")
        if p:
            processed_paths.add(os.path.abspath(p))

    # Filter to unprocessed only
    to_process = [p for p in all_photos if os.path.abspath(p) not in processed_paths]
    print(f"Already processed: {len(all_photos) - len(to_process)}")
    print(f"To process: {len(to_process)}")

    if not to_process:
        print("Nothing to process!")
        return

    # With detail="low", each image is ~2k tokens instead of ~100k
    # 200k TPM limit / ~5k per request ≈ 40 per minute
    # Using 1s delay + retry logic in extract_one handles any spikes
    batch_size = 20
    delay = 1.0  # seconds between images
    batch_pause = 10  # seconds between batches

    total_ok = 0
    total_fail = 0
    total_empty = 0

    for i in range(0, len(to_process), batch_size):
        batch = to_process[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(to_process) + batch_size - 1) // batch_size
        print(f"\n{'='*60}")
        print(f"BATCH {batch_num}/{total_batches} ({len(batch)} images)")
        print(f"{'='*60}")

        results = vision_extract.process_batch(batch, delay=delay)

        ok = sum(1 for r in results if r.get("status") == "ok")
        failed = sum(1 for r in results if r.get("status") == "failed")
        empty = sum(1 for r in results if r.get("status") == "empty")
        total_ok += ok
        total_fail += failed
        total_empty += empty

        print(f"Batch {batch_num}: {ok} ok, {failed} failed, {empty} empty")
        print(f"Running total: {total_ok} ok, {total_fail} failed, {total_empty} empty")

        # Pause between batches
        if i + batch_size < len(to_process):
            print(f"Pausing {batch_pause}s between batches...")
            time.sleep(batch_pause)

    print(f"\n{'='*60}")
    print(f"ALL DONE: {total_ok} extracted, {total_fail} failed, {total_empty} empty")
    print(f"Total findings in store: {len(intel.load_all_findings())}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
