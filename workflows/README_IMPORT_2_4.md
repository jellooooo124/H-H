# v2.4 n8n import steps

- **Existing 2.3**: leave 01–11 untouched; deploy 2.4 backend, import **12 and 13** via Editor > Import from File. Run manually, then enable if the Docker API is reachable. Both default inactive.
- **Fresh install**: unzip full import package; individually import 01–13 JSONs. ZIP itself is not an n8n workflow.
- 12 = synthetic in-app reminder watch (hourly, only aggregate counts to n8n, no real notification)
- 13 = aggregate quality snapshot (hourly, contains no patient ID)
- Both use `http://api:8000/internal/...` and `X-Internal-Key: ={{ $env.HAH_INTERNAL_KEY }}`. Only suitable for protected local Docker demo. **Do not expose n8n/API publicly or pass PHI.**
- Do not install duplicate schedule workflows; deactivate older matching jobs. Enable only after manual execution.
- Static JSON schema check passed, live n8n import/version compatibility must be tested on the target instance.
