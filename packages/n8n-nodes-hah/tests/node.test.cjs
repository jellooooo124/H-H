const { test } = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { Hah } = require('../dist/nodes/Hah/Hah.node');
const { HahApi } = require('../dist/credentials/HahApi.credentials');
const { baseUrl, requestOptions, callApi, mapResponse } = require('../dist/nodes/Hah/transport');
const credentials = { baseUrl: 'https://hah.example.invalid', apiKey: randomBytes(32).toString('hex') };
const health = { healthy: true, counts: { PENDING: 2, DEAD: 0 }, synthetic_only: true, webhook_ack_is_not_completion: true };
const ok = (body = health) => ({ statusCode: 200, headers: {}, body });

function context(request, params = {}, count = 1, continueOnFail = false) {
  return {
    getInputData: () => Array.from({ length: count }, () => ({ json: { private_content: 'must not copy' } })),
    getCredentials: async () => credentials,
    getNodeParameter: (name, i, fallback) => typeof params[name] === 'function' ? params[name](i) : params[name] ?? ({ operation: 'dispatchHealth', retries: 0 }[name] ?? fallback),
    getNode: () => ({ name: 'H@H', type: 'n8n-nodes-hah.hah', typeVersion: 1, position: [0, 0], parameters: {} }),
    continueOnFail: () => continueOnFail,
    helpers: { httpRequestWithAuthentication: async function (type, options) { assert.equal(type, 'hahApi'); return request(options); } },
  };
}

