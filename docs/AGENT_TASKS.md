# Agent Task Classification

Use this guide to scope work for coding agents and human contributors. Classification is a planning aid, not a substitute for review or required CI.

## Task classes

| Class | Typical work | Expected approach | Minimum evidence before merge |
| --- | --- | --- | --- |
| **A — Documentation / maintenance** | README, runbooks, comments, templates, non-functional config | Keep scope small; verify links, commands, and statements against current behavior | Diff review; run a Markdown/link check if available |
| **B — Isolated code / UI** | Small API, frontend, validation, or presentation change | Follow existing patterns; add focused regression tests | Relevant unit/contract tests and frontend build when applicable |
| **C — Domain / authorization / data** | State transitions, role scope, audit records, persistence, encryption, migrations | Trace trust boundaries and failure cases before editing; avoid broad rewrites | Focused tests plus backend/security/architecture checks; integration test for persistence or schema changes |
| **D — Workflow / agent / RAG** | n8n JSON, tool permissions, prompts, retrieval, model adapters, retries | Preserve backend authority, bounded tools, evidence traceability, and fail-closed behavior; never fake a live model result | Workflow import/integration checks and relevant safety/policy tests; live-provider tests only with explicit approval |
| **E — CI / dependencies / build / deployment** | GitHub Actions, Docker, dependency locks, build cache, deployment configuration | Prefer least privilege, pinned/reproducible dependencies, cache-safe behavior, and no public exposure | Relevant CI job(s), configuration review, and full runtime smoke when the stack or build path changes |
| **F — Security-sensitive / externally visible** | Authentication, secrets, network exposure, public deployment, destructive reset, paid-provider execution | Stop and identify threat, blast radius, cost, and rollback; require explicit authorization for paid/destructive/exposure changes | Security-focused review and relevant tests; document limitations and obtain approval before executing gated actions |

A change may span several classes. Use the highest-risk applicable class to decide the validation and approval needed.

## Default workflow
1. Read `AGENTS.md`, the relevant architecture/security docs, and nearby implementation/tests.
2. State the task class, expected files, acceptance criteria, and likely risks before a non-trivial change.
3. Make the smallest coherent patch; avoid unrelated refactors.
4. Add regression tests for behavior changes and failure paths.
5. Run focused checks, then the applicable CI/integration/runtime tests.
6. Inspect the final diff and ensure only synthetic data and non-sensitive configuration are present.
7. Summarize files changed, checks actually run, results, and unresolved risks in the PR.

## Non-negotiable project constraints
- Synthetic data only. Never add real patient data, PHI, secrets, or credentials.
- This portfolio is not a clinical product; do not claim diagnosis, treatment, emergency response, or clinical validation.
- Preserve backend authorization and clinician approval. Automation and LLM tools cannot bypass these boundaries.
- AI-provider calls may incur cost. Do not trigger live-provider tests or workflows without explicit user authorization.
- Never publicly deploy the demo, expose PostgreSQL/n8n administrative ports, or perform destructive volume resets without explicit authorization.
- Do not weaken tests, disable safety gates, or report unverified checks as passing.
- Keep pull requests reviewable and use `.github/PULL_REQUEST_TEMPLATE.md`.

## Automated PR triage (pilot)

The read-only GitHub Actions workflow `.github/workflows/agent-change-guard.yml` maps changed paths to these classes and publishes a JSON artifact. Classes C/D/E require PR fields `Validation evidence` and `Rollback plan`; class F additionally needs `Risk owner`. This checks that **non-placeholder text exists**, not that the tests ran or that the named person reviewed. See [pilot design, benchmark and limitations](AGENT_ENGINEERING_PLATFORM.md). Real human approvals require independently configured protected branches/CODEOWNERS.
