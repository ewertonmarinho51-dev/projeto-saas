"use server";

import { revalidatePath } from "next/cache";

import { chamarApi, ErroDaApi, type ReferenciaIndexada, type TrechoRecuperado } from "@/lib/api";

const CAMINHO = "/app/admin/base-conhecimento";
const UUID = /^[0-9a-f-]{36}$/i;
const LIMITE = 10 * 1024 * 1024;
// Indexar chama o provedor de embeddings: o tempo é do provedor, não da API.
const TEMPO_DA_INDEXACAO_MS = 150_000;

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Só o administrador do município mexe na Base de Conhecimento.",
  404: "Referência não encontrada — talvez já tenha sido excluída.",
  413: "O arquivo passa do limite de 10 MB.",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown): string {
  if (e instanceof ErroDaApi) {
    if (e.status === 422 && e.mensagem) return e.mensagem;
    return MENSAGENS[e.status] ?? "Não foi possível concluir agora. Tente de novo.";
  }
  return "Não foi possível concluir agora. Tente de novo.";
}

export type ResultadoDaIndexacao = { erro: string | null; trechos: number; pendente: boolean };

/** Um arquivo por chamada: a tela manda o lote em sequência e mostra cada resultado. */
export async function indexarArquivo(form: FormData): Promise<ResultadoDaIndexacao> {
  const arquivo = form.get("arquivo");
  if (!(arquivo instanceof File) || arquivo.size === 0) return { erro: "Arquivo vazio.", trechos: 0, pendente: false };
  if (arquivo.size > LIMITE) return { erro: MENSAGENS[413], trechos: 0, pendente: false };
  try {
    const { dados } = await chamarApi<ReferenciaIndexada>("/admin/base-conhecimento", {
      metodo: "POST",
      corpo: {
        nome_arquivo: arquivo.name.slice(0, 200),
        titulo: String(form.get("titulo") ?? "").trim().slice(0, 300),
        categoria: String(form.get("categoria") ?? ""),
        conteudo: Buffer.from(await arquivo.arrayBuffer()).toString("base64"),
      },
      tempoMs: TEMPO_DA_INDEXACAO_MS,
    });
    return { erro: null, trechos: dados.trechos, pendente: dados.pendente_de_vetor };
  } catch (e) {
    return { erro: mensagem(e), trechos: 0, pendente: false };
  }
}

/** Depois do lote: a lista de referências volta do servidor. */
export async function atualizarLista(): Promise<void> {
  revalidatePath(CAMINHO);
}

export async function excluirReferencia(id: string): Promise<{ erro: string | null }> {
  if (!UUID.test(id)) return { erro: "Referência inválida." };
  try {
    await chamarApi(`/admin/base-conhecimento/${id}`, { metodo: "DELETE" });
  } catch (e) {
    return { erro: mensagem(e) };
  }
  revalidatePath(CAMINHO);
  return { erro: null };
}

export async function testarBusca(consulta: string): Promise<{ erro: string | null; trechos: TrechoRecuperado[] }> {
  const texto = consulta.trim();
  if (texto.length < 3) return { erro: "Escreva uma consulta com pelo menos 3 letras.", trechos: [] };
  try {
    const { dados } = await chamarApi<TrechoRecuperado[]>("/admin/base-conhecimento/busca", {
      metodo: "POST",
      corpo: { consulta: texto.slice(0, 500) },
      tempoMs: 60_000,
    });
    return { erro: null, trechos: dados };
  } catch (e) {
    return { erro: mensagem(e), trechos: [] };
  }
}
