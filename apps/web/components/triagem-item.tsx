"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  Badge,
  Button,
  Dialog,
  Icon,
  IconButton,
  PriceItemNav,
  PriceReferenceRow,
  ScreeningSummary,
  TraceabilityPanel,
  type DataListItem,
  type PriceItem,
  type ReferenceStatus,
  type ScreeningKey,
} from "@/design-system";
import type { AlertaDePreco, ItemDePesquisa, ReferenciaDePreco } from "@/lib/api";

import { AcaoNaCesta } from "./acao-cesta";
import { AlertaDoPreco } from "./gestao-cotacao";
import { dataCurta, naCesta, rotuloNatureza, rotuloStatusReferencia } from "./precos";

/**
 * Situação visual de cada referência. Discrepante é a que tem o card
 * "Confira este preço" da API ainda sem decisão — sinal para revisão
 * humana, nunca exclusão automática (a API não tira nada sozinha).
 */
function situacao(r: ReferenciaDePreco, alerta: AlertaDePreco | undefined): ReferenceStatus {
  if (alerta && !alerta.mantida) return "discrepant";
  if (r.status === "selected") return "compatible";
  if (r.status === "warning" || r.status === "manual_review") return "attention";
  if (r.status === "rejected") return "excluded";
  return "pending";
}

function noFiltro(chave: ScreeningKey | null, r: ReferenciaDePreco, s: ReferenceStatus): boolean {
  if (!chave || chave === "total") return true;
  if (chave === "valid") return naCesta(r);
  if (chave === "excluded") return !naCesta(r);
  return s === chave;
}

/** Origem da referência, só com o que a coleta registrou — nunca presume verificação. */
function VerOrigem({ r }: { r: ReferenciaDePreco }) {
  const [aberto, setAberto] = useState(false);
  const campos: DataListItem[] = [
    { label: "Fonte consultada", value: r.fonte },
    { label: "Natureza do valor", value: rotuloNatureza(r.natureza_valor) },
    { label: "Identificador do registro", value: r.identificacao ? <span className="gc-mono">{r.identificacao}</span> : "Não informado" },
    { label: "Órgão", value: r.orgao || "Não informado" },
    { label: "Local", value: [r.municipio, r.uf].filter(Boolean).join("/") || "Não informado" },
    { label: "Fornecedor", value: r.fornecedor || "Não informado" },
    { label: "Data da compra", value: dataCurta(r.data_compra) || "Não informada" },
    { label: "Coletada em", value: dataCurta(r.coletado_em) },
    { label: "Descrição na fonte", value: r.descricao_original },
    {
      label: "Valor na fonte",
      value: r.valor_unitario_original
        ? `${r.valor_unitario_original.exibicao} por ${r.unidade_original ?? "unidade"}`
        : "Não informado",
      numeric: true,
    },
    {
      label: "Valor normalizado",
      value: r.valor_unitario_normalizado
        ? `${r.valor_unitario_normalizado.exibicao} por ${r.unidade_normalizada ?? "unidade"}`
        : "Não normalizado",
      numeric: true,
    },
  ];
  if (r.motivos.length > 0) campos.push({ label: "Observações", value: r.motivos.join(", ") });
  return (
    <>
      <IconButton size="sm" icon="info" label="Ver origem" onClick={() => setAberto(true)} />
      <Dialog
        open={aberto}
        onClose={() => setAberto(false)}
        icon="database"
        size="lg"
        title="Rastreabilidade da referência"
        description="Confira a origem antes de usar o preço."
        footer={
          <Button variant="secondary" onClick={() => setAberto(false)}>
            Fechar
          </Button>
        }
      >
        <TraceabilityPanel
          fields={campos}
          url={r.link_fonte ?? r.link_contratacao ?? undefined}
          status={
            <Badge variant="neutral" size="sm">
              {rotuloStatusReferencia(r.status)}
            </Badge>
          }
        />
      </Dialog>
    </>
  );
}

/**
 * Triagem do item (PriceResearchScreen do ui_kit): contadores que filtram
 * a lista, cada referência com fonte, órgão, data, valor e situação, e a
 * ação de cesta da API (`AcaoNaCesta`, com a revisão no If-Match). Os
 * valores são as `exibicao` da API — nada é somado nem convertido aqui.
 */
