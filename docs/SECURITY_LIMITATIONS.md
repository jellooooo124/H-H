# Threat model, operational limits and non-goals

## In scope / implemented

- Synthetic patient-ID allowlist; input validation; sample consent flag; scoped clinician/patient API access.
- Deterministic safe-stop on urgent reported symptoms, contradictory agent hydration directions, suspicious prompt injection and ungrounded AI citations.
- At-least-once n8n coordination with durable DB retry state, idempotent workflow starts, deadline scanning and failure reconciliation.
- Tamper-evident HMAC audit chain, encrypted synthetic payload, transaction-controlled state transitions.
- Approved operational message templates only, two-step clinician publish, in-app read acknowledgement; no treatment advice and no external notification provider.
- No PHI or token fields in n8n JSON; n8n execution data saving minimized; localhost-only port mapping.

## NOT implemented / blockers to real-world clinical use

- Hospital-approved clinical protocols, external prospective validation, safety case, device classification or regulatory clearance.
- Independent threat assessment, production-grade secrets rotation, external append-only audit anchoring, 24/7 on-call service and dependable emergency escalations.
- Real hospital EHR/FHIR OAuth and patient matching; real clinician identity provisioning and least-privilege hospital IAM.
- Correct multiworker PostgreSQL transaction pool with migration and backup/restore rehearsals at scale.
- Live healthcare notification service with authenticated delivery receipts, consent/quiet-hours requirements and communication SLAs.
- Validated HA deployment, disaster recovery, TLS ingress, network segmentation, retention/deletion policies, comprehensive adversarial testing and subpopulation fairness assessment.

## Local demo n8n security warning

The provided Docker Compose uses `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` so the bundled `$env.HAH_INTERNAL_KEY` expression works, and `N8N_SECURE_COOKIE=false` for **localhost-only HTTP**. These are not acceptable production defaults. When designing a secure hosted service, replace internal shared-header access with limited per-workflow service credentials, restrict editor users and nodes, enable TLS and secure cookies, and enforce egress policy. Never expose the demo installation publicly.

## Important distinctions

- API accepting a case ≠ n8n processing completed ≠ clinician acknowledgement ≠ patient helped.
- An in-app `PUBLISHED_IN_APP` is not proof of viewing; `ACKNOWLEDGED` is not clinical completion.
- Synthetic fixed-fixture match rates are not real-world sensitivity, specificity or clinical benefit.
- Image-derived dietary estimates are ambiguous and not a basis for medication or fluid instructions.
