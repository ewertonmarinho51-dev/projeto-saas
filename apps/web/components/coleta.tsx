"use client";

import { useRouter } from "next/navigation";
import { useActionState } from "react";

import { iniciarColeta, type EstadoDaColeta } from "@/app/app/precos/acoes";
import { useJob } from "@/components/acompanhar-job";
import { botaoPrimario } from "@/components/ui";

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
      <button type="submit" className={botaoPrimario} disabled={enviando}>
        {enviando ? "Iniciando..." : "Coletar preços"}
      </button>
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
export function ProgressoDaColeta({ jobId }: { jobId: string }) {
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
      {erro && <span className="text-xs text-secundario">{erro}</span>}
    </div>
  );
}
