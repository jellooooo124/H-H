# Portfolio Acceptance and Deployment Roadmap

This repository is an **independent AI + n8n healthcare operations portfolio project**, separate from any academic assessment.

## Verified automated quality gates

- Backend pytest, Python compilation, architecture, workflow integrity, and Vue production build.
- Disposable PostgreSQL 17 integration, multiple independent connections, transaction failure rollback, synthetic FHIR.
- n8n 2.42.6 import of all 15 workflows.
- Docker Compose runtime smoke: FastAPI + PostgreSQL + n8n + Vue/Nginx.
- Real patient API check-in to published n8n webhook to FastAPI callback to PostgreSQL.
- Chromium browser check: clinician drafts a fixed-template message; patient cannot see it before publication; clinician publishes; patient acknowledges; clinician sees acknowledgement; role-based API rejection of cross-role access.
- PostgreSQL/API restart check: communication acknowledgement persists and tamper-evident audit chain remains valid.
- Disposable PostgreSQL 17 custom-format backup and restore into a fresh database, comparing acknowledgement counts and terminal audit hashes.

All CI data and secrets are disposable synthetic fixtures. **No production medical use or real patient data.**

## Not yet verified or enabled

- A publicly accessible continuously running host, HTTPS ingress and domain, production identity provider/OIDC.
- Live OpenAI API calls and provider costs, clinical RAG quality or medical accuracy. A separate **manual and paid** GitHub Actions check is prepared but cannot execute until the owner supplies a GitHub Secret and explicitly consents.
- End-to-end browser review of actual agent-created cases and all 15 workflow types.
- External secret manager, independent backup restore, penetration/security testing, disaster recovery and load testing.
- Regulatory approval, clinical safety validation, operational 24/7 guarantees.

## Next release gate

Before a public demonstration, use a controlled HTTPS Linux host, demo-only accounts with short-lived tokens, immutable deployment version, monitored health checks, synthetic seeded fixtures, strict network exposure and disaster recovery tests. n8n editing UI is administrative and should not be publicly reachable.

**No API keys in Git or GitHub Actions logs.** Do not put real patient health information in any demo data, screenshot, bug report or issue.
