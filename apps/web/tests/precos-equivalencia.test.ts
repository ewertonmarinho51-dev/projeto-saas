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
