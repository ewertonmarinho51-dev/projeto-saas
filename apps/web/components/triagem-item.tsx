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

import { AvisoDaCesta, ControleDaCesta, useCestaDoItem } from "./cesta-do-item";
import { AlertaDoPreco } from "./gestao-cotacao";
import { dataCurta, naCesta, rotuloNatureza, rotuloStatusReferencia } from "./precos";

/**
 * Situação visual de cada referência, pela marcação QUE A TELA MOSTRA (a do
 * último clique, que a fila grava em segundo plano). Discrepante é a que tem
 * o card "Confira este preço" da API ainda sem decisão — sinal para revisão
 * humana, nunca exclusão automática.
 */
function situacao(r: ReferenciaDePreco, dentro: boolean, alerta: AlertaDePreco | undefined): ReferenceStatus {
  if (alerta && !alerta.mantida) return "discrepant";
  if (dentro) return r.status === "warning" ? "attention" : "compatible";
  if (r.status === "manual_review") return "attention";
  if (r.status === "rejected") return "excluded";
  return "pending";
}

const PENDENCIAS = new Set(["warning", "manual_review"]);

/** O status que a linha mostra enquanto a marcação nova é gravada. */
function statusMostrado(r: ReferenciaDePreco, dentro: boolean): string {
  if (dentro) return r.status === "warning" ? "warning" : "selected";
  return naCesta(r) ? "rejected" : r.status;
}

