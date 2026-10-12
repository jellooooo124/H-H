# 2.4 Release Notes — Patient Engagement & Safe Alert Display

**Release class:** synthetic educational prototype; not for patient use or clinical monitoring.

## Implemented (code, not production validation)

- `backend/app/engagement24.py`: per-patient opt-in / opt-out settings; once-per-day simulated in-app check-in prompts; automatic cancellation of pending prompts on opt-out; patient-scoped dashboard with observed trends and sanitized check-in status; clinician-only read-only alert groupings; per-patient workflow evaluation with explicit missing ground truth; aggregate-only hourly snapshot.
- `backend/app/main.py`: `/v4/patient/dashboard`, `/v4/patient/preferences` GET/PUT, `/v4/patient/prompts`, `/v4/patient/prompts/{id}/seen`, `/v4/clinician/alert-groups`, `/v4/clinician/evaluation/{patient_ref}`, `/internal/engagement/watch`, `/internal/ops/quality-snapshot`.
- `frontend/patient.html`, `frontend/src/PatientPortal.vue`: separate patient UI on `/patient.html` with short-lived patient JWT, simulated check-in/observations, time trends, opt-in and in-app prompts. Clinician UI adds grouped alerts and workflow evaluation tab.
- n8n **12 Synthetic Engagement Watch** runs hourly. All privacy checks and eligibility run in FastAPI; only aggregate counts are returned to n8n. This **does not** dispatch SMS, emails or clinical messages.
- n8n **13 Aggregate Quality Snapshot** records aggregated bucket counts once per UTC hour in the database. No patient/case identifiers are sent to n8n.
- `tests/test_engagement_v24.py`: scope, opt-in, no-plan/no-checkin, dedupe, opt-out, prompt idempotency, urgent ungrouped alerts, safe aggregation, evaluation access and metric honesty.

## Important boundaries

1. Display grouping never downgrades, closes, suppresses or modifies care tasks. Urgent tasks and clinical review/escalation tasks are never grouped; *all* task IDs remain independently actionable in original task queue. UI uses an initial 500-task read window (not a comprehensive pager); the output exposes `potentially_truncated` for that case.
2. The reminder scheduler only writes a simulated in-app record for explicitly opted-in patients with active monitoring plans. No network notifications are sent. Patient UI is not an emergency contact channel.
3. `simulated_receipts` refer to previously approved **simulated** message drafts, not actual patient delivery. There is no claim of closed-loop live care.
4. Evaluation measures synthetic task counts and acknowledgment times **not** diagnosis, sensitivity, specificity, reduction in real clinical workload, or health outcomes.
5. SQLite local test and PostgresCompat have application tables from `engagement24.py`. `database/postgres_target_schema.sql` is an **independent normalized future design**, not an applied migration for the active runtime.
6. Vue/npm build, n8n runtime imports, Docker startup, PostgreSQL live opt-in, external OIDC and real LLM calls still require your deployment environment. Offline tests cannot establish clinical performance.

## Upgrade 2.3 → 2.4

- **Backend, frontend and app files:** deploy latest project 2.4 and preserve `.env`, encryption/JWT keys, DB volumes and prior backup.
- **n8n:** keep your existing **01–11** workflows unchanged. Import **12_synthetic_engagement_watch.json** and **13_aggregate_quality_snapshot.json** through n8n Editor → Import from File. Both arrive **inactive**; check their `X-Internal-Key` and internal API reachability with manual execution before enabling.
- **Fresh installation:** import all **13** JSONs individually. Never import ZIP directly as a single workflow.
- The new endpoints return aggregate or synthetic-only data and do not authorize clinical messaging. Do not paste PHI into n8n/external LLMs.

## How to test manually

```bash
# from project root
pytest -q
python scripts/verify_artifact.py
# optional frontend, requires npm registry and node_modules:
cd frontend && npm install && npm run build
```

- Run API + n8n containers using Docker Compose; issue a synthetic patient token via existing `scripts/generate_demo_token.py` (see script usage). Log in to `http://127.0.0.1:5173/patient.html` (patient token) and the root clinician page (clinician token). Create a synthetic monitoring plan as clinician; then opt in as patient. Manual execution of **12** adds a simulated in-app prompt once (after chosen UTC hour). Re-execution same day adds none. Changing to opt-out prevents future prompts.
- Submit a synthetic urgent Check-in; confirm a separate urgent care task remains in `GET /v4/clinician/alert-groups`, never merged with another. If n8n cannot call API, keep both workflows off and diagnose local connectivity.
