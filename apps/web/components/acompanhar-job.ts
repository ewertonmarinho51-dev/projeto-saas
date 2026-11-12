"use client";

import { useEffect, useRef, useState } from "react";

import type { Job } from "@/lib/api";

const FINAIS = ["succeeded", "failed", "cancelled"];

/**
 * Acompanha um job sem prender a tela: consulta a cada 2,5 s e para no
 * estado final. Sem WebSocket nem SSE: polling basta para progresso
 * unidirecional (02_ARQUITETURA), e sobrevive a refresh, porque o job vem
 * da URL. `aoTerminar` roda uma vez só. `inacessivel`: a API respondeu 404
 * (job de outra conta ou inexistente) e a consulta parou.
 */
export function useJob(jobId: string, aoTerminar?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [inacessivel, setInacessivel] = useState(false);
  const terminou = useRef(false);
  const callback = useRef(aoTerminar);
  useEffect(() => {
    callback.current = aoTerminar;
  });

  useEffect(() => {
    let ativo = true;
    let espera: ReturnType<typeof setTimeout> | undefined;
    async function consultar() {
      try {
        const r = await fetch(`/app/precos/jobs/${jobId}`, { cache: "no-store" });
        // 404 não muda com o tempo: o job não existe ou é de outra conta (a
        // API só mostra o job ao dono, nem ao administrador). Para de
        // consultar em vez de ficar em "consultando" para sempre.
        if (r.status === 404) {
          if (ativo) {
            setInacessivel(true);
            setErro("Este acompanhamento não está disponível para a sua conta.");
          }
          return;
        }
        if (!r.ok) throw new Error(String(r.status));
        const dados = (await r.json()) as Job;
        if (!ativo) return;
        setJob(dados);
        setErro(null);
        if (FINAIS.includes(dados.estado)) {
          if (!terminou.current) {
            terminou.current = true;
            callback.current?.(dados);
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
  }, [jobId]);

  return { job, erro, inacessivel };
}
