// Repository QA only: real Chromium/canvas, synthetic inputs, simulated transport ACK.
import {readFile, realpath, stat, mkdir, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {execFile, spawn} from 'node:child_process';
import {promisify} from 'node:util';
import {brotliCompressSync, gzipSync, constants as zlibConstants} from 'node:zlib';
import {dirname, isAbsolute, join, relative, resolve, sep} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {verifyBundle} from '../assets/wordcraft_editor/validate.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const runFile = promisify(execFile);
export const QA_PIN = Object.freeze({playwright: '1.56.1', chromiumRevision: '1194', chromiumVersion: '141.0.7390.37',
  packageSha512: 'hutraynyn31F+Bifme+Ps9Vq59hKuUCz7H1kDOcBs+2oGguKkWTU50bBWrtz34OUWmIwpBTWDxaRPXrIXkgvmQ==',
  supportedPlatforms: Object.freeze(['linux', 'win32'])});
export const CASES = Object.freeze(['01-texto-listas-links', '02-tabela-210-itens', '03-timbrado-assinaturas']);
const MAX_INPUT = 8 * 1024 * 1024;
const MAX_SCREENSHOT = 8 * 1024 * 1024;
const STAGES = new Set(['configuration', 'bundle_admission', 'synthetic_admission', 'playwright_pin', 'http_confinement',
  'chromium_start', 'canvas_open', 'api_edit', 'queued_input', 'keyboard_input', 'freeze_release',
  'native_patch_undo', 'native_export', 'govbot_capture', 'govbot_backend', 'govbot_apply', 'multi_canvas',
  'mobile_emulation', 'screenshot', 'performance_metrics', 'runtime_errors', 'cleanup', 'global_timeout']);
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const check = (condition, stage) => { if (condition !== true) throw new BrowserQaFailure(stage); };
const elapsedMs = started => Number(process.hrtime.bigint() - started) / 1_000_000;

export function compressionInventory(items) {
  check(Array.isArray(items) && items.length > 0, 'bundle_admission');
  const seen = new Set(), files = [];
  for (const item of items) {
    check(item && typeof item.path === 'string' && item.path.length > 0 && !seen.has(item.path)
      && Buffer.isBuffer(item.bytes) && item.bytes.length > 0, 'bundle_admission');
    seen.add(item.path);
    const gzip = gzipSync(item.bytes, {level: 9});
    const brotli = brotliCompressSync(item.bytes, {params: {
      [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
      [zlibConstants.BROTLI_PARAM_MODE]: item.path.endsWith('.wasm')
        ? zlibConstants.BROTLI_MODE_GENERIC : zlibConstants.BROTLI_MODE_TEXT,
    }});
    files.push({path: item.path, raw_bytes: item.bytes.length, gzip_level_9_bytes: gzip.length,
      brotli_quality_11_bytes: brotli.length});
  }
  const sum = key => files.reduce((total, item) => total + item[key], 0);
  return {scope: 'ENGINE_MANIFEST_FILES_ONLY_EXCLUDES_QA_HOST', files,
    totals: {file_count: files.length, raw_bytes: sum('raw_bytes'), gzip_level_9_bytes: sum('gzip_level_9_bytes'),
      brotli_quality_11_bytes: sum('brotli_quality_11_bytes')}};
}

export class BrowserQaFailure extends Error {
  constructor(stage) { super('Browser QA refused.'); this.stage = STAGES.has(stage) ? stage : 'configuration'; }
}

export function failureRecord(stage) {
  return {status: 'FAIL_HEADLESS_BROWSER_QA', failed_stage: STAGES.has(stage) ? stage : 'configuration',
    manual_browser_observation: false, gotrue_or_database_proof: false};
}

export async function rendererMetrics(session) {
  await session.send('Performance.enable');
  const [{metrics}, dom, wasm] = await Promise.all([
    session.send('Performance.getMetrics'), session.send('Memory.getDOMCounters'),
    session.send('Runtime.evaluate', {expression: 'window.qa?.wasmLinearMemoryBytes?.()', returnByValue: true}),
  ]);
  const values = Object.fromEntries(metrics.map(item => [item.name, item.value]));
  const result = {
    js_heap_used_bytes: values.JSHeapUsedSize,
    js_heap_total_bytes: values.JSHeapTotalSize,
    documents: dom.documents,
    nodes: dom.nodes,
    listeners: dom.jsEventListeners,
    wasm_linear_memory_bytes: wasm?.result?.value,
  };
  check(Object.values(result).every(value => Number.isFinite(value) && value >= 0)
    && result.js_heap_total_bytes >= result.js_heap_used_bytes
    && Number.isSafeInteger(result.wasm_linear_memory_bytes)
    && result.wasm_linear_memory_bytes > 0
    && result.wasm_linear_memory_bytes % 65_536 === 0, 'performance_metrics');
  return result;
}

export function summarizePerformance(cases) {
  check(Array.isArray(cases) && cases.length > 0, 'performance_metrics');
  const distribution = key => {
    const values = cases.map(item => item.performance?.[key]);
    check(values.every(value => Number.isFinite(value) && value >= 0), 'performance_metrics');
    values.sort((left, right) => left - right);
    const rank = percentile => values[Math.max(0, Math.ceil(percentile * values.length) - 1)];
    return {samples: values.length, p50_ms: rank(.50), p95_ms: rank(.95)};
  };
  const readings = cases.flatMap(item => [item.performance?.after_open,
    item.performance?.after_interactions]);
  check(readings.every(item => item && Number.isFinite(item.js_heap_used_bytes)
    && Number.isFinite(item.nodes) && Number.isFinite(item.wasm_linear_memory_bytes)
    && item.wasm_linear_memory_bytes > 0), 'performance_metrics');
  return {mixed_synthetic_documents: true,
    canvas_ready: distribution('canvas_ready_ms'), document_open: distribution('document_open_ms'),
    max_renderer_js_heap_used_bytes: Math.max(...readings.map(item => item.js_heap_used_bytes)),
    max_renderer_dom_nodes: Math.max(...readings.map(item => item.nodes)),
    max_wasm_linear_memory_bytes: Math.max(...readings.map(item => item.wasm_linear_memory_bytes))};
}

export async function chromiumProcessMemory(session, platform = process.platform,
  execute = runFile, read = readFile) {
  const {processInfo} = await session.send('SystemInfo.getProcessInfo');
  check(Array.isArray(processInfo) && processInfo.length > 0, 'performance_metrics');
  const processes = processInfo.map(item => ({pid: item.id, type: item.type}));
  check(processes.every(item => Number.isSafeInteger(item.pid) && item.pid > 0
    && typeof item.type === 'string' && item.type.length > 0)
    && new Set(processes.map(item => item.pid)).size === processes.length, 'performance_metrics');
  let workingSets;
  if (platform === 'win32') {
    const script = `$ids=@(${processes.map(item => item.pid).join(',')});`
      + 'Get-Process -Id $ids -ErrorAction Stop|Select-Object Id,WorkingSet64|ConvertTo-Json -Compress';
    const {stdout} = await execute('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive',
      '-Command', script],
    {timeout: 15_000, maxBuffer: 256 * 1024, windowsHide: true});
    const parsed = JSON.parse(stdout);
    workingSets = (Array.isArray(parsed) ? parsed : [parsed]).map(item =>
      ({pid: item.Id, bytes: item.WorkingSet64}));
  } else if (platform === 'linux') {
    workingSets = await Promise.all(processes.map(async item => {
      const status = await read(`/proc/${item.pid}/status`, 'utf8');
      const match = /^VmRSS:\s+(\d+)\s+kB$/m.exec(status);
      check(Boolean(match), 'performance_metrics');
      return {pid: item.pid, bytes: Number(match[1]) * 1024};
    }));
  } else {
    throw new BrowserQaFailure('performance_metrics');
  }
  const byPid = new Map(workingSets.map(item => [item.pid, item.bytes]));
  check(workingSets.length === processes.length && byPid.size === processes.length
    && processes.every(item => Number.isSafeInteger(byPid.get(item.pid)) && byPid.get(item.pid) > 0),
  'performance_metrics');
  const byType = {};
  for (const item of processes) {
    const current = byType[item.type] ?? {processes: 0, working_set_bytes: 0};
    current.processes += 1; current.working_set_bytes += byPid.get(item.pid); byType[item.type] = current;
  }
  const total = [...byPid.values()].reduce((sum, value) => sum + value, 0);
  check(Number.isSafeInteger(total) && total > 0, 'performance_metrics');
  return {metric: platform === 'win32' ? 'WORKING_SET_SUM' : 'RSS_SUM',
    process_count: processes.length, total_bytes: total, by_type: byType};
}

export function browserEnvironment(source = process.env) {
  return Object.fromEntries(['PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP',
    'SystemRoot', 'WINDIR', 'PLAYWRIGHT_BROWSERS_PATH']
    .filter(key => source[key]).map(key => [key, source[key]]));
}

export function browserExecutablePath(source = process.env, platform = process.platform) {
  const root = source.PLAYWRIGHT_BROWSERS_PATH;
  check(typeof root === 'string' && isAbsolute(root), 'playwright_pin');
  const leaf = platform === 'win32' ? ['chrome-win', 'headless_shell.exe']
    : platform === 'linux' ? ['chrome-linux', 'headless_shell'] : null;
  check(Boolean(leaf), 'playwright_pin');
  return join(root, `chromium_headless_shell-${QA_PIN.chromiumRevision}`, ...leaf);
}

export function parseArgs(args) {
  const keys = new Set(['bundle', 'manifest-sha256', 'checkpoints', 'inputs', 'playwright', 'python', 'out', 'producer-commit']);
  const result = {};
  check(args.length === keys.size * 2, 'configuration');
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index].slice(2), value = args[index + 1];
    check(args[index].startsWith('--') && keys.has(key) && !Object.hasOwn(result, key)
      && typeof value === 'string' && value.length > 0 && value.length <= 4096, 'configuration');
    result[key] = value;
  }
  check(/^[0-9a-f]{64}$/.test(result['manifest-sha256']) && /^[0-9a-f]{40}$/.test(result['producer-commit']), 'configuration');
  for (const key of ['bundle', 'checkpoints', 'inputs', 'playwright', 'python', 'out']) check(isAbsolute(result[key]), 'configuration');
  return result;
}

