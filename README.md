# H@H Care Coordination · AI & n8n Automation Portfolio

**Independent full-stack software engineering portfolio** combining n8n workflow automation, FastAPI, PostgreSQL, Vue 3, bounded LLM agents, RAG, human review and audit trails. It is **not** an academic assignment deliverable, and it is **not a clinical product**. All supported data are synthetic; no real patients, diagnosis, treatment or emergency response.

## What actually works

- Two browser-facing Vue workspaces: clinician case/task queue and patient portal.
- Role-scoped API access, synthetic check-ins, durable task dispatch, monitoring trends, encrypted persistence, tamper-evident audit trail, FHIR R4 *synthetic* interoperability.
- **15 importable n8n workflows**, including a published synthetic Check-in webhook integrated with FastAPI.
- Clinician-approved **non-clinical, fixed-template** message drafts and publication; patients acknowledge them in the portal. No external SMS/email/hospital paging.
- Deterministic safety gates, bounded agent tools, model unavailability fail-closed to technical review.
- PostgreSQL 17-backed Docker Compose stack and disposable GitHub Actions validation, including Chromium browser closed-loop tests and persistence after PostgreSQL/API restarts.

**Scope:** synthetic demonstration for software engineering review, not clinical effectiveness. Actual LLM requests are optional and need a configured paid provider API key; CI does not silently simulate live models or spend on API calls.

## Test evidence in GitHub Actions

The repository has three automated workflows under `.github/workflows/`:

| Check | Real execution in CI |
| --- | --- |
| `tests.yml` | Python unit/contract/security checks, architecture, synthetic policy, Vue build |
| `integration.yml` | PostgreSQL 17 live tests including independent transactions; n8n 2.42.6 import of all 15 JSON workflows |
| `runtime-smoke.yml` | Full Docker Compose startup, published n8n webhook, genuine patient API → n8n → PostgreSQL triage, real Chromium clinician → patient communication acknowledgement, PostgreSQL/API restart persistence |

These run with **disposable synthetic data and ephemeral secrets**. See [Portfolio acceptance report](docs/PORTFOLIO_ACCEPTANCE.md) and current [Actions history](https://github.com/jellooooo124/H-H/actions). Green CI does **not** mean clinical validation, a continuously hosted website or all AI agents proven live.

## Run locally or on a private Linux host

Requires Docker Engine + Compose on **Linux** (a 2017 Intel Mac can use the remote Linux host through SSH and browser; Docker does not need to be installed on that Mac). Do not expose this HTTP/demo-auth setup publicly.

```bash
cp .env.example .env
python scripts/generate_secrets.py
# Copy unique generated secrets into the matching .env entries; never commit .env.
docker compose up -d --build
```

Local-only URLs (bound to 127.0.0.1 on host):

| Surface | URL |
| --- | --- |
| Clinician workspace | http://127.0.0.1:8080/ |
| Patient portal | http://127.0.0.1:8080/patient.html |
| API docs | http://127.0.0.1:8000/docs |
| n8n administrative editor | http://127.0.0.1:5678 |

Import the 15 **individual JSON files** from `workflows/` using n8n import (or its CLI). They are inactive until explicitly published/activated. Check environment key mapping (`HAH_INTERNAL_KEY` inside n8n must equal `APP_INTERNAL_KEY`), then publish only the workflows required for a synthetic demo. Existing webhook workflows use stable IDs. Avoid activating duplicate webhook paths.

Generate separate, short-lived synthetic clinician/patient JWTs with `python scripts/generate_demo_token.py --help`; keep credentials out of Git, bug reports and screenshots. Without `OPENAI_API_KEY`, AI-dependent steps **fail closed** rather than producing fictitious agent results.

## Architectural trust boundaries

| Layer | Responsibility |
| --- | --- |
| Vue 3 + Nginx | Clinician and patient workspace; browser is untrusted |
| FastAPI presentation | Authentication and scoped authorization |
| Application/domain | Validated transitions, clinician approvals, deterministic safety gates |
| PostgreSQL persistence | Durable synthetic events, encrypted records, audit and retries |
| n8n | Scheduled workflows and ID-only orchestration; not authorized to bypass backend rules |
| Model/RAG integrations | Bounded structured data, cited evidence, fail-closed when unavailable |

Browse `backend/app/{domain,application,infrastructure,presentation}`, `frontend/src/`, `workflows/`, `tests/`. Older technical migration and research notes remain in `docs/` for traceability, but **do not determine this portfolio's product requirements**.

## What's not finished

There is **no live public Demo URL yet**. External HTTPS hosting, hardened OIDC identity, protected n8n administration, real model-provider smoke tests, external secret management, monitored backups/restoration, broader UI scenario coverage, and deployment/security reviews remain outstanding. Demo auth, local HTTP n8n settings and synthetic-only checks are **not safe to repurpose for real clinical data**.

Do not upload protected health information (PHI). No clinical advice, emergency support, medication automation, patient care guarantees or regulated deployment claims.

[繁體中文說明](README_繁體中文.md) · [Portfolio acceptance](docs/PORTFOLIO_ACCEPTANCE.md) · [Architecture](docs/ARCHITECTURE.md) · [Private Linux / MacBook Air deployment](docs/PRIVATE_REMOTE_DEMO.md) · [Security limitations](docs/SECURITY_LIMITATIONS.md)
