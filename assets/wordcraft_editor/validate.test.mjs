import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm, rmdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {ModelRejected, readInput, verifyBundle, exportCheckpoint, importDocx, applyPatch, parsePatchInput,
  maxPatchInputBytes} from './validate.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const patchSource = Buffer.from('synthetic private model bytes');
const patchPlan = () => ({schema:'gc-wordcraft-native-patch/v1', source_hash:hash(patchSource),
  source_revision:1, operations:[{op:'replace_text', story:'body', path:[0], start_byte:0,
    end_byte:6, old_text:'ação', new_text:'órgão'}]});
const patchEnvelope = () => ({schema:'gc-wordcraft-native-patch-ipc/v1', revision:1,
  checkpoint_base64:patchSource.toString('base64'), plan:patchPlan()});

async function withSyntheticEngine(code, callback) {
  const root = await mkdtemp(join(tmpdir(), 'govconnect-import-contract-'));
  try {
    const js = Buffer.from('export default async function() {}\n' + code);
    const wasm = Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]);
    await writeFile(join(root, 'engine.js'), js);
    await writeFile(join(root, 'engine.wasm'), wasm);
    const raw = JSON.stringify({status: 'INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED',
      upstream_commit: 'a'.repeat(40), govconnect_commit: 'b'.repeat(40), files: [
        {path: 'engine.js', bytes: js.length, sha256: hash(js)},
        {path: 'engine.wasm', bytes: wasm.length, sha256: hash(wasm)}]});
    await writeFile(join(root, 'qa-manifest.json'), raw);
    await callback(root, hash(raw));
  } finally {
    for (const name of ['engine.js', 'engine.wasm', 'qa-manifest.json']) await rm(join(root, name), {force:true});
    await rmdir(root);
  }
}

test('import requires DOCX bytes before an engine can be loaded', async () => {
  for (const input of [new Uint8Array(), Buffer.from('text'), Buffer.from('%PDF-'), 'filename.docx']) {
    await assert.rejects(importDocx(input, '/nonexistent', 'a'.repeat(64)), ModelRejected);
  }
  const excessive = Buffer.alloc(8 * 1024 * 1024 + 1);
  excessive.set([80, 75, 3, 4]);
  await assert.rejects(importDocx(excessive, '/nonexistent', 'a'.repeat(64)), ModelRejected);
});

test('import returns bytes only after the same native model validator accepts them', async () => {
  const code = `
    export function import_docx(input) {
      if (input.length !== 5 || input[4] !== 7) throw 'unexpected document';
      return new Uint8Array([123, 125]);
    }
    export function validate_checkpoint(input) {
      if (input.length !== 2 || input[0] !== 123 || input[1] !== 125) throw 'invalid snapshot';
    }`;
  await withSyntheticEngine(code, async (root, pin) => {
    const result = await importDocx(new Uint8Array([80, 75, 3, 4, 7]), root, pin);
    assert.deepEqual(result, Buffer.from('{}'));
    await assert.rejects(importDocx(new Uint8Array([80, 75, 3, 4, 8]), root, pin), ModelRejected);
  });
});

test('import rejects missing APIs, invalid results and failed native reopens', async () => {
  for (const code of [
    'export function validate_checkpoint() {}',
    'export function validate_checkpoint() {} export function import_docx() {return "{}";}',
    'export function validate_checkpoint() {} export function import_docx() {return new Uint8Array();}',
    'export function validate_checkpoint() {} export function import_docx() {return new Uint8Array(8*1024*1024+1);}',
    'export function validate_checkpoint() {throw "invalid model";} export function import_docx() {return new Uint8Array([1]);}',
    'export function validate_checkpoint() {return true;} export function import_docx() {return new Uint8Array([1]);}',
    'export function validate_checkpoint() {} export function import_docx() {throw new Error("engine failed");}',
  ]) {
    await withSyntheticEngine(code, async (root, pin) => {
      await assert.rejects(importDocx(new Uint8Array([80, 75, 3, 4]), root, pin),
        error => error instanceof Error && !(error instanceof ModelRejected));
    });
  }
});

test('patch stdin is a closed bounded canonical envelope with strict base64 and no duplicate keys', () => {
  const envelope = patchEnvelope();
  const bytes = Buffer.from(JSON.stringify(envelope));
  const parsed = parsePatchInput(bytes);
  assert.deepEqual(parsed.content, patchSource);
  assert.equal(parsed.revision, 1);
  assert.deepEqual(parsed.plan, patchPlan());
  for (const input of [
    Buffer.from(JSON.stringify({...envelope, tenant_id:'untrusted'})),
    Buffer.from(JSON.stringify({...envelope, checkpoint_base64:envelope.checkpoint_base64 + '===='})),
    Buffer.from(JSON.stringify({...envelope, checkpoint_base64:envelope.checkpoint_base64.replace(/.$/, '!')})),
    Buffer.from(JSON.stringify({...envelope, revision:true})),
    Buffer.from(JSON.stringify({...envelope, plan:{...envelope.plan, source_hash:'0'.repeat(64)}})),
    Buffer.from(JSON.stringify(envelope).slice(0,-1) + ',"revision":1}'),
    Buffer.from(JSON.stringify(envelope).replace('"source_revision":1', '"source_revision":1,"source_revision":1')),
    Buffer.from(JSON.stringify(envelope).replace('"revision":1', '"revision":1.0')),
    Buffer.from(' ' + JSON.stringify(envelope)), Buffer.from([0xff]),
    Buffer.alloc(maxPatchInputBytes + 1),
  ]) {
    assert.throws(() => parsePatchInput(input), ModelRejected);
  }
});

