# Care Coordination 2.4 — Functional specification and delivery priority

## Product goal

Hospital-at-home multimodal multi-agent workflow for **synthetic** heart-failure and diabetes scenarios. Demonstrate a complete trace from patient-entered observations, agent/RAG review and safety gate, to clinician ownership and subsequent simulated follow-up, without overclaiming medical efficacy.

## Architecture

```text
patient.html (patient JWT) ──┐
                            ├─ FastAPI authenticated patient-scoped endpoints
clinician UI (clinician JWT) ┘          │
                                        ├─ encrypted longitudinal observations / check-ins
                                        ├─ preferences, in-app prompts (no external delivery)
                                        ├─ care_tasks and human approval / handoff
                                        ├─ evaluation / read-only alert group projection
                                        └─ auditing + PostgreSQL or local SQLite
n8n 01–11: unchanged agent orchestration / RAG / handoff / durable retry
n8n 12: hourly API call -> opt-in reminder eligibility -> count-only result
n8n 13: hourly API call -> aggregate snapshot persistence -> count-only result
```

## Priority and acceptance criteria

| Priority | Feature | Acceptance | State |
|---|---|---|---|
| P0 | Safe alert grouping | urgent and review/escalation tasks remain individual; underlying tasks untouched | Implemented/tested offline |
| P0 | Patient scope + opt-out | patient may see only their own records; default no reminder; opt-out cancels pending prompts | Implemented/tested offline |
| P0 | At-most-once simulated prompt per day | repeated scheduler runs do not create duplicate same-day prompt | Implemented/tested offline |
| P0 | Required human checkpoint | no model writes clinical decision; inherited case gate + task ownership | Maintained from 2.3 |
| P1 | Patient interface | self-view 7/14/30-day trends, add observations, report symptoms and view simulated prompt | Implemented; browser build pending verification |
| P1 | Workflow analytics | counts, acknowledgement latency with limitations; aggregate snapshot no PHI | Implemented/tested offline |
| P1 | Importable n8n files | 13 native workflow JSONs, inactive, checksums and change-only pack | Static checks passed; n8n runtime pending |
| P2 | Real app messaging | verified provider callbacks, receipts, failed-delivery handling, consent and preferences | NOT implemented |
| P2 | True hospital / EHR integration | HL7 FHIR service auth, FHIR server and patient consent workflow | NOT implemented |
| P2 | Real clinical evaluation | clinician adjudication, subgroup metrics, sensitivity, calibration and prospective outcomes | NOT implemented |
| P2 | HA and security hardening | real pool, KMS/SSO deployments, on-call SLA, DR drill, penetrations tests | NOT implemented |

## CA6117 evidence plan

Run synthetic negative cases: two urgent alerts must NOT coalesce, duplicate nonurgent reminders DO coalesce in display only, patient opt-out blocks prompts, clinician cannot read patient endpoint, nonmatching patient ID cannot access prompts, no active monitoring plan blocks reminder, snapshot has no patient ID. Evidence units = synthetic tasks, prompt IDs, internal API JSON and HMAC audit chain. **No diagnostic gold standard exists**; do not call these precision/recall metrics.

## Next release 2.5 candidates

- Secure async follow-up: patient messaging gateway in sandbox with signed callbacks, consent ledger, delivery retries, no real outgoing traffic until provider security and governance evaluation.
- Longitudinal alert burden evaluation with explicit synthetic labeled dataset, blinded clinician adjudication and denominator (alerts / 100 monitoring patient-days).
- Production persistence: PostgreSQL connection pooling + Alembic migration tests + rollback DR, OIDC assignments management with MFA, hardened n8n credential isolation.
