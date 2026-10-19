import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {CASES, QA_PIN, BrowserQaFailure, admitGovbotProposal, browserEnvironment, browserExecutablePath, failureRecord, pageModule, parseArgs,
  chromiumProcessMemory, rendererMetrics, serveAssets, staticResponse, summarizePerformance,
  verifyPlaywright} from './wordcraft_browser_qa.mjs';

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

test('renderer metrics preserve their bounded CDP meaning', async () => {
  const calls = [];
  const session = {send: async method => {
    calls.push(method);
    if (method === 'Performance.enable') return {};
    if (method === 'Performance.getMetrics') return {metrics: [
      {name:'JSHeapUsedSize', value:12_000}, {name:'JSHeapTotalSize', value:20_000},
    ]};
    if (method === 'Memory.getDOMCounters') return {documents:2, nodes:300, jsEventListeners:14};
    if (method === 'Runtime.evaluate') return {result:{type:'number', value:65_536}};
    throw new Error('unexpected method');
  }};
  assert.deepEqual(await rendererMetrics(session), {js_heap_used_bytes:12_000,
    js_heap_total_bytes:20_000, documents:2, nodes:300, listeners:14, wasm_linear_memory_bytes:65_536});
  assert.deepEqual(calls, ['Performance.enable', 'Performance.getMetrics', 'Memory.getDOMCounters', 'Runtime.evaluate']);
  session.send = async method => method === 'Performance.enable' ? {}
    : method === 'Performance.getMetrics' ? {metrics:[
      {name:'JSHeapUsedSize', value:30}, {name:'JSHeapTotalSize', value:20},
    ]} : method === 'Memory.getDOMCounters' ? {documents:1, nodes:1, jsEventListeners:1}
    : {result:{type:'number', value:65_536}};
  await assert.rejects(rendererMetrics(session), error =>
    error instanceof BrowserQaFailure && error.stage === 'performance_metrics');
  session.send = async method => method === 'Performance.enable' ? {}
    : method === 'Performance.getMetrics' ? {metrics:[
      {name:'JSHeapUsedSize', value:10}, {name:'JSHeapTotalSize', value:20},
    ]} : method === 'Memory.getDOMCounters' ? {documents:1, nodes:1, jsEventListeners:1}
    : {result:{type:'undefined'}};
  await assert.rejects(rendererMetrics(session), error =>
    error instanceof BrowserQaFailure && error.stage === 'performance_metrics');
});

test('performance summary uses nearest-rank percentiles and labels mixed fixtures', () => {
  const sample = (ready, open, heap, nodes) => ({performance: {canvas_ready_ms: ready,
    document_open_ms: open, after_open: {js_heap_used_bytes:heap, nodes, wasm_linear_memory_bytes:65_536},
    after_interactions: {js_heap_used_bytes:heap + 1, nodes:nodes + 1, wasm_linear_memory_bytes:131_072}}});
  assert.deepEqual(summarizePerformance([
    sample(10, 4, 100, 5), sample(30, 2, 300, 7), sample(20, 3, 200, 6),
  ]), {mixed_synthetic_documents:true,
    canvas_ready:{samples:3, p50_ms:20, p95_ms:30},
    document_open:{samples:3, p50_ms:3, p95_ms:4},
    max_renderer_js_heap_used_bytes:301, max_renderer_dom_nodes:8, max_wasm_linear_memory_bytes:131_072});
  assert.throws(() => summarizePerformance([]), BrowserQaFailure);
});

test('Chromium process memory sums the complete CDP process set on Windows', async () => {
  const session = {send: async method => {
    assert.equal(method, 'SystemInfo.getProcessInfo');
    return {processInfo: [{id: 11, type: 'browser'}, {id: 12, type: 'renderer'},
      {id: 13, type: 'renderer'}]};
  }};
  const execute = async (command, args, options) => {
    assert.equal(command, 'powershell.exe');
    assert.match(args.at(-1), /^\$ids=@\(11,12,13\);/);
    assert.equal(options.windowsHide, true);
    return {stdout: JSON.stringify([{Id:11, WorkingSet64:1000}, {Id:12, WorkingSet64:2000},
      {Id:13, WorkingSet64:3000}])};
  };
  assert.deepEqual(await chromiumProcessMemory(session, 'win32', execute), {
    metric:'WORKING_SET_SUM', process_count:3, total_bytes:6000,
    by_type:{browser:{processes:1, working_set_bytes:1000},
      renderer:{processes:2, working_set_bytes:5000}},
  });
});

test('Chromium process memory reads Linux RSS and fails closed on incomplete samples', async () => {
  const session = {send: async () => ({processInfo:[{id:21, type:'browser'}, {id:22, type:'gpu-process'}]})};
  const read = async path => path.includes('/21/') ? 'Name:\tchrome\nVmRSS:\t10 kB\n'
    : 'Name:\tchrome\nVmRSS:\t20 kB\n';
  assert.deepEqual(await chromiumProcessMemory(session, 'linux', undefined, read), {
    metric:'RSS_SUM', process_count:2, total_bytes:30 * 1024,
    by_type:{browser:{processes:1, working_set_bytes:10 * 1024},
      'gpu-process':{processes:1, working_set_bytes:20 * 1024}},
  });
  await assert.rejects(chromiumProcessMemory(session, 'linux', undefined, async () => 'Name:\tchrome\n'),
    error => error instanceof BrowserQaFailure && error.stage === 'performance_metrics');
});

