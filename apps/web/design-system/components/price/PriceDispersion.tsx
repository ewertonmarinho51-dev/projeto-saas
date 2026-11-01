"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { formatarReais } from "../../lib/formato";

export type DispersionState = "valid" | "attention" | "discrepant" | "excluded";

export interface DispersionValue {
  label?: string;
  value: number;
  state?: DispersionState;
  /** Valor já formatado pelo servidor; com ele, `format` não é chamado para o ponto. */
  display?: string;
  /** Menor ou maior da série: ganha contorno forte e fica por cima dos demais. */
  extreme?: "low" | "high";
  /** Detalhe do ponto, já escrito pelo servidor ("+233,33% sobre a mediana"). */
  note?: string;
}

/** Eixo pronto do servidor: `min` e `max` posicionam; as marcas vêm escritas. */
export interface DispersionScale {
  min: number;
  max: number;
  ticks: { value: number; label: string }[];
}

/**
 * Textos prontos (dinheiro formatado no servidor). Com eles o navegador só
 * POSICIONA: nenhum valor exibido nasce de conta feita aqui, e a escala
 * mostra o menor e o maior coletados em vez das pontas com folga.
 */
export interface DispersionLabels {
  median?: string;
  mean?: string;
  band?: [string, string];
  scale?: [string, string];
}

export interface PriceDispersionProps {
  values: DispersionValue[];
  median?: number;
  mean?: number;
  /** Faixa de aceitação [mínimo, máximo] da regra de triagem. */
  band?: [number, number];
  format?: (n: number) => string;
  labels?: DispersionLabels;
  legend?: boolean;
  /** Sem ela, o eixo sai dos próprios valores, com folga e sem marcas. */
  scale?: DispersionScale;
}

const ROTULO: Record<DispersionState, string> = {
  valid: "Na cesta",
  attention: "Exige conferência",
  discrepant: "Discrepante",
  excluded: "Fora do cálculo",
};

const ORDEM: DispersionState[] = ["valid", "attention", "discrepant", "excluded"];

/** Diâmetro do ponto com folga, em px: distância mínima entre dois pontos na mesma linha. */
const VIZINHANCA = 16;
/** Linhas acima e abaixo do eixo. Passou disso, os pontos se sobrepõem na última. */
const MAX_LADO = 5;
/** Largura antes da primeira medida (o servidor não mede). */
const LARGURA_INICIAL = 640;

/** Alinha o rótulo para dentro quando o ponto está perto da borda do gráfico. */
const ancora = (pct: number) => (pct < 12 ? "start" : pct > 88 ? "end" : "middle");

/**
 * Empilha na vertical os pontos que cairiam um sobre o outro. A posição
 * horizontal, que é o preço, nunca muda. Devolve a linha de cada índice:
 * 0 no eixo, negativas acima, positivas abaixo.
 */
export function distribuirLinhas(posicoes: number[], largura: number): number[] {
  const ordem = posicoes.map((_, i) => i).sort((a, b) => posicoes[a] - posicoes[b]);
  const candidatas = [0];
  for (let l = 1; l <= MAX_LADO; l++) candidatas.push(-l, l);
  const ultimo = new Map<number, number>();
  const linhas = new Array<number>(posicoes.length).fill(0);
  for (const i of ordem) {
    const x = (posicoes[i] / 100) * largura;
    const livre = candidatas.find((l) => {
      const fim = ultimo.get(l);
      return fim === undefined || x - fim >= VIZINHANCA;
    });
    // Sem linha livre, fica na que está há mais tempo sem ponto.
    const linha =
      livre ?? candidatas.reduce((melhor, l) => ((ultimo.get(l) ?? 0) < (ultimo.get(melhor) ?? 0) ? l : melhor));
    ultimo.set(linha, x);
    linhas[i] = linha;
  }
  return linhas;
}

/**
 * Todas as referências de um item num eixo de preço LINEAR: média, mediana,
 * faixa de referência e cada ponto com a forma do seu estado (círculo = na
 * cesta, anel = conferência, triângulo = discrepante, anel cinza = fora).
 * Forma e legenda, nunca só cor. Preços iguais ou muito próximos se empilham
 * na vertical, e o extremo é nomeado na ponta: nada é cortado nem espremido.
 */
