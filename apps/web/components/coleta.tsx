"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef, type RefObject } from "react";

import { iniciarColeta, type EstadoDaColeta } from "@/app/app/precos/acoes";
import { useJob } from "@/components/acompanhar-job";
import { DESFECHOS_DO_LOTE } from "@/components/precos";
import { Alert, Badge, Button, Card, DataList, JobProgress } from "@/design-system";
import type { ItemDePesquisa, Job } from "@/lib/api";

/** Rolar até o painel deixa a barra superior fixa sem cobri-lo. */
const ALVO = "scroll-mt-[calc(var(--topbar-height)+var(--space-4))]";
const SEM_REFERENCIA = "sem_referencia_compativel";

/** A causa; a tela acrescenta como retomar (exceto IMMUTABLE, que não retoma). */
const FALHAS: Record<string, string> = {
  SESSION_EXPIRED: "A coleta parou porque sua sessão estava terminando.",
  IMMUTABLE: "Esta pesquisa já foi aplicada ou arquivada e não recebe nova coleta.",
  DATABASE_UNAVAILABLE: "O banco não respondeu durante a coleta.",
  QUEUE_UNAVAILABLE: "A coleta não chegou a começar.",
};

type ItemResumido = Pick<ItemDePesquisa, "id" | "numero" | "descricao" | "unidade" | "pendencia">;

/**
 * Botões da coleta e, com `?job=` na URL, o acompanhamento do lote. Um só
 * componente porque o export do Claude Design põe o "Coletar preços" em
 * carregamento ("Coletando…", desabilitado) enquanto o lote anda — o painel
 * não tem botão próprio: retomar é o mesmo "Coletar preços".
 *
 * O lote vem da URL: recarregar a página retoma o MESMO lote.
 */
export function ColetaDaPesquisa({
  pesquisa,
  chave,
  jobId,
  editavel,
  itens,
}: {
  pesquisa: string;
  chave: string;
  jobId: string | null;
  editavel: boolean;
  itens: ItemResumido[];
}) {
  if (!jobId) return editavel ? <BotaoDeColeta pesquisa={pesquisa} chave={chave} /> : null;
  return <ColetaAcompanhada pesquisa={pesquisa} chave={chave} jobId={jobId} editavel={editavel} itens={itens} />;
}

function ColetaAcompanhada({
  pesquisa,
  chave,
  jobId,
  editavel,
  itens,
}: {
  pesquisa: string;
  chave: string;
  jobId: string;
  editavel: boolean;
  itens: ItemResumido[];
}) {
  const router = useRouter();
  const { job, erro, inacessivel } = useJob(jobId, () => router.refresh());
  const painel = useRef<HTMLElement>(null);
  // Só um lote que se sabe ativo trava os botões: sem resposta do servidor
  // ou com o lote inacessível (404), a coleta continua possível.
  const ocupado = job ? job.estado === "queued" || job.estado === "running" : !erro && !inacessivel;
  // Muda só quando o painel troca de forma: acompanhando → resumo, falha ou inacessível.
  const marco = inacessivel
    ? "inacessivel"
    : !job || ocupado
      ? "acompanhando"
      : job.estado === "succeeded"
        ? "concluida"
        : "falha";

  // O painel aparece onde a pessoa está: o botão que o criou pode estar
  // fora da tela. Na conclusão ou na falha, o destaque passa ao resumo (ou
  // à mensagem) — que é o que a pessoa lê em seguida.
  useEffect(() => {
    const el = painel.current;
    if (!el) return;
    const reduzir = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: "start", behavior: reduzir ? "auto" : "smooth" });
    el.focus({ preventScroll: true });
  }, [jobId, marco]);

  return (
    <>
      {editavel && <BotaoDeColeta pesquisa={pesquisa} chave={chave} ocupado={ocupado} />}
      {inacessivel ? (
        <div
          ref={painel as RefObject<HTMLDivElement | null>}
          tabIndex={-1}
          data-testid="progresso-coleta"
          data-job="inacessivel"
          className={`outline-none ${ALVO}`}
        >
          <Alert
            variant="neutral"
            title="Não foi possível acompanhar este lote"
            actions={
              <Button size="sm" variant="secondary" href={`/app/precos/${pesquisa}`}>
                Parar de acompanhar
              </Button>
            }
          >
            Ele foi iniciado por outra conta ou não existe mais. Os preços já coletados aparecem nos itens
            {editavel ? "; para coletar de novo, use Coletar preços." : "."}
          </Alert>
        </div>
      ) : (
        <PainelDoLote job={job} erro={erro} itens={itens} painel={painel} />
      )}
    </>
  );
}

function BotaoDeColeta({ pesquisa, chave, ocupado = false }: { pesquisa: string; chave: string; ocupado?: boolean }) {
  const [estado, acao, enviando] = useActionState<EstadoDaColeta, FormData>(iniciarColeta, { erro: null });
  const carregando = enviando || ocupado;
  return (
    <form action={acao} className="grid justify-items-start gap-2">
      <input type="hidden" name="pesquisa" value={pesquisa} />
      <input type="hidden" name="chave" value={chave} />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" name="modo" value="manual" icon="arrows-clockwise" loading={carregando} disabled={carregando}>
          {enviando ? "Iniciando..." : ocupado ? "Coletando…" : "Coletar preços"}
        </Button>
        {/* Automática: a cesta é formada pela regra determinística (teto,
            equivalência e CV); o revisor confere e conclui depois. Volta
            sozinha ao pendente com dado novo; o aceito não é tocado. */}
        <Button type="submit" name="modo" value="automatico" variant="secondary" disabled={carregando}>
          Cotação automática
        </Button>
      </div>
      {estado.erro && (
        <Alert variant="error" compact>
          {estado.erro}
        </Alert>
      )}
    </form>
  );
}

