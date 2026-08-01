#!/usr/bin/env bash
# park-relay.sh — light a PUBLIC reverse-dial relay on THIS box so a roaming node
# (e.g. the HP in the park) can trade with it over the internet.
#
# Run this on the box that STAYS PUT with its own connection (e.g. Lenny on the
# Motel WiFi). It starts three things and prints the public address:
#   1. a p2pcp relay on localhost                 (the rendezvous)
#   2. a `bore` tunnel exposing it at bore.pub:PORT   (public, no account)
#   3. a Llama seller parked at the relay          (real inference, sold over WAN)
#
# bore hands out a FRESH public port each time this box changes networks, so
# re-run this after moving Lenny to the Motel WiFi and use the new address.
#
# Needs: the p2pcp venv, the `bore` binary, and llama1b-server running (:8091).
#   ./tools/park-relay.sh
# Stop everything:
#   pkill -f 'p2pcp relay'; pkill -f 'bore local'; pkill -f 'lenny-llama-relay'
set -euo pipefail

VENV="${VENV:-$HOME/.venvs/p2pcp/bin}"
BORE="${BORE:-$HOME/.local/bin/bore}"
RELAY_PORT="${RELAY_PORT:-8794}"
OPENAI_BASE="${OPENAI_BASE:-http://127.0.0.1:8091}"
OPENAI_MODEL="${OPENAI_MODEL:-Llama-3.2-1B-Q4.gguf}"
LOG="$HOME/.p2pcp"
mkdir -p "$LOG"

[ -x "$BORE" ] || { echo "error: bore not found at $BORE (set BORE=/path/to/bore)" >&2; exit 1; }
[ -x "$VENV/p2pcp" ] || { echo "error: p2pcp venv not found at $VENV" >&2; exit 1; }

echo "· stopping any previous park relay…"
pkill -f 'p2pcp relay'          2>/dev/null || true
pkill -f 'bore local'           2>/dev/null || true
pkill -f 'lenny-llama-relay'    2>/dev/null || true
sleep 1

echo "· starting relay on 127.0.0.1:$RELAY_PORT"
nohup "$VENV/p2pcp" relay --host 127.0.0.1 --port "$RELAY_PORT" \
    > "$LOG/park-relay.log" 2>&1 &

echo "· opening public tunnel via bore.pub…"
nohup "$BORE" local "$RELAY_PORT" --to bore.pub > "$LOG/park-bore.log" 2>&1 &

PUB=""
for _ in $(seq 1 30); do
    PUB=$(grep -oE 'bore\.pub:[0-9]+' "$LOG/park-bore.log" 2>/dev/null | head -1 || true)
    [ -n "$PUB" ] && break
    sleep 0.5
done
[ -n "$PUB" ] || { echo "error: bore gave no public port; see $LOG/park-bore.log" >&2; exit 1; }

echo "· parking a Llama seller at the relay (real inference, sold over the WAN)"
OPENAI_BASE="$OPENAI_BASE" OPENAI_MODEL="$OPENAI_MODEL" \
    nohup "$VENV/p2pcp" serve --worker p2pcp.model_worker:openai --float \
        --relay 127.0.0.1:"$RELAY_PORT" --relay-pool 3 \
        --seed lenny-llama-relay --host 127.0.0.1 --port 0 \
        > "$LOG/park-seller.log" 2>&1 &
sleep 2

cat <<EOF

  ✅ PUBLIC RELAY LIVE at  $PUB

  From the roaming box (the HP in the park), buy a real AI answer over the WAN:

      ~/.venvs/p2pcp/bin/p2pcp buy "your question here" --relay $PUB --float

  Logs:  $LOG/park-{relay,bore,seller}.log
  Stop:  pkill -f 'p2pcp relay'; pkill -f 'bore local'; pkill -f 'lenny-llama-relay'
EOF
