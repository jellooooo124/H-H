# CA6117 10-minute demonstration scenario

Use fictional `DEMO-*` patients only. Each step must show a visible API result, agent trace, source or audit event; do not claim clinical efficacy.

| Minutes | Demo | Evidence |
|---|---|---|
| 0–1 | Clinical capacity and false-alert problem; scoped agents | Architecture and business problem |
| 1–2 | Synthetic patient vital + meal / check-in | API input schema, data validation |
| 2–4 | n8n orchestrator chooses and executes bounded tools | Agent plan, RAG source hashes, tool trace |
| 4–5 | Red-flag/conflict path | Deterministic safe-stop + human task |
| 5–6 | Clinician claim and review | Original data next to output; approve/reject/escalate |
| 6–7 | Two-step handoff + durable retries | Task owner, new owner ACK, audit |
| 7–8 | Draft → clinician-publish → patient in-app ACK | Communication state and expiry watch |
| 8–9 | Synthetic test benchmark | `docs/SYNTHETIC_POLICY_EVALUATION.json` (not clinical validity) |
| 9–10 | Security and limitations | Threat model; real clinical pilot prerequisites |

Rehearse all n8n imports inactive, check HTTP credentials, enable only the workflows needed for a controlled demo; avoid accidental duplicate trigger schedules. Case and patient demo tokens are generated with `scripts/generate_demo_token.py` after `.env` configuration.