for (const url of ['http://example.com', 'ftp://localhost', 'https://user:pass@example.com', 'https://example.com?key=x', 'https://example.com#x', 'http://api.evil.test', 'http://169.254.169.254']) {
  test(`reject unsafe origin ${url}`, () => assert.throws(() => baseUrl({ ...credentials, baseUrl: url, allowLocalHttp: true })));
}
test('local HTTP requires opt-in; HTTPS supports proxy prefix', () => {
  assert.throws(() => baseUrl({ ...credentials, baseUrl: 'http://api:8000' }));
  assert.equal(baseUrl({ ...credentials, baseUrl: 'http://api:8000/', allowLocalHttp: true }), 'http://api:8000');
  assert.equal(requestOptions({ ...credentials, baseUrl: credentials.baseUrl + '/hah/' }, 'dispatchHealth').url, credentials.baseUrl + '/hah/internal/ops/dispatch-health');
});
test('blank and newline credentials rejected without network access', () => {
  for (const apiKey of ['', ' ', 'a\nb']) assert.throws(() => baseUrl({ ...credentials, apiKey }));
});
test('credential definition injects secret only as header', () => {
  const c = new HahApi();
  assert.deepEqual(c.authenticate.properties, { headers: { 'X-Internal-Key': '={{$credentials.apiKey}}' } });
  assert.equal(c.properties.find(p => p.name === 'apiKey').typeOptions.password, true);
});
test('request allowlist, ID validation and body minimization', () => {
  for (const eventId of ['', '../path', 'patient notes', 'x'.repeat(129), { secret: true }]) assert.throws(() => requestOptions(credentials, 'triageCheckin', eventId));
  assert.throws(() => requestOptions(credentials, 'publish'));
  const o = requestOptions(credentials, 'triageCheckin', 'CHK-TEST-001');
  assert.deepEqual(o.body, { event_id: 'CHK-TEST-001' });
  assert.equal(o.disableFollowRedirect, true);
  assert.equal(o.timeout, 10000);
  assert.equal(o.skipSslCertificateValidation, undefined);
  assert.ok(!JSON.stringify(o).includes(credentials.apiKey));
});
test('output allowlist drops unexpected nested content', () => {
  assert.deepEqual(mapResponse('dispatchHealth', { ...health, token: 'private', counts: { ...health.counts, patient_name: 'private' } }), health);
  assert.throws(() => mapResponse('dispatchHealth', { ...health, counts: { DEAD: -1 } }));
  assert.throws(() => mapResponse('dispatchHealth', { ...health, healthy: false }));
  assert.throws(() => mapResponse('triageCheckin', { event_id: 'other', status: 'TRIAGED', idempotent: true }, 'CHK-TEST-001'));
});
test('health retries transient failures and honors Retry-After', async () => {
  let calls = 0; const waits = [];
  const result = await callApi(async () => ++calls < 3 ? { statusCode: 429, headers: { 'retry-after': '1' } } : ok(), requestOptions(credentials, 'dispatchHealth'), 'dispatchHealth', undefined, 2, async ms => waits.push(ms));
  assert.deepEqual(result, health); assert.equal(calls, 3); assert.deepEqual(waits, [1000, 1000]);
});
test('thrown HTTP errors retry with bounded backoff', async () => {
  let calls = 0; const waits = [];
  await assert.rejects(callApi(async () => { calls++; throw { response: { status: 502 } }; }, requestOptions(credentials, 'dispatchHealth'), 'dispatchHealth', undefined, 2, async ms => waits.push(ms)), { code: 'HTTP_502' });
  assert.equal(calls, 3); assert.deepEqual(waits, [250, 500]);
});
for (const status of [301, 401, 403, 404, 409, 422, 500]) {
  test(`health never retries HTTP ${status}`, async () => {
    let calls = 0;
    await assert.rejects(callApi(async () => { calls++; throw { statusCode: status, message: credentials.apiKey }; }, {}, 'dispatchHealth', undefined, 3), e => e.code === `HTTP_${status}` && !JSON.stringify(e).includes(credentials.apiKey));
    assert.equal(calls, 1);
  });
}
test('long Retry-After stops instead of retrying earlier than requested', async () => {
  await assert.rejects(callApi(async () => ({ statusCode: 429, headers: { 'retry-after': '60' } }), {}, 'dispatchHealth', undefined, 3, async () => assert.fail('must not wait/retry')), { code: 'HTTP_429' });
});
test('triage does not retry after uncertain mutation result', async () => {
  let calls = 0;
  await assert.rejects(callApi(async () => { calls++; throw { statusCode: 503 }; }, {}, 'triageCheckin', 'CHK-TEST-001', 3), { code: 'HTTP_503' });
  assert.equal(calls, 1);
});
test('batch uses item-specific IDs and paired items, never copies input', async () => {
  const requests = [];
  const ctx = context(async o => { requests.push(o); return ok({ event_id: o.body.event_id, status: 'TRIAGED', idempotent: true }); }, { operation: 'triageCheckin', eventId: i => `CHK-TEST-00${i}` }, 2);
  const [out] = await new Hah().execute.call(ctx);
  assert.deepEqual(requests.map(o => o.body), [{ event_id: 'CHK-TEST-000' }, { event_id: 'CHK-TEST-001' }]);
  assert.deepEqual(out.map(o => o.pairedItem), [{ item: 0 }, { item: 1 }]);
  assert.ok(!JSON.stringify(out).includes('private_content'));
});
test('continueOnFail returns safe errors and continues with next input', async () => {
  let calls = 0;
  const ctx = context(async () => { if (++calls === 1) throw new Error(credentials.apiKey); return ok(); }, {}, 2, true);
  const [out] = await new Hah().execute.call(ctx);
  assert.equal(out[0].json.code, 'TRANSPORT_ERROR'); assert.equal(out[1].json.healthy, true);
  assert.ok(!JSON.stringify(out).includes(credentials.apiKey));
});
test('stop on fail throws sanitized NodeOperationError with item index', async () => {
  const ctx = context(async () => { throw { statusCode: 401, request: { headers: { secret: credentials.apiKey } } }; });
  await assert.rejects(new Hah().execute.call(ctx), e => e.name === 'NodeOperationError' && e.context.itemIndex === 0 && !JSON.stringify(e).includes(credentials.apiKey));
});
test('credential test validates URL before request and disables redirects', async () => {
  const testCredential = new Hah().methods.credentialTest.hahCredentialTest;
  let calls = 0;
  const ctx = { helpers: { request: async o => { calls++; assert.equal(o.followRedirect, false); assert.equal(o.followAllRedirects, false); assert.equal(o.headers['X-Internal-Key'], credentials.apiKey); return ok(); } } };
  assert.equal((await testCredential.call(ctx, { data: credentials })).status, 'OK');
  assert.equal((await testCredential.call(ctx, { data: { ...credentials, baseUrl: 'http://external.invalid' } })).status, 'Error');
  assert.equal(calls, 1);
});
test('empty input makes no API requests', async () => {
  assert.deepEqual(await new Hah().execute.call(context(async () => assert.fail('unexpected request'), {}, 0)), [[]]);
});
test('examples are inactive, credential-free graphs using declared node type', () => {
  const fs = require('node:fs'); const path = require('node:path');
  for (const filename of ['dispatch-health.json', 'triage-checkin.json']) {
    const w = JSON.parse(fs.readFileSync(path.join(__dirname, '../examples', filename), 'utf8'));
    assert.equal(w.active, false);
    const names = new Set(w.nodes.map(n => n.name));
    for (const n of w.nodes) {
      assert.equal(n.credentials, undefined);
      assert.equal(n.retryOnFail, undefined);
    }
    for (const [name, connection] of Object.entries(w.connections)) {
      assert.ok(names.has(name));
      for (const links of connection.main) for (const link of links) assert.ok(names.has(link.node));
    }
    assert.ok(w.nodes.some(n => n.type === 'n8n-nodes-hah.hah'));
    assert.equal(w.settings.saveDataSuccessExecution, 'none');
  }
});
