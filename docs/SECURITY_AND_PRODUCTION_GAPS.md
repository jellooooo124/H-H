# Security threat model and real-world deployment gaps

**Care Coordination 2.0 update:** The code now also includes encrypted observations/checkins, synthetic monitoring plans, reviewer task claiming, a separate escalation follow-up, synchronous urgent *demo* tasks, pending check-in reconciliation and retry of pending case IDs. These additions are research scaffolding, **not** a real clinical communications or 24/7 emergency service. Production gaps remain as detailed below.


## Demo security boundaries

```
[Patient (synthetic)] -- short-lived JWT --> [FastAPI external intake]
      |                                              |
      |                        encrypted local case store (Fernet)
      |                                              |
      +-- NO DIRECT n8n --> [n8n private case-ID webhook]
                                   |
                         X-Internal-Key per service
                                   |
                            [API bounded tools]
                                   |
          +----------------------+-----------------------+
          |                      |                       |
  OpenAI API (synthetic)   Approved RAG only      Deterministic policy
          |                      |                       |
          +----------------------+-----------------------+
                                   |
                           [Clinician JWT approval]
                                   |
                        [Simulated outbox ONLY]
```

This is an engineering proof-of-concept; *not* evidence of clinical safety or regulatory compliance.

## Assets and trust boundaries

- Identity & permission: `patient` scope only own `DEMO-...` patient_ref; `clinician` can review; internal service uses dedicated shared key. No untrusted browser can call `/internal` without key.
- Protected information: synthetic data payload, optionally image data URL, Agent outputs and drafts stored encrypted at rest with Fernet, password/token never written to patient audit metadata. A screenshot/clinician browser or LLM provider will still see text necessary for the purpose. End-to-end encryption and zero-retention from providers are NOT guaranteed.
- n8n stores only case IDs and non-identifying state; n8n retains workflow credentials/settings on volume. n8n not configured to log full success/error inputs. OAuth, production credential vault and fine-grained approval privileges are not included.
- RAG policy knowledge is explicitly marked `approved_for_demo:true` AND `clinical_use_approved:false`. No arbitrary source URLs, no external search/scraping. Index records version, source ID, SHA256 to support provenance. Sources are *not* actual medical guidance.
- Tools are strictly allowlisted in API; model cannot choose arbitrary HTTP request, change database rows, dispatch email or skip mandatory steps. Clinician approval is rechecked against policy, task ownership and optimistic version.
- Audit: HMAC chained event records and `verify_audit()` detect ordinary modifications; key rotations and compromised backend admins can still rewrite the chain, so this is **not** a WORM/immutable audit trail.

## Important limitations and mitigations before a pilot

| Threat / weakness | Current educational defense | Production requirement |
|---|---|---|
| Accidental PHI to cloud model | Reject non-synthetic flag & DEMO patient reference; never use real PHI | Provider DPA, data residency, legal basis, vetted de-identification, threat evaluation, consent/privacy notices |
| Unsigned n8n webhook | n8n only localhost and Docker network; backend steps need internal key | Network microsegmentation, reverse proxy signed webhook, strict source authentication and mTLS |
| Env secrets accessible in node expressions | Demo-only `$env` secret; n8n dashboard bound localhost | Scoped n8n credentials and secret manager; lock down worker node types and roles |
| HTTP localhost traffic | 127.0.0.1 exposure only | TLS 1.2+, TLS termination or service mesh, managed certificates, encrypted network path |
| Shared JWT signing key | One-hour token from development CLI | SSO with OIDC, MFA, audience, key rotation, token revocation and staff RBAC |
| SQLCipher absent | Fernet encrypted payload/agent state; SQLite file still holds case IDs/timestamps | PostgreSQL with disk/TDE encryption, backups, PITR, access controls, migration/versioning |
| Provider outage/incomplete plan | Fail closed `TECHNICAL_REVIEW` and overdue reviewer flag | Availability SLO, reliable queue, transactional inbox/outbox, paging/acknowledgment and human staffing |
| Concurrent processing/retries | SQLite optimistic version + unique case/outbox | Durable job IDs, queue, idempotency, concurrency tests, replay-resistant signed ingress |
| Missing or drifting wearables | Review flags and age checks; missing != normal | Validated acquisition pipeline, calibrated timestamps, wear-time and completeness trends |
| LLM prompt injection | Untrusted boundary, constrained tools, conservative regex stop | Adversarial multilingual testing, output moderation, red-team, strict tool privilege separation |
| LLM hallucinations / missing citations | Pydantic JSON parse and source-ID subset policy | NLI/entailment citation tests, clinician adjudication, local validation and factual evaluation |
| Safety / alert fatigue | Routine vs escalation and SLA workflow | Formal hazard analysis, signal detection metrics, representative populations, on-call protocols |
| Model and protocol updates | versioned index docs; env-pinned models | model registry, risk sign-off, prospective validation, rollback and drift monitoring |
| Patient interface | Simulated message outbox; no send | Approved EHR integration, disclosure, two-person release policy, clinical governance |
| Observability | redacted audit only | Security monitoring, secured traces, incident response, independent audit log anchoring |
| Data retention and deletion | On completion image data URL cleared | Scoped retention schedule, backup lifecycle, secure destruction, data subject request process |

## Safety rule specification and ownership

- `REPORTED_URGENT_SYMPTOM`: Based on reported boolean flags, blocks auto-approval; routed to clinician review. **No guarantee of emergencies being addressed; no automatic paging.**
- `CONFLICTING_AGENT_HYDRATION` / `NON_BOUNDED_HYDRATION_SUGGESTION`: The agent attempted an action outside its permitted scope. System blocks release.
- `POTENTIAL_PROMPT_INJECTION`: Simple regex. Does not claim comprehensive detection.
- `NO_ACTIVE_VITALS` / `STALE_OR_FUTURE_SENSOR_DATA`: Review flags; do not present absent readings as normal. Staleness is a demo 24h review heuristic, not a validated clinical alert threshold.
- `DEMO_WEIGHT_TREND_REVIEW`: Difference >= 2kg is purely a **synthetic testing heuristic**, not an approved clinical action threshold.
- `MISSING_OR_INVALID_CITATIONS`: Stops if no source or fabricated IDs; citation semantic faithfulness still needs clinician review.
- `UNSAFE_PATIENT_DIRECTIVE`: Conservative regex catches some medication action strings; not a full medical content filter.

## Regulations

For an actual Singapore clinical setting, verify PDPA obligations, relevant MOH clinical AI governance, HSA medical device scope and hospital ethics/governance with competent legal and clinical teams. Different jurisdictions may add HIPAA/GDPR obligations. **This document does not assert certification, regulatory classification or lawful processing of actual patient data.**

## Suggested evaluation metrics

1. Triage safety: false-negative/high-severity miss rate, escalation recall, safe-stop pass rate across predefined synthetic positive and negative scenarios.
2. Alert burden: alerts per 100 cases, unnecessary escalation rate, review time, overdue rate.
3. RAG: source citation validity, evidence faithfulness adjudicated by two reviewers, stale-doc rejection.
4. Human-in-loop: time-to-decision, override rate, false approvals, safety conflict recognition.
5. Security: unauthorized ingress blocked, cross-patient access denied, duplicate replay rejected, raw payload leakage absence, audit integrity detection.
6. Model stability: prompt injection red-team, out-of-distribution, missing data, multimorbidity counterexamples, provider outage.

Demo policy gate = safeguard against unsafe automatic actions, **not** proof of safe clinical diagnosis.
