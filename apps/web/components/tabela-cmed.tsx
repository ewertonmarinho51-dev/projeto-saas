"use client";

import { Badge, DataTable, TableContainer, type DataTableColumn } from "@/design-system";
import type { TetoCmed } from "@/lib/api";

function dataDaLista(iso: string): string {
  const [ano, mes, dia] = iso.slice(0, 10).split("-");
  return `${dia}/${mes}/${ano}`;
}

/**
 * Tetos CMED por apresentação, na alíquota pedida: o teto na venda ao
 * governo (com a base — PMVG com CAP ou PF), o PF e o PMVG lado a lado, as
 * marcas que mudam o teto (CAP, isenção de ICMS, uso hospitalar) e a lista
 * oficial com a linha. Tabela de preço: rola, não empilha.
 */
export function TabelaCmed({ tetos }: { tetos: TetoCmed[] }) {
  const colunas: DataTableColumn<TetoCmed>[] = [
    {
      key: "apresentacao",
      label: "Apresentação",
      render: (t) => (
        <span className="grid gap-1">
          <span>
            <strong>{t.produto}</strong> {t.apresentacao}
          </span>
          <span className="text-[length:var(--gc-fs-xs)] text-secundario">
            {[t.substancia, t.laboratorio, t.tipo_produto].filter(Boolean).join(" · ")}
          </span>
          <span className="flex flex-wrap gap-1">
            {t.cap && (
              <Badge size="sm" variant="brand">
                CAP
              </Badge>
            )}
            {t.isento_icms && (
              <Badge size="sm" variant="warning">
                Isento de ICMS
              </Badge>
            )}
            {t.restricao_hospitalar && (
              <Badge size="sm" variant="neutral">
                Uso hospitalar
              </Badge>
            )}
            {t.analise_recursal && (
              <Badge size="sm" variant="neutral">
                Em análise recursal
              </Badge>
            )}
          </span>
        </span>
      ),
    },
    {
      key: "teto",
      label: "Teto na venda ao governo",
      align: "right",
      render: (t) => (
        <span className="grid gap-1 justify-items-end">
          <span className="gc-num" data-testid="teto-cmed">
            {t.teto_governo.exibicao}
          </span>
          <span className="text-[length:var(--gc-fs-xs)] text-secundario">{t.base_do_teto}</span>
          {t.isento_icms && (
            <span className="gc-num text-[length:var(--gc-fs-xs)] text-secundario" data-testid="teto-isento-cmed">
              isento (ICMS 0%): {t.teto_governo_isento.exibicao}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "pf",
      label: "PF",
      align: "right",
      render: (t) => <span className="gc-num">{t.pf.exibicao}</span>,
    },
    {
      key: "pmvg",
      label: "PMVG",
      align: "right",
      render: (t) => <span className="gc-num">{t.pmvg.exibicao}</span>,
    },
    {
      key: "origem",
      label: "Onde conferir",
      render: (t) => (
        <span className="grid gap-1 text-[length:var(--gc-fs-xs)]">
          <a href={t.arquivo_url} rel="noopener noreferrer">
            Lista CMED de {dataDaLista(t.publicada_em)}
          </a>
          <span className="text-secundario">
            linha {t.linha_planilha} · GGREM <span className="gc-mono">{t.ggrem}</span>
            {t.eans.length > 0 && (
              <>
                {" "}
                · EAN <span className="gc-mono">{t.eans.join(", ")}</span>
              </>
            )}
          </span>
        </span>
      ),
    },
  ];
  return (
    <TableContainer>
      <DataTable
        compact
        caption="Tetos CMED de medicamentos"
        minWidth="60rem"
        rowKey="registro_id"
        columns={colunas}
        rows={tetos}
      />
    </TableContainer>
  );
}
