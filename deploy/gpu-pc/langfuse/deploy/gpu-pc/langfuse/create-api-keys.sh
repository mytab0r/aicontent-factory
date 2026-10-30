#!/usr/bin/env bash
# Create Langfuse API keys for Hermes plugin after Langfuse is deployed
# Run this on PC after langfuse-web is up

set -euo pipefail

LANGFUSE_URL="${LANGFUSE_URL:-http://localhost:3000}"

echo "Creating Langfuse API keys for Hermes at $LANGFUSE_URL..."

# Create a project and API keys via Langfuse API
# First, need to register/login to get a session, then create project and keys
# For self-hosted, we can use the initial setup flow

# Check if Langfuse is ready
for i in {1..30}; do
  if curl -sf --max-time 5 "$LANGFUSE_URL/api/public/health" >/dev/null; then
    echo "Langfuse is healthy"
    break
  fi
  echo "Waiting for Langfuse... ($i/30)"
  sleep 10
done

# The initial setup creates the first user and project
# We'll use the API to create a project and API keys
# Note: First user must be created via UI or setup API

echo "Please complete initial setup at $LANGFUSE_URL if not done"
echo "Then run this script to create Hermes project and keys"

# After manual setup, create project and keys via API:
# POST /api/public/projects - create project
# POST /api/public/projects/:projectId/api-keys - create API key

cat <<'EOF'
MANUAL STEPS (once):
1. Open http://localhost:3000 in browser (via pc-link tunnel from VPS or direct on PC)
2. Complete initial registration (creates first user + project)
3. Go to Settings > Projects > Create new project: "hermes"
4. Go to Settings > API Keys > Create new key: "hermes-plugin"
5. Copy PUBLIC_KEY (pk-lf-...) and SECRET_KEY (sk-lf-...)
6. Add to Hermes secrets:
   HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-...
   HERMES_LANGFUSE_SECRET_KEY=sk-lf-...
   HERMES_LANGFUSE_BASE_URL=http://localhost:3000  # or via pc-link from VPS
7. Enable plugin in all profiles: hermes plugins enable observability/langfuse
EOF