test('runtime platform allowlist is explicit and bounded', () => {
  assert.deepEqual(QA_PIN.supportedPlatforms, ['linux', 'win32']);
  assert.equal(QA_PIN.supportedPlatforms.includes('darwin'), false);
});

test('browser environment admits Windows runtime keys without hosted secrets', () => {
  const environment = browserEnvironment({PATH:'bin', SystemRoot:'C:/Windows', WINDIR:'C:/Windows',
    TEMP:'tmp', PLAYWRIGHT_BROWSERS_PATH:'browsers', SUPABASE_URL:'https://outside.invalid',
    OPENAI_API_KEY:'must-not-pass', HTTPS_PROXY:'https://outside.invalid'});
  assert.deepEqual(environment, {PATH:'bin', TEMP:'tmp', SystemRoot:'C:/Windows',
    WINDIR:'C:/Windows', PLAYWRIGHT_BROWSERS_PATH:'browsers'});
});

test('headless executable is pinned inside the explicit browser store', () => {
  const root = resolve(tmpdir(), 'browser-store');
  assert.equal(browserExecutablePath({PLAYWRIGHT_BROWSERS_PATH:root}, 'win32'),
    resolve(root, 'chromium_headless_shell-1194', 'chrome-win', 'headless_shell.exe'));
  assert.equal(browserExecutablePath({PLAYWRIGHT_BROWSERS_PATH:root}, 'linux'),
    resolve(root, 'chromium_headless_shell-1194', 'chrome-linux', 'headless_shell'));
  assert.throws(() => browserExecutablePath({}, 'win32'), BrowserQaFailure);
  assert.throws(() => browserExecutablePath({PLAYWRIGHT_BROWSERS_PATH:root}, 'darwin'), BrowserQaFailure);
});

test('GovBot proposal admission is closed to one contextual replacement', () => {
  const operation = {findingId:'QA-GOVBOT-1', documentId:'tr', op:'replace',
    path:'tr/clausula/4/11111111-1111-1111-1111-111111111111', expectedOldHash:'a'.repeat(64),
    newValue:'Ensaio plenamente sintético', sourceIds:[], reason:'clareza'};
  assert.equal(admitGovbotProposal({operations:[operation], unresolvedFindings:[]}), operation);
  assert.throws(() => admitGovbotProposal({operations:[{...operation, sourceIds:['invented']}], unresolvedFindings:[]}), BrowserQaFailure);
  assert.throws(() => admitGovbotProposal({operations:[operation], unresolvedFindings:[], extra:true}), BrowserQaFailure);
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
  assert.match(code.toString(), /async probe\(\)/);
  assert.match(code.toString(), /const patchAck = await checkpointAck\(\)/);
  assert.match(code.toString(), /native\.undo\(\)/);
  assert.match(code.toString(), /undo_after_patch_ack: true/);
  assert.match(code.toString(), /async applyPersistedPatch\(operationId, expectedRevision, targetHash, plan\)/);
  assert.match(code.toString(), /async acceptPersistedPatch\(ack\)/);
  assert.match(code.toString(), /async freezeForApproval\(\)/);
  assert.match(code.toString(), /async verifyApprovedFrozen\(expected\)/);
  assert.match(code.toString(), /async acceptPersistedPatchAndUndo\(ack\)/);
  assert.match(code.toString(), /async acceptPersistedUndo\(ack\)/);
  assert.throws(() => pageModule('/outside.js', '/app/static/wordcraft/engine.wasm'), BrowserQaFailure);
  assert.throws(() => pageModule('/app/static/wordcraft/../engine.js', '/app/static/wordcraft/engine.wasm'), BrowserQaFailure);
});

test('backend proof bridge exposes a read-only correlated canvas probe', async () => {
  const source = await readFile(new URL('./wordcraft_browser_backend_bridge.mjs', import.meta.url), 'utf8');
  assert.match(source, /command\.action === 'probe'/);
  assert.match(source, /window\.qa\.probe\(\)/);
});

test('backend proof bridge exposes persisted patch acknowledgement without undo', async () => {
  const source = await readFile(new URL('./wordcraft_browser_backend_bridge.mjs', import.meta.url), 'utf8');
  assert.match(source, /command\.action === 'ack'/);
  assert.match(source, /window\.qa\.acceptPersistedPatch\(input\.ack\)/);
});

test('backend proof bridge exposes the real approval freeze without a release action', async () => {
  const source = await readFile(new URL('./wordcraft_browser_backend_bridge.mjs', import.meta.url), 'utf8');
  assert.match(source, /command\.action === 'freeze_approval'/);
  assert.match(source, /window\.qa\.freezeForApproval\(\)/);
  assert.match(source, /command\.action === 'verify_approved_frozen'/);
  assert.match(source, /window\.qa\.verifyApprovedFrozen\(input\.expected\)/);
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

test('browser scale admission measures exact 20 and 100 page profiles', async () => {
  const source = await readFile(new URL('./wordcraft_browser_qa.mjs', import.meta.url), 'utf8');
  assert.match(source, /for pages in \(20,100\):/);
  assert.match(source, /admission\.scale_profiles\.map\(item => item\.pages\)/);
  assert.match(source, /evidence\.scale_profiles = \[\]/);
  assert.match(source, /for \(const scale of scales\)/);
  assert.doesNotMatch(source, /evidence\.scale_profile =/);
});
