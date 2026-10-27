#!/usr/bin/env bash
# Set up Auriga: make scripts executable, create config, and start the bridge in the background.
# After this, the only thing left is loading the extension in Chrome (one manual step).
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$HERE/auriga" "$HERE/tunnel.sh"

mkdir -p "$HOME/.auriga"
chmod 700 "$HOME/.auriga"
if [ ! -f "$HOME/.auriga/config.json" ]; then
  cat > "$HOME/.auriga/config.json" <<'CFG'
{
  "port": 8765,
  "agent": "auriga",
  "ephor_url": "",
  "ephor_token": "",
  "webhook_url": ""
}
CFG
  echo "Created ~/.auriga/config.json"
fi
chmod 600 "$HOME/.auriga/config.json"

# Start the bridge in the background — it just sits and waits for the extension.
"$HERE/auriga" start || true

# Install the reverse-tunnel launchd agent (auto-connects + survives sleep) on macOS.
if [[ "$(uname -s)" == "Darwin" ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$HOME/Library/LaunchAgents/com.c1lab.auriga.tunnel.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.c1lab.auriga.tunnel</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$HERE/tunnel.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/auriga-tunnel.log</string>
  <key>StandardErrorPath</key><string>/tmp/auriga-tunnel.log</string>
</dict></plist>
PLIST
  launchctl unload "$HOME/Library/LaunchAgents/com.c1lab.auriga.tunnel.plist" 2>/dev/null || true
  launchctl load "$HOME/Library/LaunchAgents/com.c1lab.auriga.tunnel.plist"
  echo "Installed the reverse tunnel as a launchd agent (auto-reconnects, survives sleep)."
fi

echo
echo "✅ Setup done — the bridge is running in the background."
echo
echo "Last step, load the extension:"
echo "  chrome://extensions  →  Developer mode  →  Load unpacked  →  $HERE/extension"
echo
echo "Then it just works, e.g.   $HERE/auriga tabs"
echo "Tunnel:  $HERE/tunnel.sh  (or already running via launchd).  Log: /tmp/auriga-tunnel.log"
echo "Other:  $HERE/auriga status · stop · setup --ephor-url ... --webhook-url ..."
