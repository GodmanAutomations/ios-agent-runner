#!/usr/bin/env bash
# record_demo.sh — Boot iPhone 15 Pro sim, record VHS demo + simulator video
#
# Prerequisites:
#   brew install charmbracelet/tap/vhs ffmpeg
#
# Usage:
#   ./record_demo.sh              # record terminal only (VHS)
#   ./record_demo.sh --with-sim   # also record simulator video and merge

set -euo pipefail
cd "$(dirname "$0")"

SIM_NAME="iPhone 15 Pro"
WITH_SIM=false
SIM_VIDEO="demo_sim.mp4"
MERGED_OUTPUT="demo_merged.mp4"

if [[ "${1:-}" == "--with-sim" ]]; then
    WITH_SIM=true
fi

echo "==> Booting $SIM_NAME simulator..."
UDID=$(xcrun simctl list devices available | grep "$SIM_NAME" | head -1 | grep -oE '[0-9A-F-]{36}')
if [[ -z "$UDID" ]]; then
    echo "FATAL: $SIM_NAME simulator not found"
    exit 1
fi
xcrun simctl boot "$UDID" 2>/dev/null || true
sleep 3
echo "==> Simulator booted: $UDID"

# Verify device config detection
echo "==> Verifying device config..."
.venv/bin/python -c "from scripts.device_config import detect; c = detect('$UDID'); print(f'Screen: {c.width}x{c.height} @{c.scale}x')"

# Start simulator video recording if requested
SIM_REC_PID=""
if $WITH_SIM; then
    echo "==> Starting simulator video recording..."
    xcrun simctl io "$UDID" recordVideo "$SIM_VIDEO" &
    SIM_REC_PID=$!
    sleep 1
fi

# Run VHS tape
echo "==> Recording VHS demo..."
vhs demo.tape

# Stop simulator video
if [[ -n "$SIM_REC_PID" ]]; then
    echo "==> Stopping simulator recording..."
    kill -INT "$SIM_REC_PID" 2>/dev/null || true
    wait "$SIM_REC_PID" 2>/dev/null || true
    sleep 1

    # Merge terminal GIF and simulator video side-by-side
    if command -v ffmpeg &>/dev/null && [[ -f "$SIM_VIDEO" ]]; then
        echo "==> Merging terminal + simulator recordings..."
        ffmpeg -y -i demo.gif -i "$SIM_VIDEO" \
            -filter_complex "[0:v]scale=-1:800[left];[1:v]scale=-1:800[right];[left][right]hstack=inputs=2" \
            "$MERGED_OUTPUT" 2>/dev/null
        echo "==> Merged output: $MERGED_OUTPUT"
    fi
fi

echo "==> Done! Outputs:"
echo "    Terminal GIF: demo.gif"
[[ -f "$SIM_VIDEO" ]] && echo "    Sim video:    $SIM_VIDEO"
[[ -f "$MERGED_OUTPUT" ]] && echo "    Merged:       $MERGED_OUTPUT"
