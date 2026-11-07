# H@H custom integration node

Reusable TypeScript n8n node for the existing H@H FastAPI **synthetic-data** API. It uses n8n credentials and its authenticated HTTP helper; no patient payload, model call, clinical decision or outbound message is accepted by this node. The package is private/unpublished, not a verified community node.

## Operations and contracts

| Operation | Existing API | Input | Output / behavior |
| --- | --- | --- | --- |
| Get Dispatch Health | `POST /internal/ops/dispatch-health` | None | Allowlisted queue counts and health flags; does not drain the queue |
| Triage Check-in | `POST /internal/checkin/triage` | `event_id` only | Backend-owned status/priority/reason, or an idempotent replay result |

Each input item creates one output with `pairedItem`. Expressions such as `={{ $json.event_id }}` resolve separately for every item. Additional input fields are never sent or copied into output. IDs must be 1–128 ASCII letters/digits/underscores/hyphens, starting with a letter/digit; this deliberately narrower integration contract rejects free text.

These endpoints return one object, with no cursor/page contract. Pagination is intentionally absent. Patient/clinician endpoints, arbitrary URLs, dispatch drain and clinical approval are not exposed.

## Build and tests

From repository root, with Node 22 and the backend test dependencies installed:

```bash
npm --prefix packages/n8n-nodes-hah ci --ignore-scripts
npm --prefix packages/n8n-nodes-hah test
npm --prefix packages/n8n-nodes-hah run test:integration
python -m pytest -q tests/test_custom_node_contract.py
# Linux + Docker, exercises the actual n8n loader and credential resolver:
python packages/n8n-nodes-hah/tests/runtime_smoke.py
```

Set `PYTHON` to an **absolute** virtual-environment Python path if it is not on PATH. Integration tests start real FastAPI on an ephemeral loopback port, use a temporary SQLite database and generated secrets, then remove them. They make no cloud/provider calls. The Node integration harness substitutes only the n8n HTTP/credential adapter; the Docker test separately checks actual n8n package loading, encrypted credential resolution, both example workflows and replay. PostgreSQL and the existing 15 workflows retain their separate integration gates.

## Install in a self-hosted n8n instance

Target runtime: the repository's pinned n8n `2.42.6`; TypeScript compilation uses locked `n8n-workflow` `2.16.0`. See the [custom-node CI run](https://github.com/jellooooo124/H-H/actions/workflows/custom-node.yml) for runtime evidence. Other versions are not certified.

1. Build with `npm ci --ignore-scripts && npm run build` in this directory.
2. As the n8n operating-system user, copy `package.json` and the built `dist/` directory into `<n8n-user-folder>/.n8n/nodes/node_modules/n8n-nodes-hah/`. Do not copy development `node_modules`, tests or credentials. The default container user folder is `/home/node`; ensure file ownership permits that user to read them.
3. Enable loading community packages in that isolated instance, then restart n8n. Search for **H@H** in the node picker. In Compose, use a persistent volume or derived image for the package; manual changes to a container's writable layer disappear on recreation. The default project Compose stack is unchanged and does not automatically install this optional package.
4. Add an **H@H Internal API** credential. Set the trusted API base URL and the key matching the backend's `APP_INTERNAL_KEY`. Prefer HTTPS. For the existing private Compose demo, use `http://api:8000` with **Allow Local Demo HTTP** enabled. From a host-installed n8n use the API's loopback URL instead. `localhost` inside a container refers to that container.
5. Test the credential. This calls authenticated dispatch health, so `503` may mean valid credentials but a dead-letter queue requiring operator review. It is not a key-only validation endpoint.
6. Import [dispatch-health.json](examples/dispatch-health.json) or [triage-checkin.json](examples/triage-checkin.json), then select the credential in each H@H node. The exports contain no credential ID or secret and are inactive. Keep them manual until reviewed.

Do not use `N8N_CUSTOM_EXTENSIONS` for these package examples: that loader uses a different node namespace. The examples expect `n8n-nodes-hah.hah`.

## Demo walkthrough

- Run the health example. Expect `healthy: true`, numeric counts, `synthetic_only: true`, and `webhook_ack_is_not_completion: true`.
- Create a synthetic check-in through the existing patient portal/API. Copy **only its event ID** into the Set node of the triage example, replacing `CHK-NODE-001`. The example does not create a check-in; a nonexistent ID correctly returns `404`.
- Execute triage. The backend determines priority; this node does not receive symptoms. If an existing workflow or immediate urgent handling already processed the event, expect `idempotent: true` on the first manual call.
- Rerun the same ID: expect the idempotent response, not a second clinical task. Show the backend audit/task view separately using authorized clinician access.
- In a disposable credential, use an incorrect key: expect a sanitized authentication failure. No key, response body, full URL or patient input should appear in this node's error output.

## Reliability and security choices

- Credentials inject `X-Internal-Key` using n8n's generic authentication. Workflow JSON never holds that key. Credential testing uses n8n's credential-test request adapter (the type does not expose the execution helper), with equivalent URL and redirect checks.
- HTTPS is required except explicitly enabled `localhost`, `127.0.0.1`, `[::1]`, or Compose host `api`. User info, query strings and fragments in the base URL are rejected. TLS verification stays on; redirects are disabled so a redirect cannot forward the key to another host.
- This is **not a complete SSRF/network policy**. Trusted administrators choose the base URL; HTTPS can still target private addresses and DNS can change. Protect editor/credential access and apply network egress rules outside the node. The shared backend internal key remains broad; a custom node cannot turn it into scoped service authorization.
- Requests time out after 10 seconds. Health retries only HTTP `429/502/503/504`, with 250 ms exponential backoff and up to three retries (two by default). A valid `Retry-After` is honored up to 30 seconds; longer delays stop for rescheduling. Authentication, validation, malformed responses and ambiguous transport failures are not retried.
- Triage has **no automatic request retry**. Its backend supports sequential replay, but this is not proof of cross-worker exactly-once processing. On timeout, inspect backend state before rerunning the same ID. Leave n8n's independent node-level **Retry On Fail** off unless you have reviewed replay behavior.
- Stop-on-error is default. n8n Continue On Fail returns only a stable safe `code`/`error` plus item linkage; route these failures explicitly so they are not mistaken for success. Raw HTTP exceptions are discarded, including their cause/request/response data.
- Responses are checked and allowlisted, so unexpected fields do not enter execution output. Do not feed real patient data into upstream nodes: this node cannot scrub execution data already saved elsewhere. Examples disable saved execution payloads, but instance retention controls still need review.

## Limits and rollback

No npm publication, n8n Cloud installation, production deployment, live provider test or real-patient claim is made. The backend still has its documented demo-auth, shared-key and multiworker limitations. To roll back, unpublish any optional workflows using H@H, remove the package directory and restart n8n; the original 15 built-in-node workflows and backend APIs are unchanged. Keep workflows that reference the package disabled until it is reinstalled.

References: [n8n HTTP helper](https://docs.n8n.io/connect/create-nodes/build-your-node/reference/http-request-helpers.md), [credentials](https://docs.n8n.io/connect/create-nodes/build-your-node/reference/credentials-files.md).
