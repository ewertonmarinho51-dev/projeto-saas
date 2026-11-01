"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { DataTable, IconButton, Menu, StatusBadge, TableContainer, type MenuItem } from "@/design-system";
import type { Processo } from "@/lib/api";

import { situacaoDoProcesso } from "./situacao";

const DATA = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });

/**
 * Tabela de processos (ProcessesScreen do ui_kit). Ordem, situação,
 * etapa e progresso vêm da API como estão — a tabela não reordena nem
 * filtra a página, para não fingir uma busca que o servidor não fez.
 *
 * O menu de linha só tem ação que existe: abrir, dados da demanda e
 * consolidar demandas (com o módulo ligado). Excluir não aparece: a API
 * não exclui processo (a 0020 não dá DELETE a quem está logado).
 */
export function TabelaDeProcessos({ processos, consolidar }: { processos: Processo[]; consolidar: boolean }) {
  const router = useRouter();
  const acoes = (p: Processo): MenuItem[] => [
    { label: "Abrir processo", icon: "arrow-right", onSelect: () => router.push(`/app/processos/${p.id}`) },
    { label: "Dados da demanda", icon: "pencil-simple", onSelect: () => router.push(`/app/processos/${p.id}/formulario`) },
    ...(consolidar
      ? [{ label: "Consolidar demandas", icon: "tray", onSelect: () => router.push(`/app/processos/${p.id}/demandas`) } as MenuItem]
      : []),
  ];
  return (
    <TableContainer>
      <DataTable
        caption="Processos do órgão"
        stack
        minWidth="calc(var(--space-16) * 12)"
        rows={processos}
        columns={[
          {
            key: "nome",
            label: "Processo",
            render: (p) => (
              <>
                <Link prefetch={false} href={`/app/processos/${p.id}`} className="font-[number:var(--weight-medium)] text-texto no-underline hover:underline">
                  {p.nome_exibido}
                </Link>
                <span className="gc-table__sub">{p.orgao}</span>
              </>
            ),
          },
          {
            key: "etapa",
            label: "Etapa atual",
            render: (p) => (
              <>
                {p.etapa}
                <span className="gc-table__sub">
                  {p.progresso.feitos} de {p.progresso.total} documentos aprovados
                </span>
              </>
            ),
          },
          {
            key: "atualizado_em",
            label: "Atualizado",
            render: (p) => (
              <span className="gc-num whitespace-nowrap">{p.atualizado_em ? DATA.format(new Date(p.atualizado_em)) : "—"}</span>
            ),
          },
          {
            key: "status",
            label: "Situação",
            render: (p) => <StatusBadge status={situacaoDoProcesso(p.status)} label={p.status} size="sm" />,
          },
          {
            key: "acoes",
            label: <span className="gc-sr-only">Ações</span>,
            width: "var(--space-12)",
            render: (p) => (
              <Menu
                align="end"
                trigger={({ toggle }) => (
                  <IconButton size="sm" icon="dots-three-vertical" label={`Mais ações: ${p.nome_exibido}`} onClick={toggle} />
                )}
                items={acoes(p)}
              />
            ),
          },
        ]}
      />
    </TableContainer>
  );
}
