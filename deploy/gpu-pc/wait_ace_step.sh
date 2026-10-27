#!/bin/sh
# wait_ace_step.sh — wait for ace-step container to exist (created by janitor/ace_mode).
# Usage: wait_ace_step.sh [timeout_seconds] [-- then command...]
# Returns 0 when ace-step exists, runs optional command, or exits 1 on timeout.

set -eu
TIMEOUT=${1:-30}
shift || true

# If first arg is --, it's the command separator
if [ "${1:-}" = "--" ]; then
  shift
  HAS_CMD=1
else
  HAS_CMD=0
fi

end=$((SECONDS + TIMEOUT))
while [ $SECONDS -lt $end ]; do
  if docker inspect ace-step >/dev/null 2>&1; then
    if [ $HAS_CMD -eq 1 ]; then
      exec "$@"
    fi
    exit 0
  fi
  sleep 1
done

echo "::error::ace-step container not found after ${TIMEOUT}s (janitor/ace_mode recreate race)"
exit 1