const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { createInterface } = require('node:readline');
const { Hah } = require('../dist/nodes/Hah/Hah.node');
const { HahApi } = require('../dist/credentials/HahApi.credentials');

test('compiled node → real HTTP → FastAPI auth/persistence/triage', { timeout: 30000 }, async t => {
  const temp = mkdtempSync(path.join(tmpdir(), 'hah-node-'));
  const key = randomBytes(32).toString('hex');
  const env = { ...process.env, APP_INTERNAL_KEY: key, APP_TOKEN_SECRET: randomBytes(32).toString('hex'),
    APP_ENCRYPTION_KEY: randomBytes(32).toString('base64url') + '=', DB_PATH: path.join(temp, 'test.db'),
    DATABASE_URL: '', AUTH_MODE: 'demo', DEMO_MODE: 'true', OPENAI_API_KEY: '',
    KNOWLEDGE_DIR: path.resolve(__dirname, '../../..', 'knowledge') };
  const server = spawn(process.env.PYTHON || 'python3', [path.join(__dirname, 'serve_api.py')], { env, stdio: ['ignore', 'pipe', 'pipe'] });
  let serverErrors = '';
  server.stderr.on('data', b => { serverErrors += b.toString(); });
  t.after(async () => {
    server.kill('SIGTERM');
    if (server.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); setTimeout(() => { server.kill('SIGKILL'); resolve(); }, 2000).unref(); });
    rmSync(temp, { recursive: true, force: true });
  });
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('FastAPI startup timeout')), 10000);
    createInterface({ input: server.stdout }).once('line', line => { clearTimeout(timer); resolve(JSON.parse(line).port); });
    server.once('error', reject);
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`FastAPI exited ${code}: ${serverErrors.replaceAll(key, '[redacted]')}`)); });
  });
  const baseUrl = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(baseUrl + '/health')).ok) break; } catch {}
    await new Promise(r => setTimeout(r, 50));
  }
  // Real HTTP transport, with n8n credential-expression injection represented by
  // this adapter. Full n8n loading/credential resolution is a separate CI job.
  async function run(operation, eventId, apiKey = key) {
    const context = {
      getInputData: () => [{ json: {} }],
      getCredentials: async () => ({ baseUrl, apiKey, allowLocalHttp: true }),
      getNodeParameter: name => ({ operation, eventId, retries: 0 }[name]),
      getNode: () => ({ name: 'H@H', type: 'n8n-nodes-hah.hah', parameters: {} }),
      continueOnFail: () => false,
      helpers: { httpRequestWithAuthentication: async (type, options) => {
        assert.equal(type, 'hahApi');
        assert.equal(new HahApi().authenticate.properties.headers['X-Internal-Key'], '={{$credentials.apiKey}}');
        const r = await fetch(options.url, { method: options.method, headers: { 'Content-Type': 'application/json', 'X-Internal-Key': apiKey },
          body: JSON.stringify(options.body), redirect: 'manual', signal: AbortSignal.timeout(options.timeout) });
        return { statusCode: r.status, body: await r.json(), headers: Object.fromEntries(r.headers) };
      } },
    };
    return (await new Hah().execute.call(context))[0][0].json;
  }
  await t.test('authenticated health', async () => assert.equal((await run('dispatchHealth')).healthy, true));
  await t.test('wrong key rejected and not leaked', async () => {
    const wrong = randomBytes(32).toString('hex');
    await assert.rejects(run('dispatchHealth', undefined, wrong), e => /authentication failed/.test(e.message) && !JSON.stringify(e).includes(wrong));
  });
  await t.test('normal triage uses stored event and repeat is idempotent', async () => {
    assert.deepEqual(await run('triageCheckin', 'CHK-NODE-001'), { event_id: 'CHK-NODE-001', status: 'TRIAGED', priority: 'review', reason_code: 'CHECKIN_RECORDED' });
    assert.equal((await run('triageCheckin', 'CHK-NODE-001')).idempotent, true);
  });
  await t.test('urgent route remains backend controlled', async () => {
    const result = await run('triageCheckin', 'CHK-NODE-URGENT');
    assert.equal(result.priority, 'urgent'); assert.equal(result.reason_code, 'REPORTED_URGENT_SYMPTOM');
    assert.ok(!JSON.stringify(result).includes('chest_pain'));
  });
  await t.test('unknown stored ID becomes safe 404', async () => await assert.rejects(run('triageCheckin', 'CHK-NOT-FOUND'), /Check-in not found/));
  await t.test('internal key does not confer clinician API access', async () => {
    const response = await fetch(baseUrl + '/v1/cases', { headers: { 'X-Internal-Key': key } });
    assert.equal(response.status, 401);
  });
});
