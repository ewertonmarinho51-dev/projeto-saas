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
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

async function setup({awaitFrame} = {}) {
  const data = {instance_id: crypto.randomUUID(), session_id: crypto.randomUUID(), document_id: crypto.randomUUID(),
    nonce: 'n'.repeat(64), revision: 0, content_hash: await sha256(bytes)};
  const sent = [];
  const native = {gen: 1, unsaved: false, disposed: false, pending: null, locked: false, ready: false, bytes,
    frames: 0, serializations: 0, queuedText: '', composing: false, heldInput: false,
    generation() { return String(this.gen); },
    dirty() { return this.unsaved; },
    edit() { if (this.locked) throw new Error('locked'); this.gen++; this.unsaved = true; },
    serialize() {
      assert.ok(!this.locked || this.ready, 'a lock request is not an input barrier');
      this.serializations++; this.onSerialize?.(); return this.bytes;
    },
    set_interaction_locked(locked) { this.locked = locked; this.ready = false; },
    interaction_lock_ready() { return this.ready; },
    frame() {
      // Explicit transport stub: advance captured input through a modeled UI
      // boundary. This does not execute egui or prove real keyboard/IME behavior.
      this.frames++;
      if (this.queuedText) {
        this.bytes = new TextEncoder().encode(new TextDecoder().decode(this.bytes) + this.queuedText);
        this.queuedText = ''; this.gen++; this.unsaved = true;
      }
      this.ready = this.locked && !this.composing && !this.heldInput;
    },
    checkpoint(id) { if (!this.pending) this.pending = {id, gen: this.gen}; assert.equal(id, this.pending.id); return this.bytes; },
    apply_text_patch(revision, plan) {
      assert.equal(revision, 0); assert.equal(typeof plan, 'string');
      if (!this.patchBytes) throw new Error('no authorized patch fixture');
      this.beforePatch = this.bytes; this.bytes = this.patchBytes; this.gen++; this.unsaved = true;
    },
    selection() { return JSON.stringify({positions: [0, 1], text: this.selectedText || ''}); },
    undo() { assert.ok(this.beforePatch); this.bytes = this.beforePatch; this.beforePatch = null; this.gen++; this.unsaved = false; },
    acknowledge_checkpoint(id) { assert.equal(id, this.pending.id); this.unsaved = this.gen !== this.pending.gen; this.pending = null; },
    dispose() { this.disposed = true; this.locked = false; this.ready = false; }};
  const controller = new EditorController(native, data, (key, value) => sent.push({key, ...value}),
    {awaitFrame: signal => awaitFrame ? awaitFrame(native, signal) : Promise.resolve(native.frame())});
  await controller.loaded(bytes);
  return {data, native, controller, sent};
}

test('authorized patch changes the live session and emits one correlated checkpoint', async () => {
  const {data, native, controller: c, sent} = await setup();
  native.patchBytes = new TextEncoder().encode('authorized native patch target');
  const targetHash = await sha256(native.patchBytes);
  const commandId = crypto.randomUUID();
  const command = {schema: 'gc-wordcraft-control/v1', action: 'patch', command_id: commandId,
    revision: c.revision, content_hash: c.currentHash, target_hash: targetHash,
    plan_json: JSON.stringify({schema: 'gc-wordcraft-native-patch/v1'})};
  await c.control(command);
  const cp = sent.at(-1);
  assert.equal(cp.event, 'document.checkpoint');
  assert.equal(cp.request_id, commandId);
  assert.equal(cp.payload.content_hash, targetHash);
  assert.deepEqual(fromBase64(cp.payload.content_base64), native.patchBytes);
  assert.equal(c.state, 'saving');
  await c.control(command);
  assert.equal(sent.filter(x => x.event === 'document.checkpoint').length, 1);
  c.receive(ack(data, cp));
  assert.equal(c.state, 'saved'); assert.equal(c.revision, 1);
});

test('selection is read from the live native session and bound to the clean revision', async () => {
  const {native, controller: c, sent} = await setup();
  native.selectedText = 'trecho selecionado';
  const command = {schema: 'gc-wordcraft-control/v1', action: 'selection',
    command_id: crypto.randomUUID(), revision: c.revision, content_hash: c.currentHash};
  await c.control(command);
  assert.equal(sent.at(-1).event, 'document.selection');
  assert.deepEqual(sent.at(-1).payload, {command_id: command.command_id, text: native.selectedText});
  await c.control(command);
  assert.equal(sent.filter(x => x.event === 'document.selection').length, 1);
  native.edit(); c.changed();
  await assert.rejects(c.control({...command, command_id: crypto.randomUUID()}));
});