async function boundedFile(path, maximum, stage) {
  const info = await stat(path);
  check(info.isFile() && info.size > 0 && info.size <= maximum, stage);
  const content = await readFile(path);
  check(content.length === info.size && content.length <= maximum, stage);
  return content;
}

export async function verifyPlaywright(root) {
  root = await realpath(root);
  const pkg = JSON.parse(await boundedFile(resolve(root, 'package.json'), 32 * 1024, 'playwright_pin'));
  const catalogRaw = await boundedFile(resolve(root, 'browsers.json'), 32 * 1024, 'playwright_pin');
  const catalog = JSON.parse(catalogRaw);
  check(pkg.name === 'playwright-core' && pkg.version === QA_PIN.playwright && Array.isArray(catalog.browsers), 'playwright_pin');
  for (const name of ['chromium', 'chromium-headless-shell']) {
    const matches = catalog.browsers.filter(item => item.name === name);
    check(matches.length === 1 && matches[0].revision === QA_PIN.chromiumRevision
      && matches[0].browserVersion === QA_PIN.chromiumVersion, 'playwright_pin');
  }
  const entry = await realpath(resolve(root, 'index.mjs'));
  const confined = relative(root, entry);
  check(Boolean(confined) && !isAbsolute(confined) && confined !== '..' && !confined.startsWith('..' + sep), 'playwright_pin');
  return {entry, catalog_sha256: hash(catalogRaw)};
}

const INPUT_ADMISSION = String.raw`
import base64,hashlib,json,os,sys
from pathlib import Path
root,bundle,inputs,checkpoints=map(Path,sys.argv[1:5])
sys.path.insert(0,str(root))
from scripts import wordcraft_corpus as corpus
from scripts.wordcraft_benchmark import _pdf_pages,_synthetic_paged_docx
from src.wordcraft_native import importar_docx,validar,exportar
pin=sys.argv[5]
manifest=corpus.verify_inputs(inputs)
names=sorted(Path(item['path']).stem for item in manifest['files'])
if sorted(path.name for path in checkpoints.iterdir() if path.is_dir())!=names:
    raise ValueError('Synthetic inventory differs')
config={'node':Path(sys.argv[6]),'bundle':bundle,'manifest_sha256':pin}
cases=[]
for item in manifest['files']:
    name=Path(item['path']).stem
    path=(checkpoints/name/'checkpoint.json').resolve()
    if not path.is_relative_to(checkpoints.resolve()) or not 0<path.stat().st_size<=8*1024*1024:
        raise ValueError('Synthetic checkpoint boundary differs')
    content=path.read_bytes()
    validar(content,**config)
    source=(inputs/item['path']).read_bytes()
    if corpus.text_blocks(exportar(content,formato='docx',**config))!=corpus.text_blocks(source):
        raise ValueError('Native checkpoint differs from reviewed synthetic fixture')
    cases.append({'case':name,'checkpoint_sha256':hashlib.sha256(content).hexdigest(),
      'checkpoint_bytes':len(content),'fixture_sha256':hashlib.sha256(source).hexdigest()})
scales=[]
for pages in (20,100):
    scale_source=_synthetic_paged_docx(pages)
    scale=importar_docx(scale_source,**config)
    validar(scale,**config)
    scale_pdf=exportar(scale,formato='pdf',**config)
    if not 0<len(scale)<=8*1024*1024:
        raise ValueError('Synthetic scale checkpoint boundary differs')
    if _pdf_pages(scale_pdf)!=pages:
        raise ValueError('Synthetic scale PDF page count differs')
    scales.append({'profile':f'synthetic-explicit-breaks-{pages}-pages','pages':pages,
      'checkpoint_sha256':hashlib.sha256(scale).hexdigest(),'checkpoint_bytes':len(scale),
      'source_sha256':hashlib.sha256(scale_source).hexdigest(),
      'pdf_sha256':hashlib.sha256(scale_pdf).hexdigest(),'pdf_bytes':len(scale_pdf),
      'content_base64':base64.b64encode(scale).decode()})
print(json.dumps({'schema':'gc-wordcraft-browser-inputs/v1','synthetic_only':True,'cases':cases,
  'scale_profiles':scales}))
`;

const GOVBOT_SELECTION = String.raw`
import hashlib,json,sys
from src.wordcraft_capacidades import propositor_govbot_selecao
value=json.loads(sys.stdin.buffer.read(128*1024))
if set(value)!={'selected'} or not isinstance(value['selected'],str) or not value['selected'].strip():
    raise ValueError('invalid selection')
selected=value['selected']
path='tr/clausula/4/11111111-1111-1111-1111-111111111111'
report={'findings':[{'findingId':'QA-GOVBOT-1','documentId':'tr','autoCorrectable':True,
  'allowedPaths':[path],'blockedPaths':[],'sourceIds':[]}]}
snapshot={'documentos':{'tr':{'blocos':[{'path':path,
  'hash':hashlib.sha256(selected.encode()).hexdigest(),'conteudo':selected}]}}}
new=selected.replace('Corpus','Ensaio',1)
if new==selected:
    raise ValueError('selection target differs')
def model(system,user,**kwargs):
    del system,user,kwargs
    return json.dumps({'intent':'suggest_section_patch','response':'Sugestão sintética','target':path,
      'payload':{'new_value':new,'reason':'clareza sintética'},'sources':[]},ensure_ascii=False)
proposal=propositor_govbot_selecao(doc_key='tr',texto_selecionado=selected,
  pedido='Melhore a clareza sem alterar dados materiais',chamar=model)(
  relatorio=report,snapshot=snapshot,contexto={'processo':{'id':'qa','dados':{}},'fatos':[]})
sys.stdout.write(json.dumps(proposal,ensure_ascii=False,separators=(',',':')))
`;

