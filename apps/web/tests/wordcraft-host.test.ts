import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { emEditor, trilha } from "../components/trilha";
import { HOST_SHA256, HOST_URL } from "../lib/wordcraft/host";
import { alinharAoDispositivo, falhaNoStatus, medirCanvas } from "../lib/wordcraft/host-nativo";
import {
  dadosDoHost,
  faseDaPonte,
  TransporteDoEditor,
  type AberturaDoEditor,
  type EstadoDoEditor,
  type Lote,
  type Resposta,
} from "../lib/wordcraft/transporte";

const WEB = join(__dirname, "..");
const RAIZ = join(WEB, "..", "..");
const lf = (texto: string) => texto.replace(/\r\n/g, "\n");

describe("host nativo servido pelo web", () => {
  const original = lf(readFileSync(join(RAIZ, "assets", "wordcraft_editor", "host.mjs"), "utf8"));
  const pasta = join(WEB, "public", "app", "wordcraft-host");

  it("é cópia exata do host do Codex, com o hash no nome", () => {
    // Divergiu? `node scripts/sincronizar-wordcraft-host.mjs` — nunca editar a cópia.
    const hash = createHash("sha256").update(original).digest("hex");
    expect(HOST_SHA256).toBe(hash);
    expect(HOST_URL).toBe(`/app/wordcraft-host/host.${hash.slice(0, 16)}.mjs`);
    expect(readdirSync(pasta)).toEqual([`host.${hash.slice(0, 16)}.mjs`]);
    expect(lf(readFileSync(join(pasta, `host.${hash.slice(0, 16)}.mjs`), "utf8"))).toBe(original);
  });

  it("o host só importa JS/WASM do namespace aprovado do WordCraft", () => {
    expect(original).toContain("pathname.startsWith('/app/static/wordcraft/')");
  });

});

function estado(extra: Partial<EstadoDoEditor> = {}): EstadoDoEditor {
  return {
    instance_id: "i",
    session_id: "s",
    document_id: "d",
    nonce: "n".repeat(64),
    event_ack: 0,
    estado: "ready",
    revision: 1,
    content_hash: "a".repeat(64),
    status: "rascunho",
    escrita: true,
    ack: null,
    save_error: null,
    control: null,
    bloqueado: false,
    falha_controle: null,
    ...extra,
  };
}

const lote = (...eventos: string[]): Lote => ({ events: eventos.map((event, i) => ({ event, sequence: i + 1 })) });

function adiado<T>() {
  let resolver!: (v: T) => void;
  const promessa = new Promise<T>((r) => (resolver = r));
  return { promessa, resolver };
}

describe("transporte do editor", () => {
  it("um lote em voo por vez; o que chega no meio substitui o pendente", async () => {
    const enviados: Lote[] = [];
    const respostas = [adiado<Resposta>(), adiado<Resposta>()];
    const respondidos: EstadoDoEditor[] = [];
    const t = new TransporteDoEditor(
      (l) => {
        enviados.push(l);
        return respostas[enviados.length - 1].promessa;
      },
      (e) => respondidos.push(e),
      () => {},
    );
    t.setStateValue("edit", lote("document.loaded"));
    t.setStateValue("edit", lote("document.loaded", "document.changed"));
    t.setStateValue("edit", lote("document.loaded", "document.changed", "document.checkpoint"));
    expect(enviados).toHaveLength(1);
    respostas[0].resolver({ ok: true, estado: estado({ event_ack: 1 }) });
    await vi.waitFor(() => expect(enviados).toHaveLength(2));
    expect(enviados[1].events).toHaveLength(3);
    respostas[1].resolver({ ok: true, estado: estado({ event_ack: 3, estado: "saved" }) });
    await vi.waitFor(() => expect(respondidos).toHaveLength(2));
    expect(respondidos[1].estado).toBe("saved");
  });

  it("anuncia salvando só quando o lote leva checkpoint ou retry", async () => {
    const fases: string[] = [];
    const t = new TransporteDoEditor(async () => ({ ok: true, estado: estado() }), () => {}, () => {}, (f) => fases.push(f));
    t.setStateValue("edit", lote("document.changed"));
    await vi.waitFor(() => expect(fases).toEqual(["editando"]));
    t.setStateValue("edit", lote("document.changed", "document.checkpoint"));
    await vi.waitFor(() => expect(fases).toEqual(["editando", "salvando"]));
  });

  it("recusa da ponte para e não reenvia; sessão encerrada idem", async () => {
    for (const [status, fase] of [
      [409, "conflito"],
      [404, "encerrado"],
    ] as const) {
      const enviar = vi.fn(async (): Promise<Resposta> => ({ ok: false, status, codigo: "X" }));
      const falhas: string[] = [];
      const t = new TransporteDoEditor(enviar, () => {}, (f) => falhas.push(f));
      t.setStateValue("edit", lote("document.changed"));
      await vi.waitFor(() => expect(falhas).toEqual([fase]));
      t.setStateValue("edit", lote("document.changed", "document.checkpoint"));
      expect(enviar).toHaveBeenCalledTimes(1);
      expect(t.ativo).toBe(false);
    }
  });

  it("falha transitória guarda o lote e tenta de novo", async () => {
    let chamadas = 0;
    const respondidos: EstadoDoEditor[] = [];
    const t = new TransporteDoEditor(
      async (l): Promise<Resposta> => {
        chamadas += 1;
        expect(l.events).toHaveLength(2);
        return chamadas === 1 ? { ok: false, status: 503, codigo: "API_INDISPONIVEL" } : { ok: true, estado: estado() };
      },
      (e) => respondidos.push(e),
      () => {},
      () => {},
      () => 0,
    );
    t.setStateValue("edit", lote("document.changed", "document.checkpoint"));
    await vi.waitFor(() => expect(respondidos).toHaveLength(1));
    expect(chamadas).toBe(2);
  });

  it("ignora chave que não é a do editor e lote vazio", () => {
    const enviar = vi.fn(async (): Promise<Resposta> => ({ ok: true, estado: estado() }));
    const t = new TransporteDoEditor(enviar, () => {}, () => {});
    t.setStateValue("outra", lote("document.changed"));
    t.setStateValue("edit", { events: [] });
    expect(enviar).not.toHaveBeenCalled();
  });

  it("estado desconhecido da ponte nunca vira salvo", () => {
    expect(faseDaPonte("saved")).toBe("salvo");
    expect(faseDaPonte("frozen")).toBe("bloqueado");
    expect(faseDaPonte("inventado")).toBe("conflito");
  });

  it("dados do host: escopo da abertura + ACK/revisão/controle só da ponte", () => {
    const abertura = {
      ...estado({ estado: "opening" }),
      processo_id: "p",
      tipo: "dfd",
      sigla: "DFD",
      rotulo: "DFD",
      checkpoint_base64: "AA==",
      module_url: "https://govconect.com/app/static/wordcraft/gc.js",
      wasm_url: "https://govconect.com/app/static/wordcraft/gc.wasm",
    } satisfies AberturaDoEditor;
    const ack = { request_id: "r", revision: 2, content_hash: "b".repeat(64) };
    const dados = dadosDoHost(abertura, estado({ event_ack: 3, revision: 2, ack, content_hash: "b".repeat(64) }));
    expect(dados).toMatchObject({ instance_id: "i", nonce: "n".repeat(64), event_ack: 3, revision: 2, ack });
    // O hash de abertura confere os bytes do checkpoint inicial; não muda com o ACK.
    expect(dados.content_hash).toBe("a".repeat(64));
    expect("save_error" in dados).toBe(false);
    expect("control" in dados).toBe(false);
  });
});

