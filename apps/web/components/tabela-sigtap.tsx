"use client";

import { Badge, DataTable, TableContainer, type DataTableColumn } from "@/design-system";
import type { ProcedimentoSigtap } from "@/lib/api";

/**
 * Procedimentos do SIGTAP com o que se confere na fonte: código, modalidades,
 * as parcelas SA, SH e SP, os totais ambulatorial (SA) e hospitalar (SH + SP),
 * e o arquivo oficial do DATASUS com a linha. Valor zero é dado da tabela, e
 * a linha diz isso. Tabela de valores: rola, não empilha.
 */
export function TabelaSigtap({ procedimentos }: { procedimentos: ProcedimentoSigtap[] }) {
  const colunas: DataTableColumn<ProcedimentoSigtap>[] = [
    {
      key: "codigo",
      label: "Código",
      render: (p) => <span className="gc-mono">{p.codigo_formatado}</span>,
    },
    {
      key: "nome",
      label: "Procedimento",
      render: (p) => (
        <span className="grid gap-1">
          <span>{p.nome}</span>
          <span className="flex flex-wrap gap-1">
            {p.modalidades.map((m) => (
              <Badge key={m} size="sm" variant="neutral">
                {m}
              </Badge>
            ))}
          </span>
          <span className="text-[length:var(--gc-fs-xs)] text-secundario">
            {[p.grupo, p.subgrupo, p.forma_organizacao, p.financiamento].filter(Boolean).join(" · ")}
          </span>
        </span>
      ),
    },
    {
      key: "ambulatorial",
      label: "Ambulatorial (SA)",
      align: "right",
      render: (p) => (
        <span className="gc-num" data-testid="sigtap-sa">
          {p.total_ambulatorial.exibicao}
        </span>
      ),
    },
    {
      key: "hospitalar",
      label: "Hospitalar (SH + SP)",
      align: "right",
      render: (p) => (
        <span className="grid gap-1 justify-items-end">
          <span className="gc-num" data-testid="sigtap-hospitalar">
            {p.total_hospitalar.exibicao}
          </span>
          <span className="gc-num text-[length:var(--gc-fs-xs)] text-secundario">
            SH {p.valor_sh.exibicao} · SP {p.valor_sp.exibicao}
          </span>
        </span>
      ),
    },
    {
      key: "origem",
      label: "Onde conferir",
      render: (p) => (
        <span className="grid gap-1 text-[length:var(--gc-fs-xs)]">
          <a href={p.arquivo_url} rel="noopener noreferrer">
            Tabela Unificada {p.competencia_exibicao}
          </a>
          <span className="text-secundario">
            tb_procedimento, linha {p.linha_arquivo}
            {p.sem_valor ? " · sem valor unitário na tabela" : ""}
          </span>
        </span>
      ),
    },
  ];
  return (
    <TableContainer>
      <DataTable
        compact
        caption="Remuneração da Tabela Unificada do SUS"
        minWidth="56rem"
        rowKey="registro_id"
        columns={colunas}
        rows={procedimentos}
      />
    </TableContainer>
  );
}
