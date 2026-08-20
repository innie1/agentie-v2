#!/usr/bin/env bash
set -euo pipefail

echo "Agentie WSL Computer setup"
echo "Installing XFCE remote desktop, noVNC, x11vnc utilities, and helpers..."

sudo apt update
sudo apt install -y \
  xfce4 xfce4-goodies dbus-x11 \
  tigervnc-standalone-server tigervnc-common \
  novnc websockify \
  xdotool wmctrl xclip x11-xserver-utils \
  curl wget ca-certificates gnupg

mkdir -p "$HOME/.vnc" "$HOME/.agentie-computer"
cat > "$HOME/.vnc/xstartup" <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=XFCE
export DESKTOP_SESSION=xfce
exec startxfce4
EOF
chmod +x "$HOME/.vnc/xstartup"

cat > "$HOME/.agentie-computer/start.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export USER="${USER:-$(whoami)}"
export HOME="${HOME:-/home/$USER}"
export DISPLAY=:1
GEOMETRY="${AGENTIE_VNC_GEOMETRY:-1440x900}"
DEPTH="${AGENTIE_VNC_DEPTH:-24}"
VNC_LOG="$HOME/.agentie-computer/vnc.log"
NOVNC_LOG="$HOME/.agentie-computer/novnc.log"

mkdir -p "$HOME/.agentie-computer" "$HOME/.vnc"

if ! pgrep -u "$USER" -f "Xtigervnc.*:1" >/dev/null 2>&1; then
  vncserver -kill :1 >/dev/null 2>&1 || true
  vncserver :1 -localhost yes -SecurityTypes None -geometry "$GEOMETRY" -depth "$DEPTH" >"$VNC_LOG" 2>&1 || {
    cat "$VNC_LOG" >&2
    exit 1
  }
fi

if ! pgrep -u "$USER" -f "websockify.*6080" >/dev/null 2>&1; then
  nohup websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5901 >"$NOVNC_LOG" 2>&1 &
fi

sleep 0.8
if command -v google-chrome >/dev/null 2>&1; then
  nohup env DISPLAY=:1 google-chrome --no-first-run --disable-dev-shm-usage >/dev/null 2>&1 &
elif command -v chromium >/dev/null 2>&1; then
  nohup env DISPLAY=:1 chromium --no-first-run --disable-dev-shm-usage >/dev/null 2>&1 &
fi

echo "Agentie WSL Computer ready"
echo "noVNC: http://127.0.0.1:6080/vnc.html?host=127.0.0.1&port=6080&autoconnect=1&resize=remote"
EOF
chmod +x "$HOME/.agentie-computer/start.sh"

cat > "$HOME/.agentie-computer/stop.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
pkill -u "${USER:-$(whoami)}" -f "websockify.*6080" >/dev/null 2>&1 || true
vncserver -kill :1 >/dev/null 2>&1 || true
echo "Agentie WSL Computer stopped"
EOF
chmod +x "$HOME/.agentie-computer/stop.sh"

cat > "$HOME/.agentie-computer/status.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if pgrep -u "${USER:-$(whoami)}" -f "Xtigervnc.*:1" >/dev/null 2>&1 && pgrep -u "${USER:-$(whoami)}" -f "websockify.*6080" >/dev/null 2>&1; then
  echo ready
else
  echo stopped
fi
EOF
chmod +x "$HOME/.agentie-computer/status.sh"

echo "Done. Start it with: ~/.agentie-computer/start.sh"
