#!/bin/bash
# VidSnatch launcher
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting VidSnatch..."
python3 "$SCRIPT_DIR/app.py" &
SERVER_PID=$!

# Wait for server to start then open browser
sleep 1.5
xdg-open "http://localhost:7979" 2>/dev/null || \
  google-chrome "http://localhost:7979" 2>/dev/null || \
  firefox "http://localhost:7979" 2>/dev/null || \
  echo "Open http://localhost:7979 in your browser"

echo "VidSnatch running (PID: $SERVER_PID). Press Ctrl+C to stop."
wait $SERVER_PID
