#!/usr/bin/env bash
# Verify health endpoints for an already-started local/private demo.
set -euo pipefail
bash scripts/verify_remote_deployment.sh

check_url() {
  label="$1"
  url="$2"
  attempt=1
  while [ "$attempt" -le 30 ]; do
    if curl -fsS --max-time 3 "$url" >/dev/null; then
      echo "PASS: $label"
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  echo "FAIL: $label did not become healthy: $url" >&2
  docker compose ps >&2 || true
  docker compose logs --tail=60 api frontend n8n postgres >&2 || true
  return 1
}

check_url "FastAPI health" "http://127.0.0.1:8000/health"
check_url "Vue/Nginx frontend" "http://127.0.0.1:8080/"
check_url "n8n health" "http://127.0.0.1:5678/healthz"
echo "PASS: private synthetic demo endpoints respond. This is not clinical or production validation."