test('stale or divergent patch never receives a checkpoint', async () => {
  const {native, controller: c, sent} = await setup();
  native.patchBytes = new TextEncoder().encode('unexpected target');
  const base = {schema: 'gc-wordcraft-control/v1', action: 'patch', command_id: crypto.randomUUID(),
    revision: c.revision, content_hash: c.currentHash, target_hash: 'a'.repeat(64),
    plan_json: JSON.stringify({schema: 'gc-wordcraft-native-patch/v1'})};
  await assert.rejects(c.control({...base, revision: 1}));
  await c.control(base);
  assert.equal(c.state, 'ready');
  assert.deepEqual(native.bytes, bytes);
  assert.equal(sent.filter(x => x.event === 'document.checkpoint').length, 0);
  assert.equal(sent.at(-1).event, 'document.control_failed');
  assert.equal(sent.at(-1).payload.reason, 'target_mismatch');
});

test('native patch refusal preserves the exact clean canvas and reports a closed reason', async () => {
  const {controller: c, native, sent} = await setup();
  const command = {schema: 'gc-wordcraft-control/v1', action: 'patch', command_id: crypto.randomUUID(),
    revision: c.revision, content_hash: c.currentHash, target_hash: 'a'.repeat(64), plan_json: '{}'};
  await c.control(command);
  assert.equal(c.state, 'ready'); assert.deepEqual(native.bytes, bytes);
  assert.equal(sent.at(-1).event, 'document.control_failed');
  assert.equal(sent.at(-1).payload.reason, 'patch_refused');
});
function ack(data, cp, revision = 1) {
  return {...data, revision, ack: {request_id: cp.request_id, content_hash: cp.payload.content_hash, revision}};
}

function freeze(c, overrides = {}) {
  return {schema: 'gc-wordcraft-control/v1', action: 'freeze', command_id: crypto.randomUUID(),
    revision: c.revision, content_hash: c.currentHash, ...overrides};
}

test('freeze reserves a single native instance and releases only its exact command', async () => {
  const {native, controller: c, sent} = await setup();
  const command = freeze(c);
  const pending = c.control(command);
  assert.equal(native.locked, true);
  assert.throws(() => native.edit());
  await c.control(command); // Coalesced rerun while hashing must not run twice.
  await pending;
  assert.equal(c.state, 'frozen'); assert.equal(c.native, native);
  assert.deepEqual(sent.at(-1).payload, {command_id: command.command_id, content_hash: c.currentHash, generation: '1'});
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 1);
  await assert.rejects(c.control({...command, action: 'release', command_id: crypto.randomUUID()}));
  assert.equal(native.locked, true);
  await c.control({...command, action: 'release'});
  assert.equal(native.locked, false); assert.equal(c.state, 'ready');
  assert.equal(sent.at(-1).event, 'document.released');
  await c.control({...command, action: 'release'});
  assert.equal(sent.filter(x => x.event === 'document.released').length, 1);
  await c.control(command); // Delayed old freeze cannot relock the released canvas.
  assert.equal(native.locked, false);
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 1);
});

test('missed dirty polling refuses freeze and retains the exact ordinary checkpoint flow', async () => {
  const {data, native, controller: c, sent} = await setup();
  native.edit();
  await c.control(freeze(c));
  assert.equal(native.locked, false); assert.equal(c.state, 'dirty');
  assert.deepEqual(sent.slice(-2).map(x => x.event), ['document.changed', 'document.control_failed']);
  assert.equal(sent.at(-1).payload.reason, 'dirty');
  const cp = await c.checkpoint();
  c.receive(ack(data, cp));
  await c.control(freeze(c));
  assert.equal(c.state, 'frozen'); assert.equal(native.locked, true);
});

test('captured text drains before hashing and is saved through the ordinary checkpoint', async () => {
  const {data, native, controller: c, sent} = await setup();
  native.queuedText = ' queued synthetic input';
  const pending = c.control(freeze(c));
  assert.equal(native.locked, true); assert.equal(native.serializations, 0);
  assert.throws(() => native.edit()); // External APIs close from the request onward.
  await pending;
  assert.equal(c.native, native); assert.equal(native.locked, false); assert.equal(c.state, 'dirty');
  assert.equal(native.serializations, 0);
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 0);
  assert.deepEqual(sent.slice(-2).map(x => x.event), ['document.changed', 'document.control_failed']);
  assert.equal(sent.at(-1).payload.reason, 'dirty');
  const preserved = native.bytes.slice();
  const cp = await c.checkpoint();
  assert.deepEqual(fromBase64(cp.payload.content_base64), preserved);
  assert.ok(new TextDecoder().decode(preserved).endsWith(' queued synthetic input'));
  c.receive(ack(data, cp));
  await c.control(freeze(c));
  assert.equal(c.state, 'frozen'); assert.equal(c.native, native);
  assert.deepEqual(native.bytes, preserved);
});