export function admitGovbotProposal(value) {
  check(value && !Array.isArray(value) && Object.keys(value).sort().join(',') === 'operations,unresolvedFindings'
    && Array.isArray(value.operations) && value.operations.length === 1
    && Array.isArray(value.unresolvedFindings) && value.unresolvedFindings.length === 0, 'govbot_backend');
  const operation = value.operations[0];
  check(operation && !Array.isArray(operation)
    && Object.keys(operation).sort().join(',') === 'documentId,expectedOldHash,findingId,newValue,op,path,reason,sourceIds'
    && operation.documentId === 'tr' && operation.findingId === 'QA-GOVBOT-1' && operation.op === 'replace'
    && typeof operation.path === 'string' && operation.path.startsWith('tr/clausula/4/')
    && /^[0-9a-f]{64}$/.test(operation.expectedOldHash) && typeof operation.newValue === 'string'
    && operation.newValue.length > 0 && Buffer.byteLength(operation.newValue) <= 64 * 1024
    && typeof operation.reason === 'string' && Array.isArray(operation.sourceIds) && operation.sourceIds.length === 0,
  'govbot_backend');
  return operation;
}

async function govbotProposal(config, selected) {
  check(typeof selected === 'string' && selected.length > 0 && Buffer.byteLength(selected) <= 64 * 1024,
    'govbot_backend');
  const environment = Object.fromEntries(['PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP', 'SystemRoot', 'WINDIR']
    .filter(key => process.env[key]).map(key => [key, process.env[key]]));
  environment.PYTHONUTF8 = '1';
  const child = spawn(config.python, ['-c', GOVBOT_SELECTION],
    {cwd: ROOT, env: environment, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
  const chunks = [], errors = []; let size = 0, errorSize = 0;
  child.stdout.on('data', chunk => { size += chunk.length; if (size <= 128 * 1024) chunks.push(chunk); });
  child.stderr.on('data', chunk => { errorSize += chunk.length; if (errorSize <= 4 * 1024) errors.push(chunk); });
  child.stdin.end(JSON.stringify({selected}));
  const exitCode = await new Promise((done, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new BrowserQaFailure('govbot_backend')); }, 30_000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('close', code => { clearTimeout(timer); done(code); });
  });
  if (exitCode !== 0) throw new Error(`GovBot backend exited ${exitCode}: ${Buffer.concat(errors).toString('utf8').slice(0, 1000)}`);
  check(exitCode === 0 && size > 0 && size <= 128 * 1024, 'govbot_backend');
  return admitGovbotProposal(JSON.parse(Buffer.concat(chunks).toString('utf8')));
}

async function admitInputs(config) {
  const environment = Object.fromEntries(['PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP', 'SystemRoot', 'WINDIR']
    .filter(key => process.env[key]).map(key => [key, process.env[key]]));
  environment.PYTHONUTF8 = '1';
  let result;
  try {
    result = await runFile(config.python, ['-c', INPUT_ADMISSION, ROOT, config.bundle, config.inputs,
      config.checkpoints, config['manifest-sha256'], process.execPath],
    {cwd: ROOT, env: environment, timeout: 180_000, maxBuffer: 12 * 1024 * 1024, windowsHide: true});
  } catch (error) {
    const stderr = String(error?.stderr ?? '').slice(-1500).replace(/[\r\n]+/g, ' ');
    throw new Error(`Synthetic input admission child failed: ${stderr || error?.code || 'unknown'}`);
  }
  const admission = JSON.parse(result.stdout);
  check(admission.schema === 'gc-wordcraft-browser-inputs/v1' && admission.synthetic_only === true
    && Array.isArray(admission.cases) && admission.cases.length === 3
    && JSON.stringify(admission.cases.map(item => item.case).sort()) === JSON.stringify(CASES), 'synthetic_admission');
  const cases = [];
  for (const item of admission.cases) {
    check(/^[0-9a-f]{64}$/.test(item.checkpoint_sha256) && /^[0-9a-f]{64}$/.test(item.fixture_sha256)
      && Number.isSafeInteger(item.checkpoint_bytes) && item.checkpoint_bytes > 0 && item.checkpoint_bytes <= MAX_INPUT, 'synthetic_admission');
    const bytes = await boundedFile(resolve(config.checkpoints, item.case, 'checkpoint.json'), MAX_INPUT, 'synthetic_admission');
    check(bytes.length === item.checkpoint_bytes && hash(bytes) === item.checkpoint_sha256, 'synthetic_admission');
    cases.push({...item, bytes});
  }
  check(Array.isArray(admission.scale_profiles) && admission.scale_profiles.length === 2
    && JSON.stringify(admission.scale_profiles.map(item => item.pages)) === JSON.stringify([20, 100]),
  'synthetic_admission');
  const scales = admission.scale_profiles.map(scale => {
    check(scale.profile === `synthetic-explicit-breaks-${scale.pages}-pages`
      && /^[0-9a-f]{64}$/.test(scale.checkpoint_sha256) && /^[0-9a-f]{64}$/.test(scale.source_sha256)
      && /^[0-9a-f]{64}$/.test(scale.pdf_sha256) && Number.isSafeInteger(scale.pdf_bytes) && scale.pdf_bytes > 0
      && Number.isSafeInteger(scale.checkpoint_bytes) && scale.checkpoint_bytes > 0
      && scale.checkpoint_bytes <= MAX_INPUT && typeof scale.content_base64 === 'string', 'synthetic_admission');
    const bytes = Buffer.from(scale.content_base64, 'base64');
    check(bytes.length === scale.checkpoint_bytes && hash(bytes) === scale.checkpoint_sha256,
      'synthetic_admission');
    return {...scale, bytes, content_base64: undefined};
  });
  return {cases, scales};
}

