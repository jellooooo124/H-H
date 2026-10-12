# Clean Architecture migration v3.1 — implementation and remaining work

## Completed

- Moved `Store` and `PostgresCompat` to `infrastructure/persistence` without changing SQL semantics, encryption or audit chain; old module import names remain as shims for existing tests and third-party callers.
- Centralized patient-ref checks and clinician OIDC assignment policy in `domain/patient_scope.py` and `application/access_control.py`. OIDC patient assignment rechecked on each request, never trusted from token claims.
- Replaced mixed v1 case-query, v2 observation/check-in/task, v3 synthetic FHIR and shift/handoff, v4 engagement handlers with dedicated FastAPI routers and application services.
- Separated check-in webhook transport into an infrastructure dispatcher port; the application use case only handles persisted ID-only messages, urgent synthetic task creation, and retry state.
- Kept all 59 existing method/path contracts; no changes to the 15 n8n JSON workflow graphs. CI checks API paths, domain/application dependency boundary, synthetic policy, workflow static validation and Python tests.

## Modules

```text
backend/app/
  domain/patient_scope.py
  application/
    ports.py, access_control.py, case_queries.py, monitoring.py,
    engagement_use_cases.py, fhir_use_cases.py, handoffs.py
  presentation/
    auth.py
    routers/{case_queries,monitoring,fhir,handoffs,engagement}.py
  infrastructure/
    checkin_dispatcher.py
    persistence/{sql_store,postgres_compat}.py
  communications/              # older bounded module; further cleanup later
  legacy_api.py                 # 16 still-compatible routes; not yet complete migration
```

## Invariants

1. No routes or webhook contract names removed. API contract is checked by `tests/test_architecture_refactor.py`.
2. OIDC clinician patient assignments always derive from the server-side DB. Demo-mode behavior is intentionally retained only for teaching.
3. No raw patient data is sent to n8n: check-in dispatch contains only `event_id`.
4. Safe-stop, clinical decision gating, audit HMAC and transactional task transitions remain unchanged.
5. Any fake or live patient identifier that does not match the synthetic DEMO namespace is rejected.

## Still outstanding (not disguised as production-ready)

- Remaining `legacy_api.py` routes: intake, clinician case decisions, agent plan/tool/finalize, watchdog, RAG index control, queue drain, audit health, and administrative assignment. These need application services and adapters with transaction parity and new tests before moving.
- `coordination.py`, `operations23.py`, `engagement24.py`, `fhir_bridge.py` and the older communications repository still mix SQL and business rules. Next step is repository interfaces + migrations; do not copy SQL into HTTP routes.
- Real PostgreSQL, n8n execution, OIDC provider, model API and Vue builds still require end-to-end integration tests in a configured environment. Legacy SQLite-compat PostgreSQL adapter remains single-connection teaching code.
- Synthetic only; no production clinical paging, live EHR, real-patient data or validated clinical decision-making.

## Local commands

```bash
pip install -r backend/requirements.txt pytest pytest-asyncio
pytest -q
python scripts/check_architecture.py
python scripts/verify_artifact.py
python scripts/evaluate_synthetic_policy.py
```

## Upgrade from prior integrated build

Replace backend source code with v3.1; do not drop the old database or rotate encryption and audit signing secrets while upgrading existing encrypted educational records. Existing n8n workflows 01–15 can stay enabled as before. If using a new n8n instance, import the 15 JSON files individually from `workflows/`, set the credentials, and validate each disabled workflow before activating schedules.
