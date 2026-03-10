# demo.tape — VHS terminal recording for ios-agent-runner
# https://github.com/charmbracelet/vhs
#
# Usage: vhs demo.tape

Output demo.gif
Set Theme "Catppuccin Mocha"
Set FontFamily "JetBrains Mono"
Set FontSize 14
Set Width 1200
Set Height 800
Set Padding 20

# Activate the venv
Type "source .venv/bin/activate"
Enter
Sleep 1s

# Show help
Type "python main.py --help"
Enter
Sleep 3s

# Run the agent with a Safari search goal
Type 'python main.py --goal "Open Safari and search for weather in Austin" --max-steps 10'
Enter

# Let the agent run (adjust timing based on actual execution speed)
Sleep 45s
