// Server-side worker. It never instantiates the canvas/WordApp or returns document text.
import {readFile, realpath, stat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {isAbsolute, relative, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {maxBytes} from './host.mjs';

export class ModelRejected extends Error {}
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const hashPattern = /^[0-9a-f]{64}$/;
export const maxExportBytes = 64 * 1024 * 1024;
export const maxPatchPlanBytes = 1024 * 1024;
export const maxPatchInputBytes = 4 * Math.ceil(maxBytes / 3) + maxPatchPlanBytes + 1024;
const maxPatchTextBytes = 100 * 1024;
const patchSchema = 'gc-wordcraft-native-patch/v1';
const patchIpcSchema = 'gc-wordcraft-native-patch-ipc/v1';

export async function readInput(stream, bound = maxBytes) {
  if (!Number.isSafeInteger(bound) || bound < 1 || bound > maxPatchInputBytes) throw new Error('Invalid private input bound.');
  const chunks = [];
  let size = 0;
  for await (const chunk of stream) {
    size += chunk.length;
    if (size > bound) throw new ModelRejected('Input exceeds its byte bound.');
    chunks.push(chunk);
  }
  if (!size) throw new ModelRejected('Empty checkpoint.');
  return Buffer.concat(chunks);
}

function closedObject(value, keys) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}

function patchPlanJson(content, revision, plan) {
  if (!(content instanceof Uint8Array) || !content.length || content.length > maxBytes
      || !Number.isInteger(revision) || revision < 1 || revision > 0xffffffff
      || !closedObject(plan, ['schema', 'source_hash', 'source_revision', 'operations'])
      || plan.schema !== patchSchema || plan.source_revision !== revision
      || typeof plan.source_hash !== 'string' || plan.source_hash !== digest(content)
      || !Array.isArray(plan.operations) || plan.operations.length < 1 || plan.operations.length > 32) {
    throw new ModelRejected('Invalid private patch contract.');
  }
  let newBytes = 0;
  for (const operation of plan.operations) {
    if (!closedObject(operation, ['op', 'story', 'path', 'start_byte', 'end_byte', 'old_text', 'new_text'])
        || operation.op !== 'replace_text'
        || (operation.story !== 'body' && !(closedObject(operation.story, ['part'])
          && Number.isInteger(operation.story.part) && operation.story.part >= 0 && operation.story.part <= 0xffffffff))
        || !Array.isArray(operation.path) || operation.path.length < 1 || operation.path.length > 97 || operation.path.length % 3 !== 1
        || operation.path.some(index => !Number.isInteger(index) || index < 0 || index > 0xffffffff)
        || !Number.isInteger(operation.start_byte) || !Number.isInteger(operation.end_byte)
        || operation.start_byte < 0 || operation.start_byte >= operation.end_byte || operation.end_byte > maxBytes
        || typeof operation.old_text !== 'string' || typeof operation.new_text !== 'string'
        || !operation.old_text.isWellFormed() || !operation.new_text.isWellFormed()
        || !operation.old_text.length || Buffer.byteLength(operation.old_text) > maxPatchTextBytes
        || operation.end_byte - operation.start_byte !== Buffer.byteLength(operation.old_text)) {
      throw new ModelRejected('Invalid private replacement contract.');
    }
    newBytes += Buffer.byteLength(operation.new_text);
    if (newBytes > maxPatchTextBytes) throw new ModelRejected('Replacement text exceeds its byte bound.');
  }
  const encoded = JSON.stringify(plan);
  if (Buffer.byteLength(encoded) > maxPatchPlanBytes) throw new ModelRejected('Patch plan exceeds its byte bound.');
  return encoded;
}

export function parsePatchInput(input) {
  try {
    if (!(input instanceof Uint8Array) || !input.length || input.length > maxPatchInputBytes) throw new Error();
    const text = new TextDecoder('utf-8', {fatal:true, ignoreBOM:true}).decode(input);
    const envelope = JSON.parse(text);
    // The Python transport emits compact JSON. Requiring its exact reserialization
    // rejects duplicate keys/ambiguous numbers before they can disappear in parse.
    if (JSON.stringify(envelope) !== text
        || !closedObject(envelope, ['schema', 'revision', 'checkpoint_base64', 'plan'])
        || envelope.schema !== patchIpcSchema || typeof envelope.checkpoint_base64 !== 'string'
        || envelope.checkpoint_base64.length > 4 * Math.ceil(maxBytes / 3)
        || envelope.checkpoint_base64.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(envelope.checkpoint_base64)) {
      throw new Error();
    }
    const content = Buffer.from(envelope.checkpoint_base64, 'base64');
    if (content.toString('base64') !== envelope.checkpoint_base64) throw new Error();
    patchPlanJson(content, envelope.revision, envelope.plan);
    return {content, revision:envelope.revision, plan:envelope.plan};
  } catch {
    throw new ModelRejected('Invalid private patch input.');
  }
}

export async function verifyBundle(bundle, manifestHash) {
  if (!hashPattern.test(manifestHash)) throw new Error('Pinned manifest hash required.');
  const root = await realpath(bundle);
  const manifestPath = resolve(root, 'qa-manifest.json');
  if ((await stat(manifestPath)).size > 128 * 1024) throw new Error('Manifest exceeds its byte bound.');
  const raw = await readFile(manifestPath);
  if (digest(raw) !== manifestHash) throw new Error('Manifest hash differs.');
  const manifest = JSON.parse(raw);
  if (!['INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED', 'GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED'].includes(manifest.status)
      || !/^[0-9a-f]{40}$/.test(manifest.upstream_commit)
      || !/^[0-9a-f]{40}$/.test(manifest.govconnect_commit)
      || !Array.isArray(manifest.files) || manifest.files.length < 2 || manifest.files.length > 100) {
    throw new Error('Unexpected engine manifest.');
  }
  let total = 0;
  const files = new Map();
  for (const entry of manifest.files) {
    const name = entry.path;
    if (typeof name !== 'string' || !/^[a-zA-Z0-9._/-]+$/.test(name)
        || name.split('/').some(part => ['', '.', '..'].includes(part))
        || !/\.(js|wasm)$/.test(name) || files.has(name)
        || !Number.isSafeInteger(entry.bytes) || entry.bytes <= 0 || entry.bytes > 80 * 1024 * 1024
        || !hashPattern.test(entry.sha256)) throw new Error('Unexpected engine asset.');
    total += entry.bytes;
    if (total > 200 * 1024 * 1024) throw new Error('Engine assets exceed their byte bound.');
    const path = await realpath(resolve(root, name));
    const confined = relative(root, path);
    if (!confined || isAbsolute(confined) || confined === '..' || confined.startsWith('..' + sep)) {
      throw new Error('Engine asset escaped the bundle.');
    }
    if ((await stat(path)).size !== entry.bytes) throw new Error('Engine asset size differs.');
    const bytes = await readFile(path);
    if (digest(bytes) !== entry.sha256) throw new Error('Engine asset hash differs.');
    files.set(name, {path, bytes});
  }
  const modules = [...files.keys()].filter(name => !name.includes('/') && name.endsWith('.js'));
  const wasm = [...files.keys()].filter(name => !name.includes('/') && name.endsWith('.wasm'));
  if (modules.length !== 1 || wasm.length !== 1) throw new Error('Ambiguous engine entry points.');
  return {moduleBytes: files.get(modules[0]).bytes, wasmBytes: files.get(wasm[0]).bytes};
}

async function loadEngine(content, bundle, manifestHash) {
  if (!(content instanceof Uint8Array) || !content.length || content.length > maxBytes) {
    throw new ModelRejected('Invalid checkpoint byte bound.');
  }
  const {moduleBytes, wasmBytes} = await verifyBundle(bundle, manifestHash);
  // Production uses Debian's Node 18, which treats .js as CommonJS without a
  // package.json even though the browser bundle is an audited ES module. Load
  // the already hash-verified bytes through a data URL so both runtimes apply
  // the same ESM semantics without copying or mutating the pinned bundle.
  const engine = await import('data:text/javascript;base64,' + Buffer.from(moduleBytes).toString('base64'));
  if (typeof engine.default !== 'function' || typeof engine.validate_checkpoint !== 'function') {
    throw new Error('Required native validation API missing.');
  }
  await engine.default({module_or_path: wasmBytes});
  return engine;
}

export async function validate(content, bundle, manifestHash) {
  const engine = await loadEngine(content, bundle, manifestHash);
  let result;
  try { result = engine.validate_checkpoint(content); }
  catch (error) {
    if (typeof error === 'string') throw new ModelRejected('Native model rejected.');
    throw new Error('Native engine failed.');
  }
  if (result !== undefined) throw new Error('Unexpected native validation result.');
}

export async function exportCheckpoint(content, bundle, manifestHash, format) {
  if (!['docx', 'pdf'].includes(format)) throw new ModelRejected('Unsupported export format.');
  const engine = await loadEngine(content, bundle, manifestHash);
  if (typeof engine.export_checkpoint !== 'function') throw new Error('Native export API missing.');
  let result;
  try { result = engine.export_checkpoint(content, format); }
  catch (error) {
    if (typeof error === 'string') throw new ModelRejected('Native export rejected.');
    throw new Error('Native export failed.');
  }
  if (!(result instanceof Uint8Array) || !result.length || result.length > maxExportBytes) {
    throw new Error('Unexpected native export size.');
  }
  const bytes = Buffer.from(result);
  if (format === 'pdf' ? bytes.subarray(0, 5).toString() !== '%PDF-'
      : !bytes.subarray(0, 4).equals(Buffer.from([80, 75, 3, 4]))) {
    throw new Error('Unexpected native export format.');
  }
  return bytes;
}

// The Python admission boundary must run preflight_docx before starting this
// worker. This API never accepts a filename, path, URL or arbitrary format.
export async function importDocx(content, bundle, manifestHash) {
  if (!(content instanceof Uint8Array) || content.length < 4
      || !Buffer.from(content.subarray(0, 4)).equals(Buffer.from([80, 75, 3, 4]))) {
    throw new ModelRejected('DOCX ZIP signature required.');
  }
  const engine = await loadEngine(content, bundle, manifestHash);
  if (typeof engine.import_docx !== 'function') throw new Error('Native import API missing.');
  let result;
  try { result = engine.import_docx(content); }
  catch (error) {
    if (typeof error === 'string') throw new ModelRejected('Native import rejected.');
    throw new Error('Native import failed.');
  }
  if (!(result instanceof Uint8Array) || !result.length || result.length > maxBytes) {
    throw new Error('Unexpected native checkpoint size.');
  }
  // Reopen through the same model validator before trusting any returned bytes.
  try {
    if (engine.validate_checkpoint(result) !== undefined) throw new Error('Unexpected native validation result.');
  } catch { throw new Error('Imported native checkpoint failed validation.'); }
  return Buffer.from(result);
}

// Pure execution only; the authenticated backend owns policy/IDs/approval/CAS.
export async function applyPatch(content, bundle, manifestHash, revision, plan) {
  const encoded = patchPlanJson(content, revision, plan);
  const engine = await loadEngine(content, bundle, manifestHash);
  if (typeof engine.apply_patch !== 'function') throw new Error('Native patch API missing.');
  let result;
  try { result = engine.apply_patch(content, revision, encoded); }
  catch (error) {
    if (typeof error === 'string') throw new ModelRejected('Native patch rejected.');
    throw new Error('Native patch failed.');
  }
  if (!(result instanceof Uint8Array) || !result.length || result.length > maxBytes) {
    throw new Error('Unexpected patched checkpoint size.');
  }
  try {
    if (engine.validate_checkpoint(result) !== undefined) throw new Error('Unexpected native validation result.');
  } catch { throw new Error('Patched native checkpoint failed validation.'); }
  return Buffer.from(result);
}

async function main() {
  try {
    const args = process.argv.slice(2);
    if (![4, 5, 6].includes(args.length) || args[0] !== '--bundle' || args[2] !== '--manifest-sha256'
        || (args.length === 5 && args[4] !== '--apply-patch')
        || (args.length === 6 && !['--export-format', '--import-format'].includes(args[4]))
        || (args[4] === '--import-format' && args[5] !== 'docx')) {
      throw new Error('Explicit pinned bundle required.');
    }
    const content = await readInput(process.stdin, args[4] === '--apply-patch' ? maxPatchInputBytes : maxBytes);
    if (args[4] === '--apply-patch') {
      const {content:checkpoint, revision, plan} = parsePatchInput(content);
      process.stdout.write(await applyPatch(checkpoint, args[1], args[3], revision, plan));
    } else if (args[4] === '--import-format') {
      process.stdout.write(await importDocx(content, args[1], args[3]));
    } else if (args.length === 6) {
      process.stdout.write(await exportCheckpoint(content, args[1], args[3], args[5]));
    } else {
      await validate(content, args[1], args[3]);
      process.stdout.write('{"valid":true}\n');
    }
  } catch (error) {
    // Never echo the document or native exception text to logs/IPC.
    const rejected = error instanceof ModelRejected;
    process.stdout.write(JSON.stringify({valid: false, code: rejected ? 'MODEL_REJECTED' : 'ENGINE_UNAVAILABLE'}) + '\n');
    process.exitCode = rejected ? 2 : 3;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
