# v3.1 Migration validation

Scope: clean-architecture migration of existing research application boundaries only. Synthetic teaching data, not suitable for real-patient clinical operations.

## Local verification (2026-10-12)

| Gate | Result |
|---|---|
| Python suite (`pytest -q`) | **71 passed, 1 skipped** |
| Inherited API method/path contract | 59/59 unchanged; no duplicate registered endpoints |
| Static n8n graph validation | 15/15 JSON files validated |
| Synthetic policy cases | 12/12 expected decisions |
| Migrated domain/application import boundaries | 8 files passed |
| Python bytecode compilation | passed |
| Actual n8n import and execution | Not performed (no Docker/n8n service) |
| PostgreSQL live connection test | Skipped (live DB not available) |
| OIDC provider and external LLM | Not tested with external services |
| Frontend build | Not performed in this run (npm modules not installed) |

The workflow JSON files were carried forward byte-for-byte from the prior integrated version, so existing n8n installations **must not import duplicates**. Unchanged routes do not guarantee live third-party integration works; test the clinical review workflow in a dedicated local environment.

## Security invariants

- OIDC patient assignments are authoritative only when read from the backend DB, not from a token-provided patient list.
- Patient and clinician roles are separated at API dependency level.
- Input remains limited to synthetic `DEMO-...` patient references.
- Case read hides the image data URL without changing the encrypted underlying record.
- n8n check-in webhooks carry only `event_id`.
- Emergency check-in is triaged synchronously and does not rely on the n8n webhook being available.
- Domain/application modules migrated this release cannot import database drivers or HTTP framework modules.

## Known migration debt

16 case orchestration/administration/reliability endpoints remain in `legacy_api.py` pending a second migration. Legacy coordination, FHIR bridge and engagement SQL code have not yet been fully split into repository interfaces. The PostgreSQL compatibility adapter still holds one shared connection and is not a validated production pool.
