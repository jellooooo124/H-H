# Clean Architecture v3.3 — SQL Repository Isolation

## Scope and delivered refactor

Based on v3.2, preserving the 59 frozen method/path routes and all 15 n8n JSON files byte-for-byte.

Extracted infrastructure persistence adapters:

| Service / compatibility entry | SQL adapter |
|---|---|
| `coordination.py` | `infrastructure/persistence/coordination_repository.py` |
| `operations23.py::QueueJob` | `infrastructure/persistence/dispatch_repository.py` |
| `operations23.py::ShiftHandoff` | `infrastructure/persistence/handoff_repository.py` |
| `engagement24.py` | `infrastructure/persistence/engagement_repository.py` |
| `fhir_bridge.py` | `infrastructure/persistence/fhir_repository.py` |
| `communications/service.py` | `infrastructure/persistence/communications_repository.py` |

Services retain data-quality, escalation, care task, two-step handoff, retry / backoff and allowlisted FHIR decisions. SQL `SELECT/INSERT/UPDATE` and schema creation live only in corresponding adapters. The former `communications/repository.py` import path is a shim.

The `legacy_api.create_app` composition root explicitly injects repositories. For backwards compatibility, direct construction of historical services without repository arguments still uses a lazy default SQL adapter. This is a transitional path, not full inversion of control.

The synthetic FHIR bridge uses `Store.transaction()` rather than handwritten SQLite `BEGIN IMMEDIATE` so the unit of work works with the current PostgresCompat translation layer. Existing FHIR idempotency and rollback tests still pass.

## Remaining architecture and deployment gaps

- Services still receive a concrete Store for transaction and audit; next migration should use `UnitOfWork` / `AuditPort` protocols and inject them via the composition root.
- Repository contracts are duck-typed; formal dataclass DTOs and Protocol interfaces should be added before replacing adapters.
- PostgreSQL `PostgresCompat` compatibility layer is **not** a production-ready native driver/repository or distributed job-queue implementation.
- No actual Docker daemon, PostgreSQL instance, concurrent-worker integration test, n8n execution, external OIDC, or Vue build was available in this runtime. CI should validate these in a machine with dependencies.
- No real patient information, public endpoints, automatic medication recommendation or clinical release allowed.

## Verification commands

```bash
PYTHONPATH=backend pytest -q
python scripts/check_architecture.py
python scripts/verify_artifact.py
python scripts/evaluate_synthetic_policy.py
```

See `docs/MAC_AIR_2017_DEPLOYMENT_V33.md` for recommended remote Linux setup and execution acceptance criteria.
