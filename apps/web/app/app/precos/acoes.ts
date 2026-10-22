"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { chamarApi, ErroDaApi } from "@/lib/api";

export type EstadoDaCesta = { erro: string | null };

const UUID = /^[0-9a-f-]{36}$/i;

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Você não tem permissão para alterar esta cesta.",
  404: "Referência não encontrada nesta pesquisa.",
  409: "Esta cesta mudou depois que você abriu a página (outra aba ou outra pessoa). Recarregue e refaça.",
  429: "Muitas requisições. Aguarde um instante.",
};

/**
 * Pôr ou tirar UMA referência. A regra (motivo obrigatório só para pôr,
 * reinclusão sinalizada, trilha) é do domínio; a mensagem dele volta como
 * veio quando ele recusa (422).
 */
export async function alterarCesta(_: EstadoDaCesta, form: FormData): Promise<EstadoDaCesta> {
  const pesquisa = String(form.get("pesquisa") ?? "");
  const item = String(form.get("item") ?? "");
  const referencia = String(form.get("referencia") ?? "");
  const revisao = String(form.get("revisao") ?? "");
  if (![pesquisa, item, referencia].every((v) => UUID.test(v)) || !/^\d+$/.test(revisao)) {
    return { erro: "Requisição inválida." };
  }
  const incluir = form.get("incluir") === "1";
  const motivo = String(form.get("motivo") ?? "").trim();
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/itens/${item}/referencias/${referencia}`, {
      metodo: "PATCH",
      corpo: { incluir, ...(motivo ? { motivo } : {}) },
      cabecalhos: { "If-Match": `"${revisao}"` },
    });
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 422) {
      return { erro: e.mensagem || "A regra da cesta recusou esta mudança." };
    }
    return {
      erro: e instanceof ErroDaApi ? (MENSAGENS[e.status] ?? "Não foi possível alterar agora.") : "Não foi possível alterar agora.",
    };
  }
  const caminho = `/app/precos/${pesquisa}/itens/${item}`;
  revalidatePath(caminho);
  redirect(`${caminho}?cesta=${incluir ? "incluida" : "retirada"}`);
}
