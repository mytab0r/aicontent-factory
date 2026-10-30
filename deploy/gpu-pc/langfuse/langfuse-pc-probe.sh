#!/usr/bin/env bash
# Probe Langfuse from VPS via pc-link tunnel (127.0.0.1:3030 -> PC:3000)
set -uo pipefail

echo "=== Langfuse probe from VPS via pc-link ==="
echo "Testing http://127.0.0.1:3030/api/public/health"

# Test the tunnel
if curl -sf --max-time 10 http://127.0.0.1:3030/api/public/health; then
  echo "SUCCESS: Langfuse reachable via pc-link tunnel"
  exit 0
else
  echo "FAILED: Langfuse not reachable via pc-link"
  echo "=== Checking pc-link tunnel ports on VPS ==="
  ss -tlnp | grep -E "3030|2223|9222|2376" || echo "Port 3030 not listening"
  echo "=== pc-link container on PC (via docker proxy) ==="
  # This won't work from VPS, just diagnostic
  exit 1
fi