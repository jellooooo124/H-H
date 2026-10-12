# Verification record — original 1.0 baseline (historical)

Historical record for the original 1.0 baseline; refer to `OFFLINE_TEST_RESULTS_V2.txt` for the current 2.0 verification.

Executed in the earlier artifact authoring environment:

- Python 3.13, `python -m pytest -q tests`: **9 passed**.
- Python `compileall`: successful for backend and scripts.
- n8n workflow JSON: four parseable files; edge and node references checked by tests.
- `node --check` worked for JavaScript files; Vue SFC `App.vue` could not be compiled because Vite and Vue NPM packages were not available offline.
- n8n server, Docker Compose and real LLM provider calls were not executed in this environment. Accordingly, *no claims of live n8n import success or end-to-end clinical operation are made*.

To finish validation on your computer:

1. Copy `.env.example`, generate secrets, enter only a model API key; never enter real patient details.
2. `docker compose up -d --build`, verify both containers and import n8n workflow JSON.
3. `cd frontend && npm install && npm run build && npm run dev` and check the Vue display.
4. Run `python scripts/e2e_live.py --scenario normal`, then `redflag` and `injection`.
5. Capture n8n node run times and case state in screens/video for grading.
6. Enable 02 Watchdog, 04 Error handler and run n8n CLI/instance Security Audit.
7. Verify that `APP_INTERNAL_KEY` and model key do not appear in exported workflows/screenshots.

**Security posture: educational local-only PoC, not hardened clinical production.**
