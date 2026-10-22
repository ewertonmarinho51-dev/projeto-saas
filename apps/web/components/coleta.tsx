"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef, useState } from "react";

import { iniciarColeta, type EstadoDaColeta } from "@/app/app/precos/acoes";
import { botaoPrimario } from "@/components/ui";
import type { Job } from "@/lib/api";

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
 * Acompanha um job sem prender a tela: consulta a cada 2,5 s, para no
 * estado final e então recarrega os dados da página (itens e preços).
 * Sem WebSocket nem SSE — polling basta para progresso unidirecional
 * (02_ARQUITETURA), e sobrevive a refresh: o job vem da URL.
 */
export function ProgressoDaColeta({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const finalizado = useRef(false);

  useEffect(() => {
    let ativo = true;
    let espera: ReturnType<typeof setTimeout> | undefined;
    async function consultar() {
      try {
        const r = await fetch(`/app/precos/jobs/${jobId}`, { cache: "no-store" });
        if (!r.ok) throw new Error(String(r.status));
        const dados = (await r.json()) as Job;
        if (!ativo) return;
        setJob(dados);
        setErro(null);
        if (["succeeded", "failed", "cancelled"].includes(dados.estado)) {
          if (!finalizado.current) {
            finalizado.current = true;
            router.refresh();
          }
          return;
        }
      } catch {
        if (ativo) setErro("Sem resposta do servidor; tentando de novo.");
      }
      if (ativo) espera = setTimeout(consultar, 2500);
    }
    consultar();
    return () => {
      ativo = false;
      if (espera) clearTimeout(espera);
    };
  }, [jobId, router]);

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