test('a requested lock cannot serialize before an explicit completed native frame', async () => {
  const frame = deferred();
  const {native, controller: c, sent} = await setup({awaitFrame: async n => { await frame.promise; n.frame(); }});
  const pending = c.control(freeze(c));
  assert.equal(native.ready, false); assert.equal(native.serializations, 0);
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 0);
  frame.resolve(); await pending;
  assert.equal(native.frames, 1); assert.equal(native.serializations, 1); assert.equal(c.state, 'frozen');
});

test('IME preedit keeps draining until its commit can be preserved as dirty input', async () => {
  const {native, controller: c, sent} = await setup({awaitFrame: async n => {
    if (n.frames === 1) { n.composing = false; n.queuedText = ' composição sintética'; }
    n.frame();
  }});
  native.composing = true;
  await c.control(freeze(c));
  assert.equal(native.frames, 2); assert.equal(native.locked, false); assert.equal(c.state, 'dirty');
  assert.ok(new TextDecoder().decode(native.bytes).endsWith(' composição sintética'));
  assert.equal(native.serializations, 0); assert.equal(sent.at(-1).payload.reason, 'dirty');
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 0);
});

test('an active key or pointer gesture cannot satisfy the barrier before release', async () => {
  const {native, controller: c} = await setup({awaitFrame: async n => {
    if (n.frames === 1) n.heldInput = false;
    n.frame();
  }});
  native.heldInput = true;
  await c.control(freeze(c));
  assert.equal(native.frames, 2); assert.equal(c.state, 'frozen'); assert.equal(native.serializations, 1);
});

test('uninitialized native input and invalid readiness types never produce a proof', async () => {
  for (const cause of ['initializing', 'type']) {
    const {native, controller: c, sent} = await setup();
    if (cause === 'initializing') native.set_interaction_locked = () => { throw new Error('fonts are initializing'); };
    else native.interaction_lock_ready = () => 'true';
    await c.control(freeze(c));
    assert.equal(native.locked, false); assert.equal(c.state, 'ready'); assert.equal(native.serializations, 0);
    assert.equal(sent.at(-1).payload.reason, 'unavailable');
  }
});

test('frame readiness has a bounded attempt budget and returns the clean draft safely', async () => {
  const {native, controller: c, sent} = await setup();
  native.interaction_lock_ready = () => false;
  await c.control(freeze(c));
  assert.equal(native.frames, 120); assert.equal(native.serializations, 0); assert.equal(native.locked, false);
  assert.equal(c.state, 'ready'); assert.deepEqual(native.bytes, bytes);
  assert.equal(sent.at(-1).payload.reason, 'unavailable');
});

test('a frame callback that never resolves cannot defeat the real watchdog', {timeout: 5000}, async () => {
  const {native, controller: c, sent} = await setup({awaitFrame: () => new Promise(() => {})});
  await c.control(freeze(c));
  assert.equal(native.frames, 0); assert.equal(native.serializations, 0); assert.equal(native.locked, false);
  assert.equal(c.state, 'ready'); assert.equal(sent.at(-1).payload.reason, 'unavailable');
});

test('conflict, revision/hash change, early release and dispose cancel a pending frame barrier', async () => {
  for (const cause of ['conflict', 'revision', 'hash', 'release', 'dispose']) {
    const frame = deferred();
    const {data, native, controller: c, sent} = await setup({awaitFrame: async n => {
      await frame.promise; if (!n.disposed) n.frame();
    }});
    const command = freeze(c); const original = native.bytes.slice();
    const pending = c.control(command);
    if (cause === 'conflict') c.receive({...data, revision: data.revision + 1});
    else if (cause === 'revision') c.revision++;
    else if (cause === 'hash') c.currentHash = '0'.repeat(64);
    else if (cause === 'dispose') c.dispose();
    else await c.control({...command, action: 'release'}).catch(() => { c.state = 'conflict'; }); // applyControl wrapper.
    frame.resolve(); await pending;
    assert.equal(native.locked, false); assert.equal(native.serializations, 0);
    assert.deepEqual(native.bytes, original);
    assert.equal(sent.filter(x => x.event === 'document.frozen').length, 0);
    if (cause === 'dispose') assert.deepEqual(sent.map(x => x.event), ['document.loaded']);
    else assert.equal(sent.at(-1).payload.reason, 'stale');
    if (cause === 'conflict' || cause === 'release') assert.equal(c.state, 'conflict');
  }
});

test('dispose during hashing never emits a late proof or touches the destroyed instance', async () => {
  const {native, controller: c, sent} = await setup();
  const serialized = deferred(); native.onSerialize = serialized.resolve;
  const pending = c.control(freeze(c));
  await serialized.promise; c.dispose(); await pending;
  assert.equal(native.disposed, true); assert.equal(native.locked, false);
  assert.deepEqual(sent.map(x => x.event), ['document.loaded']);
});