/** Rastreabilidade completa, no ícone de informação — o cartão fica limpo. */
function VerOrigem({ r }: { r: ReferenciaDePreco }) {
  const [aberto, setAberto] = useState(false);
  const reg = r.registro_original;
  const campos: DataListItem[] = [
    { label: "Descrição na fonte", value: r.descricao_original },
    ...(reg?.numero_item ? [{ label: "Número do item", value: String(reg.numero_item), numeric: true }] : []),
    { label: "Órgão", value: r.orgao || "Não informado" },
    { label: "Local", value: [r.municipio, r.uf].filter(Boolean).join("/") || "Não informado" },
    { label: "Fornecedor", value: r.fornecedor || "Não informado" },
    { label: "Data da compra", value: dataCurta(r.data_compra) || "Não informada" },
    ...(r.data_resultado ? [{ label: "Data do resultado", value: dataCurta(r.data_resultado) }] : []),
    { label: "Coletada em", value: dataCurta(r.coletado_em) },
    { label: "Fonte consultada", value: r.fonte },
    ...(r.origem ? [{ label: "Origem da compra", value: r.origem }] : []),
    ...(r.canal ? [{ label: "Canal da coleta", value: r.canal }] : []),
    {
      label: "Número de controle",
      value: r.identificacao ? <span className="gc-mono">{r.identificacao}</span> : "Não informado",
    },
    { label: "Natureza do valor", value: rotuloNatureza(r.natureza_valor) },
    {
      label: "Valor original",
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
    ...(r.equivalencia_detalhe ? [{ label: "Equivalência com o item", value: r.equivalencia_detalhe }] : []),
  ];
  if (PENDENCIAS.has(r.status) && r.motivos.length > 0) {
    campos.push({ label: "Motivo da revisão", value: r.motivos.join("; ") });
  }
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
          url={reg?.pagina_url ?? undefined}
          urlLabel={reg?.pagina_rotulo || undefined}
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
 * "Consultar registro original": o item exato e o resultado oficial que deram
 * origem ao preço, legíveis. O PNCP não tem página por item: mostra-se o
 * resultado lido da fonte oficial, com o link de origem (a contratação) e o
 * dado oficial exato do resultado do item.
 */
function RegistroOriginal({ r }: { r: ReferenciaDePreco }) {
  const [aberto, setAberto] = useState(false);
  const reg = r.registro_original;
  if (!reg) return null;
  const campos: DataListItem[] = [
    { label: "Fonte oficial", value: reg.fonte },
    ...(reg.numero_controle ? [{ label: "Número de controle", value: <span className="gc-mono">{reg.numero_controle}</span> }] : []),
    ...(reg.numero_item ? [{ label: "Item", value: String(reg.numero_item), numeric: true }] : []),
    { label: "Descrição do item", value: reg.descricao || "Não informada" },
    ...(reg.quantidade ? [{ label: "Quantidade homologada", value: `${reg.quantidade.exibicao} ${reg.unidade}`.trim(), numeric: true }] : []),
    {
      label: "Valor unitário homologado",
      value: <span data-testid="registro-valor-unitario">{reg.valor_unitario?.exibicao ?? "Não informado"}</span>,
      numeric: true,
    },
    ...(reg.valor_total ? [{ label: "Valor total homologado", value: reg.valor_total.exibicao, numeric: true }] : []),
    ...(reg.fornecedor ? [{ label: "Fornecedor", value: reg.fornecedor }] : []),
    ...(reg.data_resultado ? [{ label: "Data do resultado", value: dataCurta(reg.data_resultado) }] : []),
  ];
  return (
    <>
      <Button variant="link" size="sm" icon="arrow-square-out" onClick={() => setAberto(true)} data-testid="consultar-registro">
        Consultar registro original
      </Button>
      <Dialog
        open={aberto}
        onClose={() => setAberto(false)}
        icon="file-text"
        size="lg"
        title="Registro original"
        description="O resultado da fonte oficial que deu origem a este preço."
        footer={
          <Button variant="secondary" onClick={() => setAberto(false)}>
            Fechar
          </Button>
        }
      >
        <div className="grid gap-4" data-testid="registro-original">
          {/* o link de origem vai no próprio painel: sem ele, o painel diria
              "sem URL pública" logo acima dos links (aceite de 13/11) */}
          <TraceabilityPanel
            fields={campos}
            url={reg.pagina_url ?? undefined}
            urlLabel={reg.pagina_rotulo || "Abrir na fonte oficial"}
          />
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {reg.dados_url && (
              <a href={reg.dados_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-[length:var(--gc-fs-sm)] text-acento underline">
                Dado oficial do resultado
                <Icon name="arrow-square-out" />
              </a>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}

/**
 * Triagem do item: contadores que filtram a lista e, em cada referência, o
 * controle da cesta em UM clique (`ControleDaCesta`, gravado em segundo plano).
 * As linhas ficam na ordem em que apareceram — marcar não as move de lugar.
 * Os valores são as `exibicao` da API — nada é somado nem convertido aqui.
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
  const fila = useCestaDoItem();
  const [filtro, setFiltro] = useState<ScreeningKey | null>(null);
  // A API ordena por valor e id — marcar não muda a posição da linha.
  const ordenadas = referencias;

  const alertaDe = new Map(alertas.map((a) => [a.referencia_id, a]));
  const dentro = (r: ReferenciaDePreco) => (fila ? fila.marcado(r.id, naCesta(r)) : naCesta(r));
  const linhas = ordenadas.map((r) => ({ r, d: dentro(r), s: situacao(r, dentro(r), alertaDe.get(r.id)) }));
  const contagem: Partial<Record<ScreeningKey, number>> = {
    total: linhas.length,
    valid: linhas.filter(({ d }) => d).length,
    attention: linhas.filter(({ s }) => s === "attention").length,
    discrepant: linhas.filter(({ s }) => s === "discrepant").length,
    excluded: linhas.filter(({ d }) => !d).length,
  };
  const visiveis = linhas.filter(({ d, s }) => {
    if (!filtro || filtro === "total") return true;
    if (filtro === "valid") return d;
    if (filtro === "excluded") return !d;
    return s === filtro;
  });
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
      <AvisoDaCesta />
      <ul className="grid gap-3">
        {visiveis.map(({ r, d, s }) => (
          <li key={r.id} className="grid gap-2" data-testid="referencia" data-na-cesta={d ? "1" : "0"}>
            <PriceReferenceRow
              title={r.descricao_original}
              source={r.fonte}
              agency={[r.orgao, [r.municipio, r.uf].filter(Boolean).join("/")].filter(Boolean).join(" · ") || undefined}
              date={r.data_compra ? `Compra em ${dataCurta(r.data_compra)}` : `Coletada em ${dataCurta(r.coletado_em)}`}
              value={r.valor_unitario_normalizado?.exibicao ?? r.valor_unitario_original?.exibicao ?? ""}
              unitNote={`por ${r.unidade_normalizada ?? r.unidade_original ?? "unidade"}`}
              status={s}
              statusLabel={rotuloStatusReferencia(statusMostrado(r, d))}
              actions={
                <span className="flex items-center gap-1">
                  <VerOrigem r={r} />
                  {editavel && !concluido && <ControleDaCesta referencia={r.id} naCesta={naCesta(r)} />}
                </span>
              }
            />
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 text-[length:var(--gc-fs-xs)] text-secundario">
              <span data-testid="natureza">{rotuloNatureza(r.natureza_valor)}</span>
              <RegistroOriginal r={r} />
            </div>
            {alertaDe.has(r.id) && (
              <div className="px-4">
                <AlertaDoPreco
                  pesquisa={pesquisa}
                  item={item.id}
                  revisao={item.revisao}
                  alerta={alertaDe.get(r.id)!}
                  editavel={editavel && !concluido}
                />
              </div>
            )}
          </li>
        ))}
        {visiveis.length === 0 && <li className="gc-help px-3">Nenhuma referência neste filtro.</li>}
      </ul>
      {concluido && (
        <p className="text-[length:var(--gc-fs-xs)] text-secundario">Item concluído: reabra para alterar a cesta.</p>
      )}
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
      scroll
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
