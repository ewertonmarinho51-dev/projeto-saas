"use client";

import { Badge, DataTable, type DataTableColumn } from "@/design-system";
import type { CustoSinapi } from "@/lib/api";

/**
 * Resultado da consulta ao SINAPI. Cada linha diz de onde veio: o arquivo
 * oficial da competência, a aba e a linha da planilha da CAIXA — é o que
 * permite conferir o valor na edição publicada. Os valores são as `exibicao`
 * da API; nada é somado nem convertido aqui.
 */
export function CustosSinapi({ itens }: { itens: CustoSinapi[] }) {
  const colunas: DataTableColumn<CustoSinapi>[] = [
    {
      key: "codigo",
      label: "Código",
      render: (x) => <span className="gc-mono">{x.codigo}</span>,
    },
    {
      key: "descricao",
      label: "Descrição",
      render: (x) => (
        <span className="grid gap-1">
          <span>{x.descricao}</span>
          <span className="flex flex-wrap items-center gap-2 text-[length:var(--gc-fs-xs)] text-secundario">
            <Badge size="sm">{x.rotulo_tipo}</Badge>
            {x.classificacao && <span>{x.classificacao}</span>}
            {x.rotulo_origem && <span>Preço {x.rotulo_origem}</span>}
            {x.percentual_sp && Number(x.percentual_sp) > 0 && (
              <span>Parte do custo com preço de SP: {(Number(x.percentual_sp) * 100).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%</span>
            )}
          </span>
        </span>
      ),
    },
    { key: "unidade", label: "Unidade" },
    {
      key: "valor",
      label: "Custo (R$)",
      align: "right",
      render: (x) => <span className="gc-num">{x.valor.exibicao}</span>,
    },
    {
      key: "origem",
      label: "Origem",
      render: (x) => (
        <span className="grid gap-1 text-[length:var(--gc-fs-xs)] text-secundario">
          <span>
            {x.uf} · {x.competencia_exibicao} · {x.rotulo_regime}
          </span>
          <a href={x.url_verificacao} target="_blank" rel="noopener noreferrer">
            Arquivo oficial, aba {x.aba}, linha {x.linha_planilha}
          </a>
          <span className="gc-mono" title={x.arquivo_sha256}>
            versão {x.arquivo_sha256.slice(0, 12)}
          </span>
        </span>
      ),
    },
  ];
  return (
    <DataTable
      compact
      caption="Custos de referência do SINAPI"
      minWidth="56rem"
      rowKey="chave_linha"
      columns={colunas}
      rows={itens}
    />
  );
}
