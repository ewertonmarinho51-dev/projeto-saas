import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm, rmdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {ModelRejected, readInput, verifyBundle, exportCheckpoint, importDocx} from './validate.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');

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
