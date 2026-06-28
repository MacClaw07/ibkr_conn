#!/bin/bash
# Stops IB Gateway cleanly via IBC's command server

set -euo pipefail

echo "Stopping IB Gateway via IBC command port 7462..."
echo "STOP" | nc -w 5 localhost 7462 2>/dev/null && echo "✅ Stop command sent" || echo "⚠️  Could not connect to IBC (may not be running)"

# Also try the stop.sh that comes with IBC
if [[ -x ~/Applications/IBC/stop.sh ]]; then
  ~/Applications/IBC/stop.sh 2>/dev/null || true
fi

# Kill any leftover processes
sleep 2
if pgrep -f "java.*IBC\|java.*[Gg]ateway\|DisplayBanner.*IBC" > /dev/null 2>&1; then
  echo "Processes still running, sending SIGTERM..."
  pkill -f "java.*IBC" 2>/dev/null || true
  pkill -f "java.*[Gg]ateway" 2>/dev/null || true
  pkill -f "DisplayBanner.*IBC" 2>/dev/null || true
  sleep 1
  pgrep -f "IBC\|[Gg]ateway.*java" > /dev/null 2>&1 && pkill -9 -f "IBC\|[Gg]ateway.*java" 2>/dev/null || true
fi

echo "Done."
