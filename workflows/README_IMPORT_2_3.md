# n8n v2.3 Import Instructions

- These are 11 individual inactive native Workflow JSON files; unzip first.
- New installation: import 01–11 individually using n8n Editor > Import from File.
- Upgrade from 2.2: **DEACTIVATE OLD 07**, import updated 07, then import new 10 and 11. Keep 01–06 and 08–09; do not activate duplicate old/new 07 schedules.
- 07 = database-backed dispatch retries, 10 = pending handoff expiry, 11 = dead-letter health monitor.
- Manually verify API credentials via test execution before enabling schedules.
- Internal calls require X-Internal-Key resolved from $env.HAH_INTERNAL_KEY in the Docker demo.
- No real patient data; not for clinical use.
- Passing static JSON checks does not prove import/runtime compatibility with your installed n8n release.
