"use client";

import { useRouter } from "next/navigation";
import { useActionState } from "react";

import { iniciarColeta, type EstadoDaColeta } from "@/app/app/precos/acoes";
import { useJob } from "@/components/acompanhar-job";
import { DESFECHOS_DO_LOTE } from "@/components/precos";
import { botaoPrimario, botaoSecundario } from "@/components/ui";

const FALHAS: Record<string, string> = {
  SESSION_EXPIRED: "A coleta parou porque sua sessão estava terminando. O que já foi coletado ficou; inicie de novo para continuar.",
  IMMUTABLE: "Esta pesquisa já foi aplicada ou arquivada e não recebe nova coleta.",
  DATABASE_UNAVAILABLE: "O banco não respondeu durante a coleta. Inicie de novo para continuar de onde parou.",
  QUEUE_UNAVAILABLE: "A coleta não chegou a começar. Tente de novo em instantes.",
};

export function BotaoDeColeta({ pesquisa, chave }: { pesquisa: string; chave: string }) {
  const [estado, acao, enviando] = useActionState<EstadoDaColeta, FormData>(iniciarColeta, { erro: null });
  return (
    <form action={acao} className="grid justify-items-start gap-2">
      <input type="hidden" name="pesquisa" value={pesquisa} />
      <input type="hidden" name="chave" value={chave} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" name="modo" value="manual" className={botaoPrimario} disabled={enviando}>
          {enviando ? "Iniciando..." : "Coletar preços"}
        </button>
        {/* Automática: a cesta é formada pela regra determinística (teto,
            equivalência e CV); o revisor confere e conclui depois. */}
        <button type="submit" name="modo" value="automatico" className={botaoSecundario} disabled={enviando}>
          Cotar todos os itens
        </button>
        {/* Depois de fontes novas, termos, alteração do item ou falha
            técnica: só o que ainda não tem preço proposto. Concluído não entra. */}
        <button type="submit" name="acao" value="reprocessar" className={botaoSecundario} disabled={enviando}>
          Reprocessar pendentes
        </button>
      </div>
      {estado.erro && (
        <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-3 py-2 text-sm text-erro">
          {estado.erro}
        </p>
      )}
    </form>
  );
}

/**
 * Acompanha a coleta (`useJob`) e, no fim, recarrega os dados da página
 * (itens e preços).
 */
export function ProgressoDaColeta({ jobId, pesquisa }: { jobId: string; pesquisa?: string }) {
  const router = useRouter();
  const { job, erro } = useJob(jobId, () => router.refresh());

  if (!job) {
    return (
      <p role="status" className="text-sm text-secundario">
        {erro ?? "Consultando a coleta..."}
      </p>
    );
  }
  const texto =
    job.estado === "succeeded"
      ? `Coleta concluída: ${job.feitos} de ${job.total} itens processados.`
      : job.estado === "failed"
        ? (FALHAS[job.erro_codigo] ?? "A coleta falhou. Inicie de novo para continuar de onde parou.")
        : job.estado === "queued"
          ? "Coleta na fila."
          : `Coletando: ${job.feitos} de ${job.total} itens.`;
  const cor = job.estado === "failed" ? "bg-erro-fundo text-erro" : job.estado === "succeeded" ? "bg-ok-fundo text-ok" : "bg-acento-claro text-texto";
  return (
    <div role="status" aria-live="polite" className={`grid gap-2 rounded-[var(--radius-ui)] px-4 py-3 text-sm ${cor}`} data-testid="progresso-coleta">
      <span>{texto}</span>
      {(job.estado === "running" || job.estado === "queued") && job.total > 0 && (
        <progress className="h-1.5 w-full max-w-sm accent-[var(--color-acento)]" max={100} value={job.progresso} aria-label="Progresso da coleta" />
      )}
      {job.resultado?.resumo && Object.keys(job.resultado.resumo).length > 0 && (
        <ResumoDoLote job={job} pesquisa={pesquisa} />
      )}
      {erro && <span className="text-xs text-secundario">{erro}</span>}
    </div>
  );
}

/** Cada item contado uma vez, pelo desfecho principal; acesso aos pendentes. */
function ResumoDoLote({ job, pesquisa }: { job: NonNullable<ReturnType<typeof useJob>["job"]>; pesquisa?: string }) {
  const resumo = job.resultado.resumo ?? {};
  const pendentes = job.resultado.pendentes ?? 0;
  return (
    <div className="grid gap-1" data-testid="resumo-do-lote">
      <span>
        {job.resultado.processados ?? job.feitos} de {job.total} itens processados
        {pendentes > 0 ? ` · ${pendentes} pendente(s)` : ""}
      </span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {DESFECHOS_DO_LOTE.filter(([chave]) => (resumo[chave] ?? 0) > 0).map(([chave, rotulo]) => (
          <li key={chave}>
            {rotulo}: <strong>{resumo[chave]}</strong>
          </li>
        ))}
      </ul>
      {pendentes > 0 && pesquisa && (
        <a href={`/app/precos/${pesquisa}?pendentes=1#itens`} className="text-acento underline">
          Ver os itens pendentes
        </a>
      )}
    </div>
  );
}
