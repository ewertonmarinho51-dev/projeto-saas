import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {CASES, QA_PIN, BrowserQaFailure, failureRecord, pageModule, parseArgs,
  serveAssets, staticResponse, verifyPlaywright} from './wordcraft_browser_qa.mjs';

const sha = 'a'.repeat(64), commit = 'b'.repeat(40);
const absolute = name => resolve(tmpdir(), name);

test('argument contract is closed and absolute', () => {
  const args = ['bundle','manifest-sha256','checkpoints','inputs','playwright','python','out','producer-commit']
    .flatMap(key => ['--' + key, key === 'manifest-sha256' ? sha : key === 'producer-commit' ? commit : absolute(key)]);
  const parsed = parseArgs(args);
  assert.equal(parsed['manifest-sha256'], sha);
  assert.throws(() => parseArgs([...args, '--extra', 'x']), BrowserQaFailure);
  assert.throws(() => parseArgs(args.map(value => value === absolute('out') ? 'relative' : value)), BrowserQaFailure);
});

test('failure evidence never upgrades browser or backend claims', () => {
  assert.deepEqual(failureRecord('keyboard_input'), {
    status: 'FAIL_HEADLESS_BROWSER_QA', failed_stage: 'keyboard_input',
    manual_browser_observation: false, gotrue_or_database_proof: false,
  });
  assert.equal(failureRecord('invented').failed_stage, 'configuration');
});

test('static route map rejects traversal, queries and writes', () => {
  const assets = new Map([['/', {bytes: Buffer.from('ok'), mime: 'text/plain'}]]);
  assert.equal(staticResponse(assets, 'GET', '/').bytes.toString(), 'ok');
  for (const [method, url] of [['POST','/'], ['GET','/?x=1'], ['GET','/../secret'], ['GET','/%2e%2e/secret']])
    assert.equal(staticResponse(assets, method, url), null);
});

test('page module accepts only confined WordCraft asset URLs', () => {
  const code = pageModule('/app/static/wordcraft/engine.js', '/app/static/wordcraft/engine.wasm');
  assert.ok(code.length > 1000);
  assert.throws(() => pageModule('/outside.js', '/app/static/wordcraft/engine.wasm'), BrowserQaFailure);
  assert.throws(() => pageModule('/app/static/wordcraft/../engine.js', '/app/static/wordcraft/engine.wasm'), BrowserQaFailure);
});

test('Playwright package and browser catalog are pinned', async t => {
  const root = await mkdtemp(join(tmpdir(), 'wordcraft-pw-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  await writeFile(join(root, 'package.json'), JSON.stringify({name:'playwright-core', version:QA_PIN.playwright}));
  await writeFile(join(root, 'browsers.json'), JSON.stringify({browsers:[
    {name:'chromium', revision:QA_PIN.chromiumRevision, browserVersion:QA_PIN.chromiumVersion},
    {name:'chromium-headless-shell', revision:QA_PIN.chromiumRevision, browserVersion:QA_PIN.chromiumVersion},
  ]}));
  await writeFile(join(root, 'index.mjs'), 'export const chromium = {};');
  const admitted = await verifyPlaywright(root);
  assert.ok(admitted.entry.endsWith('index.mjs'));
  await writeFile(join(root, 'package.json'), JSON.stringify({name:'playwright-core', version:'0.0.0'}));
  await assert.rejects(verifyPlaywright(root), BrowserQaFailure);
});

test('loopback server serves only the explicit in-memory map', async t => {
  const assets = new Map([['/', {bytes:Buffer.from('synthetic'), mime:'text/plain'}]]);
  const server = await serveAssets(assets);
  t.after(() => server.close());
  const allowed = await fetch(server.origin + '/');
  assert.equal(allowed.status, 200);
  assert.equal(await allowed.text(), 'synthetic');
  assert.equal((await fetch(server.origin + '/private.json')).status, 404);
});

test('reviewed corpus inventory remains exactly three fixtures', () => {
  assert.deepEqual(CASES, ['01-texto-listas-links', '02-tabela-210-itens', '03-timbrado-assinaturas']);
});
