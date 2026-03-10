#!/usr/bin/env bash
# seed_demo.sh — Prepare the simulator for the Iron Man demo
#
# Erases the sim, boots it, dismisses all first-run dialogs,
# seeds a client order message, and optionally runs the agent immediately.
#
# Because Messages doesn't persist messages to fake contacts across relaunches,
# the --run-agent flag chains the agent run directly after seeding — no app kill
# in between. This is the only reliable way to demo.
#
# Usage:
#   ./seed_demo.sh                  # seed only (message won't survive relaunch)
#   ./seed_demo.sh --run-agent      # seed + immediately run agent demo
#   ./seed_demo.sh --no-erase       # skip erase (for re-seeding)

set -euo pipefail
cd "$(dirname "$0")"

UDID="50ADC92B-85DA-40D3-BCE4-34985F363B60"
SKIP_ERASE=false
RUN_AGENT=false
for arg in "$@"; do
    case "$arg" in
        --no-erase) SKIP_ERASE=true ;;
        --run-agent) RUN_AGENT=true ;;
    esac
done

# Helper: dismiss all dialogs in the current app until we reach a target state
dismiss_dialogs() {
    .venv/bin/python -c "
import time
from scripts import idbwrap, screen_mapper
udid = '$UDID'

DISMISS = {'ok', 'continue', 'not now', 'skip', 'dismiss', 'maybe later', 'allow'}
TARGET = {'conversations', 'toolbar', 'search', 'compose', 'new message'}

for attempt in range(15):
    raw = idbwrap.describe_all(udid)
    if not raw:
        time.sleep(2)
        continue
    tree = screen_mapper.parse_tree(raw)
    elements = screen_mapper.flatten_elements(tree)
    labels = {(el.get('label') or el.get('name') or '').lower() for el in elements}

    # Are we past all dialogs?
    if labels & TARGET:
        print(f'Target reached after {attempt} attempt(s)')
        break

    # Find and tap a dismiss button
    dismissed = False
    for el in elements:
        label = (el.get('label') or el.get('name') or '').lower()
        if label in DISMISS:
            frame = el.get('frame', {})
            cx = int(frame.get('x', 0) + frame.get('width', 0) / 2)
            cy = int(frame.get('y', 0) + frame.get('height', 0) / 2)
            print(f'  Dismiss: {label} at ({cx}, {cy})')
            idbwrap.tap(udid, cx, cy)
            time.sleep(3)
            dismissed = True
            break

    if not dismissed:
        time.sleep(2)
else:
    print('  WARNING: max attempts reached')
" 2>/dev/null
}

# ── Step 1: Erase and boot ──────────────────────────────────────────
if ! $SKIP_ERASE; then
    echo "==> Shutting down simulator..."
    xcrun simctl shutdown "$UDID" 2>/dev/null || true
    sleep 2
    echo "==> Erasing simulator..."
    xcrun simctl erase "$UDID"
    sleep 1
fi

echo "==> Booting simulator..."
xcrun simctl boot "$UDID" 2>/dev/null || true
sleep 5

# ── Step 2: Warm up apps ────────────────────────────────────────────
echo "==> Warming up Settings..."
xcrun simctl launch "$UDID" com.apple.Preferences
sleep 3
xcrun simctl terminate "$UDID" com.apple.Preferences

echo "==> Warming up Reminders..."
xcrun simctl launch "$UDID" com.apple.reminders
sleep 3
xcrun simctl terminate "$UDID" com.apple.reminders

# ── Step 3: First Messages launch — dismiss dialogs ──────────────────
echo "==> Messages launch 1 — dismissing dialogs..."
xcrun simctl launch "$UDID" com.apple.MobileSMS
sleep 4
dismiss_dialogs

# Kill and relaunch to catch second-wave dialogs
xcrun simctl terminate "$UDID" com.apple.MobileSMS 2>/dev/null || true
sleep 2

echo "==> Messages launch 2 — dismissing remaining dialogs..."
xcrun simctl launch "$UDID" com.apple.MobileSMS
sleep 4
dismiss_dialogs

# Kill and relaunch one more time (Apple Intelligence shows on 2nd launch)
xcrun simctl terminate "$UDID" com.apple.MobileSMS 2>/dev/null || true
sleep 2

echo "==> Messages launch 3 — final check..."
xcrun simctl launch "$UDID" com.apple.MobileSMS
sleep 4
dismiss_dialogs

