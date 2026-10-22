"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { chamarApi, ErroDaApi, type Processo } from "@/lib/api";

export type EstadoDoFormulario = { erro: string | null };

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Você não tem permissão para esta alteração.",
  404: "Processo não encontrado.",
  409: "Outra pessoa alterou este processo depois que você o abriu. Recarregue para ver a versão atual.",
  422: "Confira os campos: órgão e objeto são obrigatórios.",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown): string {
  if (e instanceof ErroDaApi) return MENSAGENS[e.status] ?? "Não foi possível salvar agora. Tente de novo.";
  return "Não foi possível salvar agora. Tente de novo.";
}

function texto(form: FormData, nome: string): string {
  return String(form.get(nome) ?? "").trim();
}

export async function criarProcesso(_: EstadoDoFormulario, form: FormData): Promise<EstadoDoFormulario> {
  // A chave nasce com o formulário (campo oculto). Dois cliques, ou o
  // reenvio do navegador, mandam a MESMA chave — e a API devolve o mesmo
  // processo em vez de criar dois.
  const chave = texto(form, "chave");
  let id: string;
  try {
    const { dados } = await chamarApi<Processo>("/processos", {
      metodo: "POST",
      corpo: { nome: texto(form, "nome"), orgao: texto(form, "orgao"), objeto: texto(form, "objeto") },
      cabecalhos: { "Idempotency-Key": chave },
    });
    id = dados.id;
  } catch (e) {
    return { erro: mensagem(e) };
  }
  revalidatePath("/app");
  redirect(`/app/processos/${id}?criado=1`);
}

export async function editarProcesso(_: EstadoDoFormulario, form: FormData): Promise<EstadoDoFormulario> {
  const id = texto(form, "id");
  if (!/^[0-9a-f-]{36}$/i.test(id)) return { erro: "Processo inválido." };
  try {
    await chamarApi<Processo>(`/processos/${id}`, {
      metodo: "PATCH",
      corpo: { nome: texto(form, "nome"), orgao: texto(form, "orgao"), objeto: texto(form, "objeto") },
      // A versão que a pessoa LEU. Se mudou desde então, a API diz 409.
      cabecalhos: { "If-Match": `"${texto(form, "versao")}"` },
    });
  } catch (e) {
    return { erro: mensagem(e) };
  }
  revalidatePath(`/app/processos/${id}`);
  redirect(`/app/processos/${id}?salvo=1`);
}
