"use server";

import { chamarApi, ErroDaApi, type Elaboracao, type Job } from "@/lib/api";
import { criarClienteServidor } from "@/lib/supabase/server";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
// A API lê no motor o texto de cada documento aprovado antes de pôr na fila.
const LONGO = 60000;

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Só o titular do processo ou um administrador pode iniciar a elaboração.",
  404: "Processo não encontrado.",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown): string {
  if (e instanceof ErroDaApi) {
    // 409, 422 e fila fora do ar: a API escreveu o texto para a pessoa.
    if ([409, 422].includes(e.status) || e.codigo === "QUEUE_UNAVAILABLE") return e.mensagem;
    return MENSAGENS[e.status] ?? "Não foi possível iniciar a elaboração agora. Tente de novo.";
  }
  return "Não foi possível iniciar a elaboração agora. Tente de novo.";
}

/**
 * Pede o próximo documento. Quem decide qual é e quem impede o pedido repetido
 * é a API (índice da 0039): dois cliques recebem o mesmo job.
 *
 * O worker grava com o token de quem pediu, e o documento leva minutos: o token
 * é renovado aqui para não vencer no meio. Falhar a renovação não impede o
 * pedido; se ele não durar, a falha aparece na tela e a nova tentativa acha o
 * texto no cache de geração, sem outra chamada paga.
 */
export async function iniciarElaboracao(
  processoId: string,
  tipo: string | null,
): Promise<{ ok: true; estado: Elaboracao } | { ok: false; erro: string }> {
  if (!UUID.test(processoId)) return { ok: false, erro: "Processo inválido." };
  try {
    const supabase = await criarClienteServidor();
    await supabase.auth.refreshSession();
    await chamarApi<Job>(`/processos/${processoId}/elaboracao`, {
      metodo: "POST",
      corpo: { tipo },
      cabecalhos: { "Idempotency-Key": `elaboracao-${crypto.randomUUID()}` },
      tempoMs: LONGO,
    });
    const { dados } = await chamarApi<Elaboracao>(`/processos/${processoId}/elaboracao`);
    return { ok: true, estado: dados };
  } catch (e) {
    return { ok: false, erro: mensagem(e) };
  }
}
