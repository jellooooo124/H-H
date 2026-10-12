# n8n Import and Activation Guide

The **15 `.json` files** in this folder are independent n8n workflows. Unzip the release package and import the JSON files **one at a time** using the editor's "Import from File" option. Do not import the ZIP itself as one workflow.

All are inactive by default. Required deployment details:
- HTTP node targets are `http://api:8000/internal/...`, valid **inside the provided Docker Compose network**.
- Header `X-Internal-Key` is read from `$env.HAH_INTERNAL_KEY`. This environment variable must match `APP_INTERNAL_KEY` on FastAPI.
- n8n expression access to the environment is permitted only for this **local, isolated single-tenant demo**. Use a dedicated n8n credential and a secure ingress/role model before any hosted deployment.
- The 01 workflow uses the inbound `hah-case-intake` webhook; the 05 workflow handles synthetic checkins. Verify webhook paths and API calls before scheduling.
- New 14 and 15 workflows run overdue simulated message follow-up and aggregate metrics. No external patient communications are performed.
- All execution data save flags are disabled and content transmitted to n8n is limited to opaque IDs or aggregate counts.

Run all workflows manually, verify credentials and check duplicate scheduled workflows before activation. Importing alone does not prove compatibility with your installed n8n release.
