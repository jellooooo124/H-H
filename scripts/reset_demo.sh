#!/usr/bin/env bash
# Destructive: erase all Docker Compose volumes for this synthetic demo.
set -euo pipefail
echo "WARNING: this permanently deletes the PostgreSQL database, n8n workflows/credentials,"
echo "and app volumes for the Compose project. Do not use with anything but synthetic data."
read -r -p 'Type RESET-SYNTHETIC-DATA to continue: ' phrase
if [ "$phrase" != "RESET-SYNTHETIC-DATA" ]; then
  echo "Cancelled; no containers or volumes were changed."
  exit 1
fi
docker compose down --volumes --remove-orphans
echo "Synthetic demo volumes removed."
read -r -p 'Start a clean stack now? Type START to continue: ' start
if [ "$start" = "START" ]; then
  docker compose up -d --build
  echo "Stack started. Run bash scripts/check_demo.sh, then re-import only the required n8n workflows."
else
  echo "Stack remains stopped. Start later with: docker compose up -d --build"
fi
