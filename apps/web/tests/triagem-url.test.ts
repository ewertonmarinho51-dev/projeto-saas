import { describe, expect, it } from "vitest";

import { lerFiltros, paraApi, paraUrl, temFiltro } from "../components/triagem-url";
import { intensidade } from "../design-system/components/data/UfTileMap";

describe("filtros e página da triagem na URL (RF-06/RF-07)", () => {
  it("padrão: página 1, 20 por página, ordem por valor, lista", () => {
    const f = lerFiltros({});
    expect(f).toMatchObject({ pagina: 1, por_pagina: 20, ordem: "valor_asc", modo: "lista" });
    expect(paraApi(f)).toBe("pagina=1&por_pagina=20&ordem=valor_asc");
    expect(temFiltro(f)).toBe(false);
  });

  it("só 10/20/50; entrada inválida é ignorada, não repassada", () => {
    expect(lerFiltros({ por_pagina: "50" }).por_pagina).toBe(50);
    expect(lerFiltros({ por_pagina: "500" }).por_pagina).toBe(20);
    const f = lerFiltros({ pagina: "-3", uf: "PAR", fonte: "pncp;drop", desde: "ontem", preco_min: "1e9",
                           situacao: "todas", ordem: "id" });
    expect(f).toMatchObject({ pagina: 1, uf: undefined, fonte: undefined, desde: undefined,
                              preco_min: undefined, situacao: undefined, ordem: "valor_asc" });
  });

  it("filtros válidos vão para a API, preço com vírgula vira ponto", () => {
    const f = lerFiltros({ pagina: "3", situacao: "cesta", uf: "pa", fonte: "pncp", preco_min: "2,30",
                           desde: "2026-01-01", q: "luva nitrílica", ordem: "data_desc" });
    const api = new URLSearchParams(paraApi(f));
    expect(Object.fromEntries(api)).toEqual({ pagina: "3", por_pagina: "20", situacao: "cesta", fonte: "pncp",
      uf: "PA", preco_min: "2.30", desde: "2026-01-01", q: "luva nitrílica", ordem: "data_desc" });
    expect(temFiltro(f)).toBe(true);
  });

  it("mudar filtro ou tamanho volta à página 1; mudar página mantém o filtro", () => {
    const base = "/app/precos/p/itens/i";
    const f = lerFiltros({ pagina: "4", uf: "PA" });
    expect(paraUrl(base, f, { pagina: 5 })).toBe(`${base}?pagina=5&uf=PA`);
    expect(paraUrl(base, f, { situacao: "cesta" })).toBe(`${base}?situacao=cesta&uf=PA`);
    expect(paraUrl(base, f, { por_pagina: 50 })).toBe(`${base}?por_pagina=50&uf=PA`);
    expect(paraUrl(base, f, { modo: "mapa" })).toBe(`${base}?pagina=4&uf=PA&modo=mapa`);
    expect(paraUrl(base, lerFiltros({}), {})).toBe(base);
  });
});

describe("mapa por UF: intensidade pelos quartis", () => {
  it("zero é zero; o maior é 4; um valor só é 4", () => {
    const valores = [1, 2, 3, 4, 10, 20, 30, 40];
    expect(intensidade(0, valores)).toBe(0);
    expect(intensidade(40, valores)).toBe(4);
    expect(intensidade(1, valores)).toBe(1);
    expect(intensidade(5, [5])).toBe(4);
  });
});
