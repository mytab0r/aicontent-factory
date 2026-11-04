# Hermes Dashboard for aicontent-factory
# Uses the official hermes-agent image and runs the dashboard service
FROM nousresearch/hermes-agent:latest

# The dashboard is built into the hermes-agent image.
# We just need to run it with the right configuration.
# Environment variables for auth will be provided at runtime via docker-compose.

# Default command runs the dashboard on 0.0.0.0:9119
# Auth is required for non-loopback binds (June 2026 hardening)
CMD ["dashboard", "--host", "0.0.0.0", "--port", "9119", "--no-open"]
