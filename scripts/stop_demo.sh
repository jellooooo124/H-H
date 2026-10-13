#!/usr/bin/env bash
# Stop containers to avoid idle resource use; retain named volumes.
set -euo pipefail
docker compose stop
echo "Stopped demo containers. Named volumes/data are preserved."
echo "Restart later with: docker compose up -d"
