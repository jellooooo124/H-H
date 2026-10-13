# Private Linux demo — MacBook Air 2017 deployment guide

**Audience:** independent n8n / AI healthcare operations Portfolio, **synthetic data only**. This guide does NOT create a public website, configure HTTPS, enable real clinical use, or operate paid cloud services.

## Why private by default?

The Compose demonstration uses local HTTP, demo-signed bearer tokens and n8n settings that permit environment variable access from nodes and disable secure cookies. None of these should be exposed on a public IP address. Keep the host's inbound firewall restricted to your SSH access (and your provider's emergency management paths). **Do not open 8080, 8000, 5678 or PostgreSQL 5432 to the Internet.**

## Your Mac needs only SSH and a browser

1. Provision a Linux machine that **you** control, with up-to-date Ubuntu 24.04 LTS and suitable resources (starting evaluation size: approximately 4 vCPU, 8 GB RAM and 40 GB SSD). Cloud providers may charge. Restrict SSH access and keep OS/Docker patched.
2. Install Docker Engine and Compose v2 from [Docker's supported Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Docker group membership confers near-root authority.
3. On the Linux server clone the **private** GitHub repo using GitHub-approved authentication (SSH key or a restricted access token). Do not send keys to this chat:
   ```bash
   git clone git@github.com:jellooooo124/H-H.git
   cd H-H
   cp .env.example .env
   python3 -m venv .venv
   .venv/bin/pip install cryptography
   .venv/bin/python scripts/generate_secrets.py
   # Carefully paste each distinct generated value into .env.
   chmod 600 .env
   ```
4. **Never** keep placeholder values, reuse secrets between environments, commit `.env`, or insert real patient records. Set `OPENAI_API_KEY` empty unless deliberately opting in to provider costs.
5. Run the containers on the Linux server:
   ```bash
   docker compose config -q
   docker compose up -d --build
   bash scripts/verify_remote_deployment.sh
   ```
   The verification script **fails** if the published frontend/API/n8n ports are not bound to 127.0.0.1, or if PostgreSQL is exposed through a host port.
6. From your Mac Terminal (replace `SERVER_USER` and `SERVER_IP`, keep this terminal open):
   ```bash
   ssh -N \
     -L 8080:127.0.0.1:8080 \
     -L 5678:127.0.0.1:5678 \
     -L 8000:127.0.0.1:8000 \
     SERVER_USER@SERVER_IP
   ```
   Then use your Mac browser: clinician at `http://127.0.0.1:8080/`, patient at `http://127.0.0.1:8080/patient.html`, n8n **administration only** at `http://127.0.0.1:5678/`. Do not share the tunnel with other users.
7. Use n8n to import each of `workflows/*.json` (15 files). Activate only deliberate synthetic test workflows, confirm the internal API key mapping, and avoid publishing duplicate webhook paths.
8. To generate expiring demo credentials on the Linux host (not in Git), use `python scripts/generate_demo_token.py --help`. Never paste JWTs into GitHub Issues, screenshots or this chat.

## Data and deployment boundaries

- The PostgreSQL, n8n and API containers run on the Linux server; your old Mac is a remote browser/client.
- **SSH tunnel is private access**, not HTTPS public hosting. Remote SSH users and host administrators still need appropriate trust and security controls.
- `docker compose down -v` deletes named volumes; do not run it casually. Backups should be encrypted, off-host and periodically tested. CI has an isolated **synthetic-only** pg_dump/pg_restore test, not an operational backup service.
- Real AI calls, SSO/OIDC, HTTPS/TLS, monitoring, alerting, service authentication, a secrets manager and hardened n8n Credentials still need dedicated production engineering.
- To turn this into a publicly accessible Portfolio, first provision a domain, HTTPS reverse proxy, hardened demo auth and externally reviewed network/security configuration. Keep n8n editing and internal API private. **Do not expose this existing Compose setup as-is**.
- This software does not provide real-time clinical monitoring, diagnostic advice, a hospital alert service or emergency response.

## Stop or troubleshoot

```bash
docker compose ps
docker compose logs --tail=80 api frontend n8n postgres
docker compose stop      # preserves named volumes
```

In GitHub, check the latest `main` Actions runs for current automated acceptance. See [Portfolio acceptance](PORTFOLIO_ACCEPTANCE.md) and [security limitations](SECURITY_LIMITATIONS.md).

## Zero-budget workflow

Keep `OPENAI_API_KEY` empty for routine development. The app must fail closed rather than fabricate an LLM response; most synthetic workflow, persistence, access-control and UI tests do not require a paid model call. Enable a real provider only for a deliberate test, and configure a provider-side usage limit first.

Run temporary environments only while actively testing and stop them afterward. Check the current account allowance and billing controls before creating Codespaces or other hosted compute; free quotas and eligibility can change. CI concurrency cancels obsolete runs on the same branch/PR, while the newest commit still runs the quality and full-stack gates. Do not treat temporary development environments as always-on hosting.

No paid host or model key is required for normal synthetic-only development. Never expose database/n8n admin ports publicly just to avoid a tunnel or TLS setup.
