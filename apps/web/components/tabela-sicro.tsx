"use client";

import { Badge, DataTable, TableContainer, type DataTableColumn } from "@/design-system";
import type { ReferenciaSicro } from "@/lib/api";

/**
 * Referências do SICRO com tudo o que se confere na fonte: código, tipo,
 * unidade, custo (equipamento: produtivo e improdutivo), regime, origem do
 * preço na UF e o relatório de dentro do 7-Zip oficial, com a linha.
 * Tabela de custo: rola, não empilha.
 */
export function TabelaSicro({ referencias }: { referencias: ReferenciaSicro[] }) {
  const colunas: DataTableColumn<ReferenciaSicro>[] = [
    {
      key: "codigo",
      label: "Código",
      render: (r) => (
        <span className="grid gap-1">
          <span className="gc-mono">{r.codigo}</span>
          <Badge size="sm" variant={r.tipo === "composicao" ? "brand" : "neutral"}>
            {r.rotulo_tipo}
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
            {[r.rotulo_regime, r.rotulo_origem ? `origem: ${r.rotulo_origem} (${r.origem_preco})` : null]
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
      render: (r) => (
        <span className="grid gap-1 justify-items-end">
          <span className="gc-num" data-testid="custo-sicro">
            {r.valor.exibicao}
          </span>
          {r.valor_improdutivo && (
            <span className="gc-num text-[length:var(--gc-fs-xs)] text-secundario" data-testid="improdutivo-sicro">
              produtivo; improdutivo {r.valor_improdutivo.exibicao}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "origem",
      label: "Onde conferir",
      render: (r) => (
        <span className="grid gap-1 text-[length:var(--gc-fs-xs)]">
          <a href={r.arquivo_url} rel="noopener noreferrer">
            Arquivo oficial {r.competencia.slice(5)}/{r.competencia.slice(0, 4)} ({r.arquivo})
          </a>
          <span className="text-secundario">
            {r.planilha.replace(/\.xlsx$/, "")}, linha {r.linha_planilha}
          </span>
        </span>
      ),
    },
  ];
  return (
    <TableContainer>
      <DataTable
        compact
        caption="Custos de referência do SICRO"
        minWidth="56rem"
        rowKey="registro_id"
        columns={colunas}
        rows={referencias}
      />
    </TableContainer>
  );
}
