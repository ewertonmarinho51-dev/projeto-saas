// GovConnect transport host. Persistence, ACL, CAS and approval belong to the backend.
export const protocol = 'gc-wordcraft/v1';
export const checkpointSchema = 'gc-wordcraft-snapshot/v1';
export const maxBytes = 8 * 1024 * 1024;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const hashPattern = /^[0-9a-f]{64}$/;

export async function sha256(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}

export function toBase64(bytes) {
  let text = '';
  for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(text);
}

export function fromBase64(text) {
  if (typeof text !== 'string' || text.length > 4 * Math.ceil(maxBytes / 3)) throw new Error('Checkpoint excessivo.');
  const raw = atob(text);
  if (!raw.length || raw.length > maxBytes) throw new Error('Checkpoint vazio ou excessivo.');
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}

export function assetURL(value, base) {
  const url = new URL(value, base);
  const expected = new URL(base);
  if (url.origin !== expected.origin || url.username || url.password || url.search || url.hash
      || !url.pathname.startsWith('/app/static/wordcraft/') || !/\.(js|wasm)$/.test(url.pathname)) {
    throw new Error('Asset WordCraft fora da origem e do caminho autorizados.');
  }
  return url.href;
}

// State updates can be coalesced by Streamlit. Every update therefore carries
// all unconsumed events, rather than relying on callback delivery per emission.
export class EventOutbox {
  constructor(send) { this.send = send; this.events = []; this.consumed = 0; this.last = 0; this.buffered = 0; }
  push(key, event) {
    const size = JSON.stringify(event).length;
    if (key !== 'edit' || event.sequence !== this.last + 1 || this.events.length >= 256 || this.buffered + size > 2 * maxBytes) {
      throw new Error('Transporte precisa de reconciliação; nenhum evento foi descartado.');
    }
    this.events.push(event);
    this.buffered += size;
    this.last = event.sequence;
    this.flush();
  }
  flush() { if (this.events.length) this.send('edit', {events: this.events.slice()}); }
  acknowledge(sequence) {
    if (sequence === undefined) return;
    if (!Number.isSafeInteger(sequence) || sequence < this.consumed || sequence > this.last) {
      throw new Error('Confirmação de consumo inválida.');
    }
    this.consumed = sequence;
    this.events = this.events.filter(event => event.sequence > sequence);
    this.buffered = this.events.reduce((sum, event) => sum + JSON.stringify(event).length, 0);
    this.flush();
  }
}

export class EditorController {
  constructor(native, data, send) {
    for (const key of ['instance_id', 'session_id', 'document_id']) if (!uuidPattern.test(data[key])) throw new Error('Escopo inválido.');
    if (!Number.isSafeInteger(data.revision) || data.revision < 0 || !hashPattern.test(data.content_hash)
        || typeof data.nonce !== 'string' || !/^[a-zA-Z0-9_-]{32,128}$/.test(data.nonce)) throw new Error('Contrato de abertura inválido.');
    this.native = native;
    this.scope = Object.fromEntries(['instance_id', 'session_id', 'document_id', 'nonce'].map(k => [k, data[k]]));
    this.revision = data.revision;
    this.initialHash = data.content_hash;
    this.send = send;
    this.sequence = 0;
    this.state = 'opening';
    this.pending = null;
    this.lastAck = null;
    this.generation = null;
    this.disposed = false;
  }
  publish(event, payload) {
    if (this.disposed) throw new Error('Instância encerrada.');
    const message = {protocol, ...this.scope, request_id: crypto.randomUUID(),
      expected_revision: this.revision, sequence: ++this.sequence, event, payload};
    try { this.send('edit', message); }
    catch (error) { this.state = 'conflict'; throw error; }
    return message;
  }
  async loaded(bytes) {
    if (this.state !== 'opening' || await sha256(bytes) !== this.initialHash) throw new Error('Conteúdo carregado diverge da revisão autorizada.');
    this.generation = this.native.generation();
    this.state = 'ready';
    this.publish('document.loaded', {content_hash: this.initialHash});
  }
  changed() {
    if (!['ready', 'saved', 'dirty', 'saving', 'error'].includes(this.state)) return false;
    const generation = this.native.generation();
    if (generation === this.generation) return false;
    this.generation = generation;
    if (!this.pending) this.state = 'dirty';
    this.publish('document.changed', {});
    return true;
  }
  async checkpoint() {
    if (this.disposed || this.state !== 'dirty' || this.pending) return null;
    // Reserve before awaiting the digest; overlapping reruns/timers cannot create another request.
    const id = crypto.randomUUID();
    this.pending = {request_id: id, content_hash: null};
    this.state = 'saving';
    return this.prepareCheckpoint(id);
  }
  async prepareCheckpoint(id) {
    try {
      const bytes = this.native.checkpoint(id);
      const generation = this.native.generation();
      if (!bytes.length || bytes.length > maxBytes) throw new Error('Checkpoint inválido.');
      const digest = await sha256(bytes);
      if (this.disposed) return null;
      this.pending.content_hash = digest;
      const envelope = {protocol, ...this.scope, request_id: id, expected_revision: this.revision,
        sequence: ++this.sequence, event: 'document.checkpoint', payload: {
          schema_version: checkpointSchema, content_hash: digest, content_base64: toBase64(bytes)}};
      try { this.send('edit', envelope); }
      catch (error) { this.state = 'conflict'; throw error; }
      // Changes during hashing may have arrived before checkpoint on the backend.
      // Reassert dirty after it, so its ACK cannot conceal a newer native edit.
      if (this.native.generation() !== generation) this.publish('document.changed', {});
      return envelope;
    } catch (error) {
      // Native pending bytes remain available; do not pretend a save occurred.
      if (this.state !== 'conflict') this.state = 'error';
      throw error;
    }
  }
  receive(data) {
    if (this.disposed || this.state === 'conflict') return;
    for (const key of ['instance_id', 'session_id', 'document_id', 'nonce']) {
      if (data[key] !== this.scope[key]) { this.state = 'conflict'; return; }
    }
    const ack = data.ack;
    if (ack && ack.request_id !== this.lastAck) {
      if (!this.pending || ack.request_id !== this.pending.request_id || ack.content_hash !== this.pending.content_hash
          || ack.revision !== this.revision + 1 || !Number.isSafeInteger(ack.revision)) {
        this.state = 'conflict';
        return;
      }
      this.native.acknowledge_checkpoint(ack.request_id);
      this.lastAck = ack.request_id;
      this.revision = ack.revision;
      this.pending = null;
      this.state = this.native.dirty() ? 'dirty' : 'saved';
    }
    if (data.revision !== this.revision) this.state = 'conflict';
    if (data.save_error && this.pending && data.save_error.request_id === this.pending.request_id) {
      this.state = data.save_error.conflict ? 'conflict' : 'error';
    }
  }
  async retry() {
    if (this.state !== 'error' || !this.pending) throw new Error('Retry indisponível.');
    this.state = 'saving';
    if (!this.pending.content_hash) return this.prepareCheckpoint(this.pending.request_id);
    return this.publish('document.retry', {request_id: this.pending.request_id});
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.native.dispose();
  }
}

