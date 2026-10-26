"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { chamarApi, ErroDaApi } from "@/lib/api";

/**
 * Gestão da cotação e do item (M10a): o que a tela de Cotações do GovDocs
 * fazia e /app/precos ainda não. A regra é do domínio; a mensagem dele
 * volta como veio quando ele recusa (422).
 */
export type EstadoDaGestao = { erro: string | null; ok: string | null };

const UUID = /^[0-9a-f-]{36}$/i;

const POR_CODIGO: Record<string, string> = {
  FORBIDDEN: "Só quem criou a pesquisa (ou o administrador) pode alterá-la.",
  VERSION_CONFLICT: "O item mudou desde que você abriu a página. Recarregue e refaça.",
  IMMUTABLE: "Pesquisa aplicada ou arquivada: crie uma revisão nova.",
  ITEM_COMPLETE: "Item concluído: reabra o item, com o motivo, antes de mudar a cesta.",
};

const POR_STATUS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  404: "Não encontrado nesta pesquisa.",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown): string {
  if (e instanceof ErroDaApi) {
    if (e.status === 422 && e.mensagem) return e.mensagem;
    return POR_CODIGO[e.codigo] ?? POR_STATUS[e.status] ?? "Não foi possível concluir agora.";
  }
  return "Não foi possível concluir agora.";
}

const texto = (form: FormData, nome: string, maximo: number) => String(form.get(nome) ?? "").trim().slice(0, maximo);

function dadosDoItem(form: FormData) {
  return {
    descricao: texto(form, "descricao", 2000),
    unidade: texto(form, "unidade", 40),
    quantidade: texto(form, "quantidade", 30),
    codigo: texto(form, "codigo", 40),
  };
}

export async function duplicarPesquisa(pesquisa: string): Promise<EstadoDaGestao> {
  if (!UUID.test(pesquisa)) return { erro: "Pesquisa inválida.", ok: null };
  let nova: string;
  try {
    const { dados } = await chamarApi<{ id: string }>(`/precos/pesquisas/${pesquisa}/duplicacao`, { metodo: "POST" });
    nova = dados.id;
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath("/app/precos");
  redirect(`/app/precos/${nova}?duplicada=1`);
}

export async function arquivarPesquisa(pesquisa: string): Promise<EstadoDaGestao> {
  if (!UUID.test(pesquisa)) return { erro: "Pesquisa inválida.", ok: null };
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/arquivamento`, { metodo: "POST" });
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath("/app/precos");
  redirect(`/app/precos/${pesquisa}?arquivada=1`);
}

export async function incluirItem(pesquisa: string, _: EstadoDaGestao, form: FormData): Promise<EstadoDaGestao> {
  if (!UUID.test(pesquisa)) return { erro: "Pesquisa inválida.", ok: null };
  const corpo = dadosDoItem(form);
  if (corpo.descricao.length < 3) return { erro: "Descreva o item (descrição e especificação).", ok: null };
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/itens`, { metodo: "POST", corpo });
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath(`/app/precos/${pesquisa}`);
  return { erro: null, ok: "Item incluído. Ele fica pendente de coleta." };
}

export async function editarItem(
  pesquisa: string,
  item: string,
  revisao: number,
  _: EstadoDaGestao,
  form: FormData,
): Promise<EstadoDaGestao> {
  if (![pesquisa, item].every((v) => UUID.test(v))) return { erro: "Item inválido.", ok: null };
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/itens/${item}`, {
      metodo: "PUT",
      corpo: dadosDoItem(form),
      cabecalhos: { "If-Match": `"${revisao}"` },
    });
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  const caminho = `/app/precos/${pesquisa}/itens/${item}`;
  revalidatePath(caminho);
  redirect(`${caminho}?item=editado`);
}

export async function retirarItem(pesquisa: string, item: string, motivo: string): Promise<EstadoDaGestao> {
  if (![pesquisa, item].every((v) => UUID.test(v))) return { erro: "Item inválido.", ok: null };
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/itens/${item}/retirada`, {
      metodo: "POST",
      corpo: { motivo: motivo.trim().slice(0, 1000) },
    });
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  revalidatePath(`/app/precos/${pesquisa}`);
  redirect(`/app/precos/${pesquisa}?item_retirado=1`);
}

async function naCesta(
  ato: "desfazer" | "manter",
  pesquisa: string,
  item: string,
  referencia: string,
  revisao: number,
): Promise<EstadoDaGestao> {
  if (![pesquisa, item, referencia].every((v) => UUID.test(v))) return { erro: "Referência inválida.", ok: null };
  try {
    await chamarApi(`/precos/pesquisas/${pesquisa}/itens/${item}/referencias/${referencia}/${ato}`, {
      metodo: "POST",
      cabecalhos: { "If-Match": `"${revisao}"` },
    });
  } catch (e) {
    return { erro: mensagem(e), ok: null };
  }
  const caminho = `/app/precos/${pesquisa}/itens/${item}`;
  revalidatePath(caminho);
  redirect(`${caminho}?cesta=${ato === "desfazer" ? "desfeita" : "mantida"}`);
}

export async function desfazerRetirada(pesquisa: string, item: string, referencia: string, revisao: number) {
  return naCesta("desfazer", pesquisa, item, referencia, revisao);
}

export async function manterPreco(pesquisa: string, item: string, referencia: string, revisao: number) {
  return naCesta("manter", pesquisa, item, referencia, revisao);
}
