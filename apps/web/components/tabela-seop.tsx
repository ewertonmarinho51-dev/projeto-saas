"use client";

import { DataTable, TableContainer, type DataTableColumn } from "@/design-system";
import type { CustoSeop } from "@/lib/api";

/**
 * Linhas da Planilha Padrão da SEOP-PA com o que se confere na fonte:
 * código, item, grupo, unidade, custo, BDI e desoneração como a publicação
 * declara, e o PDF oficial aberto na PÁGINA da linha. Tabela de preço: rola,
 * não empilha.
 */
export function TabelaSeop({ referencias }: { referencias: CustoSeop[] }) {
  const colunas: DataTableColumn<CustoSeop>[] = [
    { key: "codigo", label: "Código", render: (r) => <span className="gc-mono">{r.codigo}</span> },
    {
      key: "descricao",
      label: "Descrição",
      render: (r) => (
        <span className="grid gap-1">
          <span>{r.descricao}</span>
          <span className="text-[length:var(--gc-fs-xs)] text-secundario">
            {[`item ${r.item}`, r.grupo].filter(Boolean).join(" · ")}
          </span>
        </span>
      ),
    },
    { key: "unidade", label: "Unid." },
    {
      key: "valor",
      label: "Custo (R$)",
      align: "right",
      render: (r) => <span className="gc-num" data-testid="custo-seop">{r.valor.exibicao}</span>,
    },
    {
      key: "origem",
      label: "Onde conferir",
      render: (r) => (
        <span className="grid gap-1 text-[length:var(--gc-fs-xs)]">
          <a href={r.url_verificacao} rel="noopener noreferrer">
            Planilha Padrão {r.competencia_exibicao}, página {r.pagina}
          </a>
          <span className="text-secundario">{[r.bdi, r.desoneracao].filter(Boolean).join(" · ").toLowerCase()}</span>
        </span>
      ),
    },
  ];
  return (
    <TableContainer>
      <DataTable
        compact
        caption="Custos de referência da SEOP-PA"
        minWidth="52rem"
        rowKey="registro_id"
        columns={colunas}
        rows={referencias}
      />
    </TableContainer>
  );
}
