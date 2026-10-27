#!/usr/bin/env bash
# Maintain the reverse SSH tunnel from this Mac to C1-G4, so an agent there can drive Auriga.
# Auto-reconnects on drop / laptop sleep.  Usage: ./tunnel.sh   (or install as a launchd agent via install.sh)
REMOTE="${AURIGA_TUNNEL_REMOTE:-root@100.74.235.132}"
PORT="${AURIGA_TUNNEL_PORT:-8765}"
while true; do
  echo "$(date '+%H:%M:%S') tunnel ${PORT} -> ${REMOTE}"
  ssh -R "${PORT}:127.0.0.1:${PORT}" \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
      -N "$REMOTE"
  echo "$(date '+%H:%M:%S') dropped — reconnecting in 5s"
  sleep 5
done
