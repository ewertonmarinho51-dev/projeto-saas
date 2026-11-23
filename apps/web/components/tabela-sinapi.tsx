"use client";

import { Badge, DataTable, TableContainer, type DataTableColumn } from "@/design-system";
import type { ReferenciaDeCusto } from "@/lib/api";

/** "0.0011" (fração) → "0,11%"; zero some (não houve preço de São Paulo). */
function percentualSP(fracao: string | null): string | null {
  if (fracao === null) return null;
  const n = Number(fracao);
  if (!Number.isFinite(n) || n <= 0) return null;
  return `${(n * 100).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% com preço de SP`;
}

const ORIGEM: Record<string, string> = { C: "coletado", CR: "coeficiente de representatividade" };

/**
 * Referências do SINAPI com tudo o que se confere na fonte: código, tipo,
 * unidade, custo, regime, origem do preço (insumo) ou %AS (composição), e a
 * aba e a linha da planilha oficial. Tabela de preço: rola, não empilha.
 */
export function TabelaSinapi({ referencias }: { referencias: ReferenciaDeCusto[] }) {
  const colunas: DataTableColumn<ReferenciaDeCusto>[] = [
    {
      key: "codigo",
      label: "Código",
      render: (r) => (
        <span className="grid gap-1">
          <span className="gc-mono">{r.codigo}</span>
          <Badge size="sm" variant={r.tipo === "insumo" ? "neutral" : "brand"}>
            {r.tipo === "insumo" ? "Insumo" : "Composição"}
          </Badge>
        </span>
      ),
    },
    {
      key: "descricao",
      label: "Descrição",
      render: (r) => (
        <span className="grid gap-1">
          <span>{r.descricao}</span>
          <span className="text-[length:var(--gc-fs-xs)] text-secundario">
            {[r.classificacao, r.origem_preco ? `origem ${ORIGEM[r.origem_preco] ?? r.origem_preco}` : null, percentualSP(r.percentual_sp)]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
      ),
    },
    { key: "unidade", label: "Unid.", render: (r) => r.unidade ?? "—" },
    {
      key: "valor",
      label: "Custo (R$)",
      align: "right",
      render: (r) => <span className="gc-num" data-testid="custo-sinapi">{r.valor.exibicao}</span>,
    },
    {
      key: "origem",
      label: "Onde conferir",
      render: (r) => (
        <span className="grid gap-1 text-[length:var(--gc-fs-xs)]">
          <a href={r.planilha} rel="noopener noreferrer">
            Relatório oficial {r.competencia.slice(5)}/{r.competencia.slice(0, 4)}
          </a>
          <span className="text-secundario">
            aba {r.aba}, linha {r.linha_planilha} · {r.rotulo_regime}
          </span>
        </span>
      ),
    },
  ];
  return (
    <TableContainer>
      <DataTable
        compact
        caption="Custos de referência do SINAPI"
        minWidth="56rem"
        rowKey="registro_id"
        columns={colunas}
        rows={referencias}
      />
    </TableContainer>
  );
}
