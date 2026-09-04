const VISUAL_STATES = Object.freeze([
  "IDLE",
  "HOVER",
  "LISTENING",
  "THINKING",
  "WORKING",
  "SUGGESTION",
  "APPLYING",
  "SUCCESS",
  "ATTENTION",
  "CELEBRATE",
  "ERROR",
]);

const EYE_STATES = Object.freeze([
  "normal",
  "blink",
  "left",
  "right",
  "up",
  "down",
  "happy",
  "thinking",
  "attention",
  "working",
  "success",
]);

const STATE_LABELS = Object.freeze({
  IDLE: "Pronto para ajudar",
  HOVER: "Atento ao seu processo",
  LISTENING: "Ouvindo sua solicitação",
  THINKING: "Analisando a solicitação",
  WORKING: "Consultando contexto e validações",
  SUGGESTION: "Sugestão pronta para revisão",
  APPLYING: "Validando e aplicando a alteração",
  SUCCESS: "Operação concluída",
  ATTENTION: "Há uma pendência que requer atenção",
  CELEBRATE: "Etapa concluída",
  ERROR: "Não foi possível concluir a operação",
});

const EYES_BY_STATE = Object.freeze({
  IDLE: ["normal", "normal"],
  HOVER: ["normal", "normal"],
  LISTENING: ["normal", "normal"],
  THINKING: ["thinking", "thinking"],
  WORKING: ["working", "working"],
  SUGGESTION: ["attention", "normal"],
  APPLYING: ["working", "working"],
  SUCCESS: ["success", "success"],
  ATTENTION: ["attention", "attention"],
  CELEBRATE: ["happy", "happy"],
  ERROR: ["attention", "attention"],
});

const FORM_FIELD_SELECTOR =
  '[class*="st-key-govbot_campo_"], [class*="st-key-editor_"]';
const KNOWN_FORM_FIELDS = Object.freeze([
  "orgao",
  "responsavel",
  "prazo",
  "modelo_execucao",
  "objeto",
  "justificativa",
  "memorando",
  "alinhamento",
  "requisitos",
  "riscos",
]);
const PROACTIVE_COOLDOWN_MS = 90000;
const OPEN_PREFERENCE_KEY = "govdocs.govbot.open";
const PROACTIVE_LAST_KEY = "govdocs.govbot.proactive.last";
const PROACTIVE_SEEN_KEY = "govdocs.govbot.proactive.seen";
const CLEANUP_SLOT = Symbol.for("govdocs.govbot.cleanup");

const LOCAL_GUIDANCE = Object.freeze({
  orgao: "Use a denominação oficial do órgão responsável pela demanda.",
  responsavel: "Identifique a unidade ou pessoa responsável conforme o processo.",
  prazo: "Informe apenas um prazo já decidido ou registrado no processo.",
  modelo_execucao: "Escolha o modelo que corresponda à decisão administrativa vigente.",
  objeto: "Descreva o que será contratado de forma objetiva, sem antecipar requisitos indevidos.",
  justificativa: "Explique a necessidade pública e o resultado esperado da contratação.",
  memorando: "Revise o texto importado antes de usá-lo como origem da demanda.",
  alinhamento: "Relacione a demanda ao planejamento institucional já aprovado.",
  requisitos: "Registre requisitos verificáveis e ligados à necessidade administrativa.",
  riscos: "Indique riscos concretos e medidas de tratamento proporcionais.",
  editor_dfd: "O DFD deve refletir os fatos confirmados no formulário.",
  editor_etp: "O ETP deve comparar alternativas sem inventar dados materiais.",
  editor_tr: "O TR deve manter coerência com o ETP aprovado.",
  editor_edital: "Corrija a origem do dado quando a minuta determinística apontar divergência.",
});

function plainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function textValue(value, fallback = "") {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function clearChildren(element) {
  while (element.firstChild) element.removeChild(element.firstChild);
}

function requestId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const randomPart = Math.random().toString(36).slice(2, 12);
  return `govbot-${Date.now().toString(36)}-${randomPart}`;
}

