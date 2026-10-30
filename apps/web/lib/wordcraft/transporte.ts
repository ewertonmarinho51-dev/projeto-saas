/**
 * Transporte do host nativo do WordCraft até a API, pelo BFF.
 *
 * O `host.mjs` (do Codex) foi escrito para o componente v2 do Streamlit:
 * ele chama `setStateValue("edit", {events})` com TODOS os eventos ainda não
 * consumidos e espera ser renderizado de novo com o `event_ack` da ponte do
 * servidor. Aqui está a mesma troca por HTTP, sem nada de Streamlit:
 *
 * - um lote em voo por vez; o que chegar enquanto isso substitui o pendente
 *   (cada lote já carrega tudo o que falta, então o último basta);
 * - a resposta da API é o único lugar de onde vêm ACK, revisão e controle —
 *   este arquivo não inventa confirmação de gravação;
 * - recusa da ponte (409) ou sessão encerrada (404) PARAM o transporte: o
 *   rascunho fica no canvas e a pessoa decide reabrir. Rede e 503 tentam de
 *   novo com espera crescente, sem perder o lote.
 */

export type Ack = { request_id: string; revision: number; content_hash: string };

export type EstadoDoEditor = {
  instance_id: string;
  session_id: string;
  document_id: string;
  nonce: string;
  event_ack: number;
  estado: string;
  revision: number;
  content_hash: string;
  status: string;
  escrita: boolean;
  ack: Ack | null;
  save_error: { request_id: string; conflict: boolean } | null;
  control: Record<string, unknown> | null;
  bloqueado: boolean;
  falha_controle: string | null;
};

export type AberturaDoEditor = EstadoDoEditor & {
  processo_id: string;
  tipo: string;
  sigla: string;
  rotulo: string;
  checkpoint_base64: string;
  module_url: string;
  wasm_url: string;
};

export type Lote = { events: unknown[] };

export type Resposta = { ok: true; estado: EstadoDoEditor } | { ok: false; status: number; codigo: string };

/** O que a interface mostra. Só `editando`/`salvando` nascem do lote local; o resto é da ponte. */
export type Fase =
  | "abrindo"
  | "pronto"
  | "editando"
  | "salvando"
  | "salvo"
  | "erro"
  | "conflito"
  | "bloqueado"
  | "encerrado";

const DA_PONTE: Record<string, Fase> = {
  opening: "abrindo",
  ready: "pronto",
  dirty: "editando",
  saving: "salvando",
  saved: "salvo",
  error: "erro",
  conflict: "conflito",
  frozen: "bloqueado",
};

export function faseDaPonte(estado: string): Fase {
  return DA_PONTE[estado] ?? "conflito";
}

function temEvento(lote: Lote, tipo: string): boolean {
  return lote.events.some((e) => typeof e === "object" && e !== null && (e as { event?: unknown }).event === tipo);
}

export class TransporteDoEditor {
  private pendente: Lote | null = null;
  private emVoo = false;
  private parado = false;
  private tentativa = 0;
  private relogio: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly enviar: (lote: Lote) => Promise<Resposta>,
    private readonly aoResponder: (estado: EstadoDoEditor) => void,
    private readonly aoFalhar: (fase: Fase, codigo: string) => void,
    private readonly aoEnviar: (fase: Fase) => void = () => {},
    private readonly espera: (tentativa: number) => number = (t) => Math.min(15000, 500 * 2 ** t),
  ) {}

  /** A assinatura exata que o host chama (`setStateValue`). */
  readonly setStateValue = (chave: string, valor: unknown): void => {
    if (chave !== "edit" || this.parado) return;
    const lote = valor as Lote;
    if (!lote || !Array.isArray(lote.events) || lote.events.length === 0) return;
    this.pendente = lote;
    void this.drenar();
  };

  get ativo(): boolean {
    return !this.parado;
  }

  parar(): void {
    this.parado = true;
    this.pendente = null;
    if (this.relogio) clearTimeout(this.relogio);
  }

  private async drenar(): Promise<void> {
    if (this.emVoo || this.parado || !this.pendente || this.relogio) return;
    const lote = this.pendente;
    this.pendente = null;
    this.emVoo = true;
    this.aoEnviar(temEvento(lote, "document.checkpoint") || temEvento(lote, "document.retry") ? "salvando" : "editando");
    let resposta: Resposta;
    try {
      resposta = await this.enviar(lote);
    } catch {
      resposta = { ok: false, status: 503, codigo: "API_INDISPONIVEL" };
    }
    this.emVoo = false;
    if (this.parado) return;
    if (resposta.ok) {
      this.tentativa = 0;
      this.aoResponder(resposta.estado);
    } else if (resposta.status === 409 || resposta.status === 404 || resposta.status === 401 || resposta.status === 403) {
      this.parado = true;
      this.pendente = null;
      this.aoFalhar(resposta.status === 409 ? "conflito" : "encerrado", resposta.codigo);
      return;
    } else {
      // Transitório: o lote volta (se nada mais novo chegou) e tenta depois.
      this.pendente ??= lote;
      this.aoFalhar("erro", resposta.codigo);
      this.relogio = setTimeout(() => {
        this.relogio = null;
        void this.drenar();
      }, this.espera(this.tentativa++));
      return;
    }
    void this.drenar();
  }
}

/** Dados que o host lê a cada renderização: escopo da abertura + estado da ponte. */
export function dadosDoHost(abertura: AberturaDoEditor, estado: EstadoDoEditor): Record<string, unknown> {
  return {
    instance_id: abertura.instance_id,
    session_id: abertura.session_id,
    document_id: abertura.document_id,
    nonce: abertura.nonce,
    checkpoint_base64: abertura.checkpoint_base64,
    module_url: abertura.module_url,
    wasm_url: abertura.wasm_url,
    revision: estado.revision,
    content_hash: abertura.content_hash,
    event_ack: estado.event_ack,
    ...(estado.ack ? { ack: estado.ack } : {}),
    ...(estado.save_error ? { save_error: estado.save_error } : {}),
    ...(estado.control ? { control: estado.control } : {}),
  };
}