// This function is serialized as reviewed test JS, never as a document/command payload.
async function installCanvasHarness(paths) {
  const {EditorController, EventOutbox, sha256, fromBase64} = await import('/qa/host.mjs');
  const engine = await import(paths.module);
  const wasm = await engine.default({module_or_path: paths.wasm});
  const wasmMemory = wasm?.memory;
  if (!(wasmMemory instanceof WebAssembly.Memory)) throw new Error('WASM linear memory unavailable.');
  const assert = condition => { if (!condition) throw new Error('Closed canvas QA assertion.'); };
  const frames = async count => { for (let index = 0; index < count; index++) await new Promise(requestAnimationFrame); };
  const instanceToken = crypto.randomUUID();
  let native, controller, initialNative, data, outbox;
  let events = [], acks = 0, reruns = 0;
  const snapshot = () => native.serialize();
  const snapshotHash = () => sha256(snapshot());
  const model = () => JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(snapshot()));
  const control = action => ({schema: 'gc-wordcraft-control/v1', command_id: crypto.randomUUID(), action,
    revision: controller.revision, content_hash: controller.currentHash});
  async function checkpointAck() {
    controller.changed();
    assert(controller.state === 'dirty');
    const checkpoint = await controller.checkpoint();
    assert(checkpoint && checkpoint.payload.content_hash === await sha256(fromBase64(checkpoint.payload.content_base64)));
    const ack = {request_id: checkpoint.request_id, revision: controller.revision + 1, content_hash: checkpoint.payload.content_hash};
    data = {...data, revision: ack.revision, content_hash: ack.content_hash, ack};
    controller.receive(data); // Explicitly SIMULATED transport ACK, no persistence claim.
    outbox.acknowledge(controller.sequence);
    assert(controller.state === 'saved' && native.dirty() === false && await snapshotHash() === ack.content_hash);
    acks++;
    return {revision: controller.revision, content_hash: ack.content_hash};
  }
  async function settle() {
    await frames(6);
    if (native.dirty()) {
      controller.changed();
      if (controller.state !== 'dirty') await controller.control(control('freeze'));
      await checkpointAck();
    }
    assert(['ready', 'saved'].includes(controller.state) && !native.dirty());
    assert(await snapshotHash() === controller.currentHash);
  }
  const targetPlan = () => {
    const source = model();
    const index = source.document.body.findIndex(block => block.kind === 'para' && block.text.startsWith('Corpus plenamente sintético'));
    assert(index >= 0);
    return {schema: 'gc-wordcraft-native-patch/v1', source_revision: controller.revision,
      source_hash: controller.currentHash, operations: [{op: 'replace_text', story: 'body', path: [index],
        start_byte: 0, end_byte: 6, old_text: 'Corpus', new_text: 'Ensaio'}]};
  };
  window.qa = Object.freeze({
    wasmLinearMemoryBytes() { return wasmMemory.buffer.byteLength; },
    async probe() { return {instance_token: instanceToken, source_hash: await snapshotHash(), generation: native.generation(),
      responsive_profile: JSON.parse(native.responsive_profile())}; },
    async open(base64, expectedHash) {
      assert(!native);
      const bytes = fromBase64(base64);
      assert(await sha256(bytes) === expectedHash);
      native = new engine.GovConnectEditor(); initialNative = native;
      for (const name of ['interaction_lock_ready', 'set_interaction_locked', 'apply_text_patch', 'undo', 'redo']) assert(typeof native[name] === 'function');
      await native.start(document.querySelector('#canvas'), bytes, true);
      data = {instance_id: crypto.randomUUID(), session_id: crypto.randomUUID(), document_id: crypto.randomUUID(),
        nonce: crypto.randomUUID().replaceAll('-', '') + crypto.randomUUID().replaceAll('-', ''), revision: 1, content_hash: expectedHash};
      outbox = new EventOutbox(() => {});
      controller = new EditorController(native, data, (key, event) => { events.push(event); outbox.push(key, event); });
      await controller.loaded(bytes);
      await settle();
      return {source_hash: expectedHash, canonical_hash: await snapshotHash(), initial_source_acks_simulated: acks};
    },
    async apiEdit() {
      const before = await snapshotHash(), generation = native.generation();
      native.select_text('inteiramente'); native.insert_text('plenamente');
      controller.changed(); await frames(2);
      assert(native.generation() !== generation && await snapshotHash() !== before && native.dirty());
      assert(model().document.body.some(block => block.kind === 'para' && block.text.startsWith('Corpus plenamente sintético')));
      return {generation_changed: true, source_changed: true, ...await checkpointAck()};
    },
    async prepareQueuedInput() { await frames(2); native.select_text('Corpus'); await frames(2); },
    async queuedInputFreeze() {
      const before = await snapshotHash(), generation = native.generation();
      const input = document.querySelector('#canvas').parentElement.querySelector('input[type="text"]');
      assert(input); input.focus();
      // Uses the actual eframe TextAgent listener. No fake native queue or Session access.
      input.value = 'Dreno';
      input.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: 'Dreno'}));
      assert(native.generation() === generation); // Mandatory pending-before-frame precondition.
      const request = control('freeze');
      const task = controller.control(request);
      assert(native.interaction_lock_ready() === false);
      await task;
      assert(controller.state === 'dirty' && native.dirty() && !native.interaction_lock_ready());
      assert(events.at(-1).event === 'document.control_failed' && events.at(-1).payload.reason === 'dirty');
      assert(native.generation() !== generation && await snapshotHash() !== before);
      assert(model().document.body.some(block => block.kind === 'para' && block.text.startsWith('Dreno plenamente sintético')));
      return {event_source: 'SYNTHETIC_DOM_INPUT_EVENT_REAL_EFRAME_CAPTURE', pending_before_frame: true,
        false_freeze_proofs: events.filter(event => event.event === 'document.frozen').length, ...await checkpointAck()};
    },
    async prepareKeyboard() {
      native.select_text('Dreno'); await frames(2);
      return {generation: native.generation(), content_hash: await snapshotHash()};
    },
    async verifyKeyboard(before) {
      await frames(3); controller.changed();
      assert(native.generation() !== before.generation && await snapshotHash() !== before.content_hash && native.dirty());
      assert(model().document.body.some(block => block.kind === 'para' && block.text.startsWith('Corpus plenamente sintético')));
      return {event_source: 'PLAYWRIGHT_KEYBOARD_TYPE', generation_changed: true, source_bytes_changed: true, ...await checkpointAck()};
    },
    async rerun() {
      const before = await snapshotHash();
      controller.receive({...data, checkpoint_base64: 'obsolete-prop-must-not-reload-the-session'});
      controller.receive({...data}); reruns++;
      assert(native === initialNative && controller.native === initialNative && await snapshotHash() === before && controller.state === 'saved');
      return {same_native_instance: true, duplicate_ack_accepted: true, old_checkpoint_prop_ignored: true};
    },
    async freezeRelease() {
      const before = await snapshotHash(), generation = native.generation(), request = control('freeze');
      assert(native.interaction_lock_ready() === false);
      const task = controller.control(request);
      assert(native.interaction_lock_ready() === false); // Request must not claim completion synchronously.
      await task;
      assert(controller.state === 'frozen' && native.interaction_lock_ready() === true);
      assert(await snapshotHash() === before && native.generation() === generation);
      const plan = targetPlan();
      const calls = [() => native.insert_text('Blocked QA'), () => native.bold(), () => native.undo(), () => native.redo(),
        () => native.select_text('Corpus'), () => native.apply_text_patch(controller.revision, JSON.stringify(plan))];
      for (const call of calls) { let rejected = false; try { call(); } catch { rejected = true; } assert(rejected); }
      assert(await snapshotHash() === before && native.generation() === generation);
      await controller.control({...request, action: 'release'});
      await controller.control({...request, action: 'release'});
      await controller.control(request); // Terminal replay cannot relock.
      assert(controller.state === 'saved' && native.interaction_lock_ready() === false && await snapshotHash() === before);
      native.select_text('Corpus');
      return {frame_barrier_observed: true, frozen_source_hash: before, blocked_edit_apis: calls.length,
        exact_release_and_terminal_replay: true, same_native_instance: native === initialNative};
    },
    async freezeForApproval() {
      const before = await snapshotHash(), generation = native.generation(), request = control('freeze');
      await controller.control(request);
      assert(controller.state === 'frozen' && native.interaction_lock_ready() === true
        && await snapshotHash() === before && native.generation() === generation);
      return {command_id: request.command_id, revision: request.revision,
        content_hash: before, generation, instance_token: instanceToken};
    },
    async verifyApprovedFrozen(expected) {
      assert(expected && controller.state === 'frozen' && native.interaction_lock_ready() === true
        && controller.revision === expected.revision && controller.currentHash === expected.content_hash
        && instanceToken === expected.instance_token && native.generation() === expected.generation);
      const before = await snapshotHash(), source = model();
      const index = source.document.body.findIndex(block => block.kind === 'para' && block.text.length >= 6);
      assert(index >= 0);
      const oldText = source.document.body[index].text;
      const oldPrefix = oldText.slice(0, 6), newPrefix = oldPrefix === 'Ensaio' ? 'Corpus' : 'Ensaio';
      const plan = {schema: 'gc-wordcraft-native-patch/v1', source_revision: controller.revision,
        source_hash: controller.currentHash, operations: [{op: 'replace_text', story: 'body', path: [index],
          start_byte: 0, end_byte: new TextEncoder().encode(oldPrefix).length,
          old_text: oldPrefix, new_text: newPrefix}]};
      const calls = [() => native.insert_text('Blocked C11'), () => native.bold(), () => native.undo(),
        () => native.redo(), () => native.select_text('Corpus'),
        () => native.apply_text_patch(controller.revision, JSON.stringify(plan))];
      for (const call of calls) { let rejected = false; try { call(); } catch { rejected = true; } assert(rejected); }
      assert(await snapshotHash() === before && before === expected.content_hash
        && native.generation() === expected.generation && controller.state === 'frozen');
      return {revision: controller.revision, content_hash: before, generation: native.generation(),
        instance_token: instanceToken, blocked_edit_apis: calls.length, state: controller.state};
    },
    async captureGovbotSelection() {
      await settle();
      const block = model().document.body.find(item => item.kind === 'para' && item.text.startsWith('Corpus plenamente sintético'));
      assert(block && block.text.length > 0); native.select_text(block.text); await frames(2);
      const request = control('selection'); await controller.control(request);
      const event = events.at(-1);
      assert(event.event === 'document.selection' && event.payload.command_id === request.command_id
        && event.payload.text === block.text && await snapshotHash() === request.content_hash);
      return {command_id: request.command_id, text: event.payload.text, source_hash: request.content_hash};
    },
    async applyGovbotSelection(newText) {
      assert(typeof newText === 'string' && newText.startsWith('Ensaio plenamente sintético'));
      const before = await snapshotHash(), source = model();
      const index = source.document.body.findIndex(item => item.kind === 'para' && item.text.startsWith('Corpus plenamente sintético'));
      assert(index >= 0); const oldText = source.document.body[index].text;
      const plan = {schema: 'gc-wordcraft-native-patch/v1', source_revision: controller.revision,
        source_hash: before, operations: [{op: 'replace_text', story: 'body', path: [index], start_byte: 0,
          end_byte: new TextEncoder().encode(oldText).length, old_text: oldText, new_text: newText}]};
      native.apply_text_patch(controller.revision, JSON.stringify(plan));
      const patched = await snapshotHash(); assert(patched !== before && model().document.body[index].text === newText);
      controller.changed();
      const patchAck = await checkpointAck();
      assert(patchAck.content_hash === patched);
      native.undo();
      assert(await snapshotHash() === before && model().document.body[index].text === oldText);
      controller.changed();
      const undoAck = await checkpointAck();
      assert(undoAck.content_hash === before && undoAck.revision === patchAck.revision + 1);
      return {source_hash: before, patched_hash: patched, restored_hash: undoAck.content_hash,
        patch_ack_revision: patchAck.revision, patch_ack_hash: patchAck.content_hash,
        undo_ack_revision: undoAck.revision, undo_ack_hash: undoAck.content_hash,
        undo_after_patch_ack: true, exact_undo: undoAck.content_hash === before, gateway_mocked: true};
    },
    async applyPersistedPatch(operationId, expectedRevision, targetHash, plan) {
      assert(typeof operationId === 'string' && typeof targetHash === 'string');
      assert(Number.isSafeInteger(expectedRevision) && expectedRevision === controller.revision);
      assert(plan && plan.schema === 'gc-wordcraft-native-patch/v1'
        && plan.source_revision === expectedRevision && plan.source_hash === controller.currentHash);
      const before = await snapshotHash();
      const eventCount = events.length;
      await controller.control({schema: 'gc-wordcraft-control/v1', command_id: operationId,
        action: 'patch', revision: expectedRevision, content_hash: before,
        target_hash: targetHash, plan_json: JSON.stringify(plan)});
      const patched = await snapshotHash();
      const checkpoint = events.slice(eventCount).findLast(item => item.event === 'document.checkpoint');
      assert(checkpoint && checkpoint.payload.content_hash === patched
        && checkpoint.expected_revision === expectedRevision && checkpoint.request_id === operationId
        && patched === targetHash && native.dirty());
      return {request_id: checkpoint.request_id, expected_revision: checkpoint.expected_revision,
        ...checkpoint.payload, source_hash: before};
    },
    async acceptPersistedPatch(ack) {
      if (!(ack && ack.request_id && ack.revision === controller.revision + 1
          && ack.content_hash === await snapshotHash())) throw new Error('PATCH_ACK_INPUT');
      data = {...data, revision: ack.revision, content_hash: ack.content_hash, ack};
      controller.receive(data); outbox.acknowledge(controller.sequence);
      if (!(controller.state === 'saved' && native.dirty() === false
          && controller.revision === ack.revision && controller.currentHash === ack.content_hash)) {
        throw new Error('PATCH_ACK_REJECTED');
      }
      return {revision: controller.revision, content_hash: controller.currentHash,
        native_hash: await snapshotHash(), saved: true};
    },
    async acceptPersistedPatchAndUndo(ack) {
      if (!(ack && ack.request_id && ack.revision === controller.revision + 1
          && ack.content_hash === await snapshotHash())) throw new Error('PATCH_ACK_INPUT');
      data = {...data, revision: ack.revision, content_hash: ack.content_hash, ack};
      controller.receive(data); outbox.acknowledge(controller.sequence);
      if (!(controller.state === 'saved' && native.dirty() === false)) throw new Error('PATCH_ACK_REJECTED');
      const persisted = await snapshotHash();
      try { native.undo(); } catch { throw new Error('UNDO_COMMAND_REFUSED'); }
      const restored = await snapshotHash();
      if (!(restored !== persisted && native.dirty())) throw new Error('UNDO_DID_NOT_CHANGE');
      controller.changed();
      const checkpoint = await controller.checkpoint();
      if (!(checkpoint && checkpoint.expected_revision === ack.revision
          && checkpoint.payload.content_hash === restored)) throw new Error('UNDO_CHECKPOINT_INVALID');
      return {request_id: checkpoint.request_id, expected_revision: checkpoint.expected_revision,
        ...checkpoint.payload, persisted_hash: persisted};
    },
    async acceptPersistedUndo(ack) {
      assert(ack && ack.request_id && ack.revision === controller.revision + 1
        && ack.content_hash === await snapshotHash());
      data = {...data, revision: ack.revision, content_hash: ack.content_hash, ack};
      controller.receive(data); outbox.acknowledge(controller.sequence);
      assert(controller.state === 'saved' && native.dirty() === false
        && controller.revision === ack.revision && controller.currentHash === ack.content_hash);
      return {revision: controller.revision, content_hash: controller.currentHash,
        native_hash: await snapshotHash(), saved: true};
    },
    async nativePatchUndo() {
      const before = await snapshotHash(), plan = targetPlan();
      assert(plan.source_hash === before && native.dirty() === false);
      let rejected = false;
      try { native.apply_text_patch(controller.revision, JSON.stringify({...plan, source_hash: '0'.repeat(64)})); }
      catch { rejected = true; }
      assert(rejected && await snapshotHash() === before);
      native.apply_text_patch(controller.revision, JSON.stringify(plan));
      const after = await snapshotHash();
      assert(after !== before && native.dirty());
      assert(model().document.body[plan.operations[0].path[0]].text.startsWith('Ensaio plenamente sintético'));
      native.undo(); assert(await snapshotHash() === before);
      native.undo(); assert(await snapshotHash() !== before); // Earlier editing history is still present.
      native.redo(); assert(await snapshotHash() === before);
      native.redo(); assert(await snapshotHash() === after);
      controller.changed(); await checkpointAck();
      rejected = false;
      try { native.apply_text_patch(controller.revision, JSON.stringify(plan)); } catch { rejected = true; }
      assert(rejected && await snapshotHash() === after && native === initialNative);
      return {source_hash: before, patched_hash: after, one_patch_undo_exact_source: true,
        earlier_undo_history_preserved: true, redo_exact_patched_source: true, stale_source_rejected: true};
    },
    async exports() {
      const before = await snapshotHash();
      engine.validate_checkpoint(snapshot());
      const result = {};
      for (const format of ['docx', 'pdf']) {
        const bytes = format === 'docx' ? native.export_docx() : native.export_pdf();
        assert(bytes.length > 0 && bytes.length <= 64 * 1024 * 1024);
        assert(format === 'docx' ? bytes[0] === 80 && bytes[1] === 75 && bytes[2] === 3 && bytes[3] === 4
          : new TextDecoder().decode(bytes.slice(0, 5)) === '%PDF-');
        result[format] = {bytes: bytes.length, sha256: await sha256(bytes)};
      }
      assert(await snapshotHash() === before);
      return {source_hash: before, formats: result, final_revision_transport_only: controller.revision,
        simulated_ack_count: acks, simulated_rerun_count: reruns,
        event_counts: Object.fromEntries([...new Set(events.map(event => event.event))].map(name => [name, events.filter(event => event.event === name).length]))};
    },
    close() { controller?.dispose(); native = null; },
  });
}