export function TriagemDoItem({
  pesquisa,
  item,
  referencias,
  alertas,
  editavel,
}: {
  pesquisa: string;
  item: Pick<ItemDePesquisa, "id" | "revisao" | "estado">;
  referencias: ReferenciaDePreco[];
  alertas: AlertaDePreco[];
  editavel: boolean;
}) {
  const [filtro, setFiltro] = useState<ScreeningKey | null>(null);
  const alertaDe = new Map(alertas.map((a) => [a.referencia_id, a]));
  const linhas = referencias.map((r) => ({ r, s: situacao(r, alertaDe.get(r.id)) }));
  const contagem: Partial<Record<ScreeningKey, number>> = {
    total: linhas.length,
    valid: linhas.filter(({ r }) => naCesta(r)).length,
    attention: linhas.filter(({ s }) => s === "attention").length,
    discrepant: linhas.filter(({ s }) => s === "discrepant").length,
    excluded: linhas.filter(({ r }) => !naCesta(r)).length,
  };
  const visiveis = linhas.filter(({ r, s }) => noFiltro(filtro, r, s));
  const concluido = item.estado === "complete";

  if (referencias.length === 0) {
    return (
      <p className="gc-card px-6 py-10 text-center text-[length:var(--gc-fs-sm)] text-secundario">
        Nenhuma referência coletada para este item.
      </p>
    );
  }

  return (
    <div className="grid gap-4">
      <ScreeningSummary counts={contagem} active={filtro} onFilter={setFiltro} />
      <ul className="grid gap-3" aria-live="polite">
        {visiveis.map(({ r, s }) => (
          <li key={r.id} className="grid gap-2" data-testid="referencia">
            <PriceReferenceRow
              title={r.descricao_original}
              source={r.fonte}
              agency={[r.orgao, [r.municipio, r.uf].filter(Boolean).join("/")].filter(Boolean).join(" · ") || undefined}
              date={r.data_compra ? `Compra em ${dataCurta(r.data_compra)}` : `Coletada em ${dataCurta(r.coletado_em)}`}
              value={r.valor_unitario_normalizado?.exibicao ?? r.valor_unitario_original?.exibicao ?? ""}
              unitNote={`por ${r.unidade_normalizada ?? r.unidade_original ?? "unidade"}`}
              status={s}
              statusLabel={rotuloStatusReferencia(r.status)}
              actions={<VerOrigem r={r} />}
            />
            <div className="flex flex-wrap items-start justify-between gap-3 px-4">
              <div className="grid min-w-0 flex-1 gap-2 text-[length:var(--gc-fs-xs)] text-secundario">
                <span>
                  {rotuloNatureza(r.natureza_valor)}
                  {r.identificacao && <span className="gc-mono"> · {r.identificacao}</span>}
                </span>
                {alertaDe.has(r.id) && (
                  <AlertaDoPreco
                    pesquisa={pesquisa}
                    item={item.id}
                    revisao={item.revisao}
                    alerta={alertaDe.get(r.id)!}
                    editavel={editavel && !concluido}
                  />
                )}
                {r.motivos.length > 0 && <span>Observações: {r.motivos.join(", ")}</span>}
                {r.link_contratacao && (
                  <a
                    href={r.link_contratacao}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 justify-self-start text-[length:var(--gc-fs-sm)]"
                  >
                    {r.rotulo_contratacao || "Ver na fonte"}
                    <Icon name="arrow-square-out" />
                  </a>
                )}
              </div>
              {concluido ? (
                <p className="text-[length:var(--gc-fs-xs)] text-secundario">Item concluído: reabra para alterar a cesta.</p>
              ) : (
                <AcaoNaCesta pesquisa={pesquisa} item={item.id} referencia={r.id} revisao={item.revisao} naCesta={naCesta(r)} />
              )}
            </div>
          </li>
        ))}
        {visiveis.length === 0 && <li className="gc-help px-3">Nenhuma referência neste filtro.</li>}
      </ul>
    </div>
  );
}

/** Navegação entre os itens da pesquisa (PriceItemNav), por rota: cada item é uma página. */
export function NavegadorDeItens({ pesquisa, itens, atual }: { pesquisa: string; itens: ItemDePesquisa[]; atual: string }) {
  const router = useRouter();
  const situacaoNav: Record<string, PriceItem["status"]> = {
    complete: "done",
    review: "review",
    error: "blocked",
    incomplete: "blocked",
  };
  return (
    <PriceItemNav
      activeId={atual}
      onSelect={(id) => router.push(`/app/precos/${pesquisa}/itens/${id}`)}
      items={itens.map((i) => ({
        id: i.id,
        n: String(i.numero).padStart(2, "0"),
        title: i.descricao,
        unit: i.unidade,
        value: i.preco_estimado?.exibicao,
        status: situacaoNav[i.estado] ?? "pending",
      }))}
    />
  );
}
