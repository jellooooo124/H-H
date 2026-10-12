# v3.2 release verification (offline)

Run from project root:

```bash
python scripts/check_architecture.py
python scripts/verify_artifact.py
python scripts/evaluate_synthetic_policy.py
pytest -q
```

Observed on the build environment:

```
PASS: 13 migrated application/domain files do not import HTTP or database adapters
n8n workflows: 15 IDs-only boundary: validated
PASS: well-formed graph, internal-only HTTP nodes, no embedded provider key literals
Synthetic scenario checks: 12/12
79 passed, 1 skipped
```

The skipped test is the opt-in live PostgreSQL test; this environment does not include a configured PostgreSQL server. There are 59 preserved HTTP method/path pairs and 15 byte-identical n8n workflows compared with v3.1.

Added fault-injection tests cover rollback of urgent intake and finalization on review-task creation failure, planner fail-close review assignment, watch delay escalation, SQL adapter boundary, dependency imports, and frozen HTTP contract parity.

Not verified: complete Docker stack, real PostgreSQL transactions, real n8n import/execution, frontend production build, external OIDC, live LLM/RAG inference, actual clinical safety. No PHI or clinical paging should be used.