function storageGet(key) {
  try {
    return globalThis.sessionStorage.getItem(key);
  } catch (_error) {
    return null;
  }
}

function storageSet(key, value) {
  try {
    globalThis.sessionStorage.setItem(key, value);
  } catch (_error) {
    // A interface continua funcional quando o armazenamento da aba é bloqueado.
  }
}

function normalizedCanonicalKey(rawKey) {
  const raw = textValue(rawKey).trim();
  if (!raw || raw.startsWith("editor_itens_")) return null;
  if (raw.startsWith("govbot_campo_")) {
    const field = raw.slice("govbot_campo_".length);
    return /^[a-z][a-z0-9_]{0,63}$/.test(field) ? field : null;
  }
  if (/^editor_(dfd|etp|tr|edital)$/.test(raw)) return raw;
  return /^[a-z][a-z0-9_]{0,63}$/.test(raw) ? raw : null;
}

function wrapperKey(wrapper) {
  if (!wrapper || !wrapper.classList) return null;
  for (const className of wrapper.classList) {
    if (className.startsWith("st-key-govbot_campo_")) {
      return normalizedCanonicalKey(className.slice("st-key-".length));
    }
    if (className.startsWith("st-key-editor_")) {
      return normalizedCanonicalKey(className.slice("st-key-".length));
    }
  }
  return null;
}

function inputForWrapper(wrapper) {
  if (!wrapper) return null;
  return wrapper.querySelector(
    'textarea, select, input:not([type="hidden"]), [contenteditable="true"]'
  );
}

function inputText(input) {
  if (!input) return "";
  if (input instanceof HTMLInputElement && input.type === "checkbox") {
    return input.checked ? "true" : "false";
  }
  if ("value" in input) return textValue(input.value);
  return textValue(input.textContent);
}

function normalizedAllowedFields(data) {
  const supplied = Array.isArray(data.allowed_fields)
    ? data.allowed_fields
    : Array.isArray(data.recognized_fields)
      ? data.recognized_fields
      : [];
  const fields = new Set();
  for (const raw of supplied) {
    const key = normalizedCanonicalKey(raw);
    if (key && key !== "itens") fields.add(key);
  }
  return fields;
}

