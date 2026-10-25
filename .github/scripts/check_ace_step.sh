#!/usr/bin/env bash
set -euo pipefail
# Wait for ace-step container healthy status, timeout 300s
MAX=300
INTERVAL=5
elapsed=0
while true; do
  status=$(docker inspect -f '{{.State.Health.Status}}' ace-step 2>/dev/null || echo "none")
  if [[ "$status" == "healthy" ]]; then
    echo "ace-step healthy"
    exit 0
  fi
  if [[ $elapsed -ge $MAX ]]; then
    echo "ace-step not healthy after $MAX seconds"
    docker logs ace-step || true
    exit 1
  fi
  sleep $INTERVAL
  ((elapsed+=INTERVAL))
done
