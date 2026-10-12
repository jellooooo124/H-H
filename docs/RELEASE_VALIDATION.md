# Final research-build verification (2026-10-12)

## Executed in this environment

- `pytest -q` → **64 passed, 1 skipped**. Skipped test requires an actual PostgreSQL server and driver/runtime connection.
- `python scripts/verify_artifact.py` → **15 JSON workflows passed static graph, credential and private-data-boundary checks**.
- `python scripts/evaluate_synthetic_policy.py` → **12/12 authored synthetic rule scenarios met their pre-specified expected outcome** (not a clinical performance measurement).
- `python -m compileall -q backend/app` → passed.
- Local code review of n8n workflows: no hardcoded OpenAI API token, all internal HTTP requests target `http://api:8000/internal/` and use local injected `X-Internal-Key`.

## Not verified in this environment

- `docker compose up -d --build`: Docker Engine not available; PostgreSQL and real n8n execution were not tested together.
- `npm run build`: failed because Vite dependencies were not installed in this offline environment (`vite: not found`). A GitHub Actions workflow installs dependencies and will run `npm run build` after publication.
- OIDC connection to external issuer, HTTPS/TLS, real EHR/FHIR OAuth, online model API, production monitoring, secure real-patient handling, clinical accuracy or utility.
- Publishing to a **new** GitHub remote: GitHub connector did not expose a create-repository action; see `GITHUB_PUBLISH.md`.

## Acceptance checklist on a normal development machine

1. Generate strong secrets in `.env`, confirm loopback-only URLs.
2. Run `docker compose build && docker compose up -d` and inspect the health endpoint.
3. Open local clinician and patient Vue routes; inspect browser console and generated assets.
4. Import 15 n8n JSON workflows, verify each manually with internal shared key, and only then activate required schedules.
5. Run synthetic normal/redflag/injection test cases against running API + model provider (model must fail closed without key).
6. Exercise case claim → clinician review → follow-up and fixed-template clinician publish → patient ACK; force expiry and confirm idempotent follow-up task.
7. Check PostgreSQL restart persistence, replays, handoff recovery, and HMAC audit verification.
8. Review security gaps and verify no secrets/PHI in Git history or n8n logs.