export default function renderGovBot(component) {
  const { data: incomingData, setTriggerValue, parentElement } = component;
  const data = plainObject(incomingData) ? incomingData : {};
  const root = parentElement.querySelector(".govbot-root");
  if (!root) return undefined;

  // Components v2 may invoke the renderer again when ``data`` changes while
  // preserving the same ShadowRoot. Remove the previous instance's global
  // listeners and timers before binding the new view-model.
  const previousCleanup = root[CLEANUP_SLOT];
  if (typeof previousCleanup === "function") previousCleanup();

  const panel = root.querySelector("#govbot-panel");
  const launcher = root.querySelector("#govbot-launcher");
  const scrim = root.querySelector("#govbot-scrim");
  const closeButton = root.querySelector("#govbot-close");
  const form = root.querySelector("#govbot-form");
  const composer = root.querySelector("#govbot-input");
  const sendButton = root.querySelector("#govbot-send");
  const undoButton = root.querySelector("#govbot-undo");
  const messagesElement = root.querySelector("#govbot-messages");
  const proposalsElement = root.querySelector("#govbot-proposals");
  const visibleStatus = root.querySelector("#govbot-visible-status");
  const stateAnnouncer = root.querySelector("#govbot-state-announcer");
  const alertAnnouncer = root.querySelector("#govbot-alert-announcer");
  const nudge = root.querySelector("#govbot-nudge");
  const mascotWrap = root.querySelector("#govbot-mascot-wrap");
  const mascot = root.querySelector("#govbot-mascot");
  const mascotDescription = root.querySelector("#govbot-mascot-description");

  if (
    !panel || !launcher || !scrim || !closeButton || !form || !composer ||
    !sendButton || !undoButton || !messagesElement || !proposalsElement ||
    !visibleStatus || !stateAnnouncer || !alertAnnouncer || !nudge ||
    !mascotWrap || !mascot
  ) {
    return undefined;
  }

  const allowedFields = normalizedAllowedFields(data);
  const reducedMotion = globalThis.matchMedia("(prefers-reduced-motion: reduce)");
  const compactLayout = globalThis.matchMedia("(max-width: 1024px)");
  let inViewport = true;
  const initialFocus = normalizedCanonicalKey(data.focus);
  let currentFocus = keyIsAllowed(initialFocus) ? initialFocus : null;
  let isOpen = false;
  let eventPending = false;
  let blinkTimer = null;
  const blinkRestoreTimers = new Set();

  const requestedState = textValue(data.state, "IDLE").toUpperCase();
  const serverState = VISUAL_STATES.includes(requestedState) ? requestedState : "ERROR";
  const isBusy = ["THINKING", "WORKING", "APPLYING"].includes(serverState) || data.busy === true;

  function keyIsAllowed(key) {
    if (!key || key === "itens" || key.startsWith("editor_itens_")) return false;
    if (/^editor_(dfd|etp|tr|edital)$/.test(key)) return true;
    if (!KNOWN_FORM_FIELDS.includes(key)) return false;
    return allowedFields.size === 0 || allowedFields.has(key);
  }

  function findRecognizedWrapper(target) {
    if (!(target instanceof Element)) return null;
    const wrapper = target.closest(FORM_FIELD_SELECTOR);
    if (!wrapper) return null;
    const key = wrapperKey(wrapper);
    return keyIsAllowed(key) ? wrapper : null;
  }

  function captureDraft() {
    const draft = {};
    const wrappers = document.querySelectorAll(FORM_FIELD_SELECTOR);
    for (const wrapper of wrappers) {
      const key = wrapperKey(wrapper);
      if (!keyIsAllowed(key) || Object.prototype.hasOwnProperty.call(draft, key)) continue;
      draft[key] = inputText(inputForWrapper(wrapper));
    }
    return draft;
  }

  function emit(eventType, text = "", proposalId = null) {
    if (eventPending) return;
    eventPending = true;
    composer.disabled = true;
    sendButton.disabled = true;
    undoButton.disabled = true;
    setTriggerValue("event", {
      request_id: requestId(),
      event_type: eventType,
      text: textValue(text),
      focus: currentFocus,
      proposal_id: proposalId === null ? null : textValue(proposalId),
      draft: captureDraft(),
    });
  }

  function eyeState(raw, fallback) {
    const candidate = textValue(raw, fallback).toLowerCase();
    return EYE_STATES.includes(candidate) ? candidate : fallback;
  }

  function setEyeExpression(state) {
    const defaults = EYES_BY_STATE[state] || EYES_BY_STATE.IDLE;
    const eyes = plainObject(data.eyes) ? data.eyes : {};
    mascot.dataset.leftEye = eyeState(data.left_eye ?? eyes.left, defaults[0]);
    mascot.dataset.rightEye = eyeState(data.right_eye ?? eyes.right, defaults[1]);
  }

  function stateText(state) {
    const override = textValue(data.status_text).trim();
    return override || STATE_LABELS[state] || STATE_LABELS.IDLE;
  }

  function setVisualState(state, announce = true) {
    const normalized = VISUAL_STATES.includes(state) ? state : "ERROR";
    root.dataset.state = normalized;
    mascot.dataset.state = normalized;
    setEyeExpression(normalized);
    const label = stateText(normalized);
    visibleStatus.textContent = label;
    if (mascotDescription) mascotDescription.textContent = `GovBot: ${label}.`;
    if (announce) {
      stateAnnouncer.textContent = label;
      alertAnnouncer.textContent = normalized === "ERROR" ? label : "";
    }
  }

  function setBodyMarker(open) {
    if (open) {
      document.body.dataset.govbot = "open";
    } else {
      delete document.body.dataset.govbot;
    }
  }

  function updatePanelSemantics() {
    if (compactLayout.matches) {
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-modal", "true");
    } else {
      panel.setAttribute("role", "complementary");
      panel.removeAttribute("aria-modal");
    }
  }

  function setOpen(nextOpen, persist = true) {
    isOpen = Boolean(nextOpen);
    root.dataset.open = isOpen ? "true" : "false";
    panel.setAttribute("aria-hidden", isOpen ? "false" : "true");
    launcher.setAttribute("aria-expanded", isOpen ? "true" : "false");
    launcher.setAttribute("aria-label", isOpen ? "GovBot aberto" : "Abrir o GovBot");
    scrim.tabIndex = isOpen && compactLayout.matches ? 0 : -1;
    setBodyMarker(isOpen);
    if (persist) storageSet(OPEN_PREFERENCE_KEY, isOpen ? "open" : "closed");
  }

  function closeAndRestoreFocus() {
    setOpen(false);
    launcher.focus({ preventScroll: true });
  }

  function onLauncherClick() {
    setOpen(true);
  }

  function onUndoClick() {
    emit("undo", "", null);
  }

  function recognizedFocus(target) {
    const wrapper = findRecognizedWrapper(target);
    return wrapper ? wrapperKey(wrapper) : null;
  }

  function guidanceFor(key) {
    const supplied = plainObject(data.guidance) ? data.guidance : {};
    const suppliedText = textValue(supplied[key]).trim();
    return suppliedText || LOCAL_GUIDANCE[key] || "";
  }

  function maybeShowGuidance(key) {
    if (data.proactive === false || !keyIsAllowed(key)) return;
    const guidance = guidanceFor(key);
    if (!guidance) return;

    const version = textValue(data.form_version ?? data.context_version, "0");
    const marker = `${key}:${version}`;
    let seen = [];
    try {
      const parsed = JSON.parse(storageGet(PROACTIVE_SEEN_KEY) || "[]");
      if (Array.isArray(parsed)) seen = parsed.filter((item) => typeof item === "string");
    } catch (_error) {
      seen = [];
    }
    if (seen.includes(marker)) return;

    const previous = Number(storageGet(PROACTIVE_LAST_KEY) || "0");
    const now = Date.now();
    if (Number.isFinite(previous) && now - previous < PROACTIVE_COOLDOWN_MS) return;

    nudge.textContent = guidance;
    nudge.hidden = false;
    storageSet(PROACTIVE_LAST_KEY, String(now));
    storageSet(PROACTIVE_SEEN_KEY, JSON.stringify([...seen.slice(-79), marker]));
  }

  function onDocumentFocus(event) {
    const key = recognizedFocus(event.target);
    if (!key) return;
    currentFocus = key;
    maybeShowGuidance(key);
  }

  function renderMessages() {
    clearChildren(messagesElement);
    const messages = Array.isArray(data.messages) ? data.messages.slice(-40) : [];
    if (messages.length === 0) {
      const empty = document.createElement("p");
      empty.className = "govbot-empty";
      empty.textContent = "Posso explicar esta etapa, localizar pendências e preparar melhorias para sua revisão.";
      messagesElement.appendChild(empty);
      return;
    }

    for (const item of messages) {
      if (!plainObject(item)) continue;
      const role = ["user", "assistant", "system"].includes(item.role)
        ? item.role
        : "assistant";
      const text = textValue(item.text ?? item.content).trim();
      if (!text) continue;

      const message = document.createElement("article");
      message.className = "govbot-message";
      message.dataset.role = role;

      const meta = document.createElement("span");
      meta.className = "govbot-message-meta";
      meta.textContent = role === "user" ? "Você" : role === "system" ? "GovDocs" : "GovBot";

      const body = document.createElement("span");
      body.textContent = text;
      message.append(meta, body);
      messagesElement.appendChild(message);
    }
    messagesElement.scrollTop = messagesElement.scrollHeight;
  }

  function appendComparison(card, label, value, kind) {
    const block = document.createElement("div");
    block.className = "govbot-compare-block";
    block.dataset.kind = kind;

    const heading = document.createElement("p");
    heading.className = "govbot-compare-label";
    heading.textContent = label;

    const content = document.createElement("p");
    content.className = "govbot-compare-text";
    content.textContent = textValue(value, "—") || "—";

    block.append(heading, content);
    card.appendChild(block);
  }

  function sourceText(source) {
    if (plainObject(source)) {
      return textValue(source.label ?? source.title ?? source.reference ?? source.id);
    }
    return textValue(source);
  }

  function renderProposals() {
    clearChildren(proposalsElement);
    const proposals = Array.isArray(data.proposals)
      ? data.proposals
      : plainObject(data.proposal)
        ? [data.proposal]
        : [];

    for (const proposal of proposals) {
      if (!plainObject(proposal)) continue;
      const proposalId = textValue(proposal.id ?? proposal.proposal_id).trim();
      if (!proposalId) continue;

      const article = document.createElement("article");
      article.className = "govbot-proposal";

      const header = document.createElement("header");
      header.className = "govbot-proposal-header";
      const title = document.createElement("h3");
      title.className = "govbot-proposal-title";
      const target = textValue(proposal.target ?? proposal.alvo, "trecho atual");
      title.textContent = `Proposta para ${target}`;
      header.appendChild(title);

      const reasonText = textValue(proposal.justification ?? proposal.justificativa).trim();
      if (reasonText) {
        const reason = document.createElement("p");
        reason.className = "govbot-proposal-reason";
        reason.textContent = reasonText;
        header.appendChild(reason);
      }
      article.appendChild(header);

      const comparison = document.createElement("div");
      comparison.className = "govbot-comparison";
      appendComparison(comparison, "Antes", proposal.before ?? proposal.antes, "before");
      appendComparison(comparison, "Depois", proposal.after ?? proposal.depois, "after");
      article.appendChild(comparison);

      const sources = Array.isArray(proposal.sources ?? proposal.fontes)
        ? proposal.sources ?? proposal.fontes
        : [];
      const usableSources = sources.map(sourceText).filter(Boolean);
      if (usableSources.length > 0) {
        const list = document.createElement("ul");
        list.className = "govbot-sources";
        list.setAttribute("aria-label", "Fontes da proposta");
        for (const source of usableSources) {
          const item = document.createElement("li");
          item.className = "govbot-source";
          item.textContent = source;
          list.appendChild(item);
        }
        article.appendChild(list);
      }

      const footer = document.createElement("footer");
      footer.className = "govbot-proposal-footer";
      const applyButton = document.createElement("button");
      applyButton.className = "govbot-apply-button";
      applyButton.type = "button";
      applyButton.textContent = "Aplicar";
      applyButton.disabled = isBusy || proposal.can_apply === false;
      applyButton.setAttribute("aria-label", `Aplicar proposta para ${target}`);
      applyButton.addEventListener("click", () => emit("apply_proposal", "", proposalId));
      footer.appendChild(applyButton);
      article.appendChild(footer);
      proposalsElement.appendChild(article);
    }
  }

  function resetEyeTracking() {
    mascot.style.setProperty("--left-eye-x", "0px");
    mascot.style.setProperty("--left-eye-y", "0px");
    mascot.style.setProperty("--right-eye-x", "0px");
    mascot.style.setProperty("--right-eye-y", "0px");
  }

  function motionPaused() {
    return reducedMotion.matches || document.hidden || !inViewport;
  }

  function stopBlinking() {
    if (blinkTimer !== null) {
      globalThis.clearTimeout(blinkTimer);
      blinkTimer = null;
    }
    for (const timer of blinkRestoreTimers) globalThis.clearTimeout(timer);
    blinkRestoreTimers.clear();
  }

  function scheduleBlink() {
    if (motionPaused() || blinkTimer !== null) return;
    const delay = 4200 + Math.floor(Math.random() * 4800);
    blinkTimer = globalThis.setTimeout(() => {
      blinkTimer = null;
      const leftBefore = mascot.dataset.leftEye || "normal";
      const rightBefore = mascot.dataset.rightEye || "normal";
      mascot.dataset.leftEye = "blink";

      const rightTimer = globalThis.setTimeout(() => {
        mascot.dataset.rightEye = "blink";
        blinkRestoreTimers.delete(rightTimer);
      }, 28);
      blinkRestoreTimers.add(rightTimer);

      const leftRestore = globalThis.setTimeout(() => {
        mascot.dataset.leftEye = leftBefore;
        blinkRestoreTimers.delete(leftRestore);
      }, 145);
      blinkRestoreTimers.add(leftRestore);

      const rightRestore = globalThis.setTimeout(() => {
        mascot.dataset.rightEye = rightBefore;
        blinkRestoreTimers.delete(rightRestore);
        scheduleBlink();
      }, 175);
      blinkRestoreTimers.add(rightRestore);
    }, delay);
  }

  function syncMotion() {
    const paused = motionPaused();
    root.classList.toggle("is-paused", paused);
    root.classList.toggle("reduce-motion", reducedMotion.matches);
    if (paused) {
      stopBlinking();
      resetEyeTracking();
    } else {
      scheduleBlink();
    }
  }

  function onMascotMove(event) {
    if (motionPaused()) return;
    const rect = mascot.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const relativeX = (event.clientX - rect.left) / rect.width;
    const relativeY = (event.clientY - rect.top) / rect.height;
    const leftX = Math.max(-3, Math.min(3, (relativeX - 0.39) * 7));
    const rightX = Math.max(-3, Math.min(3, (relativeX - 0.61) * 7));
    const eyeY = Math.max(-2.3, Math.min(2.3, (relativeY - 0.48) * 5));
    mascot.style.setProperty("--left-eye-x", `${leftX.toFixed(2)}px`);
    mascot.style.setProperty("--left-eye-y", `${eyeY.toFixed(2)}px`);
    mascot.style.setProperty("--right-eye-x", `${rightX.toFixed(2)}px`);
    mascot.style.setProperty("--right-eye-y", `${eyeY.toFixed(2)}px`);
  }

  function onMascotEnter() {
    if (serverState === "IDLE") setVisualState("HOVER", false);
  }

  function onMascotLeave() {
    resetEyeTracking();
    if (serverState === "IDLE") setVisualState(serverState, false);
  }

  function onComposerInput() {
    if (serverState === "IDLE") setVisualState(composer.value ? "LISTENING" : serverState, false);
  }

  function onComposerBlur() {
    if (serverState === "IDLE") setVisualState(serverState, false);
  }

  function onSubmit(event) {
    event.preventDefault();
    if (isBusy) return;
    const text = composer.value.trim();
    if (!text) {
      alertAnnouncer.textContent = "Digite uma mensagem antes de enviar.";
      return;
    }
    emit("message", text, null);
    composer.value = "";
    setVisualState("THINKING");
  }

  function onComposerKeydown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (typeof form.requestSubmit === "function") form.requestSubmit();
    }
  }

  function onGlobalKeydown(event) {
    if (event.altKey && !event.ctrlKey && !event.metaKey && event.key.toLowerCase() === "g") {
      event.preventDefault();
      setOpen(true);
      composer.focus({ preventScroll: true });
      return;
    }
    if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      closeAndRestoreFocus();
    }
  }

  function onPanelKeydown(event) {
    if (event.key !== "Tab" || !isOpen || !compactLayout.matches) return;
    const focusable = Array.from(
      panel.querySelectorAll('button:not([disabled]):not([hidden]), textarea:not([disabled]), [tabindex="0"]')
    ).filter((element) => element.getClientRects().length > 0);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = parentElement.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onLayoutChange() {
    updatePanelSemantics();
    scrim.tabIndex = isOpen && compactLayout.matches ? 0 : -1;
  }

  function onReducedMotionChange() {
    syncMotion();
  }

  function onVisibilityChange() {
    syncMotion();
  }

  const savedOpen = storageGet(OPEN_PREFERENCE_KEY);
  const firstOpen = typeof data.open === "boolean" ? data.open : true;
  if (data.force_open === true) {
    setOpen(true, false);
  } else {
    setOpen(savedOpen === null ? firstOpen : savedOpen === "open", false);
  }

  updatePanelSemantics();
  setVisualState(serverState);
  panel.setAttribute("aria-busy", isBusy ? "true" : "false");
  composer.disabled = isBusy || data.disabled === true;
  sendButton.disabled = isBusy || data.disabled === true;
  undoButton.hidden = data.can_undo !== true;
  undoButton.disabled = isBusy;

  if (typeof data.composer_draft === "string" && parentElement.activeElement !== composer) {
    composer.value = data.composer_draft;
  }

  renderMessages();
  renderProposals();

  launcher.addEventListener("click", onLauncherClick);
  closeButton.addEventListener("click", closeAndRestoreFocus);
  scrim.addEventListener("click", closeAndRestoreFocus);
  form.addEventListener("submit", onSubmit);
  composer.addEventListener("input", onComposerInput);
  composer.addEventListener("blur", onComposerBlur);
  composer.addEventListener("keydown", onComposerKeydown);
  undoButton.addEventListener("click", onUndoClick);
  mascotWrap.addEventListener("pointerenter", onMascotEnter);
  mascotWrap.addEventListener("pointermove", onMascotMove);
  mascotWrap.addEventListener("pointerleave", onMascotLeave);
  panel.addEventListener("keydown", onPanelKeydown);
  document.addEventListener("focusin", onDocumentFocus, true);
  document.addEventListener("keydown", onGlobalKeydown, true);
  document.addEventListener("visibilitychange", onVisibilityChange);

  if (typeof reducedMotion.addEventListener === "function") {
    reducedMotion.addEventListener("change", onReducedMotionChange);
    compactLayout.addEventListener("change", onLayoutChange);
  } else {
    reducedMotion.addListener(onReducedMotionChange);
    compactLayout.addListener(onLayoutChange);
  }

  let intersectionObserver = null;
  if ("IntersectionObserver" in globalThis) {
    intersectionObserver = new IntersectionObserver((entries) => {
      inViewport = entries.some((entry) => entry.isIntersecting);
      syncMotion();
    });
    intersectionObserver.observe(mascotWrap);
  }
  syncMotion();

  let cleanedUp = false;
  const cleanup = () => {
    if (cleanedUp) return;
    cleanedUp = true;
    stopBlinking();
    resetEyeTracking();
    if (intersectionObserver) intersectionObserver.disconnect();
    document.removeEventListener("focusin", onDocumentFocus, true);
    document.removeEventListener("keydown", onGlobalKeydown, true);
    document.removeEventListener("visibilitychange", onVisibilityChange);
    launcher.removeEventListener("click", onLauncherClick);
    closeButton.removeEventListener("click", closeAndRestoreFocus);
    scrim.removeEventListener("click", closeAndRestoreFocus);
    form.removeEventListener("submit", onSubmit);
    composer.removeEventListener("input", onComposerInput);
    composer.removeEventListener("blur", onComposerBlur);
    composer.removeEventListener("keydown", onComposerKeydown);
    undoButton.removeEventListener("click", onUndoClick);
    mascotWrap.removeEventListener("pointerenter", onMascotEnter);
    mascotWrap.removeEventListener("pointermove", onMascotMove);
    mascotWrap.removeEventListener("pointerleave", onMascotLeave);
    panel.removeEventListener("keydown", onPanelKeydown);
    if (typeof reducedMotion.removeEventListener === "function") {
      reducedMotion.removeEventListener("change", onReducedMotionChange);
      compactLayout.removeEventListener("change", onLayoutChange);
    } else {
      reducedMotion.removeListener(onReducedMotionChange);
      compactLayout.removeListener(onLayoutChange);
    }
    if (root[CLEANUP_SLOT] === cleanup) {
      delete root[CLEANUP_SLOT];
      delete document.body.dataset.govbot;
    }
  };
  root[CLEANUP_SLOT] = cleanup;
  return cleanup;
}
