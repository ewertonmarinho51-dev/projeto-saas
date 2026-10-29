import type { Metadata } from "next";
import Link from "next/link";

import { ListaDeProcessos } from "@/components/lista-processos";
import { rotuloEstadoPesquisa } from "@/components/precos";
import { situacaoDaPesquisa, STATUS } from "@/components/situacao";
import { Alert, Button, Card, EmptyState, Icon, KpiCard, PageHead, StatusBadge } from "@/design-system";
import { chamarApi, precosHabilitado, type Pagina, type Processo, type ResumoPesquisa } from "@/lib/api";

export const metadata: Metadata = { title: "Início" };

/** O máximo que a API entrega numa página: os indicadores contam sobre ela. */
const AMOSTRA = 100;

/** Pesquisas recentes, ou `null` quando o módulo está desligado ou a leitura falhou. */
async function pesquisasRecentes(): Promise<{ itens: ResumoPesquisa[] } | { falhou: true } | null> {
  if (!precosHabilitado()) return null;
  try {
    return { itens: (await chamarApi<Pagina<ResumoPesquisa>>("/precos/pesquisas?limit=5")).dados.itens };
  } catch {
    return { falhou: true };
  }
}

/**
 * Painel inicial (HomeScreen do ui_kit) com dados da API, só:
 * indicadores contados sobre os processos que a pessoa pode ver (o RLS
 * decide quais), situação e progresso como o domínio calculou, e as
 * pesquisas de preços recentes quando o módulo está ligado. Nenhum valor
 * monetário é somado aqui — o que aparece de dinheiro é a `exibicao` da
 * API, como veio.
 */
export default async function Inicio() {
  const [{ dados }, pesquisas] = await Promise.all([
    chamarApi<Pagina<Processo>>(`/processos?limit=${AMOSTRA}`),
    pesquisasRecentes(),
  ]);
  const processos = dados.itens;
  const parcial = dados.proximo_cursor !== null;
  const escopo = parcial ? `entre os ${AMOSTRA} mais recentes` : "no seu acesso";

  const contar = (status: string) => processos.filter((p) => p.status === status).length;
  const concluidos = contar(STATUS.concluido);
  const emRevisao = contar(STATUS.emRevisao);
  const andamento = processos.length - concluidos - contar(STATUS.arquivado);
  const aguardando = processos.filter((p) => p.status === STATUS.aguardandoPrecos);
  const aprovados = processos.reduce((s, p) => s + p.progresso.feitos, 0);
  const exigidos = processos.reduce((s, p) => s + p.progresso.total, 0);
  const comPrecos = pesquisas !== null;

  return (
    <>
      <PageHead
        title="Início"
        desc="O andamento dos processos do seu órgão e o que está esperando por você."
        actions={
          <>
            {comPrecos && (
              <Button variant="secondary" icon="currency-circle-dollar" href="/app/precos/nova">
                Nova pesquisa de preços
              </Button>
            )}
            <Button icon="plus" href="/app/processos#novo">
              Novo processo
            </Button>
          </>
        }
      />

      {processos.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Processos em andamento" value={andamento} icon="folder-open" footnote={escopo} />
          <KpiCard
            label="Documentos aprovados"
            value={aprovados}
            icon="file-text"
            footnote={`de ${exigidos} exigidos pelos processos`}
          />
          <KpiCard
            label="Em revisão"
            value={emRevisao}
            icon="eye"
            footnote="documento gerado esperando conferência"
          />
          <KpiCard label="Concluídos" value={concluidos} icon="check-circle" footnote="todos os documentos aprovados" />
        </div>
      )}

      {aguardando.length > 0 && (
        <Alert
          variant="warning"
          title={
            aguardando.length === 1
              ? "1 processo aguardando pesquisa de preços"
              : `${aguardando.length} processos aguardando pesquisa de preços`
          }
          actions={
            <>
              <Button size="sm" variant="secondary" href={`/app/processos/${aguardando[0].id}`}>
                Abrir {aguardando.length === 1 ? "o processo" : "o mais recente"}
              </Button>
              {comPrecos && (
                <Button size="sm" variant="ghost" href="/app/precos">
                  Ir para Preços
                </Button>
              )}
            </>
          }
        >
          O DFD já foi aprovado e o ETP e o TR dependem do valor estimado: falta aplicar uma pesquisa de preços.
        </Alert>
      )}

      <Card
        title="Processos recentes"
        subtitle="Os últimos atualizados no seu órgão."
        flush
        actions={
          processos.length > 0 && (
            <Button variant="link" size="sm" href="/app/processos">
              Ver todos
            </Button>
          )
        }
      >
        {processos.length > 0 ? (
          <ListaDeProcessos processos={processos.slice(0, 5)} />
        ) : (
          <EmptyState
            title="Nenhum processo ainda"
            description="Comece registrando o órgão e o objeto da contratação. Os documentos vêm depois."
            actions={
              <Button icon="plus" href="/app/processos#novo">
                Novo processo
              </Button>
            }
          />
        )}
      </Card>

      {pesquisas && (
        <Card
          title="Pesquisas de preços recentes"
          subtitle="Cada valor com fonte, data e critério registrados."
          flush
          actions={
            <Button variant="link" size="sm" href="/app/precos">
              Ver todas
            </Button>
          }
        >
          {"falhou" in pesquisas ? (
            <div className="p-5">
              <Alert variant="neutral" compact>
                Não foi possível carregar as pesquisas agora. A lista completa está em Preços.
              </Alert>
            </div>
          ) : pesquisas.itens.length > 0 ? (
            <ul className="divide-y divide-linha">
              {pesquisas.itens.map((q) => (
                <li key={q.id}>
                  <Link
                    href={`/app/precos/${q.id}`}
                    className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 gap-y-2 px-5 py-3.5 text-texto no-underline transition-colors hover:bg-[var(--surface-hover)] hover:text-texto md:grid-cols-[minmax(0,1fr)_auto_auto_var(--space-4)]"
                  >
                    <span className="grid min-w-0 gap-1">
                      <span className="truncate font-[number:var(--weight-medium)]">{q.nome || q.objeto}</span>
                      {q.nome && q.objeto && (
                        <span className="truncate text-[length:var(--gc-fs-sm)] text-secundario">{q.objeto}</span>
                      )}
                    </span>
                    <span className="gc-num text-[length:var(--gc-fs-sm)] text-secundario">
                      {q.valor_global ? q.valor_global.exibicao : "Sem valor global"}
                    </span>
                    <StatusBadge status={situacaoDaPesquisa(q.estado)} label={rotuloEstadoPesquisa(q.estado)} />
                    <Icon
                      name="caret-right"
                      className="hidden text-[color:var(--text-tertiary)] transition-transform group-hover:translate-x-0.5 md:block"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon="currency-circle-dollar"
              title="Nenhuma pesquisa de preços ainda"
              description="Importe a planilha de itens e o sistema busca referências em fontes oficiais."
              actions={
                <Button variant="secondary" href="/app/precos/nova">
                  Nova pesquisa de preços
                </Button>
              }
            />
          )}
        </Card>
      )}
    </>
  );
}