function PainelDoLote({
  job,
  erro,
  itens,
  painel,
}: {
  job: Job | null;
  erro: string | null;
  itens: ItemResumido[];
  painel: RefObject<HTMLElement | null>;
}) {
  const comum = { ref: painel, tabIndex: -1, "data-testid": "progresso-coleta", className: ALVO } as const;
  const semReferencia = job?.resultado?.resumo?.[SEM_REFERENCIA] ?? 0;

  if (!job || job.estado === "queued") {
    return (
      <JobProgress
        {...comum}
        state="prep"
        data-job={job?.estado ?? "consultando"}
        title="Preparando a pesquisa"
        description={erro ?? "Validando os itens e abrindo conexão com as fontes de preço."}
        done={0}
        total={job?.total ?? 0}
        meta="Aguardando início da coleta"
        barLabel="Preparando a pesquisa"
      />
    );
  }
  if (job.estado === "running") {
    const faltam = Math.max(0, job.total - job.feitos);
    return (
      <JobProgress
        {...comum}
        state="run"
        data-job="running"
        title="Pesquisando preços"
        description={erro ?? "A coleta continua em segundo plano — você pode navegar pelo sistema e voltar depois."}
        done={job.feitos}
        total={job.total}
        meta={job.total > 0 ? <>Faltam <b>{faltam}</b> {faltam === 1 ? "item" : "itens"}</> : "Contando os itens"}
        barLabel="Itens processados"
        outcome={
          semReferencia > 0
            ? { title: `${semReferencia} sem referência compatível`, detail: "Ficam listados no resumo para pesquisa complementar." }
            : undefined
        }
      />
    );
  }
  if (job.estado === "succeeded") {
    return (
      <div ref={painel as RefObject<HTMLDivElement | null>} tabIndex={-1} data-testid="progresso-coleta" data-job="succeeded" className={`grid gap-4 outline-none ${ALVO}`}>
        <ResumoDaColeta job={job} itens={itens} />
      </div>
    );
  }
  // failed (e cancelled, que a coleta não usa mas a API conhece).
  const mensagem = FALHAS[job.erro_codigo] ?? (job.resultado?.mensagem || "A coleta falhou.");
  return (
    <JobProgress
      {...comum}
      state="error"
      data-job={job.estado}
      title="Falha na coleta"
      description={
        job.erro_codigo === "IMMUTABLE" ? (
          mensagem
        ) : (
          <>
            {mensagem} Os itens já processados foram mantidos; use <b>Coletar preços</b> para retomar.
          </>
        )
      }
      done={job.feitos}
      total={job.total}
      meta={job.total > 0 ? <>Interrompida após <b>{job.feitos}</b> de {job.total} itens</> : "Interrompida antes do primeiro item"}
      barLabel="Itens processados até a falha"
      outcome={semReferencia > 0 ? { title: `${semReferencia} sem referência compatível`, detail: "Independem da falha." } : undefined}
    />
  );
}

/** Na conclusão o painel dá lugar ao resumo, dentro da própria cotação. */
function ResumoDaColeta({ job, itens }: { job: Job; itens: ItemResumido[] }) {
  const resumo = job.resultado.resumo ?? {};
  const pendentes = job.resultado.pendentes ?? 0;
  const duracao = minutos(job.iniciado_em, job.concluido_em);
  const semReferencia = itens.filter((i) => i.pendencia === SEM_REFERENCIA);
  const contagens = DESFECHOS_DO_LOTE.filter(([chave]) => (resumo[chave] ?? 0) > 0);
  return (
    <>
      <Alert variant="success" title="Coleta concluída">
        {job.feitos} de {job.total} itens processados{duracao ? ` em ${duracao}` : ""}.
      </Alert>
      <Card title="Resumo da coleta" subtitle={quando(job.concluido_em)} divided data-testid="resumo-do-lote">
        <DataList
          stacked
          items={[
            { label: "Itens processados", value: `${job.resultado.processados ?? job.feitos} de ${job.total}`, numeric: true },
            ...contagens.map(([chave, rotulo]) => ({ label: rotulo, value: resumo[chave], numeric: true })),
            ...(pendentes > 0 ? [{ label: "Pendentes", value: pendentes, numeric: true }] : []),
          ]}
        />
      </Card>
      {semReferencia.length > 0 && (
        <Card
          title={`${semReferencia.length} sem referência compatível`}
          subtitle="Precisam de pesquisa complementar antes da triagem."
          flush
        >
          <ul className="grid">
            {semReferencia.map((i) => (
              <li
                key={i.id}
                className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 border-t border-linha px-5 py-2.5 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
              >
                <span className="font-mono text-xs text-secundario">{String(i.numero).padStart(3, "0")}</span>
                <span className="text-sm">
                  {i.descricao}
                  <small className="block text-xs text-secundario">{i.unidade}</small>
                </span>
                <span className="col-start-2 sm:col-start-auto">
                  <Badge variant="warning" size="sm" icon="warning-circle">
                    Sem referência
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

function minutos(inicio: string | null, fim: string | null): string {
  if (!inicio || !fim) return "";
  const ms = Date.parse(fim) - Date.parse(inicio);
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const min = Math.round(ms / 60000);
  return min < 1 ? "menos de 1 min" : `${min} min`;
}

function quando(iso: string | null): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return undefined;
  const fmt = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", ...o }).format(d);
  return `${fmt({ day: "2-digit", month: "2-digit", year: "numeric" })} · ${fmt({ hour: "2-digit", minute: "2-digit" })} (horário de Brasília)`;
}