export function pageModule(moduleUrl, wasmUrl) {
  for (const value of [moduleUrl, wasmUrl]) check(/^\/app\/static\/wordcraft\/[a-zA-Z0-9._/-]+$/.test(value)
    && !value.split('/').includes('..'), 'http_confinement');
  return Buffer.from(`(${installCanvasHarness.toString()})(${JSON.stringify({module: moduleUrl, wasm: wasmUrl})});\n`);
}

export function staticResponse(assets, method, rawUrl) {
  if (!['GET', 'HEAD'].includes(method) || typeof rawUrl !== 'string' || !/^\/[a-zA-Z0-9._/-]*$/.test(rawUrl)
      || rawUrl.split('/').some(part => ['.', '..'].includes(part)) || !assets.has(rawUrl)) return null;
  return assets.get(rawUrl);
}

export async function serveAssets(assets) {
  const server = createServer((request, response) => {
    const item = staticResponse(assets, request.method, request.url);
    response.setHeader('Cache-Control', 'no-store'); response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
    response.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
    response.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; worker-src 'self' blob:; frame-ancestors 'none'");
    if (!item) { response.writeHead(404, {'Content-Length': '0'}); response.end(); return; }
    response.writeHead(200, {'Content-Type': item.mime, 'Content-Length': item.bytes.length});
    response.end(request.method === 'HEAD' ? undefined : item.bytes);
  });
  server.maxRequestsPerSocket = 100; server.requestTimeout = 5000; server.headersTimeout = 5000;
  await new Promise((done, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', done); });
  return {origin: `http://127.0.0.1:${server.address().port}`, close: () => new Promise((done, reject) => {
    server.close(error => error ? reject(error) : done()); server.closeAllConnections();
  })};
}

export async function buildAssets(config) {
  const bundle = await verifyBundle(config.bundle, config['manifest-sha256']);
  const manifestRaw = await boundedFile(resolve(config.bundle, 'qa-manifest.json'), 128 * 1024, 'bundle_admission');
  const manifest = JSON.parse(manifestRaw);
  const upstream = JSON.parse(await readFile(resolve(ROOT, 'docs/wordcraft/upstream.lock.json'))).commit;
  check(hash(manifestRaw) === config['manifest-sha256'] && manifest.govconnect_commit === config['producer-commit']
    && manifest.upstream_commit === upstream, 'bundle_admission');
  const assets = new Map();
  const engineAssetBytes = [];
  for (const item of manifest.files) {
    const bytes = await boundedFile(resolve(config.bundle, item.path), 80 * 1024 * 1024, 'bundle_admission');
    check(hash(bytes) === item.sha256 && bytes.length === item.bytes, 'bundle_admission');
    assets.set('/app/static/wordcraft/' + item.path, {bytes, mime: item.path.endsWith('.wasm') ? 'application/wasm' : 'text/javascript; charset=utf-8'});
    engineAssetBytes.push({path: item.path, bytes});
  }
  // verifyBundle deliberately exposes verified bytes only. Derive the public
  // entry-point URLs from the same admitted manifest instead of reaching for
  // an internal filesystem path that is not part of its contract.
  const rootModule = manifest.files.find(item => !item.path.includes('/') && item.path.endsWith('.js'));
  const rootWasm = manifest.files.find(item => !item.path.includes('/') && item.path.endsWith('.wasm'));
  check(Boolean(rootModule && rootWasm), 'bundle_admission');
  const moduleUrl = '/app/static/wordcraft/' + rootModule.path;
  const wasmUrl = '/app/static/wordcraft/' + rootWasm.path;
  const host = await boundedFile(resolve(ROOT, 'assets/wordcraft_editor/host.mjs'), 256 * 1024, 'bundle_admission');
  assets.set('/qa/host.mjs', {bytes: host, mime: 'text/javascript; charset=utf-8'});
  assets.set('/qa/page.mjs', {bytes: pageModule(moduleUrl, wasmUrl), mime: 'text/javascript; charset=utf-8'});
  assets.set('/', {bytes: Buffer.from('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>GovConnect synthetic canvas QA</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden}canvas{width:100vw;height:100vh;display:block}</style><canvas id="canvas"></canvas><script type="module" src="/qa/page.mjs"></script></html>'), mime: 'text/html; charset=utf-8'});
  return {assets, manifest, host_sha256: hash(host), compression: compressionInventory(engineAssetBytes)};
}

export async function run(config) {
  let phase = 'configuration', outputReady = false, server, browser, context, mobileContext, page;
  const extraPages = [];
  let deniedRequests = 0, pageErrors = 0, consoleErrors = 0;
  const diagnostics = [];
  const evidence = {schema: 'gc-wordcraft-headless-browser-qa/v1', status: 'FAIL_HEADLESS_BROWSER_QA',
    manual_browser_observation: false, gotrue_or_database_proof: false, production_access: false,
    ack_model: 'SIMULATED_TRANSPORT_ONLY_NOT_PERSISTENCE', cases: [],
    performance: {scope: 'HEADLESS_CHROMIUM_QA_SYNTHETIC_NOT_TARGET_INFRASTRUCTURE',
      browser_process_total_memory_measured: true, wasm_linear_memory_measured: true,
      renderer_js_heap_and_dom_measured: true, cold_warm_kind: 'NEW_PAGE_SAME_BROWSER_CONTEXT_CACHE'},
    limits: {cases: 3, checkpoint_bytes: MAX_INPUT, stage_timeout_ms: 45_000, global_timeout_ms: 300_000},
    pending: ['MANUAL_IME', 'TOOLBAR_UI', 'FULL_STREAMLIT', 'DATABASE_PERSISTENCE', 'HUMAN_VISUAL_FIDELITY_REVIEW',
      'PHYSICAL_MOBILE_DEVICE', 'HUMAN_MOBILE_USABILITY_REVIEW']};
  const stage = async (name, operation) => { phase = name; return operation(); };
  let watchdog;
  try {
    check(QA_PIN.supportedPlatforms.includes(process.platform), phase);
    for (const key of ['bundle', 'checkpoints', 'inputs', 'playwright', 'python']) config[key] = await realpath(config[key]);
    check(!(await stat(config.out).catch(() => null)), phase);
    // Create the fresh evidence directory before admissions so failures in a
    // child process retain their bounded diagnostic instead of collapsing to
    // a stage name only.
    await mkdir(config.out, {mode: 0o700}); outputReady = true;
    const built = await stage('bundle_admission', () => buildAssets(config));
    const admitted = await stage('synthetic_admission', () => admitInputs(config));
    const {cases, scales} = admitted;
    const pkg = await stage('playwright_pin', () => verifyPlaywright(config.playwright));
    evidence.runtime = {...QA_PIN, platform_observed: process.platform,
      engine_manifest_sha256: config['manifest-sha256'],
      producer_commit: built.manifest.govconnect_commit, upstream_commit: built.manifest.upstream_commit,
      host_sha256: built.host_sha256, playwright_catalog_sha256: pkg.catalog_sha256,
      engine_asset_sizes: built.compression};
    server = await stage('http_confinement', () => serveAssets(built.assets));
    const {chromium} = await stage('playwright_pin', () => import(pathToFileURL(pkg.entry).href));
    const environment = browserEnvironment();
    const executablePath = await stage('playwright_pin', () => realpath(browserExecutablePath()));
    evidence.runtime.browser_executable_sha256 = hash(await stage('playwright_pin', () => readFile(executablePath)));
    const browserStarted = process.hrtime.bigint();
    browser = await stage('chromium_start', () => chromium.launch({headless: true, timeout: 45_000, env: environment,
      executablePath,
      args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--disable-dev-shm-usage',
        '--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run']}));
    evidence.performance.browser_startup_ms = elapsedMs(browserStarted);
    check(Number.isFinite(evidence.performance.browser_startup_ms)
      && evidence.performance.browser_startup_ms >= 0, 'performance_metrics');
    check(browser.version() === QA_PIN.chromiumVersion, 'chromium_start');
    evidence.runtime.browser_version_observed = browser.version();
    const routeConfined = route => {
      const url = new URL(route.request().url());
      if (url.origin === server.origin && built.assets.has(url.pathname) && !url.search) return route.continue();
      deniedRequests++; return route.abort();
    };
    context = await browser.newContext({viewport: {width: 1366, height: 900}, locale: 'pt-BR', timezoneId: 'UTC',
      acceptDownloads: false, serviceWorkers: 'block'});
    context.setDefaultTimeout(45_000);
    await context.route('**/*', routeConfined);
    watchdog = setTimeout(() => { phase = 'global_timeout'; void browser?.close(); }, 300_000);
    for (const [caseIndex, item] of cases.entries()) {
      page = await context.newPage();
      const cdp = await context.newCDPSession(page);
      page.on('pageerror', error => { pageErrors++; diagnostics.push({kind: 'pageerror', message: String(error).slice(0, 1000)}); });
      page.on('console', message => { if (message.type() === 'error') {
        consoleErrors++; diagnostics.push({kind: 'console', message: message.text().slice(0, 1000)});
      }});
      const canvasStarted = process.hrtime.bigint();
      await stage('canvas_open', async () => {
        await page.goto(server.origin + '/', {waitUntil: 'load'});
        await page.waitForFunction(() => Boolean(window.qa));
      });
      const result = {case: item.case, input_sha256: item.checkpoint_sha256, fixture_sha256: item.fixture_sha256,
        source_bytes: item.checkpoint_bytes, steps: {}, performance: {
          cache_state: caseIndex === 0 ? 'cold_browser_context' : 'warm_browser_context',
          canvas_ready_ms: elapsedMs(canvasStarted),
        }};
      const openStarted = process.hrtime.bigint();
      result.steps.open = await stage('canvas_open', () => page.evaluate(({content, sha}) => window.qa.open(content, sha),
        {content: item.bytes.toString('base64'), sha: item.checkpoint_sha256}));
      result.performance.document_open_ms = elapsedMs(openStarted);
      result.performance.after_open = await stage('performance_metrics', () => rendererMetrics(cdp));
      await page.locator('#canvas').click({position: {x: 600, y: 500}});
      await page.locator('input[type="text"]').focus();
      result.steps.api_edit = await stage('api_edit', () => page.evaluate(() => window.qa.apiEdit()));
      await page.keyboard.press('Control'); // The actual TextAgent clears prior text-agent history on modifiers.
      await page.evaluate(() => window.qa.prepareQueuedInput());
      result.steps.queued_input = await stage('queued_input', () => page.evaluate(() => window.qa.queuedInputFreeze()));
      check(result.steps.queued_input.pending_before_frame === true && result.steps.queued_input.false_freeze_proofs === 0, phase);
      await page.locator('input[type="text"]').focus();
      const beforeKeyboard = await page.evaluate(() => window.qa.prepareKeyboard());
      await stage('keyboard_input', () => page.keyboard.type('Corpus', {delay: 10}));
      result.steps.keyboard = await stage('keyboard_input', () => page.evaluate(before => window.qa.verifyKeyboard(before), beforeKeyboard));
      result.steps.rerun = await page.evaluate(() => window.qa.rerun());
      result.steps.freeze_release = await stage('freeze_release', () => page.evaluate(() => window.qa.freezeRelease()));
      if (caseIndex === 0) {
        const selection = await stage('govbot_capture', () => page.evaluate(() => window.qa.captureGovbotSelection()));
        const proposal = await stage('govbot_backend', () => govbotProposal(config, selection.text));
        result.steps.govbot_selection = await stage('govbot_apply', () =>
          page.evaluate(value => window.qa.applyGovbotSelection(value), proposal.newValue));
        result.steps.govbot_selection.selection_bound_to_source = selection.source_hash;
        result.steps.govbot_selection.backend_compiler = 'wordcraft_capacidades.propositor_govbot_selecao';
      }
      result.steps.patch_undo_redo = await stage('native_patch_undo', () => page.evaluate(() => window.qa.nativePatchUndo()));
      result.steps.exports = await stage('native_export', () => page.evaluate(() => window.qa.exports()));
      result.performance.after_interactions = await stage('performance_metrics', () => rendererMetrics(cdp));
      const screenshot = await stage('screenshot', () => page.screenshot({animations: 'disabled', fullPage: false}));
      check(screenshot.length > 1024 && screenshot.length <= MAX_SCREENSHOT
        && screenshot.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])), 'screenshot');
      const screenshotName = item.case + '.png';
      await writeFile(resolve(config.out, screenshotName), screenshot, {flag: 'wx'});
      result.screenshot = {path: screenshotName, bytes: screenshot.length, sha256: hash(screenshot), human_visual_approval: false};
      evidence.cases.push(result);
      await page.evaluate(() => window.qa.close()); await cdp.detach(); await page.close(); page = undefined;
    }
    const pair = cases.slice(0, 2), opened = [];
    for (const item of pair) {
      const concurrent = await context.newPage(); extraPages.push(concurrent);
      concurrent.on('pageerror', error => { pageErrors++; diagnostics.push({kind: 'pageerror', message: String(error).slice(0, 1000)}); });
      concurrent.on('console', message => { if (message.type() === 'error') {
        consoleErrors++; diagnostics.push({kind: 'console', message: message.text().slice(0, 1000)});
      }});
      await stage('multi_canvas', async () => {
        await concurrent.goto(server.origin + '/', {waitUntil: 'load'});
        await concurrent.waitForFunction(() => Boolean(window.qa));
        await concurrent.evaluate(({content, sha}) => window.qa.open(content, sha),
          {content: item.bytes.toString('base64'), sha: item.checkpoint_sha256});
      });
      opened.push(await concurrent.evaluate(() => window.qa.probe()));
    }
    check(opened[0].instance_token !== opened[1].instance_token
      && opened[0].source_hash === pair[0].checkpoint_sha256
      && opened[1].source_hash === pair[1].checkpoint_sha256, 'multi_canvas');
    const firstEdit = await stage('multi_canvas', () => extraPages[0].evaluate(() => window.qa.apiEdit()));
    const [firstAfter, secondUntouched] = await Promise.all(extraPages.map(item => item.evaluate(() => window.qa.probe())));
    check(firstAfter.source_hash !== opened[0].source_hash && firstAfter.generation !== opened[0].generation
      && secondUntouched.source_hash === opened[1].source_hash && secondUntouched.generation === opened[1].generation,
    'multi_canvas');
    const browserCdp = await browser.newBrowserCDPSession();
    try {
      evidence.performance.browser_process_memory_at_two_canvas_peak = await stage('performance_metrics', () =>
        chromiumProcessMemory(browserCdp));
    } finally {
      await browserCdp.detach();
    }
    await extraPages[0].evaluate(() => window.qa.close()); await extraPages[0].close();
    const secondEdit = await stage('multi_canvas', () => extraPages[1].evaluate(() => window.qa.apiEdit()));
    const secondAfter = await extraPages[1].evaluate(() => window.qa.probe());
    check(secondAfter.source_hash !== opened[1].source_hash && secondAfter.generation !== opened[1].generation,
      'multi_canvas');
    evidence.multi_canvas = {simultaneous_instances: 2, distinct_instance_tokens: true,
      first_edit_hash: firstEdit.content_hash, second_unchanged_while_first_edited: true,
      second_edit_after_first_closed_hash: secondEdit.content_hash, independent_close: true};
    await extraPages[1].evaluate(() => window.qa.close()); await extraPages[1].close();
    evidence.performance.summary = await stage('performance_metrics', () => summarizePerformance(evidence.cases));
    evidence.scale_profiles = [];
    for (const scale of scales) {
      page = await context.newPage();
      const scaleCdp = await context.newCDPSession(page);
      const scaleStarted = process.hrtime.bigint();
      await stage('canvas_open', async () => {
        await page.goto(server.origin + '/', {waitUntil: 'load'});
        await page.waitForFunction(() => Boolean(window.qa));
      });
      const scaleCanvasReadyMs = elapsedMs(scaleStarted);
      const scaleOpenStarted = process.hrtime.bigint();
      const scaleOpen = await stage('canvas_open', () => page.evaluate(({content, sha}) => window.qa.open(content, sha),
        {content: scale.bytes.toString('base64'), sha: scale.checkpoint_sha256}));
      const scaleDocumentOpenMs = elapsedMs(scaleOpenStarted);
      const scaleProbe = await page.evaluate(() => window.qa.probe());
      check(scaleProbe.source_hash === scale.checkpoint_sha256, 'canvas_open');
      const scaleMetrics = await stage('performance_metrics', () => rendererMetrics(scaleCdp));
      const scaleExports = await stage('native_export', () => page.evaluate(() => window.qa.exports()));
      check(scaleExports?.formats?.pdf?.sha256 === scale.pdf_sha256
        && scaleExports?.formats?.pdf?.bytes === scale.pdf_bytes, 'native_export');
      const scaleBrowserCdp = await browser.newBrowserCDPSession();
      let scaleProcessMemory;
      try {
        scaleProcessMemory = await stage('performance_metrics', () => chromiumProcessMemory(scaleBrowserCdp));
      } finally {
        await scaleBrowserCdp.detach();
      }
      evidence.scale_profiles.push({profile: scale.profile, declared_pages: scale.pages,
        source_sha256: scale.source_sha256, checkpoint_sha256: scale.checkpoint_sha256,
        checkpoint_bytes: scale.checkpoint_bytes, canvas_ready_ms: scaleCanvasReadyMs,
        document_open_ms: scaleDocumentOpenMs, open_generation: scaleOpen.generation,
        admitted_pdf_pages: scale.pages, admitted_pdf_sha256: scale.pdf_sha256,
        renderer: scaleMetrics, browser_process_memory: scaleProcessMemory, exports: scaleExports});
      await page.evaluate(() => window.qa.close()); await scaleCdp.detach(); await page.close(); page = undefined;
    }
    const mobileScale = scales[0];
    mobileContext = await browser.newContext({viewport: {width: 390, height: 844}, screen: {width: 390, height: 844},
      deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: 'pt-BR', timezoneId: 'UTC',
      acceptDownloads: false, serviceWorkers: 'block'});
    mobileContext.setDefaultTimeout(45_000);
    await mobileContext.route('**/*', routeConfined);
    page = await mobileContext.newPage();
    page.on('pageerror', error => { pageErrors++; diagnostics.push({kind: 'pageerror', message: String(error).slice(0, 1000)}); });
    page.on('console', message => { if (message.type() === 'error') {
      consoleErrors++; diagnostics.push({kind: 'console', message: message.text().slice(0, 1000)});
    }});
    const mobileCdp = await mobileContext.newCDPSession(page);
    const mobileStarted = process.hrtime.bigint();
    await stage('mobile_emulation', async () => {
      await page.goto(server.origin + '/', {waitUntil: 'load'});
      await page.waitForFunction(() => Boolean(window.qa));
    });
    const mobileCanvasReadyMs = elapsedMs(mobileStarted);
    const mobileOpenStarted = process.hrtime.bigint();
    const mobileOpen = await stage('mobile_emulation', () => page.evaluate(({content, sha}) => window.qa.open(content, sha),
      {content: mobileScale.bytes.toString('base64'), sha: mobileScale.checkpoint_sha256}));
    const mobileDocumentOpenMs = elapsedMs(mobileOpenStarted);
    const mobileProbe = await page.evaluate(() => window.qa.probe());
    check(mobileProbe.source_hash === mobileScale.checkpoint_sha256, 'mobile_emulation');
    check(mobileProbe.responsive_profile?.initialized === true
      && mobileProbe.responsive_profile?.ribbon_collapsed === true
      && mobileProbe.responsive_profile?.interface_percent === 75
      && mobileProbe.responsive_profile?.fit === 'pageWidth'
      && mobileProbe.responsive_profile?.single_column === true, 'mobile_emulation');
    const mobileExports = await stage('mobile_emulation', () => page.evaluate(() => window.qa.exports()));
    check(mobileExports?.formats?.pdf?.sha256 === mobileScale.pdf_sha256
      && mobileExports?.formats?.pdf?.bytes === mobileScale.pdf_bytes, 'mobile_emulation');
    const mobileMetrics = await stage('performance_metrics', () => rendererMetrics(mobileCdp));
    const mobileScreenshot = await stage('screenshot', () => page.screenshot({animations: 'disabled', fullPage: false}));
    check(mobileScreenshot.length > 1024 && mobileScreenshot.length <= MAX_SCREENSHOT, 'screenshot');
    await writeFile(resolve(config.out, 'mobile-390x844.png'), mobileScreenshot, {flag: 'wx'});
    evidence.mobile_profile = {emulation_only_not_physical_device: true, mobile_usability_approved: false,
      viewport_css: {width: 390, height: 844},
      screen_css: {width: 390, height: 844}, device_scale_factor: 2, is_mobile: true, has_touch: true,
      profile: mobileScale.profile, declared_pages: mobileScale.pages, canvas_ready_ms: mobileCanvasReadyMs,
      document_open_ms: mobileDocumentOpenMs, open_generation: mobileOpen.generation, renderer: mobileMetrics,
      responsive_profile: mobileProbe.responsive_profile,
      pdf_sha256: mobileExports.formats.pdf.sha256, pdf_bytes: mobileExports.formats.pdf.bytes,
      screenshot: {path: 'mobile-390x844.png', bytes: mobileScreenshot.length, sha256: hash(mobileScreenshot),
        human_visual_approval: false}};
    await page.evaluate(() => window.qa.close()); await mobileCdp.detach(); await page.close(); page = undefined;
    await mobileContext.close(); mobileContext = undefined;
    check(deniedRequests === 0 && pageErrors === 0 && consoleErrors === 0, 'runtime_errors');
    evidence.network = {external_requests_blocked: deniedRequests, page_errors: pageErrors, console_errors: consoleErrors,
      static_document_routes: 0, loopback_only: true};
    evidence.status = 'PASS_HEADLESS_NATIVE_CANVAS_TRANSPORT_QA_NOT_MANUAL_ACCEPTANCE';
  } catch (error) {
    diagnostics.push({kind: 'runner', name: error?.name ?? 'Error', message: String(error?.message ?? error).slice(0, 1000)});
    evidence.diagnostics = diagnostics.slice(0, 10);
    evidence.network_observed_before_failure = {external_requests_blocked: deniedRequests, page_errors: pageErrors,
      console_errors: consoleErrors};
    Object.assign(evidence, failureRecord(phase));
  } finally {
    clearTimeout(watchdog);
    let cleanup = true;
    for (const action of [...extraPages.map(item => () => item.isClosed() ? undefined : item.close()),
      () => page?.close(), () => mobileContext?.close(), () => context?.close(), () => browser?.close(), () => server?.close()]) {
      try { await action(); } catch { cleanup = false; }
    }
    evidence.cleanup = cleanup;
    if (!cleanup) Object.assign(evidence, failureRecord('cleanup'));
    if (outputReady) await writeFile(resolve(config.out, 'browser-qa.json'), JSON.stringify(evidence, null, 2) + '\n', {flag: 'wx'});
  }
  return evidence;
}

async function main() {
  let result;
  try { result = await run(parseArgs(process.argv.slice(2))); }
  catch { result = failureRecord('configuration'); }
  console.log(JSON.stringify({status: result.status, failed_stage: result.failed_stage,
    completed_cases: result.cases?.length ?? 0, manual_browser_observation: false, gotrue_or_database_proof: false}));
  return result.status === 'PASS_HEADLESS_NATIVE_CANVAS_TRANSPORT_QA_NOT_MANUAL_ACCEPTANCE' ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
