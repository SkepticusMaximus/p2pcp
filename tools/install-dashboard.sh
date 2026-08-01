#!/usr/bin/env bash
# install-dashboard.sh — give this machine a double-click launcher for the p2pcp
# mesh dashboard, so it never has to be started from the command line.
#
# It writes a .desktop entry (app menu + Desktop icon) that runs the dashboard
# from this box's p2pcp venv, and seeds ~/.p2pcp/nodes.txt (the list of nodes the
# dashboard watches when launched with no arguments). Re-runnable; safe to repeat.
#
#   ./tools/install-dashboard.sh            # use ~/.venvs/p2pcp, watch loopback
#   PY=/path/to/venv/bin/python ./tools/install-dashboard.sh
#
# Add more nodes any time by editing ~/.p2pcp/nodes.txt (one host:port per line).
set -euo pipefail

PY="${PY:-$HOME/.venvs/p2pcp/bin/python}"
if [ ! -x "$PY" ]; then
    PY="$(command -v python3)"
    echo "note: $HOME/.venvs/p2pcp/bin/python not found; using $PY" >&2
fi
"$PY" -c "import p2pcp.dashboard" 2>/dev/null \
    || { echo "error: p2pcp not importable by $PY — install it first (pip install -e .)" >&2; exit 1; }

APPS="$HOME/.local/share/applications"
DESKTOP="$APPS/p2pcp-dashboard.desktop"
mkdir -p "$APPS" "$HOME/.p2pcp"

cat > "$DESKTOP" <<DESK
[Desktop Entry]
Type=Application
Version=1.0
Name=P2PCP Mesh Monitor
GenericName=CompuCoin compute mesh
Comment=Live view of the CompuCoin compute mesh — wallets, compute meter, buy inference
Exec=$PY -m p2pcp.dashboard
Terminal=false
Categories=Network;Utility;Monitor;
Keywords=p2pcp;compucoin;mesh;compute;dashboard;
StartupNotify=true
DESK
chmod +x "$DESKTOP"
gio set "$DESKTOP" metadata::trusted true 2>/dev/null || true
update-desktop-database "$APPS" 2>/dev/null || true

if [ -d "$HOME/Desktop" ]; then
    cp "$DESKTOP" "$HOME/Desktop/" && chmod +x "$HOME/Desktop/p2pcp-dashboard.desktop"
    gio set "$HOME/Desktop/p2pcp-dashboard.desktop" metadata::trusted true 2>/dev/null || true
    echo "· Desktop icon:  $HOME/Desktop/p2pcp-dashboard.desktop"
fi

if [ ! -s "$HOME/.p2pcp/nodes.txt" ]; then
    cat > "$HOME/.p2pcp/nodes.txt" <<'NODES'
# p2pcp dashboard — nodes to watch when launched with no arguments.
# One host:port per line. Blank lines and #comments are ignored.

127.0.0.1:9000          # this box
NODES
    echo "· Seeded:        $HOME/.p2pcp/nodes.txt (edit to add mesh peers)"
fi

echo "· App launcher:  $DESKTOP"
echo "Done. Find 'P2PCP Mesh Monitor' in your app menu, or double-click the Desktop icon."
