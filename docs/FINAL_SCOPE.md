# Feature scope and priorities

| Area | Included in repository | Status |
|---|---|---|
| Multi-agent planning / LLM tool use | Planner, nutrition/vision, heart failure, diabetes, synthesis | API backed; live calls require model credentials |
| RAG | Versioned synthetic guideline documents with checked source IDs | Research demo; not approved clinical guideline content |
| Safety policy | Hard stop on urgent symptoms/conflicts/unsupported text | Deterministic, unit tested, not clinically validated |
| Patient monitoring | Typed observations, time trends, missingness flags, in-app reminders | Synthetic prototype |
| EHR/FHIR | Restricted FHIR R4 Observation sandbox import/export | Synthetic; no production EHR interface |
| Case coordination | Clinician claim, reject/approve/escalate, shift handoff, retry, reconcilers | DB-backed prototype |
| Communication closed loop | Clinician template draft/publish, patient in-app ACK, overdue follow-up | Newly integrated clean bounded context |
| Secure infrastructure | Demo JWT / OIDC verifier, optional PostgreSQL, encrypted synthetic payloads | Production hardening outstanding |
| Evaluation | 64 offline tests + 12 author-labelled synthetic safety scenarios | No external clinical validity |
| User experience | Patient portal, clinician queue and communication UI | Source written; production frontend build pending |
| Operations | 15 importable n8n JSON files, Docker Compose, CI workflows | Static checks passed, real n8n import pending |

**No** real SMS/email, prescription changes, automatic treatment instructions, real clinician pages, hospital integration or clinical deployment are included.
