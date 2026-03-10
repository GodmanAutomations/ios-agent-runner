#!/usr/bin/env bash
# film_demo.sh — Record the Iron Man demo (terminal + optional sim video)
#
# Runs seed_demo.sh --run-agent (seeding + agent in one pass to avoid
# message persistence issues), with filtered output:
#   - Seeding phase: single "Preparing..." line with dots
#   - Agent phase: full output
#
# Usage:
#   ./film_demo.sh                              # just run it
#   asciinema rec -c ./film_demo.sh demo.cast   # record terminal
#   ./film_demo.sh --with-video                 # also capture sim video

set -euo pipefail
cd "$(dirname "$0")"

UDID="50ADC92B-85DA-40D3-BCE4-34985F363B60"
WITH_VIDEO=false
[[ "${1:-}" == "--with-video" ]] && WITH_VIDEO=true

source .venv/bin/activate 2>/dev/null

# Start simulator video recording if requested
SIM_VIDEO=""
if $WITH_VIDEO; then
    SIM_VIDEO="/tmp/ironman_sim_$(date +%Y%m%d_%H%M%S).mp4"
    xcrun simctl io "$UDID" recordVideo --codec h264 "$SIM_VIDEO" &
    VIDEO_PID=$!
    sleep 1
fi

# Run seed + agent in one pass.
# Seeding output (==> lines) gets condensed to progress dots.
# Agent output (everything after "Running agent") shown in full.
./seed_demo.sh --run-agent 2>&1 | awk '
    BEGIN { seeding = 1 }
    seeding && /^==>/ {
        printf "." > "/dev/stderr"
        next
    }
    /Running agent/ {
        seeding = 0
        printf "\n" > "/dev/stderr"
        print ""
        print "┌─────────────────────────────────────────────────────────┐"
        print "│  ios-agent-runner — Iron Man Demo                       │"
        print "│  A client texted an order. The AI agent handles it.     │"
        print "└─────────────────────────────────────────────────────────┘"
        print ""
        next
    }
    seeding { next }
    !seeding { print }
'

# Stop simulator video
if $WITH_VIDEO && [[ -n "${VIDEO_PID:-}" ]]; then
    kill "$VIDEO_PID" 2>/dev/null || true
    wait "$VIDEO_PID" 2>/dev/null || true
    echo ""
    echo "Simulator video saved: $SIM_VIDEO"
fi
