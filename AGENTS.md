# Agent Working Agreement

This repository is an independent software-engineering portfolio for synthetic-data healthcare workflow automation. It is not a clinical product.

## Before changing code
- Read `README_繁體中文.md` or `README.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_LIMITATIONS.md`, and the relevant tests before editing.
- Treat the current implementation and automated tests as the source of truth. Do not revive old migration notes or superseded specifications without explicit direction.
- Identify the smallest coherent change. Avoid unrelated refactors, dependency upgrades, generated-file churn, or broad formatting changes.

## Safety and privacy boundaries
- Use synthetic data only. Never add real patient data, PHI, secrets, API keys, access tokens, credentials, or private deployment details to source, fixtures, logs, screenshots, or documentation.
- Do not claim clinical effectiveness, diagnostic accuracy, production readiness, or emergency-response capability.
- Keep clinician approval and backend authorization boundaries intact. n8n and LLM tools must not bypass backend rules or directly authorize clinical decisions.
- If an AI provider is unavailable or not configured, preserve fail-closed behavior. Never fake a successful live-model call.
- Do not trigger paid AI workflows, deploy publicly, expose service ports, alter repository visibility, or perform destructive data resets unless explicitly authorized.

## Implementation guidance
- Follow existing architecture and naming conventions. Keep domain rules in the appropriate backend layer and UI behavior in the frontend.
- Preserve least-privilege access, input validation, auditability, synthetic-only policies, and loopback-only demo defaults.
- Workflow JSON changes should be validated against the repository's n8n version and import/integration tests.
- Add or update focused tests for behavior changes, especially authorization, state transitions, failure paths, persistence, and safety gates.
- Do not weaken, skip, or rewrite tests just to obtain a green CI run. Explain any test that could not be run.

## Validation
- Run the narrowest relevant tests first, then applicable project checks. For full-stack changes, prefer the existing GitHub Actions quality, integration, and runtime-smoke workflows.
- Review the final diff for accidental secrets, real-world patient data, unrelated changes, misleading claims, and insecure port bindings.
- Report exactly what changed, which checks ran, and any outstanding failures or limitations. Do not say tests passed unless there is evidence.

## Git and pull requests
- Use a focused branch and descriptive commit/PR title. Never force-push, rewrite shared history, or push directly to `main` unless explicitly requested.
- Keep commits small and explain behavior-impacting changes. Do not commit local `.env`, generated secrets, caches, build outputs, or real data.
- Follow `.github/PULL_REQUEST_TEMPLATE.md` and `docs/AGENT_TASKS.md` when preparing changes.