# ── Step 4: Seed the order message ───────────────────────────────────
echo "==> Seeding client order message..."
.venv/bin/python -c "
import time, sys
from scripts import idbwrap, screen_mapper
udid = '$UDID'

def get_elements():
    raw = idbwrap.describe_all(udid)
    if not raw:
        return []
    tree = screen_mapper.parse_tree(raw)
    return screen_mapper.flatten_elements(tree)

def find_by_label(elements, target):
    for el in elements:
        label = (el.get('label') or el.get('name') or '').lower()
        if label == target:
            frame = el.get('frame', {})
            cx = int(frame.get('x', 0) + frame.get('width', 0) / 2)
            cy = int(frame.get('y', 0) + frame.get('height', 0) / 2)
            return cx, cy
    return None, None

elements = get_elements()

# Tap the first conversation in the list
# The conversations appear below the header. Tap at y=290 (center of first row)
print('Tapping first conversation...')
idbwrap.tap(udid, 201, 290)
time.sleep(3)

# Verify we're in a conversation (should see a Message text field)
elements = get_elements()
cx, cy = find_by_label(elements, 'message')
if cx is None:
    # Try 'imessage' label
    cx, cy = find_by_label(elements, 'imessage')
if cx is None:
    print('ERROR: Could not find message text field')
    sys.exit(1)

# Tap the message field
print(f'Tapping message field at ({cx}, {cy})...')
idbwrap.tap(udid, cx, cy)
time.sleep(2)

# Type the order
print('Typing order...')
idbwrap.type_text(udid, 'Order: 500 business cards, matte finish, rush delivery')
time.sleep(2)

# Find and tap Send
elements = get_elements()
cx, cy = find_by_label(elements, 'send')
if cx is None:
    print('ERROR: Send button not found after typing')
    sys.exit(1)

print(f'Tapping Send at ({cx}, {cy})...')
idbwrap.tap(udid, cx, cy)
time.sleep(5)

# Verify: check for delivered status or send button gone
elements = get_elements()
all_labels = [(el.get('label') or el.get('name') or el.get('value') or '').lower() for el in elements]
if any('delivered' in l for l in all_labels):
    print('Message delivered')
else:
    send_cx, _ = find_by_label(elements, 'send')
    if send_cx is None:
        print('Message sent (send button cleared)')
    else:
        print('WARNING: Send still visible — retrying...')
        idbwrap.tap(udid, send_cx, cy)
        time.sleep(5)
" 2>/dev/null

# ── Step 5: Go back to inbox ──────────────────────────────────────────
echo "==> Returning to inbox..."
.venv/bin/python -c "
from scripts import idbwrap
import time
udid = '$UDID'
# Tap Back button (top left)
idbwrap.tap(udid, 38, 84)
time.sleep(1)
" 2>/dev/null

sleep 1

# ── Step 6: Either chain into agent or stop ───────────────────────────
if $RUN_AGENT; then
    # Messages is on inbox view with the seeded conversation visible.
    # DO NOT terminate — message may not persist in sim SMS database.
    # The agent will see Messages already open on the inbox.
    echo ""
    echo "==> Seeding complete. Messages on inbox view."
    echo "==> Launching agent in 3s..."
    sleep 3

    GOAL="You are in Messages. Tap the first conversation to open it. Read the message text EXACTLY as written — do not paraphrase or invent different words. Then switch to Reminders (bundle: com.apple.reminders) and create a new reminder with that EXACT text as the title. Finally switch back to Messages (bundle: com.apple.MobileSMS), tap the iMessage text field at the bottom, type Done, and tap Send."

    echo "==> Running agent..."
    .venv/bin/python main.py \
        --goal "$GOAL" \
        --bundle-id com.apple.MobileSMS \
        --max-steps 30
else
    xcrun simctl terminate "$UDID" com.apple.MobileSMS 2>/dev/null || true

    echo ""
    echo "==> Simulator staged for Iron Man demo!"
    echo "    UDID: $UDID"
    echo "    Messages: 1 conversation with order text"
    echo "    Reminders: empty (clean)"
    echo ""
    echo "    WARNING: Message does NOT persist across Messages relaunch."
    echo "    Use --run-agent to chain the agent run immediately."
    echo ""
    echo "    ./seed_demo.sh --run-agent"
fi
