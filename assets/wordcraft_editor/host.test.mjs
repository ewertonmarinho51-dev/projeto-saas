import test from 'node:test';
import assert from 'node:assert/strict';
import {EditorController, EventOutbox, assetURL, fromBase64, toBase64, sha256} from './host.mjs';

const bytes = new TextEncoder().encode('synthetic transport fixture; not a native document corpus');

test('coalesced Streamlit state retains every event until backend consumption', () => {
  let latest;
  const outbox = new EventOutbox((key, value) => { latest = value; });
  outbox.push('edit', {sequence: 1, event: 'document.loaded'});
  outbox.push('edit', {sequence: 2, event: 'document.changed'});
  outbox.push('edit', {sequence: 3, event: 'document.checkpoint'});
  assert.deepEqual(latest.events.map(e => e.sequence), [1, 2, 3]);
  outbox.acknowledge(2);
  assert.deepEqual(latest.events.map(e => e.sequence), [3]);
  assert.throws(() => outbox.acknowledge(4));
  assert.throws(() => outbox.acknowledge(1));
  assert.deepEqual(outbox.events.map(e => e.sequence), [3]);
  outbox.acknowledge(3);
  assert.equal(outbox.events.length, 0);
  outbox.push('edit', {sequence: 4, event: 'document.changed'});
  assert.deepEqual(latest.events.map(e => e.sequence), [4]);
});

test('outbox applies backpressure without dropping unconsumed events', () => {
  const outbox = new EventOutbox(() => {});
  for (let sequence = 1; sequence <= 256; sequence++) outbox.push('edit', {sequence});
  assert.throws(() => outbox.push('edit', {sequence: 257}));
  assert.equal(outbox.events.length, 256);
  assert.equal(outbox.last, 256);
});
async function setup() {
  const data = {instance_id: crypto.randomUUID(), session_id: crypto.randomUUID(), document_id: crypto.randomUUID(),
    nonce: 'n'.repeat(64), revision: 0, content_hash: await sha256(bytes)};
  const sent = [];
  const native = {gen: 1, unsaved: false, disposed: false, pending: null,
    generation() { return String(this.gen); },
    dirty() { return this.unsaved; },
    edit() { this.gen++; this.unsaved = true; },
    checkpoint(id) { if (!this.pending) this.pending = {id, gen: this.gen}; assert.equal(id, this.pending.id); return bytes; },
    acknowledge_checkpoint(id) { assert.equal(id, this.pending.id); this.unsaved = this.gen !== this.pending.gen; this.pending = null; },
    dispose() { this.disposed = true; }};
  const controller = new EditorController(native, data, (key, value) => sent.push({key, ...value}));
  await controller.loaded(bytes);
  return {data, native, controller, sent};
}
function ack(data, cp, revision = 1) {
  return {...data, revision, ack: {request_id: cp.request_id, content_hash: cp.payload.content_hash, revision}};
}

test('opening, edit, checkpoint, backend ACK and duplicate ACK retain one native instance', async () => {
  const {data, native, controller: c, sent} = await setup();
  assert.equal(c.state, 'ready');
  native.edit(); assert.ok(c.changed());
  const cp = await c.checkpoint();
  assert.equal(c.state, 'saving'); assert.equal(c.revision, 0);
  assert.equal(fromBase64(cp.payload.content_base64).length, bytes.length);
  c.receive(ack(data, cp));
  assert.equal(c.native, native); assert.equal(c.state, 'saved'); assert.equal(c.revision, 1);
  c.receive(ack(data, cp)); assert.equal(c.state, 'saved');
  assert.deepEqual(sent.map(x => x.event), ['document.loaded', 'document.changed', 'document.checkpoint']);
});

test('overlapping save attempts produce only one checkpoint', async () => {
  const {native, controller: c, sent} = await setup();
  native.edit(); c.changed();
  const first = c.checkpoint();
  assert.equal(await c.checkpoint(), null);
  await first;
  assert.equal(sent.filter(x => x.event === 'document.checkpoint').length, 1);
});

test('new edits during digest remain dirty after persisted ACK', async () => {
  const {data, native, controller: c, sent} = await setup();
  native.edit(); c.changed();
  const task = c.checkpoint();
  native.edit(); c.changed();
  const cp = await task;
  assert.deepEqual(sent.slice(-2).map(x => x.event), ['document.checkpoint', 'document.changed']);
  c.receive(ack(data, cp));
  assert.equal(c.state, 'dirty');
  const next = await c.checkpoint();
  assert.equal(next.expected_revision, 1);
  assert.notEqual(next.request_id, cp.request_id);
});

test('backend timeout retry preserves the original operation identity', async () => {
  const {data, native, controller: c} = await setup();
  native.edit(); c.changed();
  const cp = await c.checkpoint();
  c.receive({...data, save_error: {request_id: cp.request_id, conflict: false}});
  assert.equal(c.state, 'error');
  native.edit(); c.changed();
  const retry = await c.retry();
  assert.equal(retry.event, 'document.retry');
  assert.equal(retry.payload.request_id, cp.request_id);
  assert.notEqual(retry.request_id, cp.request_id);
  c.receive(ack(data, cp));
  assert.equal(c.state, 'dirty');
});

test('divergent ACK and external revision cause conflict without native ACK or overwrite', async () => {
  for (const type of ['hash', 'revision', 'scope']) {
    const {data, native, controller: c} = await setup();
    native.edit(); c.changed(); const cp = await c.checkpoint();
    const response = ack(data, cp);
    if (type === 'hash') response.ack.content_hash = '0'.repeat(64);
    if (type === 'revision') { response.revision = 8; response.ack.revision = 8; }
    if (type === 'scope') response.session_id = crypto.randomUUID();
    c.receive(response);
    assert.equal(c.state, 'conflict'); assert.equal(c.revision, 0); assert.ok(native.pending);
    c.receive(ack(data, cp));
    assert.equal(c.state, 'conflict'); assert.ok(native.pending);
    assert.equal(await c.checkpoint(), null);
    await assert.rejects(c.retry());
  }
});

test('serialize failure can be retried without inventing a saved state', async () => {
  const {native, controller: c} = await setup();
  native.edit(); c.changed();
  const checkpoint = native.checkpoint.bind(native);
  native.checkpoint = () => { throw new Error('too large'); };
  await assert.rejects(c.checkpoint()); assert.equal(c.state, 'error');
  const id = c.pending.request_id;
  native.checkpoint = checkpoint;
  const retry = await c.retry();
  assert.equal(retry.event, 'document.checkpoint'); assert.equal(retry.request_id, id);
  assert.equal(c.state, 'saving');
});

test('only same-origin self-hosted JS/WASM assets are accepted', () => {
  const base = 'https://gov.example/app';
  assert.equal(assetURL('/app/static/wordcraft/pinned/editor.js', base), 'https://gov.example/app/static/wordcraft/pinned/editor.js');
  for (const value of ['https://outside.example/editor.js', 'data:text/javascript,x', '/other/editor.js',
    '/app/static/wordcraft/../private.js', '/app/static/wordcraft/x.js?token=sensitive', '/app/static/wordcraft/x.txt']) {
    assert.throws(() => assetURL(value, base));
  }
});

test('dispose stops emission and byte conversion preserves all values', async () => {
  const {native, controller: c} = await setup();
  const raw = Uint8Array.from({length: 100_000}, (_, i) => i % 256);
  assert.deepEqual(fromBase64(toBase64(raw)), raw);
  c.dispose(); c.dispose(); assert.ok(native.disposed);
  assert.throws(() => c.publish('document.changed', {}));
});