describe("canvas e casca", () => {
  it("tamanho cai em pixel inteiro do aparelho", () => {
    expect(alinharAoDispositivo(1000.4, 1)).toBe(1000);
    expect(alinharAoDispositivo(1000.4, 2)).toBe(1000);
    expect(alinharAoDispositivo(333.37, 1.5)).toBeCloseTo(1000 / 3, 5);
    expect(alinharAoDispositivo(-4, 2)).toBe(0);
    expect(alinharAoDispositivo(10, 0)).toBe(10);
  });

  it("ignora os 720 px herdados do host e usa a área real do workspace", () => {
    const raiz = { clientWidth: 1468, clientHeight: 532 };
    const canvas = { style: { display: "", width: "1468px", height: "720px" } };

    medirCanvas(raiz, canvas as unknown as Pick<HTMLCanvasElement, "style">, 1.25);

    expect(canvas.style).toEqual({ display: "block", width: "1468px", height: "532px" });
  });

  it("falha do host não fica muda; status normal não é falha", () => {
    expect(falhaNoStatus("Não foi possível abrir o editor (wasm). Nenhuma gravação foi confirmada.")).toContain("(wasm)");
    expect(falhaNoStatus("Editor indisponível. Preserve o rascunho antes de recarregar.")).toContain("indisponível");
    expect(falhaNoStatus("O contexto mudou. Abra novamente o documento autorizado.")).toContain("contexto");
    expect(falhaNoStatus("Abrindo documento…")).toBeNull();
    expect(falhaNoStatus("Falha ao salvar. O rascunho permanece neste editor.")).toBeNull();
    expect(falhaNoStatus(undefined)).toBeNull();
    // A cópia servida é a do host: a mensagem precisa continuar existindo lá.
    const host = readFileSync(join(RAIZ, "assets", "wordcraft_editor", "host.mjs"), "utf8");
    expect(host).toContain("Não foi possível abrir o editor (");
    expect(host).toContain("Editor indisponível.");
  });

  it("modo de trabalho só na rota do editor", () => {
    expect(emEditor("/app/processos/abc/documentos/def/editar")).toBe(true);
    expect(emEditor("/app/processos/abc")).toBe(false);
    expect(emEditor("/app/processos/abc/documentos/def/editar/x")).toBe(false);
  });

  it("trilha do editor vai do processo ao documento sem links que não são página", () => {
    expect(trilha("/app/processos/abc/documentos/def/editar")).toEqual([
      { label: "Processos", href: "/app/processos" },
      { label: "Processo", href: "/app/processos/abc" },
      { label: "Documento" },
      { label: "Editar documento", href: "/app/processos/abc/documentos/def/editar" },
    ]);
  });
});
