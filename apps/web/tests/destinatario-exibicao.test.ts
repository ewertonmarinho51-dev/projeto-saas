import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

/**
 * Quem vê a troca de destinatário (0041). Só o autor da pesquisa ou o
 * administrador conseguem salvá-la — a API devolve 403 aos demais —, então
 * só eles recebem o formulário. Os outros leem a linha que diz qual timbrado
 * sai, sem um botão que só daria erro.
 */
vi.mock("@/lib/api", () => ({
  ErroDaApi: class ErroDaApi extends Error {},
  chamarApi: async () => ({ dados: {}, cabecalhos: new Headers() }),
}));
vi.mock("next/cache", () => ({ revalidatePath: () => undefined }));
vi.mock("next/navigation", () => ({ redirect: () => undefined }));

const { DestinatarioDaPesquisa } = await import("../components/destinatario");

const ORGAOS = [
  { id: "bbbbbbbb-0000-4000-8000-000000000001", nome: "Prefeitura Municipal de Paragominas", padrao: true, vinculo: true },
];

const html = (podeAlterar: boolean, atual = { tipo: "externo" as const, secretaria_id: null, nome: "Prefeitura de Ulianópolis" }) =>
  renderToStaticMarkup(
    createElement(DestinatarioDaPesquisa, {
      pesquisa: "eeeeeeee-0000-4000-8000-000000000001",
      orgaos: ORGAOS,
      atual,
      podeAlterar,
    }),
  );

describe("Destinatário de pesquisa existente", () => {
  it("autor ou administrador recebe o formulário de troca", () => {
    const markup = html(true);
    expect(markup).toContain("<form");
    expect(markup).toContain('name="destinatario"');
    expect(markup).toContain("Salvar destinatário");
    expect(markup).toContain("Prefeitura de Ulianópolis (sem timbrado)");
  });

  it("quem não pode salvar só lê qual timbrado sai, sem formulário nem botão", () => {
    const markup = html(false);
    expect(markup).not.toContain("<form");
    expect(markup).not.toContain("<select");
    expect(markup).not.toContain("<button");
    expect(markup).not.toContain("Salvar destinatário");
    expect(markup).toContain("Destinatário e timbrado: Prefeitura de Ulianópolis (sem timbrado)");
  });

  it("a linha de leitura também nomeia a secretaria do município", () => {
    const markup = html(false, { tipo: "secretaria", secretaria_id: ORGAOS[0].id, nome: "" } as never);
    expect(markup).toContain("Destinatário e timbrado: Prefeitura Municipal de Paragominas");
  });
});