test('patch rejects scope, malformed ranges and unapproved operations before loading an engine', async () => {
  const variants = [];
  variants.push({...patchPlan(), operations:[{...patchPlan().operations[0], command:'file.open'}]});
  variants.push({...patchPlan(), operations:[{...patchPlan().operations[0], op:'file.open'}]});
  variants.push({...patchPlan(), operations:[{...patchPlan().operations[0], story:{part:true}}]});
  variants.push({...patchPlan(), operations:[{...patchPlan().operations[0], path:[0,0]}]});
  variants.push({...patchPlan(), operations:[{...patchPlan().operations[0], end_byte:4}]});
  variants.push({...patchPlan(), operations:[{...patchPlan().operations[0], new_text:'x'.repeat(100*1024+1)}]});
  variants.push({...patchPlan(), operations:[{...patchPlan().operations[0], new_text:'\ud800'}]});
  variants.push({...patchPlan(), operations:Array(33).fill(patchPlan().operations[0])});
  for (const plan of variants) {
    await assert.rejects(applyPatch(patchSource, '/nonexistent', 'a'.repeat(64), 1, plan), ModelRejected);
  }
});

test('patch results stay binary and must reopen through the same engine validator', async () => {
  const code = `
    export function apply_patch(bytes, revision, encoded) {
      const plan=JSON.parse(encoded);
      if (revision !== 1 || plan.schema !== 'gc-wordcraft-native-patch/v1'
          || plan.operations[0].new_text !== 'órgão') throw 'native patch refused';
      return new Uint8Array([123,125]);
    }
    export function validate_checkpoint(bytes) {
      if (bytes.length!==2 || bytes[0]!==123 || bytes[1]!==125) throw 'invalid result';
    }`;
  await withSyntheticEngine(code, async (root, pin) => {
    assert.deepEqual(await applyPatch(patchSource, root, pin, 1, patchPlan()), Buffer.from('{}'));
    const bad = patchPlan(); bad.operations[0].new_text = 'native rejection sentinel';
    await assert.rejects(applyPatch(patchSource, root, pin, 1, bad), ModelRejected);
  });
});

test('old bundles or ambiguous patch results never produce success', async () => {
  for (const code of [
    'export function validate_checkpoint() {}',
    'export function validate_checkpoint() {} export function apply_patch() {return "{}";}',
    'export function validate_checkpoint() {} export function apply_patch() {return new Uint8Array();}',
    'export function validate_checkpoint() {} export function apply_patch() {return new Uint8Array(8*1024*1024+1);}',
    'export function validate_checkpoint() {throw "invalid";} export function apply_patch() {return new Uint8Array([1]);}',
    'export function validate_checkpoint() {return true;} export function apply_patch() {return new Uint8Array([1]);}',
    'export function validate_checkpoint() {} export function apply_patch() {throw new Error("engine failure");}',
  ]) {
    await withSyntheticEngine(code, async (root, pin) => {
      await assert.rejects(applyPatch(patchSource, root, pin, 1, patchPlan()),
        error => error instanceof Error && !(error instanceof ModelRejected));
    });
  }
});

test('larger stdin allowance exists only for the bounded private patch envelope', async () => {
  const data = Buffer.alloc(8*1024*1024+1, 32);
  async function* input() {yield data;}
  await assert.rejects(readInput(input()), ModelRejected);
  assert.equal((await readInput(input(), maxPatchInputBytes)).length, data.length);
  async function* excessive() {yield Buffer.alloc(maxPatchInputBytes+1);}
  await assert.rejects(readInput(excessive(), maxPatchInputBytes), ModelRejected);
});

test('unapproved export formats never load or execute an engine', async () => {
  for (const format of ['html', '../file', '', 'DOCX']) {
    await assert.rejects(exportCheckpoint(new Uint8Array([1]), '/nonexistent', 'a'.repeat(64), format), ModelRejected);
  }
});

test('worker input has a byte bound and never treats empty input as valid', async () => {
  async function* empty() {}
  async function* bytes() { yield Buffer.from('synthetic'); yield Buffer.from(' bytes'); }
  async function* tooLarge() { yield Buffer.alloc(8 * 1024 * 1024 + 1); }
  assert.equal((await readInput(bytes())).toString(), 'synthetic bytes');
  await assert.rejects(readInput(empty()), ModelRejected);
  await assert.rejects(readInput(tooLarge()), ModelRejected);
});

test('pinned worker bundle rejects changed assets before module execution', async () => {
  const root = await mkdtemp(join(tmpdir(), 'govconnect-validator-'));
  try {
    const js = Buffer.from('export default async function() {}');
    const wasm = Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]);
    await writeFile(join(root, 'engine.js'), js);
    await writeFile(join(root, 'engine.wasm'), wasm);
    const raw = JSON.stringify({status: 'INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED',
      upstream_commit: 'a'.repeat(40), govconnect_commit: 'b'.repeat(40), files: [
        {path: 'engine.js', bytes: js.length, sha256: hash(js)},
        {path: 'engine.wasm', bytes: wasm.length, sha256: hash(wasm)}]});
    await writeFile(join(root, 'qa-manifest.json'), raw);
    const result = await verifyBundle(root, hash(raw));
    assert.equal(result.modulePath, join(root, 'engine.js'));
    assert.deepEqual(result.wasmBytes, wasm);
    await assert.rejects(verifyBundle(root, '0'.repeat(64)), /Manifest hash differs/);
    await writeFile(join(root, 'engine.js'), 'changed untrusted code');
    await assert.rejects(verifyBundle(root, hash(raw)), /asset (size|hash) differs/);
  } finally {
    // Remove only the three files this test created; preserve any unexpected file.
    for (const name of ['engine.js', 'engine.wasm', 'qa-manifest.json']) await rm(join(root, name), {force: true});
    await rmdir(root);
  }
});
