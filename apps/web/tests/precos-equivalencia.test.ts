import { describe, expect, it } from "vitest";

import { comparativoDaEquivalencia, varianteDaEquivalencia } from "@/components/precos";

describe("rótulo de equivalência da referência", () => {
  it("só o que entra sozinho na cesta é verde", () => {
    expect(varianteDaEquivalencia("mesmo item")).toBe("success");
    expect(varianteDaEquivalencia("equivalente comprovado")).toBe("success");
    expect(varianteDaEquivalencia("similar para revisão")).toBe("warning");
    expect(varianteDaEquivalencia("incompatível")).toBe("error");
    expect(varianteDaEquivalencia(undefined)).toBe("neutral");
    expect(varianteDaEquivalencia("outra coisa")).toBe("neutral");
  });

  it("o comparativo é o que vem depois do rótulo", () => {
    expect(
      comparativoDaEquivalencia(
        "incompatível — diverge: gramatura 90 g/m² na fonte, 75 g/m² no item — conferido: formato A4",
      ),
    ).toBe("diverge: gramatura 90 g/m² na fonte, 75 g/m² no item · conferido: formato A4");
    expect(comparativoDaEquivalencia("mesmo item")).toBe("");
    expect(comparativoDaEquivalencia(undefined)).toBe("");
  });
});

describe("itens pendentes do lote", () => {
  it("o mesmo critério do Reprocessar pendentes no servidor", async () => {
    const { itemPendente } = await import("@/components/precos");
    const preco = { valor: "10", exibicao: "R$ 10,00" };
    expect(itemPendente({ estado: "pending", preco_estimado: null })).toBe(true);
    expect(itemPendente({ estado: "error", preco_estimado: null })).toBe(true);
    expect(itemPendente({ estado: "incomplete", preco_estimado: preco })).toBe(true);
    expect(itemPendente({ estado: "review", preco_estimado: null })).toBe(true);
    expect(itemPendente({ estado: "review", preco_estimado: preco })).toBe(false);
    expect(
      itemPendente({
        estado: "review",
        preco_estimado: preco,
        revisao_cv: { motivo: "cv_acima_do_limite", cv: "30%", limite: "25%", quantidade: 3, sugeridas: 3, texto: "" },
      }),
    ).toBe(true);
    expect(itemPendente({ estado: "complete", preco_estimado: null })).toBe(false);
  });
});

describe("lista da pesquisa: o que exige atenção primeiro", () => {
  it("pendentes por gravidade, depois propostas aptas, por último o concluído", async () => {
    const { ordenarPorAtencao, rotuloDaPendencia } = await import("@/components/precos");
    const preco = { valor: "10", exibicao: "R$ 10,00" };
    const itens = [
      { numero: 1, estado: "complete", preco_estimado: preco, pendencia: "" as const, apta: false },
      { numero: 2, estado: "review", preco_estimado: preco, pendencia: "pronto_para_revisao" as const, apta: true },
      { numero: 3, estado: "incomplete", preco_estimado: null, pendencia: "amostra_insuficiente" as const, apta: false },
      { numero: 4, estado: "error", preco_estimado: null, pendencia: "falha_tecnica" as const, apta: false },
      { numero: 5, estado: "review", preco_estimado: preco, pendencia: "revisar_similaridade" as const, apta: false },
    ];
    expect(ordenarPorAtencao(itens).map((i) => i.numero)).toEqual([4, 3, 5, 2, 1]);
    expect(rotuloDaPendencia(itens[1])).toBe("Proposta apta");
    expect(rotuloDaPendencia(itens[3])).toBe("Falha técnica");
    expect(rotuloDaPendencia(itens[0])).toBe("");
  });
});
