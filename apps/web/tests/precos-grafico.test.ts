import { describe, expect, it } from "vitest";

import { distribuirLinhas } from "../design-system/components/price/PriceDispersion";

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
