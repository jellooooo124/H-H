# Hospital-at-Home Care Coordination — Research Platform

**CA6117 agentic healthcare prototype · Synthetic records only · Not for clinical use**

A runnable research prototype for multi-agent hospital-at-home coordination across heart failure and diabetes monitoring. This repository uses n8n for **workflow orchestration** and FastAPI for **authorized state transitions and safety enforcement**. It is deliberately not an autonomous diagnosis/treatment system.

## Demonstrated journey

1. A demo patient submits monitoring data, dietary input, or a symptom check-in.
2. FastAPI validates the synthetic patient scope, persists a durable event and initiates an n8n orchestration.
3. A bounded planner coordinates nutrition/vision, heart failure, diabetes, and approved-guideline retrieval tools.
4. A deterministic safety gate reconciles conflicting agents, flags missing evidence and blocks disallowed advice.
5. A clinician claims and reviews the case, examines citations and original measurements, and approves/rejects/escalates; only a **simulated** case outbox is created.
6. Clinical task queues, two-party handoff, outbox retries and SLA watch processes reconcile failures.
7. A clinician can create and explicitly publish only pre-approved **non-clinical in-app communication templates**. The patient can read/acknowledge them. Unacknowledged messages create follow-up tasks, **never** real hospital pages.
8. Synthetic fixtures and operational metrics are available for repeatable CA6117 demonstrations.

## Quick start (local synthetic test)

Prerequisites: Docker Engine/Compose, an authenticated n8n administrator for importing workflows, and optional OpenAI API credentials for real LLM/embedding tool calls.

```bash
cp .env.example .env
python scripts/generate_secrets.py
# Copy the generated values into .env. Leave OPENAI_API_KEY unset to test fail-closed behavior.
docker compose up -d --build
```

Once services are ready, open:

- Clinician UI: `http://127.0.0.1:8080/`
- Patient UI: `http://127.0.0.1:8080/patient.html`
- FastAPI docs: `http://127.0.0.1:8000/docs`
- n8n: `http://127.0.0.1:5678`

Import each of the **15 files from `workflows/*.json`** in n8n using **Import from File**. They are initially inactive. The HTTP nodes access `http://api:8000/internal/...` from the n8n Docker network. The local environment variable `HAH_INTERNAL_KEY` must equal the FastAPI `APP_INTERNAL_KEY`. Run manually before enabling schedules. **Do not import the workflow ZIP itself as a single n8n workflow.**

A real LLM API key and online Docker/npm access are necessary for a full integration demonstration. If absent, model operations must fail closed to human technical review. Generate short-lived demo tokens with `python scripts/generate_demo_token.py --help`. Never put patient data or credentials in n8n workflow JSON or Git.

## Verify

```bash
pip install -r backend/requirements.txt pytest pytest-asyncio
pytest -q
python scripts/verify_artifact.py
python scripts/evaluate_synthetic_policy.py
python -m compileall -q backend/app
cd frontend && npm install && npm run build
```

The last frontend build requires npm packages; Docker Compose additionally requires Docker and Postgres. The codebase was verified offline; see [`docs/RELEASE_VALIDATION.md`](docs/RELEASE_VALIDATION.md) for exactly what was and was not run.

## Architecture

| Layer | Package/module | Responsibility |
|---|---|---|
| Domain | `backend/app/communications/domain.py`, `backend/app/policy.py` | Pure transitions, deterministic safe-stop policy |
| Application | `backend/app/communications/service.py`, `backend/app/agents.py` | Use-cases, bounded agent calls, follow-up coordination |
| Infrastructure | `backend/app/communications/repository.py`, `backend/app/store.py`, `postgres_compat.py`, `rag.py` | Data access, encryption, RAG |
| Presentation | `backend/app/communications/api.py`, `frontend/src/*.vue` | Scoped HTTP endpoints and patient/clinician UIs |
| Integration | `workflows/*.json` | n8n scheduling and ID-only orchestration |
| Compatibility | `backend/app/legacy_api.py` | Existing v1–v4 routes; retained intact to avoid regressions |

The new communications bounded context follows dependency direction from transport → application → domain, with persistence behind the repository. Legacy coordination code is explicitly isolated but **has not been fully rewritten** into clean architecture. See [Architecture Decision Records](docs/ARCHITECTURE.md).

## Publications / safety

All fixtures, data and interfaces are **synthetic and educational**. No validated clinical thresholds, no real emergency line, no regulated device qualification, no real EHR integration, no real delivery channel, no certified secure deployment. The document set is not patient care advice. Do not upload actual PHI, nor expose the default HTTP/demo-auth deployment on a public network.

Additional documentation: [Chinese guide](README_繁體中文.md) · [Threats and gaps](docs/SECURITY_LIMITATIONS.md) · [CA6117 demo](docs/CA6117_DEMO.md) · [Publish private GitHub repo](docs/GITHUB_PUBLISH.md).
