import { describe, expect, it } from "vitest";

import { JANELA_PADRAO_DIAS, JANELAS_DA_BUSCA } from "@/components/precos";

describe("período da busca de preços", () => {
  it("vai de 30 dias a 1 ano, em ordem, com o ano como padrão", () => {
    const dias = JANELAS_DA_BUSCA.map((j) => Number(j.value));
    expect(dias).toEqual([30, 60, 90, 120, 180, 365]);
    expect(JANELA_PADRAO_DIAS).toBe(365);
    expect(JANELAS_DA_BUSCA.at(-1)).toEqual({ value: "365", label: "Último ano" });
  });

  it("nenhuma opção passa do teto que a API aceita (IN 65/2021, 1 ano)", () => {
    for (const j of JANELAS_DA_BUSCA) {
      expect(Number(j.value)).toBeGreaterThanOrEqual(30);
      expect(Number(j.value)).toBeLessThanOrEqual(365);
    }
  });
});