export function PriceDispersion({
  values,
  median,
  mean,
  band,
  format = formatarReais,
  labels,
  legend = true,
  scale,
}: PriceDispersionProps) {
  const area = useRef<HTMLDivElement>(null);
  const [largura, setLargura] = useState(LARGURA_INICIAL);
  useEffect(() => {
    const el = area.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const medir = () => setLargura(el.clientWidth || LARGURA_INICIAL);
    medir();
    const vigia = new ResizeObserver(medir);
    vigia.observe(el);
    return () => vigia.disconnect();
  }, []);

  const texto = (v: DispersionValue) => v.display ?? format(v.value);
  const vs = values.map((v) => v.value);
  const baixo = Math.min(...vs, band ? band[0] : Infinity);
  const alto = Math.max(...vs, band ? band[1] : -Infinity);
  const folga = (alto - baixo) * 0.08 || 1;
  const min = scale?.min ?? baixo - folga;
  const max = scale?.max ?? alto + folga;
  const pos = (v: number) => ((v - min) / (max - min)) * 100;

  const posicoes = values.map((v) => pos(v.value));
  const linhas = distribuirLinhas(posicoes, largura);
  const lado = linhas.reduce((m, l) => Math.max(m, Math.abs(l)), 0);
  const dica = (v: DispersionValue) =>
    [v.label, texto(v), v.note, ROTULO[v.state ?? "valid"]].filter(Boolean).join(" · ");

  return (
    <figure className="gc-disp">
      <div
        ref={area}
        className="gc-disp__plot"
        role="img"
        aria-label={values.map((v) => `${v.label ?? ""} ${texto(v)} — ${ROTULO[v.state ?? "valid"]}`).join("; ")}
        style={{ "--gc-disp-lado": lado } as CSSProperties}
      >
        {scale?.ticks.map((t) => (
          <span key={t.value} className="gc-disp__grid" style={{ left: `${pos(t.value)}%` }} />
        ))}
        <div className="gc-disp__axis" />
        {band && (
          <div
            className="gc-disp__band"
            style={{ left: `${pos(band[0])}%`, width: `${pos(band[1]) - pos(band[0])}%` }}
            title={`Faixa de referência: ${labels?.band?.[0] ?? format(band[0])} a ${labels?.band?.[1] ?? format(band[1])}`}
          />
        )}
        {mean != null && (
          <div className="gc-disp__ref gc-disp__ref--mean" style={{ left: `${pos(mean)}%` }} data-anchor={ancora(pos(mean))}>
            <span>Média {labels?.mean ?? format(mean)}</span>
          </div>
        )}
        {median != null && (
          <div className="gc-disp__ref" style={{ left: `${pos(median)}%` }} data-anchor={ancora(pos(median))}>
            <span>Mediana {labels?.median ?? format(median)}</span>
          </div>
        )}
        {values.map((v, i) => (
          <span
            key={i}
            className="gc-disp__mark"
            data-anchor={ancora(posicoes[i])}
            data-extreme={v.extreme}
            data-tip={dica(v)}
            style={{ left: `${posicoes[i]}%`, "--gc-disp-linha": linhas[i] } as CSSProperties}
          >
            <span className="gc-disp__dot" data-state={v.state ?? "valid"} />
          </span>
        ))}
      </div>
      {scale && (
        <div className="gc-disp__ticks" aria-hidden="true">
          {scale.ticks.map((t) => (
            <span key={t.value} style={{ left: `${pos(t.value)}%` }} data-anchor={ancora(pos(t.value))}>
              {t.label}
            </span>
          ))}
        </div>
      )}
      {/* Com eixo próprio e sem extremos informados, as marcas já dizem tudo:
          os limites do eixo não são preços e não podem ser lidos como "menor" e "maior". */}
      {(labels?.scale || !scale) && (
        <div className="gc-disp__scale">
          <span>{labels?.scale ? `Menor ${labels.scale[0]}` : format(min)}</span>
          <span>{labels?.scale ? `Maior ${labels.scale[1]}` : format(max)}</span>
        </div>
      )}
      {legend && (
        <figcaption className="gc-disp__legend">
          {ORDEM.filter((s) => values.some((v) => (v.state ?? "valid") === s)).map((s) => (
            <span key={s}>
              <span className="gc-disp__dot gc-disp__dot--static" data-state={s} />
              {ROTULO[s]}
            </span>
          ))}
          {values.some((v) => v.extreme) && (
            <span>
              <span className="gc-disp__swatch gc-disp__swatch--extreme" />
              Extremo da série
            </span>
          )}
          {mean != null && (
            <span>
              <span className="gc-disp__swatch gc-disp__swatch--mean" />
              Média
            </span>
          )}
          {median != null && (
            <span>
              <span className="gc-disp__swatch gc-disp__swatch--median" />
              Mediana
            </span>
          )}
          {band && (
            <span>
              <span className="gc-disp__swatch" />
              Faixa de referência
            </span>
          )}
        </figcaption>
      )}
    </figure>
  );
}
