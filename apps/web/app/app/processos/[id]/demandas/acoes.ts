"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { baixarDaApiComCorpo, chamarApi, ErroDaApi, type AplicacaoDaDemanda, type Consolidacao } from "@/lib/api";

const UUID = /^[0-9a-f-]{36}$/i;
const POR_ARQUIVO = 10 * 1024 * 1024;
const TOTAL = 30 * 1024 * 1024;
const MAX_ARQUIVOS = 30;

type Pedido = { arquivos: { nome: string; conteudo: string }[]; rotulos: Record<string, string>; conflitos_aceitos: string[] };

const MENSAGENS: Record<number, string> = {
  401: "Sua sessão expirou. Entre novamente.",
  403: "Só quem criou o processo (ou o administrador) pode aplicar a consolidação.",
  404: "Processo não encontrado, ou Consolidar Demandas não está disponível para você.",
  413: "Os arquivos passam do limite (10 MB cada, 30 MB no total).",
  429: "Muitas requisições. Aguarde um instante.",
};

function mensagem(e: unknown, padrao: string): string {
  if (e instanceof ErroDaApi) {
    if (e.status === 422 && e.mensagem) return e.mensagem;
    if (e.status === 409 && e.codigo === "VERSION_CONFLICT")
      return "Outra pessoa alterou este processo depois que você o abriu. Recarregue para ver a versão atual.";
    return MENSAGENS[e.status] ?? padrao;
  }
  return padrao;
}

/** Os PDFs do formulário, em base64, com as decisões do servidor. */
async function pedido(form: FormData): Promise<Pedido | string> {
  const arquivos = form.getAll("arquivos").filter((a): a is File => a instanceof File && a.size > 0);
  if (arquivos.length === 0) return "Envie ao menos um Documento de Formalização de Demanda (PDF).";
  if (arquivos.length > MAX_ARQUIVOS) return `Envie no máximo ${MAX_ARQUIVOS} arquivos de cada vez.`;
  let total = 0;
  const saida: Pedido["arquivos"] = [];
  for (const arquivo of arquivos) {
    total += arquivo.size;
    if (arquivo.size > POR_ARQUIVO || total > TOTAL) return MENSAGENS[413];
    saida.push({ nome: arquivo.name.slice(0, 200), conteudo: Buffer.from(await arquivo.arrayBuffer()).toString("base64") });
  }
  let rotulos: Record<string, string> = {};
  let aceitos: string[] = [];
  try {
    rotulos = JSON.parse(String(form.get("rotulos") ?? "{}")) as Record<string, string>;
    aceitos = JSON.parse(String(form.get("aceitos") ?? "[]")) as string[];
  } catch {
    return "Não foi possível ler as decisões da tela. Recarregue a página.";
  }
  return { arquivos: saida, rotulos, conflitos_aceitos: aceitos };
}

export type EstadoDaConsolidacao = { erro: string | null; resultado: Consolidacao | null };

export async function consolidar(id: string, form: FormData): Promise<EstadoDaConsolidacao> {
  if (!UUID.test(id)) return { erro: "Processo inválido.", resultado: null };
  const corpo = await pedido(form);
  if (typeof corpo === "string") return { erro: corpo, resultado: null };
  try {
    const { dados } = await chamarApi<Consolidacao>(`/processos/${id}/demandas/consolidacao`, {
      metodo: "POST",
      corpo,
      tempoMs: 60000,
    });
    return { erro: null, resultado: dados };
  } catch (e) {
    return { erro: mensagem(e, "Não foi possível ler os arquivos agora."), resultado: null };
  }
}

export type EstadoDaPlanilha = { erro: string | null; base64: string | null };

/** A tabela consolidada em XLSX (a tela monta o download). */
export async function planilhaConsolidada(id: string, form: FormData): Promise<EstadoDaPlanilha> {
  if (!UUID.test(id)) return { erro: "Processo inválido.", base64: null };
  const corpo = await pedido(form);
  if (typeof corpo === "string") return { erro: corpo, base64: null };
  try {
    const conteudo = await baixarDaApiComCorpo(`/processos/${id}/demandas/planilha`, corpo);
    return { erro: null, base64: Buffer.from(conteudo).toString("base64") };
  } catch (e) {
    return { erro: mensagem(e, "Não foi possível gerar a planilha agora."), base64: null };
  }
}

export type EstadoDaAplicacao = { erro: string | null; descarte: string | null };

export async function aplicarDemanda(id: string, versao: string, confirmar: boolean, form: FormData): Promise<EstadoDaAplicacao> {
  if (!UUID.test(id)) return { erro: "Processo inválido.", descarte: null };
  const corpo = await pedido(form);
  if (typeof corpo === "string") return { erro: corpo, descarte: null };
  let resultado: AplicacaoDaDemanda;
  try {
    ({ dados: resultado } = await chamarApi<AplicacaoDaDemanda>(`/processos/${id}/demandas/aplicacao`, {
      metodo: "PUT",
      corpo: { ...corpo, confirmar_descarte: confirmar },
      cabecalhos: { "If-Match": `"${versao}"` },
      tempoMs: 60000,
    }));
  } catch (e) {
    if (e instanceof ErroDaApi && e.codigo === "DESCARTE_PENDENTE") return { erro: null, descarte: e.mensagem };
    return { erro: mensagem(e, "Não foi possível aplicar agora."), descarte: null };
  }
  revalidatePath(`/app/processos/${id}`);
  redirect(`/app/processos/${id}/formulario?demanda=${resultado.itens}`);
}
