import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { distribuirLinhas, PriceDispersion } from "../design-system/components/price/PriceDispersion";

const VIZINHANCA = 16;
const MAX_LADO = 5;

/** Pontos na mesma linha, em px, do mais à esquerda ao mais à direita. */
function porLinha(posicoes: number[], linhas: number[], largura: number) {
  const grupos = new Map<number, number[]>();
  linhas.forEach((l, i) => grupos.set(l, [...(grupos.get(l) ?? []), (posicoes[i] / 100) * largura]));
  return [...grupos.values()].map((xs) => xs.sort((a, b) => a - b));
}

describe("empilhamento do gráfico de dispersão", () => {
  it("devolve uma linha para cada preço, na ordem de entrada", () => {
    const posicoes = [90, 10, 50, 10];
    const linhas = distribuirLinhas(posicoes, 800);
    // Os dois de 10% não dividem a linha; os outros, isolados, ficam no eixo.
    expect(linhas).toEqual([0, 0, 0, -1]);
  });

  it("não sobrepõe preços enquanto houver linha livre", () => {
    const posicoes = Array.from({ length: 11 }, () => 42);
    const linhas = distribuirLinhas(posicoes, 358);
    expect(new Set(linhas).size).toBe(11);
    for (const xs of porLinha(posicoes, linhas, 358)) {
      xs.slice(1).forEach((x, i) => expect(x - xs[i]).toBeGreaterThanOrEqual(VIZINHANCA));
    }
  });

  it("preços distantes ficam no eixo, sem altura à toa", () => {
    expect(distribuirLinhas([0, 25, 50, 75, 100], 1136)).toEqual([0, 0, 0, 0, 0]);
  });

  it("série enorme não estoura a altura e não perde preço", () => {
    const posicoes = Array.from({ length: 500 }, (_, i) => i % 7);
    const linhas = distribuirLinhas(posicoes, 358);
    expect(linhas).toHaveLength(500);
    expect(Math.max(...linhas.map(Math.abs))).toBeLessThanOrEqual(MAX_LADO);
  });

  it("a largura muda o empilhamento, nunca a posição do preço", () => {
    const posicoes = [10, 11, 12, 13, 95];
    const copia = [...posicoes];
    const estreita = distribuirLinhas(posicoes, 358);
    const larga = distribuirLinhas(posicoes, 3200);
    expect(posicoes).toEqual(copia);
    expect(Math.max(...estreita.map(Math.abs))).toBeGreaterThan(0);
    expect(larga).toEqual([0, 0, 0, 0, 0]);
  });
});

describe("pontas do gráfico de dispersão", () => {
  const scale = { min: 18, max: 26, ticks: [18, 22, 26].map((v) => ({ value: v, label: `R$ ${v},00` })) };
  const values = [{ value: 20, display: "R$ 20,00" }];

  it("limite do eixo ampliado não vira menor nem maior preço", () => {
    const html = renderToStaticMarkup(createElement(PriceDispersion, { values, scale }));
    expect(html).not.toContain("gc-disp__scale");
    expect(html).not.toMatch(/Menor|Maior/);
    expect(html).toContain("R$ 26,00");
  });

  it("extremo informado pelo servidor continua nomeado", () => {
    const html = renderToStaticMarkup(
      createElement(PriceDispersion, { values, scale, labels: { scale: ["R$ 4,60 · PNCP", "R$ 371,00 · PNCP"] } }),
    );
    expect(html).toContain("Menor R$ 4,60 · PNCP");
    expect(html).toContain("Maior R$ 371,00 · PNCP");
  });
});
