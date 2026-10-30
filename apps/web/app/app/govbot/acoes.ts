"use server";

import { chamarApi, ErroDaApi, type RespostaDoGovBot } from "@/lib/api";

export type Turno = { papel: "user" | "assistant"; texto: string };

export type ResultadoDaPergunta = { resposta: RespostaDoGovBot; erro: null } | { resposta: null; erro: string };

const UUID = /^[0-9a-f-]{36}$/i;

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  404: "O GovBot ou o processo não está disponível para a sua conta.",
  422: "Não entendi a pergunta. Escreva de novo, em até 2.000 caracteres.",
  429: "Muitas perguntas seguidas. Aguarde um instante.",
};

/**
 * Uma pergunta ao GovBot. O navegador manda só o texto, o id do processo e
 * os últimos turnos; o processo é lido pela API com o token da sessão, e a
 * resposta volta sem nada que altere o processo.
 */
export async function perguntarAoGovBot(entrada: {
  pergunta: string;
  processoId: string | null;
  historico: Turno[];
}): Promise<ResultadoDaPergunta> {
  const pergunta = String(entrada.pergunta ?? "").trim();
  if (!pergunta) return { resposta: null, erro: "Escreva uma pergunta." };
  const processoId = entrada.processoId && UUID.test(entrada.processoId) ? entrada.processoId : null;
  const historico = (Array.isArray(entrada.historico) ? entrada.historico : [])
    .filter((t) => (t?.papel === "user" || t?.papel === "assistant") && String(t.texto ?? "").trim())
    .slice(-8)
    .map((t) => ({ papel: t.papel, texto: String(t.texto).trim().slice(0, 2000) }));
  try {
    const { dados } = await chamarApi<RespostaDoGovBot>("/govbot/perguntas", {
      metodo: "POST",
      corpo: { pergunta: pergunta.slice(0, 2000), historico, ...(processoId ? { processo_id: processoId } : {}) },
      // O motor de IA pode levar dezenas de segundos; a busca na Base também.
      tempoMs: 90_000,
    });
    return { resposta: dados, erro: null };
  } catch (e) {
    const status = e instanceof ErroDaApi ? e.status : 503;
    return { resposta: null, erro: MENSAGENS[status] ?? "O GovBot está indisponível no momento. Tente de novo em instantes." };
  }
}
