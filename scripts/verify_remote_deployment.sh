#!/usr/bin/env bash
# Run on the Docker host from the project directory. No PHI or secrets printed.
set -euo pipefail
if ! command -v docker >/dev/null; then echo 'FAIL: Docker CLI not found'; exit 1; fi
if ! docker compose version >/dev/null; then echo 'FAIL: Docker Compose v2 not found'; exit 1; fi
docker compose config -q
# Verify actual published sockets. Container-only networking is insufficient
# protection if someone changes 127.0.0.1 bindings to 0.0.0.0.
for service_port in 'frontend 80' 'api 8000' 'n8n 5678'; do
  read -r service port <<< "$service_port"
  published="$(docker compose port "$service" "$port")"
  if [[ ! "$published" =~ ^127\.0\.0\.1:[0-9]+$ ]]; then
    echo "FAIL: $service port $port is not bound exclusively to 127.0.0.1 (found: $published)" >&2
    exit 1
  fi
  echo "PASS: $service accessible only via host loopback $published"
done
if docker compose port postgres 5432 >/dev/null 2>&1; then
  echo "FAIL: PostgreSQL must not publish a host port" >&2
  exit 1
fi
echo "PASS: PostgreSQL has no published host port"
printf '\nContainer status:\n'; docker compose ps
printf '\nHealth checks:\n'
curl -fsS --max-time 8 http://127.0.0.1:8000/health >/dev/null && echo 'PASS FastAPI /health'
curl -fsS --max-time 8 http://127.0.0.1:5678/healthz >/dev/null && echo 'PASS n8n /healthz'
curl -fsS --max-time 8 http://127.0.0.1:8080/ >/dev/null && echo 'PASS Frontend /'
docker compose exec -T postgres pg_isready -U hah_demo -d hah_demo && echo 'PASS PostgreSQL ready'
echo 'NOTE: This is health-only; separately test workflow execution, review and rollback.'
