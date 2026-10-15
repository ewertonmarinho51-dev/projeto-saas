import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm, rmdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {ModelRejected, readInput, verifyBundle, exportCheckpoint} from './validate.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');

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
