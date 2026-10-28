# Agentic engineering guardrails — portfolio pilot

## Why this exists

The healthcare automation stack is the **test bed**, not the audience for this feature. This pilot demonstrates a developer platform primitive: an autonomous coding agent can propose a pull request, but **code changes are classified, evaluated, and surfaced for human judgment before merge**. It does not run an autonomous coding agent or verify a real reviewer approved the PR.

## Pilot workflow

1. A human or coding agent opens a GitHub pull request.
2. `.github/workflows/agent-change-guard.yml` runs as a **read-only** PR check, with no paid AI calls, deployment access, or secrets.
3. `scripts/agent_change_guard.py` computes changed paths from two commit SHAs without shell evaluation, maps paths to the task classes defined by `docs/AGENT_TASKS.md`, and writes a machine-readable JSON risk report and Actions summary.
4. For classes C/D/E, the PR must supply **Validation evidence** and **Rollback plan**. For F, a **Risk owner** is required too. Evidence is **self-reported text**, not verified tests or a verifiable GitHub review identity.
5. `scripts/evaluate_agent_guard.py` runs a deterministic synthetic benchmark in CI. All 12 fixtures must pass, with zero missed review-required examples.
6. A human still reviews changes, checks code/test evidence and permissions, and decides whether to merge. **Branch protection and CODEOWNERS must be configured independently** to make human review mandatory.

## Risk taxonomy

| Class | Examples | PR gate |
| --- | --- | --- |
| A | Docs and ordinary Markdown | Advisory |
| B | Isolated API/UI/test changes | Advisory; standard quality CI remains |
| C | Domain rules, DB persistence, unknown new paths | Validation + rollback text required |
| D | Agent tools, RAG sources, n8n JSON workflows | Validation + rollback text required |
| E | Dependencies, scripts, CI support config | Validation + rollback text required |
| F | Authentication, secrets, Docker exposure, GitHub Actions, guardrail code | Validation + owner + rollback text required |

The rule is deliberately conservative for unknown paths. Mixed PRs inherit the highest-risk class. This is **path-based triage**, not semantic static analysis: a change to a known lower-risk file may still introduce serious security issues. Deletions and renames require human attention; the current diff uses added/copied/modified/renamed destinations, not deleted file entries.

## Try it without Docker or an AI provider

```bash
python scripts/evaluate_agent_guard.py --output /tmp/agent-eval.json
python -m pytest -q tests/test_agent_change_guard.py
# In a git checkout with two local commits:
python scripts/agent_change_guard.py --base HEAD~1 --head HEAD --output /tmp/risk.json
```

Example PR evidence fields (put real evidence in the PR, not placeholders):

```text
- Agent involvement: assisted
- Validation evidence: python -m pytest -q tests/test_agent_change_guard.py (passed)
- Risk owner: repository maintainer
- Rollback plan: revert the PR; no migration required
```

## What is measured

- **Fixture agreement** = exact matches for risk class, review flag and evidence completeness / fixture count.
- **Missed high-risk reviews** = fixtures requiring review but classified as not requiring review; CI target: zero.
- **Artifacts**: `agent-guard-benchmark` JSON and `agent-change-risk` JSON in GitHub Actions.
- **Not measured**: LLM code-generation correctness, autonomous agent task success, attack resistance, production reviewer activity, real developer adoption, or time saved.

## Next pilot milestones (not implemented)

1. Integrate an actual coding-agent runner in a sandbox with per-task credentials, egress controls, budget limits and human approval before privileged operations.
2. Add evaluated agent-written PRs in a protected fork/test repo; compare defect escape rate and time to review against human PRs.
3. Enforce CODEOWNERS + protected branches, add verified CI status checks, audit events, rollback drills and incident response.
4. Add a measured developer pilot (opt-in engineer cohort, task completion, PR cycle time, override reasons, failure taxonomy and cost per accepted change).
5. Only after these checks, consider cross-repo orchestration via n8n.

## Safety / trust boundaries

- **No production agent runner or sandbox** is claimed.
- A green triage check verifies required **text fields only**. It does not make the code safe or mean a human has approved.
- A pull request workflow checks out untrusted PR code; its token has `contents: read`, checkout does not persist credentials, and no secrets or deployments are provided. Review workflow changes carefully.
- No real patient data, billable provider calls, live clinical use, or public service port exposure.
- Original application quality, real PostgreSQL/n8n integration and runtime-smoke gates remain unchanged.
