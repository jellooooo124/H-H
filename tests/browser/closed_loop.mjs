/**
 * Real browser acceptance test against Vue + FastAPI + PostgreSQL.
 * Synthetic-only, tokens generated per CI run, no screenshots with PHI.
 */
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync } from 'node:fs';
import { chromium } from 'playwright';

const tokens = JSON.parse(readFileSync(process.env.HAH_BROWSER_TOKENS_PATH, 'utf8'));
const baseURL = process.env.HAH_FRONTEND_URL || 'http://127.0.0.1:8080';
let browser, clinician, patient;

try {
  browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ baseURL, viewport: { width: 1365, height: 940 } });
  clinician = await ctx.newPage();
  patient = await ctx.newPage();

  await patient.goto('/patient.html', { waitUntil: 'networkidle' });
  await patient.locator('input[type=password]').fill(tokens.patient);
  await patient.getByRole('button', { name: '讀取我的合成資料' }).click();
  await patient.getByText('我的監測摘要 · DEMO-P001').waitFor({ state: 'visible', timeout: 15000 });
  await patient.getByText('目前沒有已發佈的示範訊息。').waitFor({ state: 'visible' });

  await clinician.goto('/', { waitUntil: 'networkidle' });
  await clinician.locator('input[type=password]').fill(tokens.clinician);
  await clinician.getByRole('button', { name: '重新載入任務及案件' }).click();
  await clinician.getByRole('button', { name: '站內訊息閉環' }).click();
  await clinician.getByRole('button', { name: '建立草稿' }).click();
  await clinician.getByText('已建立草稿；需另外由醫護發佈').waitFor({ state: 'visible', timeout: 15000 });

  // Patient must not receive an unapproved draft.
  await patient.getByRole('button', { name: '讀取我的合成資料' }).click();
  await patient.getByText('目前沒有已發佈的示範訊息。').waitFor({ state: 'visible' });

  await clinician.getByRole('button', { name: '核對後發佈站內訊息' }).click();
  await clinician.getByText('已發佈至合成患者站內收件匣（無外部訊息）').waitFor({ state: 'visible', timeout: 15000 });

  await patient.getByRole('button', { name: '讀取我的合成資料' }).click();
  await patient.getByRole('button', { name: '確認已閱讀' }).waitFor({ state: 'visible', timeout: 15000 });
  await patient.getByRole('button', { name: '確認已閱讀' }).click();
  await patient.locator('.task').filter({ hasText: 'ACKNOWLEDGED' }).first().waitFor({ state: 'visible', timeout: 15000 });
  assert.equal(await patient.getByRole('button', { name: '確認已閱讀' }).count(), 0);

  await clinician.getByRole('button', { name: '重新載入', exact: true }).click();
  await clinician.locator('article .task').filter({ hasText: 'ACKNOWLEDGED' }).first().waitFor({ state: 'visible', timeout: 15000 });

  // Roles remain isolated across the HTTP boundary.
  const forbiddenClinician = await patient.request.get(baseURL + '/v5/clinician/communications/DEMO-P001', {
    headers: { Authorization: 'Bearer ' + tokens.patient }
  });
  assert.equal(forbiddenClinician.status(), 403);
  const forbiddenPatient = await clinician.request.get(baseURL + '/v5/patient/communications', {
    headers: { Authorization: 'Bearer ' + tokens.clinician }
  });
  assert.equal(forbiddenPatient.status(), 403);
  console.log('PASS: real browser clinician draft -> publish -> patient acknowledge -> clinician sees receipt; role separation');
  await ctx.close();
} catch (e) {
  mkdirSync('tests/browser/artifacts', { recursive: true });
  if (clinician) await clinician.screenshot({ path: 'tests/browser/artifacts/clinician.png', fullPage: true }).catch(() => {});
  if (patient) await patient.screenshot({ path: 'tests/browser/artifacts/patient.png', fullPage: true }).catch(() => {});
  console.error('Synthetic browser acceptance test failed: ' + e.message);
  process.exitCode = 1;
} finally {
  await browser?.close();
}