test('a readiness change during hashing invalidates the proof', async () => {
  const {native, controller: c, sent} = await setup();
  const serialized = deferred(); native.onSerialize = serialized.resolve;
  const pending = c.control(freeze(c));
  await serialized.promise; native.ready = false; await pending;
  assert.equal(native.locked, false); assert.equal(c.state, 'conflict');
  assert.equal(sent.at(-1).payload.reason, 'stale');
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 0);
});

test('a frozen event already placed in transport retains the lock if delivery throws', async () => {
  const {native, controller: c, sent} = await setup();
  const send = c.send;
  c.send = (key, event) => { send(key, event); if (event.event === 'document.frozen') throw new Error('transport unavailable'); };
  await c.control(freeze(c));
  assert.equal(c.state, 'conflict'); assert.equal(native.locked, true);
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 1);
  assert.equal(sent.filter(x => x.event === 'document.control_failed').length, 0);
  assert.throws(() => native.edit());
  c.dispose(); assert.equal(native.locked, false);
});

test('a pending checkpoint never becomes a frozen or saved proof', async () => {
  const {native, controller: c, sent} = await setup();
  native.edit(); c.changed(); const cp = await c.checkpoint();
  await c.control(freeze(c));
  assert.equal(c.state, 'saving'); assert.equal(c.pending.request_id, cp.request_id);
  assert.equal(sent.at(-1).payload.reason, 'pending'); assert.equal(native.locked, false);
});

test('freeze binds the newest persisted hash after a real-content ACK', async () => {
  const {data, native, controller: c, sent} = await setup();
  native.bytes = new TextEncoder().encode('a changed synthetic native stub'); native.edit(); c.changed();
  const cp = await c.checkpoint(); c.receive(ack(data, cp));
  assert.notEqual(c.currentHash, c.initialHash);
  await c.control(freeze(c));
  assert.equal(c.state, 'frozen'); assert.equal(sent.at(-1).payload.content_hash, cp.payload.content_hash);
});

test('changed generation during digest fails closed and releases the draft', async () => {
  const {native, controller: c, sent} = await setup();
  const serialized = deferred(); native.onSerialize = serialized.resolve;
  const pending = c.control(freeze(c));
  await serialized.promise;
  native.gen++; native.unsaved = true; // Simulate an unexpected native mutation despite the input lock.
  await pending;
  assert.equal(native.locked, false); assert.equal(c.state, 'conflict');
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 0);
  assert.equal(sent.at(-1).payload.reason, 'stale');
});

test('a conflict during asynchronous hashing cannot resurrect a frozen proof', async () => {
  const {data, native, controller: c, sent} = await setup();
  const command = freeze(c);
  const serialized = deferred(); native.onSerialize = serialized.resolve;
  const pending = c.control(command);
  await serialized.promise;
  c.receive({...data, revision: data.revision + 1});
  assert.equal(c.state, 'conflict');
  await pending;
  assert.equal(c.state, 'conflict'); assert.equal(native.locked, false);
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 0);
});

test('a second control cannot replace a freeze while its digest is pending', async () => {
  const {native, controller: c, sent} = await setup();
  const pending = c.control(freeze(c));
  await assert.rejects(c.control(freeze(c)));
  await pending;
  assert.equal(c.state, 'frozen'); assert.equal(native.locked, true);
  assert.equal(sent.filter(x => x.event === 'document.frozen').length, 1);
});

test('older native bundles and serialization failures cannot freeze a canvas', async () => {
  for (const cause of ['missing', 'readiness', 'serialize']) {
    const {native, controller: c, sent} = await setup();
    if (cause === 'missing') native.set_interaction_locked = undefined;
    else if (cause === 'readiness') native.interaction_lock_ready = undefined;
    else native.serialize = () => { throw new Error('native failure'); };
    await c.control(freeze(c));
    assert.equal(native.locked, false); assert.equal(c.state, 'ready');
    assert.equal(sent.at(-1).payload.reason, 'unavailable');
  }
});

test('stale and malformed commands never change native content', async () => {
  const {native, controller: c, sent} = await setup();
  await c.control(freeze(c, {revision: c.revision + 1}));
  assert.equal(sent.at(-1).payload.reason, 'stale'); assert.equal(native.locked, false);
  for (const invalid of [true, [], {...freeze(c), approved: true}, freeze(c, {action: 'run'}),
      freeze(c, {command_id: [crypto.randomUUID()]}), freeze(c, {content_hash: [c.currentHash]})]) {
    await assert.rejects(c.control(invalid));
    assert.equal(native.locked, false);
  }
});

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
