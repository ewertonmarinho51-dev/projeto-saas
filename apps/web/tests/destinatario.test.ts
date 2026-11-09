import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * O destinatário do relatório nas ações do servidor (0041). A API é falsa: o
 * que se prova é o CORPO que sai daqui. "Outro órgão" sem nome não pode virar
 * "não informado" — cairia no vínculo, que dá o timbrado de Paragominas.
 */
const api = vi.hoisted(() => ({ chamadas: [] as Array<{ caminho: string; init: { metodo?: string; corpo?: unknown } }> }));

vi.mock("@/lib/api", () => ({
  ErroDaApi: class ErroDaApi extends Error {
    constructor(public status: number, public mensagem = "") {
      super(mensagem);
    }
  },
  chamarApi: async (caminho: string, init: { metodo?: string; corpo?: unknown } = {}) => {
    api.chamadas.push({ caminho, init });
    return { dados: { id: "eeeeeeee-0000-4000-8000-000000000001" }, cabecalhos: new Headers() };
  },
}));
vi.mock("next/cache", () => ({ revalidatePath: () => undefined }));
vi.mock("next/navigation", () => ({
  redirect: (destino: string) => {
    throw new Error(`redirect:${destino}`);
  },
}));

const { criarPesquisa, definirDestinatario } = await import("../app/app/precos/acoes");

const PESQUISA = "eeeeeeee-0000-4000-8000-000000000001";
const SECRETARIA = "bbbbbbbb-0000-4000-8000-000000000001";

function formulario(campos: Record<string, string>) {
  const f = new FormData();
  for (const [k, v] of Object.entries(campos)) f.set(k, v);
  return f;
}

beforeEach(() => {
  api.chamadas = [];
});

describe("definirDestinatario", () => {
  it("secretaria do município vai como secretaria_id", async () => {
    const r = await definirDestinatario({ erro: null, ok: null }, formulario({ pesquisa: PESQUISA, destinatario: SECRETARIA }));
    expect(r.erro).toBeNull();
    expect(api.chamadas).toEqual([
      { caminho: `/precos/pesquisas/${PESQUISA}/destinatario`, init: { metodo: "PUT", corpo: { secretaria_id: SECRETARIA, externo: "" } } },
    ]);
  });

  it("outro órgão vai com o nome, sem secretaria", async () => {
    await definirDestinatario(
      { erro: null, ok: null },
      formulario({ pesquisa: PESQUISA, destinatario: "outro", destinatario_externo: "  Prefeitura   de Ulianópolis " }),
    );
    expect(api.chamadas[0]?.init.corpo).toEqual({ secretaria_id: null, externo: "Prefeitura de Ulianópolis" });
  });

  it("outro órgão sem nome é recusado e nada é enviado", async () => {
    const r = await definirDestinatario(
      { erro: null, ok: null },
      formulario({ pesquisa: PESQUISA, destinatario: "outro", destinatario_externo: "   " }),
    );
    expect(r.erro).toBe("Informe o nome do outro órgão.");
    expect(api.chamadas).toEqual([]);
  });

  it("valor que não é secretaria, outro nem nenhum é recusado", async () => {
    const r = await definirDestinatario({ erro: null, ok: null }, formulario({ pesquisa: PESQUISA, destinatario: "paragominas" }));
    expect(r.erro).toBe("Requisição inválida.");
    expect(api.chamadas).toEqual([]);
  });
});

describe("criarPesquisa", () => {
  const base = { nome: "Material", chave: "web-nova-0000001" };

  it("leva o destinatário escolhido", async () => {
    await expect(criarPesquisa({ erro: null }, formulario({ ...base, destinatario: "outro", destinatario_externo: "Prefeitura X" }))).rejects.toThrow(
      /^redirect:/,
    );
    expect(api.chamadas[0]?.init.corpo).toMatchObject({ destinatario_externo: "Prefeitura X" });
    expect(api.chamadas[0]?.init.corpo).not.toHaveProperty("destinatario_secretaria_id");
  });

  it("outro órgão sem nome não cria", async () => {
    const r = await criarPesquisa({ erro: null }, formulario({ ...base, destinatario: "outro" }));
    expect(r.erro).toBe("Informe o nome do outro órgão.");
    expect(api.chamadas).toEqual([]);
  });
});
