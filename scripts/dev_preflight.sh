#!/usr/bin/env bash
# Non-destructive setup checks for a private, synthetic-only Docker Compose demo.
set -euo pipefail

command -v docker >/dev/null || { echo "ERROR: Docker Engine/CLI is not installed on this host." >&2; exit 1; }
docker compose version >/dev/null || { echo "ERROR: Docker Compose v2 is required." >&2; exit 1; }
[ -f .env ] || { echo "ERROR: .env is missing. Copy .env.example and generate unique secrets first." >&2; exit 1; }

for name in APP_INTERNAL_KEY APP_TOKEN_SECRET APP_ENCRYPTION_KEY N8N_ENCRYPTION_KEY POSTGRES_PASSWORD APP_ADMIN_KEY; do
  value="$(sed -n "s/^$name=//p" .env | tail -n 1)"
  if [ -z "$value" ] || [[ "$value" == *REPLACE* ]]; then
    echo "ERROR: $name is empty or still a placeholder in .env." >&2
    exit 1
  fi
done

if grep -Eq '^(OPENAI_API_KEY=.+)$' .env; then
  echo "NOTE: OPENAI_API_KEY is configured. Confirm provider spending limits before any live model call."
else
  echo "AI provider key is empty; AI-dependent paths should fail closed without model spend."
fi

docker compose config -q
bash scripts/verify_remote_deployment.sh
echo "PASS: Compose configuration valid and host ports remain loopback-only."
echo "Next: docker compose up -d --build && bash scripts/check_demo.sh"
