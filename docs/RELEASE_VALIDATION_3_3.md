# v3.3 Validation Record — 2026-10-12

The following were **actually executed in the local Python environment** on a clean checkout of the restored v3.2 Git bundle with v3.3 patches applied:

| Check | Outcome |
|---|---|
| `PYTHONPATH=backend pytest -q` | **86 passed, 1 skipped** |
| `python scripts/check_architecture.py` | **PASS** — 13 previously migrated pure modules |
| `python scripts/verify_artifact.py` | **PASS** — 15 inactive n8n JSON static graph/headers checks |
| `python scripts/evaluate_synthetic_policy.py` | **12/12 synthetic policy cases** |
| SHA-256 comparison against v3.2 `workflows/*.json` | **15/15 byte-identical** |
| New v3.3 persistence boundary tests | **7 passed** (included in 86) |
| Original frozen 59 API method/path contracts | Covered by existing API contract tests, unchanged |

### Not run — required on a real Linux or macOS environment with dependencies

- Docker Compose bring-up and service networking
- Native PostgreSQL transaction rollback and schema compatibility with real PostgreSQL
- Simultaneous n8n / queue-worker claims across multiple processes
- n8n execution and import on pinned image version
- Real OAuth/OIDC, external model APIs, and frontend `npm run build`

These are explicit release acceptance blockers for any meaningful pilot beyond a synthetic course demo. No clinical benefit, diagnostic accuracy, or real patient safety validation is claimed.
