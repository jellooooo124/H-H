# API integration and 10-minute project demonstration

## Data flow

```
patient/caregiver app (synthetic data)
    -> POST /v1/intake (patient JWT, consent, schema validation)
    -> encrypted case store
    -> n8n internal POST /webhook/hah-case-intake (only {case_id})
    -> internal/start
    -> internal/plan (real LLM chooses next allowed tool)
    -> internal/tool (nutrition/vision, HF, diabetes, RAG)
    -> repeat until all 4 complete
    -> internal/finalize (LLM synthesis + deterministic safe gate)
    -> clinician GET /v1/cases/{id}
    -> clinician POST /v1/decisions (approve/reject/escalate)
    -> simulation outbox (NO send)
```

### Public patient & clinician API (example)

- `POST /v1/intake` — synthetic patient bearer token + `examples/normal.json` schema.
- `GET /v1/cases` — clinician only; list cases (case ID, pseudonymous reference, status).
- `GET /v1/cases/{id}` — clinician only; returns synthetic raw readings, structured agent outputs, document ID/version/hash, policy results and current state version; image is omitted.
- `POST /v1/decisions` — clinician only; `{case_id,choice:"approve|reject|escalate",comment:"min 8 chars",expected_version:number}`.
- `GET /v1/audit/{id}` — clinician audit, with chain_valid.
- `GET /v1/outbox` — clinician view of simulated send queue, not actual SMS/email.

### Internal API (from n8n only)

- `POST /internal/start`: `{case_id}`.
- `POST /internal/plan`: `{case_id}` -> `{next_tool,done}`.
- `POST /internal/tool`: `{case_id,tool}`. Requires latest model plan + allowlist.
- `POST /internal/finalize`: `{case_id}` -> safe-stop and review status.
- `POST /internal/knowledge/reindex`: `{}`. Requires OpenAI key for embeddings.
- `POST /internal/watchdog`: `{}`.
- `POST /internal/error`: `{workflow_name,error_code}` with no PHI.

All internal API requests MUST include the private `X-Internal-Key`. No case/PHI data travels through workflow nodes besides the synthetic case ID. API retains encrypted payload and agent states.

## Spring Boot or EHR/FHIR future integration

Your proposal mentioned Vue + Spring Boot. This demonstrator includes Vue but uses FastAPI for the secure agent/tool gateway to minimize complexity for a working n8n proof-of-concept. Spring Boot can later serve as the trusted hospital façade (JWT/OIDC provider and FHIR connector), forwarding pseudonymous / allowlisted data to the same FastAPI route. Do not bypass API policy endpoints or write to an EHR from an LLM agent directly.

Recommended production separation:

```
Vue clinician UI --> Spring Boot (OIDC + MFA, RBAC, EHR FHIR API)
                           |
                  reviewed, scoped event
                           |
                    FastAPI tool gateway
                           |
                      n8n work planner
                           |
                    safe review case ID
                           |
                Spring Boot approval/writeback
```

FHIR data contract (design target, **not implemented**): `Observation` for measured vitals, `Patient` pseudonym / identity resolved only behind hospital gateway, `Device` / `DeviceMetric` for wearables, `CommunicationRequest` draft, `Provenance`/`AuditEvent` for evidence and actions, `Task` for clinician work queue. Do not claim those integrations currently exist.

## 10-minute presentation flow (CA6117)

| Segment | Suggested time | Evidence |
|---|---|---|
| Problem & audience | 1 min | Heart failure + diabetes H@H alert fatigue and missingness |
| Architecture | 1 min | n8n canvas + FastAPI layers + Vue screenshot |
| Perceive/Reason/Act | 2 min | Synthetic intake -> actual planner choose next tool -> four tool results |
| Agentic RAG | 1 min | guideline embedding retrieval ID/version and final cited source IDs |
| Safety hazard demo | 1.5 min | redflag input -> urgent/blocked; injection input -> safe-stop |
| Human checkpoint | 1.5 min | Vue raw-vitals-side-by-side with agent results, reject/escalate, audit |
| Tests & evaluation | 1 min | automated `pytest` results, known limitations |
| Conclusion | 1 min | no real patient sending, clinical deployment gap & future work |

Use exactly synthetic data in slides/video. Capture n8n node outputs that show **case IDs, tool selection and state only**. Do not show env values, API keys or real patient data.

## Execution verification checklist

1. `python -m pytest -q tests`: all offline unit/integration-with-fake-model tests pass.
2. Docker: `docker compose ps` shows both services healthy/running, and GET `/health` responds.
3. n8n: confirm `01` is **Published**, then send synthetic normal case and see 4 tool calls before finalize.
4. RAG: run `03` and verify retrieved source IDs, versions and content hashes.
5. Redflag: status `ESCALATION_REQUIRED`; attempted Approve HTTP 409.
6. Prompt Injection: status blocked; model did not send communications.
7. No-key drill: remove API key in a separate demo instance, case goes to `TECHNICAL_REVIEW` after attempt, not `AWAITING_CLINICIAN`.
8. Duplicate `case_id` returns 409, invalid JWT returns 401, patient role cannot read clinician endpoints.
9. Clinician audit shows chain_valid=true and does not include raw meal text/image.
10. Browser dashboard and model API must be verified separately in your own environment; this archive's offline test result alone doesn't prove deployment.
