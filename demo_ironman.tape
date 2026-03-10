# demo_ironman.tape — 60-second "Iron Man" demo for ios-agent-runner
# https://github.com/charmbracelet/vhs
#
# Scenario: A client texts an order. The AI agent autonomously:
#   1. Reads the message in Messages
#   2. Opens Reminders and logs the order
#   3. Switches back to Messages and replies "Done"
#
# Usage:
#   vhs demo_ironman.tape
#
# This tape calls film_demo.sh which handles seeding + agent in one pass.

Output demo_ironman.gif
Set Theme "Catppuccin Mocha"
Set FontFamily "JetBrains Mono"
Set FontSize 13
Set Width 1400
Set Height 900
Set Padding 16
Set TypingSpeed 40ms

# ── Act 1: Launch the demo ─────────────────────────────────────────────
Type "./film_demo.sh"
Enter

# ── Act 2: Agent runs autonomously ─────────────────────────────────────
# ~60s for seeding + ~90s for agent = ~150s total
# The film_demo.sh script hides seeding and shows the agent output.
Sleep 180s

# ── Act 3: Victory ───────────────────────────────────────────────────
# Terminal shows AGENT SUCCESS. Full Trigger→Action→Confirmation loop.
Sleep 5s