const labels = {opening: 'Abrindo documento…', ready: 'Documento aberto.', dirty: 'Alterações ainda não salvas.',
  saving: 'Salvando…', saved: 'Gravação confirmada pelo servidor.', error: 'Falha ao salvar. O rascunho permanece neste editor.',
  conflict: 'Conflito de revisão. Preserve o rascunho e solicite reconciliação.'};

export default function render(component) {
  const {data, parentElement, setStateValue} = component;
  const root = parentElement.querySelector('.gc-wordcraft-editor');
  if (!root) return;
  if (root.__instance) {
    const instance = root.__instance;
    if (['instance_id', 'session_id', 'document_id', 'nonce'].some(key => data[key] !== instance.data[key])) {
      instance.cleanup();
      root.textContent = 'O contexto mudou. Abra novamente o documento autorizado.';
      return;
    }
    instance.data = data;
    root.__instance.send = setStateValue;
    try { instance.outbox.acknowledge(data.event_ack); }
    catch { if (instance.controller) instance.controller.state = 'conflict'; }
    root.__instance.controller?.receive(data);
    instance.update?.();
    if (instance.controller?.state === 'dirty') instance.schedule?.();
    return;
  }
  const status = document.createElement('p'); status.setAttribute('role', 'status'); status.textContent = labels.opening;
  const canvas = document.createElement('canvas'); canvas.style.cssText = 'width:100%;height:720px;display:block';
  const retry = document.createElement('button'); retry.textContent = 'Tentar salvar novamente'; retry.disabled = true;
  root.append(status, canvas, retry);
  const instance = {data, send: setStateValue, controller: null, native: null, starting: false, timer: null, disposed: false}; root.__instance = instance;
  instance.outbox = new EventOutbox((...args) => instance.send(...args));
  const update = () => { if (instance.controller) { status.textContent = labels[instance.controller.state]; retry.disabled = instance.controller.state !== 'error'; } };
  const unload = event => { if (instance.controller && !['ready', 'saved'].includes(instance.controller.state)) { event.preventDefault(); event.returnValue = ''; } };
  window.addEventListener('beforeunload', unload);
  instance.update = update;
  instance.schedule = () => {
    clearTimeout(instance.timer);
    instance.timer = setTimeout(() => { instance.controller.checkpoint().then(update).catch(update); }, 800);
  };
  retry.onclick = async () => { try { await instance.controller.retry(); update(); } catch { status.textContent = labels.error; } };
  instance.cleanup = () => {
    instance.disposed = true;
    clearInterval(instance.interval); clearTimeout(instance.timer);
    window.removeEventListener('beforeunload', unload);
    if (!instance.starting) instance.native?.dispose();
    if (instance.controller) instance.controller.disposed = true;
    root.__instance = null;
  };
  (async () => {
    const bytes = fromBase64(data.checkpoint_base64);
    if (await sha256(bytes) !== data.content_hash) throw new Error('Hash de abertura divergente.');
    const module = await import(assetURL(data.module_url, window.location.href));
    await module.default({module_or_path: assetURL(data.wasm_url, window.location.href)});
    if (instance.disposed) return;
    const native = new module.GovConnectEditor();
    instance.native = native;
    instance.starting = true;
    try { await native.start(canvas, bytes, Boolean(data.webgl)); }
    finally { instance.starting = false; }
    if (instance.disposed) { native.dispose(); return; }
    const controller = new EditorController(native, data, (...args) => instance.outbox.push(...args));
    instance.controller = controller;
    await controller.loaded(bytes);
    controller.receive(instance.data);
    update();
    instance.interval = setInterval(() => {
      try {
        if (controller.changed()) {
          instance.schedule();
        }
        update();
      } catch { status.textContent = 'Editor indisponível. Preserve o rascunho antes de recarregar.'; }
    }, 250);
  })().catch(() => { instance.native?.dispose(); status.textContent = 'Não foi possível abrir o editor. Nenhuma gravação foi confirmada.'; });
  return instance.cleanup;
}
