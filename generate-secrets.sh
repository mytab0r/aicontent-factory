#!/usr/bin/env bash
# Generate Langfuse secrets for PC deployment
# Run this ONCE on the PC to create secret files, then commit only the workflow
# Never commit actual secrets to git

set -euo pipefail
SECRETS_DIR="$(dirname "$0")/secrets"
mkdir -p "$SECRETS_DIR"

gen() { openssl rand -base64 32 | tr -d '\n'; }

echo "Generating secrets in $SECRETS_DIR..."
echo "$(gen)" > "$SECRETS_DIR/postgres_password.txt"
echo "$(gen)" > "$SECRETS_DIR/clickhouse_password.txt"
echo "$(gen)" > "$SECRETS_DIR/redis_password.txt"
echo "$(gen)" > "$SECRETS_DIR/minio_root_user.txt"
echo "$(gen)" > "$SECRETS_DIR/minio_root_password.txt"
echo "$(gen)" > "$SECRETS_DIR/nextauth_secret.txt"

chmod 600 "$SECRETS_DIR"/*.txt

echo "Secrets generated:"
ls -la "$SECRETS_DIR"
echo ""
echo "IMPORTANT: Copy these to PC at /mnt/d/docker-volumes/langfuse/secrets/ or use the deploy workflow"
echo "PUBLIC_KEY and SECRET_KEY for Hermes plugin will be created AFTER Langfuse is up (via Langfuse UI/API)"