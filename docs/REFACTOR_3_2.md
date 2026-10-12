# Clean Architecture migration v3.2 — clinical-case and agent-boundary hardening

## Scope actually implemented

This release moves every remaining route from the 3.1 `legacy_api.py` into narrow presentation routers and plain Python use cases **without changing HTTP method/path pairs or the 15 n8n JSON files**. Existing `main.py` and `legacy_api.py` module paths remain compatibility entrypoints. All inputs are synthetic educational data (`DEMO-*`).

### New bounded modules

| Layer | Module | Ownership |
|---|---|---|
| Domain | `domain/workflow_rules.py` | Urgent symptom flag, approval eligibility, mandatory tool set, tool allowlist, typed business failures |
| Application | `application/clinical_cases.py` | Transactional intake, clinician decision, SLA/watchdog, failed-agent human review |
| Application | `application/agent_execution.py` | Start, plan, bounded tool execution, synthesized safety finalization, RAG indexing |
| Application | `application/dispatch_operations.py` | Queue draining, bounded retry, dead-letter review, health status, operational audit |
| Application | `application/access_administration.py` | Admin-only patient assignment use case |
| Infrastructure | `infrastructure/case_dispatcher.py` | Case-ID-only HTTP webhook adapter |
| Infrastructure | `infrastructure/persistence/checkin_reader.py` | Check-in state SQL adapter |
| Infrastructure | `infrastructure/persistence/health_reader.py` | Database/audit chain health SQL adapter |
| Presentation | `presentation/routers/{clinical_cases,agent_execution,dispatch_operations,system_admin}.py` | Existing HTTP contracts and auth dependencies |

### Concrete safety improvements

1. Urgent intake: encrypted case creation, queue insertion **and** urgent review-task creation now share one DB transaction. On task creation failure the entire intake rolls back.
2. Finalization: policy/audit/state update and clinician review-task creation share one DB transaction. Injected task-write failure rolls back policy finalization; a separate fail-closed step creates `TECHNICAL_REVIEW` with human review task (provided the datastore is healthy).
3. Planner/agent failure: records a `TECHNICAL_REVIEW` case plus review task instead of a terminal state with no assigned work.
4. Decision: server-side version, task ownership, approval eligibility and all decision writes are enclosed in one transaction. The safety policy is independently recomputed when approving.
5. Watchdog: when a case is escalated for delay, it also creates an idempotent human review task inside the transaction.
6. Dispatch: case and check-in webhook adapters send **opaque identifiers only**; app code no longer makes HTTP calls or runs SQL statements directly for the check-in state.

All of these functions are synthetic workflow demonstrations, **not** an independently validated clinical paging/monitoring system. If the database itself is unavailable even a fail-closed transition may fail; this still requires external operations monitoring.

## Contract parity and tests

- `contracts/api_routes_v3_1.json` freezes the exact 59 method/path pairs from the original v3.1 app; v3.2 compares itself against them in tests.
- All 15 `workflows/*.json` files are byte-identical with v3.1; there is no new Webhook or activation required for an existing n8n installation.
- 79 Python offline tests pass; 1 opted-in PostgreSQL live test is skipped in an environment without an instance.
- 12/12 synthetic safety scenarios pass.
- Static guards verify that 13 migrated domain/application files do not import HTTP or persistence frameworks.
- Frontend build, real n8n execution, PostgreSQL integration, OIDC provider and live model calls **were not run in this release**.

## What is NOT yet fully clean or production-ready

- Existing `coordination.py`, `operations23.py`, `engagement24.py`, `fhir_bridge.py`, `communications/repository.py` still combine transaction logic and SQL with domain coordination. These are the next targets for deeper repository extraction; moving their filenames alone would not make them clean.
- The existing PostgreSQL compatibility layer is single-connection educational architecture; it needs a proper connection pool, migration tool, concurrency validation and Postgres integration tests.
- New application ports use Protocol, but adapters are not uniformly injected across the older services.
- Retry acceptance is not proof of workflow completion. Live care operations, paging, incident response, clinical thresholds, regulated-device qualification, local validation and evidence governance remain out of scope.
- Real patient records and secrets must **never** be placed in this course repository or n8n execution history.

## Upgrade procedure

1. Backup the synthetic encrypted DB and retain the **existing** encryption and audit-signing keys.
2. Replace application code with v3.2 and install the existing locked runtime dependencies.
3. Run `python scripts/check_architecture.py`, `python scripts/verify_artifact.py`, `python scripts/evaluate_synthetic_policy.py` and `pytest -q`.
4. The 15 n8n Workflow JSONs are unchanged. **Do not reimport into an existing deployment** (would risk duplicate schedulers/webhooks). Only import the supplied JSONs into a brand-new n8n environment, one at a time, initially disabled.
5. Run real Docker/PostgreSQL/n8n end-to-end testing before activating any workflows.
