#!/usr/bin/env bash
set -euo pipefail

if ! command -v apt >/dev/null 2>&1; then
  echo "This setup script is intended for Ubuntu/Debian under WSL2." >&2
  exit 1
fi

sudo apt update
sudo apt install -y tigervnc-standalone-server tigervnc-tools novnc websockify xfce4 xfce4-goodies dbus-x11

if ! command -v google-chrome >/dev/null 2>&1; then
  echo "Google Chrome is not installed yet. Install google-chrome-stable, then rerun Agentie." >&2
  exit 2
fi

mkdir -p "$HOME/.vnc"
cat > "$HOME/.vnc/xstartup" <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
startxfce4 &
EOF
chmod +x "$HOME/.vnc/xstartup"

echo "Agentie WSL desktop dependencies are ready."
echo "You do not need to run this setup script again. Agentie will start the desktop automatically when needed."
