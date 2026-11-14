import type { ReactNode } from "react";

/**
 * Esquema do Brasil em blocos, um por UF (pacote de 14/11/2026, RF-08).
 * NÃO é mapa em escala nem usa coordenada inventada: cada UF ocupa a mesma
 * célula de uma grade aproximada, e a intensidade diz quantas referências
 * há nela. Toda informação também sai em tabela (leitor de tela, impressão).
 */
export interface UfTileValue {
  uf: string;
  quantidade: number;
}

export interface UfTileMapProps {
  values: UfTileValue[];
  /** O que a UF significa ("UF do órgão comprador"). Obrigatório: não misturar bases. */
  basis: string;
  /** O que o número conta ("referências"). */
  metric: string;
  /** Quantas ficaram sem UF — mostradas à parte, nunca distribuídas. */
  unknown?: number;
  /** Ao escolher uma UF (ex.: filtrar). Sem isso, só leitura. */
  onSelect?: (uf: string) => void;
  selected?: string | null;
  caption?: ReactNode;
}

/** [linha, coluna] de cada UF numa grade 8×8 aproximada. */
export const POSICAO_DA_UF: Record<string, [number, number]> = {
  RR: [0, 2], AP: [0, 4],
  AM: [1, 1], PA: [1, 3], MA: [1, 4], CE: [1, 5], RN: [1, 6],
  AC: [2, 0], RO: [2, 2], TO: [2, 3], PI: [2, 4], PB: [2, 6],
  MT: [3, 2], GO: [3, 3], BA: [3, 4], SE: [3, 5], PE: [3, 6], AL: [3, 7],
  MS: [4, 2], DF: [4, 3], MG: [4, 4], ES: [4, 5],
  PR: [5, 2], SP: [5, 3], RJ: [5, 4],
  SC: [6, 2],
  RS: [7, 2],
};

/** Faixa de intensidade (0 = nenhuma; 1–4 pelos quartis dos valores > 0). */
export function intensidade(valor: number, valores: number[]): 0 | 1 | 2 | 3 | 4 {
  if (valor <= 0) return 0;
  const positivos = valores.filter((v) => v > 0).sort((a, b) => a - b);
  if (positivos.length <= 1) return 4;
  const posicao = positivos.filter((v) => v <= valor).length / positivos.length;
  return posicao > 0.75 ? 4 : posicao > 0.5 ? 3 : posicao > 0.25 ? 2 : 1;
}

export function UfTileMap({ values, basis, metric, unknown = 0, onSelect, selected, caption }: UfTileMapProps) {
  const por = new Map(values.map((v) => [v.uf.toUpperCase(), v.quantidade]));
  const todos = [...por.values()];
  return (
    <figure className="gc-ufmap">
      <div className="gc-ufmap__grid" role="group" aria-label={`${metric} por ${basis}`}>
        {Object.entries(POSICAO_DA_UF).map(([uf, [linha, coluna]]) => {
          const n = por.get(uf) ?? 0;
          const nivel = intensidade(n, todos);
          const rotulo = `${uf}: ${n} ${metric}`;
          const estilo = { gridRow: linha + 1, gridColumn: coluna + 1 };
          return onSelect && n > 0 ? (
            <button
              key={uf}
              type="button"
              className={`gc-ufmap__tile gc-ufmap__tile--n${nivel}`}
              style={estilo}
              aria-pressed={selected === uf}
              aria-label={rotulo}
              onClick={() => onSelect(uf)}
            >
              <span className="gc-ufmap__uf">{uf}</span>
              <span className="gc-ufmap__n">{n}</span>
            </button>
          ) : (
            <span key={uf} className={`gc-ufmap__tile gc-ufmap__tile--n${nivel}`} style={estilo} aria-label={rotulo}>
              <span className="gc-ufmap__uf">{uf}</span>
              <span className="gc-ufmap__n">{n || "—"}</span>
            </span>
          );
        })}
      </div>
      <figcaption className="gc-ufmap__caption">
        {caption ?? `Esquema por UF (não é mapa em escala). Base: ${basis}. Número: ${metric}.`}
        {unknown > 0 && ` ${unknown} sem UF informada.`}
      </figcaption>
      <table className="gc-ufmap__table">
        <caption>{`${metric} por ${basis}`}</caption>
        <thead>
          <tr>
            <th scope="col">UF</th>
            <th scope="col">{metric}</th>
          </tr>
        </thead>
        <tbody>
          {[...por.entries()]
            .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
            .map(([uf, n]) => (
              <tr key={uf}>
                <th scope="row">{uf}</th>
                <td>{n}</td>
              </tr>
            ))}
          {unknown > 0 && (
            <tr>
              <th scope="row">Sem UF</th>
              <td>{unknown}</td>
            </tr>
          )}
        </tbody>
      </table>
    </figure>
  );
}
